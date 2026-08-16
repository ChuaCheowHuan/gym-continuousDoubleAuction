"""The episode-end NAV conservation check, in both halves.

The sum of every agent's NAV must equal the cash the system started with: the
ledger is Decimal end to end, so nothing is created or destroyed by trading,
only moved. A violation means the ledger is corrupt and every reward computed
from NAV after it is meaningless, which is why the run stops.

**The check is in two pieces, and the split is the point.** It used to be one:
`on_episode_end` raised, and the raise was the stop. That works only at
`num_env_runners=0`. The hook runs on the env runner, so with remote sampling
the raise arrives as a `RayTaskError` from `sample()`, RLlib's
`restart_failed_env_runners` (True by default) logs it through Ray's own logger
and restarts the actor, and `algo.train()` returns normally - the run carries on
training on the ledger the check just condemned. The raise also destroyed the
evidence: `synchronous_parallel_sample` asks each runner for
`(sample(), get_metrics())` in one call, so a throwing `sample()` means the
metrics for that runner are discarded with the error. See doc/21 §2.1.

So now the callback *reports* - the ERROR, `nav_conservation_error`, and a
`nav_conservation_violations` count - and `train._check_nav_conservation` acts
on it, on the driver, where an exception genuinely ends a run. These tests cover
both halves and the seam between them.
"""
import logging
import sys
import os
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

# Add the project root to sys.path to allow imports from gym_continuousDoubleAuction
# Assuming the tests are run from the project root or the test directory
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from ray.rllib.utils.metrics import ENV_RUNNER_RESULTS

from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import (
    NAV_VIOLATIONS_METRIC,
    SelfPlayCallback,
)
from gym_continuousDoubleAuction.train.train import (
    NavConservationError,
    TrainConfig,
    _check_nav_conservation,
    nav_violations,
)

LOGGER = "gym_continuousDoubleAuction"


class MockEpisode:
    def __init__(self, id, last_info):
        self.id_ = id
        self.last_info = last_info

    def get_infos(self, index):
        if index == -1:
            return self.last_info
        return {}


class MockEnv:
    def __init__(self, init_cash, num_of_agents):
        self.init_cash = init_cash
        self.num_of_agents = num_of_agents


def _emitted(metrics, name):
    """The last call that logged `name`, or None."""
    found = None
    for call in metrics.log_value.call_args_list:
        if call.args and call.args[0] == name:
            found = call
    return found


class TestNAVCallback:
    def setup_method(self):
        self.init_cash = 1000000
        self.num_agents = 4
        self.mock_env = MockEnv(self.init_cash, self.num_agents)
        self.mock_runner = MagicMock()
        # Mocking the config in env_runner to test the robust parameter retrieval
        self.mock_runner.config = MagicMock()
        self.mock_runner.config.env_config = {
            "init_cash": self.init_cash,
            "num_of_agents": self.num_agents
        }

    def _callback(self, **kwargs):
        """A callback that writes no episode record.

        The previous version of these tests left `episode_data_dir` at its
        configured default, so running them dropped files into the repo's
        `episode_data/` - which is where the two committed .pkl fixtures came
        from.
        """
        kwargs.setdefault("episode_data_dir", None)
        return SelfPlayCallback(
            num_trainable_policies=2, num_random_policies=2, **kwargs
        )

    def _end_episode(self, callback, episode_id, nav_each, metrics_logger=None):
        info = {
            f"agent_{i}": {"NAV": str(float(nav_each))}
            for i in range(self.num_agents)
        }
        callback.on_episode_end(
            episode=MockEpisode(episode_id, info),
            env_runner=self.mock_runner,
            metrics_logger=metrics_logger,
            env=self.mock_env,
            env_index=0,
            rl_module=None,
        )

    def test_conserved_navs_pass_and_log_zero_error(self):
        callback = self._callback()
        metrics = MagicMock()

        self._end_episode(callback, "ep_success", self.init_cash, metrics)

        assert _emitted(metrics, "nav_conservation_error").args[1] == pytest.approx(0.0)

    def test_a_conserved_episode_reports_zero_violations(self):
        """The counter is emitted every episode, not only on a violation.

        A key that only appears when something is wrong forces the driver to
        distinguish "no violations" from "the metric never arrived" - which are
        different states with the same reading, and the second one is what a
        crashed runner produces.
        """
        callback = self._callback()
        metrics = MagicMock()

        self._end_episode(callback, "ep_success", self.init_cash, metrics)

        call = _emitted(metrics, NAV_VIOLATIONS_METRIC)
        assert call.args[1] == 0.0
        assert call.kwargs["reduce"] == "sum"

    def test_a_violation_is_counted_and_does_not_raise(self):
        """The hook reports; the driver decides.

        Raising here is what used to happen, and on an env runner it is
        swallowed by RLlib's fault tolerance - so it stopped nothing and cost
        the iteration its metrics.
        """
        callback = self._callback()
        assert callback.strict_nav_check is True
        metrics = MagicMock()

        self._end_episode(callback, "ep_failure", self.init_cash - 1000, metrics)

        assert _emitted(metrics, NAV_VIOLATIONS_METRIC).args[1] == 1.0
        assert _emitted(metrics, "nav_conservation_error").args[1] == pytest.approx(
            1000.0 * self.num_agents
        )

    def test_a_violation_is_logged_as_an_error(self, caplog):
        callback = self._callback()

        with caplog.at_level(logging.ERROR, logger=LOGGER):
            self._end_episode(callback, "ep_failure", self.init_cash - 1000)

        assert "NAV conservation VIOLATED" in caplog.text
        assert any(r.levelno == logging.ERROR for r in caplog.records)

    def test_tolerance_admits_a_difference_below_it(self):
        """The tolerance is headroom for real cash leaving the system, not
        arithmetic slack: the check is Decimal end to end, so it is what
        separates a legitimate difference from a corrupt ledger."""
        drift = 0.001
        per_agent = self.init_cash + drift / self.num_agents

        tolerant = self._callback(nav_tolerance=1.0)
        metrics = MagicMock()
        self._end_episode(tolerant, "ep_within", per_agent, metrics)
        assert _emitted(metrics, NAV_VIOLATIONS_METRIC).args[1] == 0.0

        strict = self._callback(nav_tolerance=1e-9)
        metrics = MagicMock()
        self._end_episode(strict, "ep_outside", per_agent, metrics)
        assert _emitted(metrics, NAV_VIOLATIONS_METRIC).args[1] == 1.0

    def test_a_breach_is_caught_at_an_account_size_float_cannot_resolve(self):
        """The check must be Decimal end to end, not float.

        At init_cash 1e15 the spacing between adjacent floats near the total is
        0.5, so a real quarter-dollar of destroyed cash rounds to exactly 0.0 -
        the old float() round trip reported perfect conservation and the run
        continued on a corrupt ledger. Decimal sees the 0.25. The cliff is at
        roughly init_cash 1e10; see doc/16 §16.10.
        """
        self.init_cash = 10 ** 15
        self.mock_env = MockEnv(self.init_cash, self.num_agents)
        callback = self._callback()
        metrics = MagicMock()

        # 0.0625 short per agent = 0.25 destroyed across the four of them.
        info = {
            f"agent_{i}": {"NAV": str(Decimal(self.init_cash) - Decimal("0.0625"))}
            for i in range(self.num_agents)
        }
        callback.on_episode_end(
            episode=MockEpisode("ep_large", info),
            env_runner=self.mock_runner,
            metrics_logger=metrics,
            env=self.mock_env,
            env_index=0,
            rl_module=None,
        )

        assert _emitted(metrics, NAV_VIOLATIONS_METRIC).args[1] == 1.0
        assert _emitted(metrics, "nav_conservation_error").args[1] == pytest.approx(0.25)

    def test_conservation_error_is_exactly_zero_not_merely_close(self):
        """Decimal end to end means the expected error is 0, so a tolerance of
        0 is a usable setting rather than an impossible one."""
        callback = self._callback(nav_tolerance=0.0)
        metrics = MagicMock()

        # Long fractional tails that cancel exactly - what the ledger produces.
        tails = ["0.000000000000000000001", "-0.000000000000000000001",
                 "0.000000000000000000002", "-0.000000000000000000002"]
        info = {
            f"agent_{i}": {"NAV": str(Decimal(self.init_cash) + Decimal(t))}
            for i, t in enumerate(tails)
        }
        callback.on_episode_end(
            episode=MockEpisode("ep_exact", info),
            env_runner=self.mock_runner,
            metrics_logger=metrics,
            env=self.mock_env,
            env_index=0,
            rl_module=None,
        )

        assert _emitted(metrics, "nav_conservation_error").args[1] == 0.0
        assert _emitted(metrics, NAV_VIOLATIONS_METRIC).args[1] == 0.0

    def test_no_metrics_logger_is_tolerated(self):
        """The hook is also driven by tests and by a runner mid-restore."""
        callback = self._callback()
        self._end_episode(callback, "ep_failure", self.init_cash - 1000, None)

    def test_config_supplies_the_defaults(self):
        """Neither knob is a literal in the callback."""
        from gym_continuousDoubleAuction.config_loader import group

        league = group("train_config.json", "league_self_play")
        callback = self._callback()

        assert callback.nav_tolerance == league["nav_tolerance"]
        assert callback.strict_nav_check == league["strict_nav_check"]


class TestDriverCheck:
    """The half that actually stops the run.

    Everything here reads the result dict RLlib hands back, because that is the
    only channel a violation on a remote env runner travels on.
    """

    def _cfg(self, **kwargs):
        return TrainConfig(episode_data_dir=None, **kwargs)

    def _result(self, violations):
        return {ENV_RUNNER_RESULTS: {NAV_VIOLATIONS_METRIC: violations}}

    def test_a_clean_iteration_passes(self):
        _check_nav_conservation(3, self._result(0.0), self._cfg())

    def test_a_violation_stops_a_strict_run(self):
        cfg = self._cfg(strict_nav_check=True)

        with pytest.raises(NavConservationError, match="iteration 7"):
            _check_nav_conservation(7, self._result(2.0), cfg)

    def test_it_is_still_an_assertion_error(self):
        """doc/11 §1.5 has always documented this as an AssertionError, and any
        `except AssertionError` written around a training call still works."""
        assert issubclass(NavConservationError, AssertionError)

    def test_a_non_strict_run_warns_and_continues(self, caplog):
        cfg = self._cfg(strict_nav_check=False)

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            _check_nav_conservation(7, self._result(2.0), cfg)

        assert "strict_nav_check is off" in caplog.text

    def test_the_driver_says_where_the_detail_is(self, caplog):
        """With remote runners the per-episode ERROR is in a *worker's* file.
        A driver log that only said "violated" would send a reader to the one
        file that does not have the numbers."""
        cfg = self._cfg(strict_nav_check=False)

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            _check_nav_conservation(1, self._result(1.0), cfg)

        assert "run.<pid>.<worker>.log" in caplog.text

    def test_a_missing_metric_reads_as_no_violations(self):
        """An iteration that completed no episode never emits the counter, and
        that must not look like a failure of its own."""
        assert nav_violations({}) == 0.0
        assert nav_violations({ENV_RUNNER_RESULTS: {}}) == 0.0
        _check_nav_conservation(1, {}, self._cfg(strict_nav_check=True))

    def test_an_unreadable_metric_reads_as_no_violations(self):
        """RLlib nests metrics differently across versions. A shape this cannot
        parse must degrade to "nothing seen", not stop a healthy run."""
        assert nav_violations({ENV_RUNNER_RESULTS: {NAV_VIOLATIONS_METRIC: {}}}) == 0.0
