"""The episode-end NAV conservation check.

The sum of every agent's NAV must equal the cash the system started with: the
ledger is Decimal end to end, so nothing is created or destroyed by trading,
only moved. A violation means the ledger is corrupt and every reward computed
from NAV after it is meaningless, which is why the default is to raise.

These tests used to call `on_episode_end` twice and assert nothing at all -
they passed as long as it did not throw, which is precisely the behaviour that
is now under test. See doc/11_logging_and_observability.md.
"""
import logging
import sys
import os
from unittest.mock import MagicMock

import pytest

# Add the project root to sys.path to allow imports from gym_continuousDoubleAuction
# Assuming the tests are run from the project root or the test directory
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import SelfPlayCallback

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
        """A callback that writes no episode pickles.

        The previous version of these tests left `episode_data_dir` at its
        configured default, so running them dropped two .pkl files into the
        repo's `episode_data/` - which is where the two committed fixtures came
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

        metrics.log_value.assert_called_once_with(
            "nav_conservation_error", pytest.approx(0.0), window=1
        )

    def test_violation_raises_under_the_default(self):
        """Strict is the default: a corrupt ledger stops the run."""
        callback = self._callback()
        assert callback.strict_nav_check is True

        with pytest.raises(AssertionError, match="NAV conservation VIOLATED"):
            self._end_episode(callback, "ep_failure", self.init_cash - 1000)

    def test_violation_reports_the_metric_before_raising(self):
        """The metric is what a run is diagnosed from afterwards."""
        callback = self._callback()
        metrics = MagicMock()

        with pytest.raises(AssertionError):
            self._end_episode(callback, "ep_failure", self.init_cash - 1000, metrics)

        metrics.log_value.assert_called_once_with(
            "nav_conservation_error",
            pytest.approx(1000.0 * self.num_agents),
            window=1,
        )

    def test_non_strict_logs_an_error_and_continues(self, caplog):
        callback = self._callback(strict_nav_check=False)

        with caplog.at_level(logging.ERROR, logger="gym_continuousDoubleAuction"):
            self._end_episode(callback, "ep_failure", self.init_cash - 1000)

        assert "NAV conservation VIOLATED" in caplog.text
        assert any(r.levelno == logging.ERROR for r in caplog.records)

    def test_tolerance_admits_a_difference_below_it(self):
        """The tolerance absorbs the float() round trip, nothing larger."""
        drift = 0.001
        per_agent = self.init_cash + drift / self.num_agents

        tolerant = self._callback(nav_tolerance=1.0)
        self._end_episode(tolerant, "ep_within", per_agent)  # no raise

        strict = self._callback(nav_tolerance=1e-9)
        with pytest.raises(AssertionError):
            self._end_episode(strict, "ep_outside", per_agent)

    def test_config_supplies_the_defaults(self):
        """Neither knob is a literal in the callback."""
        from gym_continuousDoubleAuction.config_loader import group

        league = group("train_config.json", "league_self_play")
        callback = self._callback()

        assert callback.nav_tolerance == league["nav_tolerance"]
        assert callback.strict_nav_check == league["strict_nav_check"]
