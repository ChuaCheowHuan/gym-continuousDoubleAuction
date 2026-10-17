"""A failed champion snapshot leaves the league as it found it (issues #176 and #178).

Two halves of one rule: whatever a failed snapshot did must be undone, and nothing may be
taken away for a snapshot that has not succeeded.

* #176 - `add_module` ships a frozen copy of the matchmaking pool to every remote env runner.
  If a later step failed, only the driver's pool was rolled back: the runners kept a pool
  naming a module that had never received its weights, and it stayed in the Algorithm.
* #178 - a full league evicted its oldest champion before taking the snapshot, so a failure
  shrank the league by one for nothing.

Neither needs Ray: the Algorithm is a stand-in that records the calls made on it.
"""

from unittest.mock import MagicMock


from gym_continuousDoubleAuction.train.callbk import league as league_module
from gym_continuousDoubleAuction.train.callbk.league import League

RETURNS = {
    "policy_0": 9.0,
    "policy_1": 1.0,
    "policy_2": 0.0,
    "policy_3": 0.0,
    "policy_4": 0.0,
    "policy_5": 0.0,
}


class Ep:
    def __init__(self, id_):
        self.id_ = id_


def _league(champions=0, max_champions=2):
    league = League(
        2,
        4,
        std_dev_multiplier=1.0,
        max_champions=max_champions,
        min_iterations_between_champions=0,
        original_opponent_weight=1.0,
        champion_weight=1.0,
        min_champion_trades=0.0,
        promotion_reference="pooled",
    )
    for n in range(1, champions + 1):
        champion = {
            "id": f"champion_{n}",
            "source_policy": "policy_0",
            "iteration": n,
            "return": 1.0,
        }
        league.champion_history.append(champion)
        league.available_modules.append(champion["id"])
    league.champion_count = champions
    league.champion_id_counter = champions
    return league


def _algorithm(*, fail_at=None):
    """A stand-in Algorithm; `fail_at` names the call that raises."""
    algo = MagicMock()
    algo.learner_group.get_state.return_value = {"learner": {"rl_module": {"policy_0": {}}}}
    if fail_at:
        target = algo
        for part in fail_at.split("."):
            target = getattr(target, part)
        target.side_effect = RuntimeError(f"{fail_at} failed")
    return algo


def _picks(mapping_fn, n=300):
    return {mapping_fn("agent_2", Ep(f"episode-{i}")) for i in range(n)}


class TestARolledBackSnapshotIsRemovedFromTheRunners:
    def test_a_failure_after_add_module_removes_the_module_and_corrects_the_pool(self):
        league = _league()
        algo = _algorithm(fail_at="set_state")

        league.create_snapshot(algo, "policy_0", 5.0, 3)

        algo.remove_module.assert_called_once()
        assert algo.remove_module.call_args.kwargs["module_id"] == "champion_1"
        corrected = algo.remove_module.call_args.kwargs["new_agent_to_module_mapping_fn"]
        assert "champion_1" not in _picks(corrected), "the runners no longer offer it"
        assert "champion_1" not in league.available_modules
        assert league.champion_history == [] and league.champion_count == 0

    def test_a_failure_before_add_module_has_nothing_to_remove(self):
        league = _league()
        algo = _algorithm(fail_at="learner_group.get_state")

        league.create_snapshot(algo, "policy_0", 5.0, 3)

        algo.add_module.assert_not_called()
        algo.remove_module.assert_not_called()
        assert "champion_1" not in league.available_modules

    def test_a_failure_while_removing_is_only_logged(self, monkeypatch):
        # A stand-in logger, not caplog: other suites leave the package's logging
        # reconfigured, and this test is about what the league reports, not where.
        said = MagicMock()
        monkeypatch.setattr(league_module, "logger", said)
        league = _league()
        algo = _algorithm(fail_at="set_state")
        algo.remove_module.side_effect = RuntimeError("the runner is gone")

        league.create_snapshot(algo, "policy_0", 5.0, 3)  # must not raise

        reported = " ".join(str(a) for call in said.warning.call_args_list for a in call.args)
        assert "champion_1" in reported and "the runner is gone" in reported
        assert "champion_1" not in league.available_modules

    def test_a_successful_snapshot_removes_nothing(self):
        league = _league()
        algo = _algorithm()

        league.create_snapshot(algo, "policy_0", 5.0, 3)

        algo.remove_module.assert_not_called()
        assert [c["id"] for c in league.champion_history] == ["champion_1"]

    def test_the_failed_id_is_not_reused(self):
        league = _league()
        league.create_snapshot(_algorithm(fail_at="set_state"), "policy_0", 5.0, 3)
        league.create_snapshot(_algorithm(), "policy_0", 5.0, 4)

        assert [c["id"] for c in league.champion_history] == ["champion_2"]


class TestAFullLeagueOnlyEvictsAfterASuccessfulSnapshot:
    def test_a_failed_snapshot_keeps_every_champion(self):
        league = _league(champions=2, max_champions=2)
        algo = _algorithm(fail_at="learner_group.get_state")

        out = league.assess(algo, RETURNS, {}, 10)

        assert [c["id"] for c in league.champion_history] == ["champion_1", "champion_2"]
        assert league.champion_count == 2
        assert {"champion_1", "champion_2"} <= set(league.available_modules)
        assert out.promoted == 0
        algo.remove_module.assert_not_called()

    def test_a_successful_snapshot_evicts_the_oldest_after_it_exists(self, monkeypatch):
        league = _league(champions=2, max_champions=2)
        algo = _algorithm()
        events = []

        def snapshot(algorithm, source, value, iteration):
            events.append("snapshot")
            league.champion_id_counter += 1
            champion = {
                "id": "champion_3",
                "source_policy": source,
                "iteration": iteration,
                "return": value,
            }
            league.champion_history.append(champion)
            league.available_modules.append("champion_3")
            league.champion_count += 1

        monkeypatch.setattr(league, "create_snapshot", snapshot)
        algo.remove_module.side_effect = lambda **kw: events.append("evict")

        out = league.assess(algo, RETURNS, {}, 10)

        assert events == ["snapshot", "evict"], "the new champion exists before the old one goes"
        assert [c["id"] for c in league.champion_history] == ["champion_2", "champion_3"]
        assert league.champion_count == 2 and out.promoted == 1
        assert "champion_1" not in league.available_modules

    def test_a_league_below_its_limit_evicts_nothing(self, monkeypatch):
        league = _league(champions=1, max_champions=3)
        algo = _algorithm()

        def snapshot(algorithm, source, value, iteration):
            league.champion_history.append(
                {
                    "id": "champion_2",
                    "source_policy": source,
                    "iteration": iteration,
                    "return": value,
                }
            )
            league.champion_count += 1

        monkeypatch.setattr(league, "create_snapshot", snapshot)

        league.assess(algo, RETURNS, {}, 10)

        algo.remove_module.assert_not_called()
        assert league.champion_count == 2
