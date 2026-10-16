"""Issue #286: the realised / unrealised P&L split and adverse-selection mark-outs.

The split is checked against the one thing that can falsify it: the ledger. With the
fees it must account for NAV, to the last digit the ledger keeps, through partial
closes, flips, fees, liquidation and ADL.
"""
from decimal import Decimal
from unittest.mock import MagicMock

import numpy as np
import pytest

from gym_continuousDoubleAuction.envs.account.account import Account
from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import (
    MODULE_PERFORMANCE_PREFIX,
    SelfPlayCallback,
    _market_mid,
)
from gym_continuousDoubleAuction.train.performance import METRICS, PerformanceTally
from gym_continuousDoubleAuction.train.train import TrainConfig, build_config


def _fill(acc, side, price, qty):
    trade = {"price": Decimal(price), "quantity": qty, "init_party": {"ID": acc.ID, "side": side}}
    acc.process_acc(trade, "init_party", fee_role="none")


class TestRealisedPnl:

    def test_a_partial_close_realises_against_the_average_entry(self):
        acc = Account(0, 100_000)
        _fill(acc, "bid", 100, 10)
        _fill(acc, "ask", 110, 4)
        assert acc.realised_pnl == 40 and acc.net_position == 6
        assert acc.entry_vwap == 100            # a partial close leaves it alone

    def test_closing_the_rest_adds_to_it(self):
        acc = Account(0, 100_000)
        _fill(acc, "bid", 100, 10)
        _fill(acc, "ask", 110, 4)
        _fill(acc, "ask", 90, 6)
        assert acc.realised_pnl == 40 - 60 and acc.net_position == 0

    def test_a_short_realises_the_other_way(self):
        acc = Account(0, 100_000)
        _fill(acc, "ask", 100, 5)
        _fill(acc, "bid", 90, 2)
        assert acc.realised_pnl == 20

    def test_a_flip_realises_only_what_it_closes(self):
        acc = Account(0, 100_000)
        _fill(acc, "bid", 100, 3)
        _fill(acc, "ask", 110, 5)               # closes 3, opens a 2-short at 110
        assert acc.realised_pnl == 30
        assert acc.net_position == -2 and acc.entry_vwap == 110

    def test_adding_to_a_position_realises_nothing(self):
        acc = Account(0, 100_000)
        _fill(acc, "bid", 100, 3)
        _fill(acc, "bid", 120, 3)
        assert acc.realised_pnl == 0 and acc.entry_vwap == 110

    def test_a_fee_is_not_in_it(self):
        acc = Account(0, 100_000, 0, 10)
        trade = {"price": Decimal(100), "quantity": 10, "init_party": {"ID": 0, "side": "bid"}}
        acc.process_acc(trade, "init_party")
        trade = {"price": Decimal(110), "quantity": 10, "init_party": {"ID": 0, "side": "ask"}}
        acc.process_acc(trade, "init_party")
        assert acc.realised_pnl == 100 and acc.fees_paid > 0

    def test_unrealised_is_the_open_position_at_the_mark(self):
        acc = Account(0, 100_000)
        _fill(acc, "bid", 100, 10)
        assert acc.unrealised_pnl(Decimal(107)) == 70
        flat = Account(1, 1000)
        assert flat.unrealised_pnl(Decimal(50)) == 0
        _fill(flat, "ask", 100, 4)
        assert flat.unrealised_pnl(Decimal(93)) == 28

    def test_a_reset_clears_it(self):
        acc = Account(0, 100_000)
        _fill(acc, "bid", 100, 2)
        _fill(acc, "ask", 120, 2)
        acc.reset_acc(0, 100_000)
        assert acc.realised_pnl == 0 and acc.fill_qty_step == 0 and acc.fill_value_step == 0


class TestTheSplitAccountsForNav:
    """`nav - init_nav == realised + unrealised - fees_paid`, in random play."""

    @pytest.mark.parametrize("clearing", ["sequential", "batch"])
    @pytest.mark.parametrize("fee", [0, 10])
    def test_it_holds_every_agent_every_step(self, clearing, fee):
        env = continuousDoubleAuctionEnv({
            "num_of_agents": 4, "max_step": 150, "is_render": False, "step_clearing": clearing,
            "taker_fee_bps": fee, "maker_fee_bps": fee // 2, "init_cash": 100_000,
            "initial_price_min": 80, "initial_price_max": 120,
            "liquidation": "market_adl", "maintenance_margin": 0.3})
        env.reset(seed=2)
        banked = 0
        for _ in range(150):
            _o, _r, term, trunc, _i = env.step({a: env.action_spaces[a].sample() for a in env.agents})
            mark = env.mark_price()
            for trader in env.traders:
                acc = trader.acc
                lhs = acc.nav - acc.init_nav
                rhs = acc.realised_pnl + acc.unrealised_pnl(mark) - acc.fees_paid
                assert abs(lhs - rhs) < Decimal("1e-9"), (trader.ID, lhs, rhs)
                banked += acc.realised_pnl != 0
            if term["__all__"] or trunc["__all__"]:
                break
        assert banked > 0, "no trader ever realised anything: the identity was vacuous"


class TestFillCounters:

    def test_buys_are_positive_sells_negative_and_the_value_is_signed_too(self):
        acc = Account(0, 100_000)
        _fill(acc, "bid", 100, 10)
        _fill(acc, "ask", 110, 4)
        assert acc.fill_qty_step == 6 and acc.fill_value_step == 1000 - 440

    def test_they_are_zeroed_every_step(self):
        env = continuousDoubleAuctionEnv({"num_of_agents": 2, "is_render": False})
        env.reset(seed=1)
        t = env.traders
        t[1].place_order("limit", "ask", 5, 101.0, env.LOB, t)
        t[0].place_order("market", "bid", 3, -1.0, env.LOB, t)
        assert t[0].acc.fill_qty_step == 3
        pass_all = {a: {"category": 0, "order_slot": 0, "price": 0, "price_offset": 1,
                        "size": np.zeros(1, dtype=np.float32)} for a in env.agents}
        env.step(pass_all)
        assert t[0].acc.fill_qty_step == 0 and t[0].acc.fill_value_step == 0

    def test_info_carries_the_four_fields_with_their_types(self):
        env = continuousDoubleAuctionEnv({"num_of_agents": 2, "is_render": False})
        env.reset(seed=1)
        _o, _r, _t, _tr, infos = env.step({a: env.action_spaces[a].sample() for a in env.agents})
        info = infos["agent_0"]
        assert isinstance(info["realised_pnl"], float) and isinstance(info["unrealised_pnl"], float)
        assert isinstance(info["fill_qty_step"], int) and isinstance(info["fill_value_step"], float)


class TestForcedFillsAreNotTheAgentsExecutions:
    """A liquidation is realised P&L, but not an execution to mark out."""

    @staticmethod
    def _squeeze():
        env = continuousDoubleAuctionEnv({
            "num_of_agents": 4, "init_cash": 10_000, "max_step": 50, "is_render": False,
            "initial_price_min": 100, "initial_price_max": 100})
        env.reset(seed=1)
        t = env.traders
        t[1].place_order("limit", "bid", 90, 100.0, env.LOB, t)
        t[0].place_order("market", "ask", 90, -1.0, env.LOB, t)
        t[2].place_order("limit", "bid", 1, 170.0, env.LOB, t)
        t[3].place_order("limit", "ask", 50, 180.0, env.LOB, t)
        env.mark_to_mkt()
        return env

    def test_the_liquidated_traders_fill_counters_do_not_move(self):
        env = self._squeeze()
        victim = env.traders[0].acc
        before = (victim.fill_qty_step, victim.fill_value_step)
        env.liquidate()
        assert env.traders[0].acc.net_position == 0
        assert (victim.fill_qty_step, victim.fill_value_step) == before

    def test_but_the_loss_is_realised(self):
        env = self._squeeze()
        env.liquidate()
        assert env.traders[0].acc.realised_pnl < 0

    def test_the_counterparty_that_made_the_market_still_counts_its_fill(self):
        env = self._squeeze()
        maker = env.traders[3].acc
        before = maker.fill_qty_step
        env.liquidate()
        assert maker.fill_qty_step < before         # it sold into the forced buy


class TestMarkouts:

    @staticmethod
    def _run(steps, horizons=(1, 2)):
        tally = PerformanceTally(markout_horizons=horizons)
        for qty, value, mid in steps:
            tally.update("1000", 0, fill_qty=qty, fill_value=value, mid=mid)
        return tally.summary()

    def test_a_buy_that_the_price_then_beat(self):
        # buy 10 @ 100; the mid is 103 a step later and 99 two later.
        summary = self._run([(10, 1000, 101), (0, 0, 103), (0, 0, 99)])
        assert summary["markout_1"] == pytest.approx(3.0)
        assert summary["markout_2"] == pytest.approx(-1.0)

    def test_a_sell_is_signed_the_other_way(self):
        # sell 10 @ 100; the mid falls to 97: the agent sold before the drop.
        summary = self._run([(-10, -1000, 100), (0, 0, 97)], horizons=(1,))
        assert summary["markout_1"] == pytest.approx(3.0)

    def test_it_is_per_contract_over_every_resolved_fill(self):
        summary = self._run([(10, 1000, 100), (-5, -520, 104), (0, 0, 106)], horizons=(1,))
        # step0 buy 10 @100 marked at 104: +40; step1 sell 5 @104 marked at 106: -10
        assert summary["markout_1"] == pytest.approx((40 - 10) / 15)

    def test_a_fill_whose_horizon_passes_the_end_is_dropped_not_marked_at_the_last_price(self):
        summary = self._run([(10, 1000, 101)], horizons=(5,))
        assert summary["markout_5"] is None

    def test_steps_without_fills_contribute_nothing(self):
        assert self._run([(0, 0, 100)] * 5)["markout_1"] is None

    def test_a_missing_mid_resolves_nothing_but_keeps_the_clock(self):
        tally = PerformanceTally(markout_horizons=(1,))
        tally.update("1000", 0, fill_qty=10, fill_value=1000, mid=100)
        tally.update("1000", 0, mid=None)            # nothing to mark with
        tally.update("1000", 0, mid=105)             # the fill of step 1 (none) resolves
        assert tally.summary()["markout_1"] is None

    def test_no_horizons_means_no_markout_keys(self):
        assert not [k for k in PerformanceTally().summary() if k.startswith("markout")]

    def test_invalid_horizons_are_ignored_and_duplicates_collapse(self):
        assert PerformanceTally(markout_horizons=(0, -2, 3, 3)).horizons == (3,)

    def test_the_pnl_split_is_reported_as_the_last_value_fed(self):
        tally = PerformanceTally()
        tally.update("1000", 0, realised=5.0, unrealised=1.0)
        tally.update("1010", 0, realised=7.5, unrealised=-2.0)
        summary = tally.summary()
        assert summary["realised_pnl"] == 7.5 and summary["unrealised_pnl"] == -2.0

    def test_the_fixed_names_include_the_split(self):
        assert "realised_pnl" in METRICS and "unrealised_pnl" in METRICS


class TestMarketMid:

    def test_two_sided_book_uses_the_midpoint(self):
        assert _market_mid({"best_bid": 99.0, "best_ask": 101.0, "last_price": 50.0}) == 100.0

    def test_one_sided_falls_back_to_the_last_price(self):
        assert _market_mid({"best_bid": 99.0, "best_ask": None, "last_price": 98.0}) == 98.0

    def test_nothing_is_none(self):
        assert _market_mid({}) is None


def _callback(**kwargs):
    return SelfPlayCallback(num_trainable_policies=2, num_random_policies=6,
                            episode_data_dir=None, **kwargs)


class TestTheCallbackWiring:

    def test_the_step_hook_feeds_pnl_fills_and_mid(self):
        cb = _callback(markout_horizons=(1,))

        class Ep:
            id_ = "e"

            def __init__(self, info):
                self._info = {"agent_0": info}

            def get_infos(self, index):
                return self._info

        steps = [
            {"NAV": "1000", "net_position": 0, "realised_pnl": 0.0, "unrealised_pnl": 0.0,
             "fill_qty_step": 10, "fill_value_step": 1000.0, "best_bid": 99.0, "best_ask": 101.0},
            {"NAV": "1030", "net_position": 10, "realised_pnl": 0.0, "unrealised_pnl": 30.0,
             "fill_qty_step": 0, "fill_value_step": 0.0, "best_bid": 102.0, "best_ask": 104.0},
        ]
        for info in steps:
            cb.on_episode_step(episode=Ep(info), env_runner=None, metrics_logger=MagicMock(),
                               env=None, env_index=0, rl_module=None)
        summary = cb._activity["e"]["performance"]["agent_0"].summary()
        assert summary["unrealised_pnl"] == 30.0
        assert summary["markout_1"] == pytest.approx(3.0)      # 10 x 103 - 1000, per contract

    def test_markouts_are_logged_per_module(self):
        tally = PerformanceTally(markout_horizons=(1,))
        tally.update("1000", 0, fill_qty=10, fill_value=1000, mid=100)
        tally.update("1000", 0, mid=103)

        class Ep:
            def module_for(self, agent):
                return "policy_0"

        metrics = MagicMock()
        _callback()._log_module_performance(Ep(), {"performance": {"agent_0": tally}}, metrics)
        logged = {c.args[0]: c.args[1] for c in metrics.log_value.call_args_list}
        assert logged[(MODULE_PERFORMANCE_PREFIX + "markout_1", "policy_0")] == pytest.approx(3.0)

    def test_the_default_horizons_come_from_the_config(self):
        assert TrainConfig().markout_horizons == [1, 10]
        assert _callback().markout_horizons == (1, 10)

    def test_train_config_hands_them_to_the_callback(self):
        _ppo, callback = build_config(TrainConfig(markout_horizons=[2, 5]))
        assert callback.markout_horizons == (2, 5)

    @pytest.mark.parametrize("bad", [[0], [-1, 3]])
    def test_a_non_positive_horizon_is_refused_naming_the_key(self, bad):
        with pytest.raises(ValueError, match="markout_horizons"):
            TrainConfig(markout_horizons=bad)
        with pytest.raises(ValueError, match="markout_horizons"):
            _callback(markout_horizons=bad)

    def test_an_empty_list_switches_them_off(self):
        assert _callback(markout_horizons=[]).markout_horizons == ()

    def test_a_callback_saved_before_the_key_has_none(self):
        state = _callback().__getstate__()
        del state["markout_horizons"]
        old = SelfPlayCallback.__new__(SelfPlayCallback)
        old.__setstate__(state)
        assert old.markout_horizons == ()
