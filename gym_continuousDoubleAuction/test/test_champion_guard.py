"""docs/15 S3-11: a league that can promote a policy that has stopped trading.

Three things made it possible, and each is pinned here.

* `entropy_coeff` was RLlib's 0.0, so nothing pushed a policy away from
  collapsing to always-pass.
* `std_dev_multiplier` was 0.1, so a champion was promoted on the very first
  iteration, whatever it had learned.
* Nothing looked at whether the candidate traded. A policy that passes earns
  exactly 0, and 0 beats a league of modules that are losing money, so it
  cleared the return threshold and the pool filled with snapshots of it.
"""

import dataclasses
import logging
import math
from unittest.mock import MagicMock

import pytest

from gym_continuousDoubleAuction.logging_setup import ROOT_NAME as LOGGER
from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import (
    MODULE_TRADES_METRIC,
    SelfPlayCallback,
)
from gym_continuousDoubleAuction.train.train import TrainConfig, build_config


class TestEntropyBonus:
    def test_the_shipped_run_has_a_positive_decaying_bonus(self):
        cfg = TrainConfig()
        ppo = build_config(cfg)
        ppo = ppo[0] if isinstance(ppo, tuple) else ppo
        (t0, v0), (t1, v1) = ppo.entropy_coeff
        assert t0 == 0 and v0 == cfg.entropy_coeff > 0
        assert v1 == cfg.entropy_coeff_final and 0 < v1 < v0
        assert t1 == cfg.train_batch_size * cfg.entropy_decay_iters

    def test_equal_ends_are_a_constant(self):
        cfg = dataclasses.replace(TrainConfig(), entropy_coeff=0.005, entropy_coeff_final=0.005)
        assert cfg.entropy_setting == 0.005

    def test_zero_ends_are_the_old_behaviour(self):
        cfg = dataclasses.replace(TrainConfig(), entropy_coeff=0.0, entropy_coeff_final=0.0)
        assert cfg.entropy_setting == 0.0

    @pytest.mark.parametrize(
        "field,value",
        [
            ("entropy_coeff", -0.1),
            ("entropy_coeff_final", -0.1),
            ("entropy_decay_iters", 0),
            ("min_champion_trades", -1.0),
        ],
    )
    def test_nonsense_is_refused_naming_the_key(self, field, value):
        with pytest.raises(ValueError, match=field):
            dataclasses.replace(TrainConfig(), **{field: value})


def _callback(**kwargs):
    kwargs.setdefault("min_iterations_between_champions", 0)
    return SelfPlayCallback(num_trainable_policies=2, num_random_policies=6, **kwargs)


def _result(returns, trades=None, iteration=1):
    runner = {"module_episode_returns_mean": returns}
    if trades is not None:
        runner[MODULE_TRADES_METRIC] = trades
    return {"training_iteration": iteration, "env_runners": runner}


@pytest.fixture
def snapshots(monkeypatch):
    created = []

    def attach(cb):
        monkeypatch.setattr(
            cb.league,
            "create_snapshot",
            lambda algorithm, pid, value, iteration: created.append(pid),
        )
        return created

    return attach


#: A do-nothing policy_0 (return exactly 0) against modules losing money.
PASSIVE_LEAGUE = {
    "policy_0": 0.0,
    "policy_1": -50.0,
    **{f"policy_{i}": -100.0 + i for i in range(2, 8)},
}


class TestThePromotionGuard:
    def test_a_policy_that_stopped_trading_is_not_promoted(self, snapshots, caplog):
        cb = _callback()
        created = snapshots(cb)
        result = _result(PASSIVE_LEAGUE, trades={"policy_0": 0.0, "policy_1": 9.0})
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            cb.on_train_result(algorithm=object(), result=result)

        assert created == []
        assert result["league"]["refused_passive"] == 1
        assert "not promoting a policy that has stopped trading" in caplog.text

    def test_the_same_league_promotes_a_policy_that_trades(self, snapshots):
        cb = _callback()
        created = snapshots(cb)
        result = _result(PASSIVE_LEAGUE, trades={"policy_0": 12.0, "policy_1": 9.0})
        cb.on_train_result(algorithm=object(), result=result)

        assert created == ["policy_0"]
        assert result["league"]["refused_passive"] == 0

    def test_the_bar_is_inclusive(self, snapshots):
        cb = _callback(min_champion_trades=2.0)
        created = snapshots(cb)
        cb.on_train_result(
            algorithm=object(), result=_result(PASSIVE_LEAGUE, trades={"policy_0": 2.0})
        )
        assert created == ["policy_0"]

    def test_zero_switches_the_guard_off(self, snapshots):
        cb = _callback(min_champion_trades=0)
        created = snapshots(cb)
        cb.on_train_result(
            algorithm=object(), result=_result(PASSIVE_LEAGUE, trades={"policy_0": 0.0})
        )
        assert created == ["policy_0"]

    def test_missing_counts_do_not_block_and_are_reported(self, snapshots, caplog):
        """A guard that blocks on absent data would stop the league growing,
        silently and for good - the failure the NaN threshold once caused."""
        cb = _callback()
        created = snapshots(cb)
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            cb.on_train_result(algorithm=object(), result=_result(PASSIVE_LEAGUE))

        assert created == ["policy_0"]
        assert "guard could not run" in caplog.text

    def test_a_refusal_leaves_the_league_alone(self, snapshots):
        cb = _callback()
        snapshots(cb)
        cb.on_train_result(
            algorithm=object(), result=_result(PASSIVE_LEAGUE, trades={"policy_0": 0.0})
        )
        assert cb.champion_history == [] and cb.champion_count == 0

    def test_the_guard_only_asks_about_a_candidate_that_cleared_the_bar(self, snapshots, caplog):
        cb = _callback()
        snapshots(cb)
        flat = {f"policy_{i}": -10.0 for i in range(8)}
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            cb.on_train_result(algorithm=object(), result=_result(flat, trades={"policy_0": 0.0}))
        assert "not promoting" not in caplog.text


def _old_style_state(cb):
    """`cb.__getstate__()` as a checkpoint written before the league was an object held it:
    the league's attributes flat on the callback (issue #253)."""
    state = cb.__getstate__()
    state.update(vars(state.pop("league")))
    return state


class TestACallbackSavedBeforeTheGuard:
    """A resume takes its callback from the checkpoint, not from the config."""

    def _restored(self):
        cb = _callback(std_dev_multiplier=0.1)
        state = _old_style_state(cb)
        del state["min_champion_trades"]
        old = SelfPlayCallback.__new__(SelfPlayCallback)
        old.__setstate__(state)
        return old

    def test_it_does_not_crash_at_the_first_champion_check(self, snapshots):
        old = self._restored()
        created = snapshots(old)
        old.on_train_result(algorithm=object(), result=_result(PASSIVE_LEAGUE))
        assert created == ["policy_0"]

    def test_it_runs_without_the_guard_and_says_so(self, caplog):
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            old = self._restored()
        assert old.min_champion_trades == 0.0
        assert "passivity guard" in caplog.text and "fresh run" in caplog.text

    def test_a_current_callback_is_restored_without_a_warning(self, caplog):
        cb = _callback()
        fresh = SelfPlayCallback.__new__(SelfPlayCallback)
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            fresh.__setstate__(cb.__getstate__())
        assert "passivity guard" not in caplog.text
        assert fresh.min_champion_trades == cb.min_champion_trades


class TestTheShippedMultiplier:
    def test_it_is_not_the_one_that_promoted_on_the_first_iteration(self):
        assert _callback().std_dev_multiplier >= 1.5

    def test_barely_better_than_the_pack_is_not_a_champion(self, snapshots):
        cb = _callback()
        created = snapshots(cb)
        returns = {
            "policy_0": 1.0,
            "policy_1": 0.0,
            **{f"policy_{i}": float(i % 3 - 1) for i in range(2, 8)},
        }
        cb.on_train_result(algorithm=object(), result=_result(returns, trades={"policy_0": 20.0}))
        assert created == []

    def test_clearly_better_is(self, snapshots):
        cb = _callback()
        created = snapshots(cb)
        returns = {
            "policy_0": 100.0,
            "policy_1": 0.0,
            **{f"policy_{i}": float(i % 3 - 1) for i in range(2, 8)},
        }
        cb.on_train_result(algorithm=object(), result=_result(returns, trades={"policy_0": 20.0}))
        assert created == ["policy_0"]

    def test_a_multiplier_no_league_can_clear_is_warned_about(self, caplog):
        """With n modules nobody is more than sqrt(n - 1) standard deviations
        above the mean: 2.65 at the default 8, so 3.0 can never promote."""
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            _callback(std_dev_multiplier=3.0)
        assert "can never be cleared" in caplog.text
        assert f"{math.sqrt(7):.2f}" in caplog.text

    def test_the_shipped_one_is_not(self, caplog):
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            _callback()
        assert "can never be cleared" not in caplog.text


class MockEpisode:
    def __init__(self, modules):
        self.id_ = "ep"
        self._modules = modules

    def module_for(self, agent_id):
        return self._modules.get(agent_id)


class TestTheTradeCountsTravel:
    def _log(self, modules, fills, reporting):
        cb = _callback(episode_data_dir=None)
        metrics = MagicMock()
        tally = {"last_nav": {a: "0" for a in reporting}, "per_agent_fills": fills}
        cb._log_module_trades(MockEpisode(modules), tally, metrics)
        return {
            c.args[0][1]: (c.args[1], c.kwargs)
            for c in metrics.log_value.call_args_list
            if c.args[0][0] == MODULE_TRADES_METRIC
        }

    def test_each_module_reports_its_agents_trades(self):
        out = self._log(
            {"agent_0": "policy_0", "agent_1": "policy_1"},
            {"agent_0": {"trades": 7, "passive": 3}},
            reporting=["agent_0", "agent_1"],
        )
        assert out["policy_0"][0] == 7.0

    def test_an_agent_that_never_traded_reports_zero_not_nothing(self):
        out = self._log(
            {"agent_0": "policy_0", "agent_1": "policy_1"},
            {"agent_0": {"trades": 7, "passive": 3}},
            reporting=["agent_0", "agent_1"],
        )
        assert out["policy_1"][0] == 0.0

    def test_it_is_a_mean_over_the_iteration(self):
        out = self._log({"agent_0": "policy_0"}, {}, reporting=["agent_0"])
        assert out["policy_0"][1] == {"reduce": "mean"}

    def test_an_episode_that_cannot_name_modules_logs_nothing(self):
        cb = _callback(episode_data_dir=None)
        metrics = MagicMock()
        cb._log_module_trades(object(), {"last_nav": {"a": "0"}, "per_agent_fills": {}}, metrics)
        metrics.log_value.assert_not_called()
