"""doc/15 S3-9: risk-adjusted metrics from running sums.

The arithmetic is checked against a four-step series worked by hand, so a change to a
definition (annualising, a different denominator, counting passes in the hit rate) fails
here rather than quietly moving every reported number.
"""
import math
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import (
    MODULE_PERFORMANCE_PREFIX,
    SelfPlayCallback,
)
from gym_continuousDoubleAuction.train.performance import METRICS, PerformanceTally

#: NAV 100 -> 110 -> 99 -> 120 -> 120, with these net positions.
SERIES = [("100", 0), ("110", 5), ("99", 5), ("120", -2), ("120", -2)]


def _tally(series=SERIES):
    tally = PerformanceTally()
    for nav, position in series:
        tally.update(nav, position)
    return tally


class TestTheDefinitions:
    """Returns are +0.1, -0.1, +0.21212 (120/99 - 1) and 0."""

    def test_sharpe_is_mean_over_sample_std_not_annualised(self):
        returns = [0.1, -0.1, 120 / 99 - 1, 0.0]
        mean = sum(returns) / 4
        std = math.sqrt(sum((r - mean) ** 2 for r in returns) / 3)
        assert _tally().sharpe() == pytest.approx(mean / std)

    def test_sortino_uses_the_downside_over_every_step(self):
        returns = [0.1, -0.1, 120 / 99 - 1, 0.0]
        downside = math.sqrt(sum(min(r, 0) ** 2 for r in returns) / 4)
        assert _tally().sortino() == pytest.approx((sum(returns) / 4) / downside)

    def test_max_drawdown_is_the_largest_peak_to_trough_fraction(self):
        assert _tally().max_drawdown == pytest.approx((110 - 99) / 110)

    def test_hit_rate_counts_only_steps_that_moved(self):
        # two up, one down; the flat last step is neither.
        assert _tally().hit_rate() == pytest.approx(2 / 3)

    def test_turnover_is_the_sum_of_position_changes(self):
        assert _tally().turnover == 5 + 0 + 7 + 0

    def test_inventory_is_mean_and_max_absolute_position(self):
        summary = _tally().summary()
        assert summary["mean_abs_position"] == pytest.approx((0 + 5 + 5 + 2 + 2) / 5)
        assert summary["max_abs_position"] == 5

    def test_every_metric_is_reported_under_a_fixed_name(self):
        assert tuple(_tally().summary()) == METRICS


class TestUndefinedIsNotZero:

    def test_an_agent_that_did_nothing_has_no_sharpe_sortino_or_hit_rate(self):
        summary = _tally([("100", 0)] * 5).summary()
        assert summary["sharpe"] is None and summary["sortino"] is None
        assert summary["hit_rate"] is None
        assert summary["max_drawdown"] == 0.0           # it is defined, and it is zero
        assert summary["position_turnover"] == 0.0

    def test_no_losing_step_means_no_sortino(self):
        assert _tally([("100", 0), ("101", 0), ("103", 0)]).sortino() is None

    def test_one_step_has_no_sharpe(self):
        assert _tally([("100", 0), ("101", 0)]).sharpe() is None

    def test_an_empty_tally_is_all_none(self):
        assert all(v is None for v in PerformanceTally().summary().values())


class TestBadInput:

    def test_a_nonpositive_previous_nav_gives_no_return_for_that_step(self):
        tally = _tally([("0", 0), ("10", 0), ("20", 0)])
        assert tally.n == 1                              # only 10 -> 20

    def test_a_negative_nav_does_not_divide_by_it(self):
        tally = _tally([("-5", 0), ("10", 0)])
        assert tally.n == 0 and tally.max_drawdown == 0.0

    @pytest.mark.parametrize("bad", [None, "nan", "x", float("inf"), ""])
    def test_a_bad_nav_is_skipped_not_raised(self, bad):
        tally = PerformanceTally()
        tally.update("100", 0)
        tally.update(bad, 1)
        tally.update("110", 1)
        assert tally.n == 1 and tally.sharpe() is None

    def test_a_missing_position_still_scores_the_nav(self):
        tally = PerformanceTally()
        for nav in ("100", "110", "99"):
            tally.update(nav, None)
        assert tally.n == 2 and tally.summary()["position_turnover"] is None

    def test_nav_is_taken_exactly_not_through_a_float_string(self):
        tally = PerformanceTally()
        tally.update(Decimal("1000000000000000.01"), 0)
        tally.update(Decimal("1000000000000000.02"), 0)
        assert tally._sum > 0                            # a float round trip makes this 0


def _callback():
    return SelfPlayCallback(num_trainable_policies=2, num_random_policies=6,
                            episode_data_dir=None)


class _Episode:
    def __init__(self, modules):
        self._modules = modules

    def module_for(self, agent_id):
        return self._modules.get(agent_id)


class TestTheCallbackLogsPerModule:

    @staticmethod
    def _logged(tally, modules):
        metrics = MagicMock()
        _callback()._log_module_performance(_Episode(modules), {"performance": tally}, metrics)
        return {c.args[0]: (c.args[1], c.kwargs) for c in metrics.log_value.call_args_list}

    def test_each_metric_is_keyed_by_module(self):
        logged = self._logged({"agent_0": _tally()}, {"agent_0": "policy_0"})
        assert (MODULE_PERFORMANCE_PREFIX + "sharpe", "policy_0") in logged
        assert set(k[0] for k in logged) == {MODULE_PERFORMANCE_PREFIX + m for m in METRICS}

    def test_it_is_a_mean_over_the_iteration(self):
        logged = self._logged({"agent_0": _tally()}, {"agent_0": "policy_0"})
        assert all(kwargs == {"reduce": "mean"} for _v, kwargs in logged.values())

    def test_two_agents_on_one_module_count_once(self):
        a, b = _tally(), _tally([("100", 0), ("120", 10), ("90", 10)])
        logged = self._logged({"agent_0": a, "agent_1": b},
                              {"agent_0": "policy_2", "agent_1": "policy_2"})
        expected = (a.max_drawdown + b.max_drawdown) / 2
        assert logged[(MODULE_PERFORMANCE_PREFIX + "max_drawdown", "policy_2")][0] == pytest.approx(expected)

    def test_an_undefined_metric_is_left_out_not_logged_as_zero(self):
        logged = self._logged({"agent_0": _tally([("100", 0)] * 4)}, {"agent_0": "policy_0"})
        assert (MODULE_PERFORMANCE_PREFIX + "sharpe", "policy_0") not in logged
        assert (MODULE_PERFORMANCE_PREFIX + "max_drawdown", "policy_0") in logged

    def test_an_episode_that_cannot_name_modules_logs_nothing(self):
        metrics = MagicMock()
        _callback()._log_module_performance(object(), {"performance": {"a": _tally()}}, metrics)
        metrics.log_value.assert_not_called()

    def test_an_agent_with_no_module_is_skipped(self):
        assert self._logged({"agent_0": _tally()}, {}) == {}

    def test_the_step_hook_feeds_the_tally(self):
        cb = _callback()

        class Ep:
            id_ = "e1"

            def __init__(self, nav, pos):
                self._info = {"agent_0": {"NAV": nav, "net_position": pos}}

            def get_infos(self, index):
                return self._info

        for nav, pos in SERIES:
            cb.on_episode_step(episode=Ep(nav, pos), env_runner=None,
                               metrics_logger=MagicMock(), env=None, env_index=0,
                               rl_module=None)
        perf = cb._activity["e1"]["performance"]["agent_0"]
        assert perf.summary() == _tally().summary()
