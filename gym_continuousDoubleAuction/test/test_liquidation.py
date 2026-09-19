"""Maintenance margin, liquidation in the book, and ADL as the backstop.

doc/04 section 8. Bankruptcy used to be checked only at NAV <= 0 and did not
close the position, so a bankrupt short stayed open and marked to market for
the rest of the episode - measured in CDA_train.ipynb at -1.9M, collected by
the agents on the other side from a counterparty that could not act. Now a
trader whose equity falls to `maintenance_margin` of its position's value is
closed out at the end of the step: book first, inside its bankruptcy price,
then ADL at the mark for whatever the book could not take.

Every scenario below is built by hand on a 4-agent book with 10,000 each, so
the numbers can be checked with a pencil. agent_0 goes short 90 @ 100 against
agent_1's bid; agents 2 and 3 then quote where the test needs the mid.
"""
import dataclasses
from decimal import Decimal

import numpy as np
import pytest

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.envs.exchg.liquidation_helper import Liquidation_Helper

CASH = 10000
TOTAL = Decimal(4 * CASH)


def _env(**overrides):
    config = {"num_of_agents": 4, "init_cash": CASH, "max_step": 50, "is_render": False,
              "initial_price_min": 100, "initial_price_max": 100}
    config.update(overrides)
    env = continuousDoubleAuctionEnv(config)
    env.reset(seed=1)
    return env


def _order(env, tid, type, side, size, price=-1.0):
    trader = env.traders[tid]
    trader.place_order(type, side, size, price, env.LOB, env.traders)


def _short_90(env):
    """agent_0 short 90 @ 100 (9,000 of its 10,000 in the position), agent_1 long 90."""
    _order(env, 1, "limit", "bid", 90, 100.0)
    _order(env, 0, "market", "ask", 90)
    assert env.traders[0].acc.net_position == -90
    assert env.traders[1].acc.net_position == 90


def _pass(env):
    return {agent: {"category": 0, "order_slot": 0, "price": 0, "price_offset": 1,
                    "size_mean": np.zeros(1, dtype=np.float32),
                    "size_sigma": np.zeros(1, dtype=np.float32)}
            for agent in env.agents}


def _total_nav(env):
    return sum(t.acc.nav for t in env.traders)


class TestTheTrigger:

    def test_a_squeezed_short_breaches_before_it_is_bankrupt(self):
        env = _env()
        _short_90(env)
        _order(env, 2, "limit", "bid", 1, 170.0)
        _order(env, 3, "limit", "ask", 50, 180.0)
        env.mark_to_mkt()
        # mid 175: NAV 10,000 - 90 x 75 = 3,250 > 0, but below
        # 0.3 x 90 x 175 = 4,725 - so margin called, not yet bankrupt.
        assert env.mark_price() == Decimal(175)
        assert env.traders[0].acc.nav == Decimal(3250)
        assert env._in_breach(env.traders[0], env.mark_price())

    def test_a_fully_paid_long_never_breaches(self):
        """The cash check escrows 100% of an opening order, so a long's
        equity cannot fall below its value: only shorts are margin called."""
        env = _env()
        _short_90(env)
        _order(env, 2, "limit", "bid", 1, 1.0)
        _order(env, 3, "limit", "ask", 1, 3.0)
        env.mark_to_mkt()
        assert env.mark_price() == Decimal(2)
        # agent_1: 1,000 cash + 90 x 2 = 1,180 of equity on 180 of value.
        assert not env._in_breach(env.traders[1], env.mark_price())
        assert env.liquidate() == []


class TestBookThenADL:

    def _squeeze(self, env):
        _short_90(env)
        _order(env, 2, "limit", "bid", 1, 170.0)
        _order(env, 3, "limit", "ask", 50, 180.0)
        env.mark_to_mkt()

    def test_the_book_takes_what_it_can_inside_the_band_and_adl_the_rest(self):
        env = _env()
        self._squeeze(env)
        events = env.liquidate()
        assert len(events) == 1
        event = events[0]
        # Bankruptcy price: 175 + 3,250 / 90 = 211.1, floored to the tick.
        assert event["band"] == Decimal(211)
        # agent_3's 50 @ 180 is inside the band; nothing else is resting.
        assert event["book_qty"] == 50 and event["adl_qty"] == 40
        a0, a1 = env.traders[0].acc, env.traders[1].acc
        assert a0.net_position == 0
        assert a1.net_position == 50  # ADL took 40 of its 90
        assert env.traders[3].acc.net_position == -50  # its ask was filled
        # 3,250 less the book slippage 50 x (180 - 175); ADL at the mark is free.
        assert a0.nav == Decimal(3000)
        assert _total_nav(env) == TOTAL

    def test_the_counters_say_what_happened(self):
        env = _env()
        self._squeeze(env)
        a0, a1 = env.traders[0].acc, env.traders[1].acc
        # agent_0's own setup sale is already in its step count.
        own = a0.num_trades_step
        env.liquidate()
        assert (a0.num_liquidations_step, a0.liquidated_book_qty_step,
                a0.liquidated_adl_qty_step) == (1, 50, 40)
        assert a1.adl_qty_step == 40
        # Forced fills are not the agent's trades: trade_penalty must not see them.
        assert a0.num_trades_step == own

    def test_the_liquidation_order_rests_nothing(self):
        env = _env()
        self._squeeze(env)
        env.liquidate()
        mine = [o for o in env.LOB.bids.order_map.values() if o.trade_id == 0]
        assert mine == []

    def test_a_price_gap_past_bankruptcy_goes_entirely_to_adl(self):
        """NAV already negative: the band is the mark, the book offers
        nothing that good, and ADL closes all of it. The shortfall stays on
        the liquidated account - there is no insurance fund to cover it."""
        env = _env()
        _short_90(env)
        _order(env, 2, "limit", "bid", 1, 230.0)
        _order(env, 3, "limit", "ask", 1, 240.0)
        env.mark_to_mkt()
        assert env.traders[0].acc.nav == Decimal(-2150)  # 10,000 - 90 x 135
        (event,) = env.liquidate()
        assert event["band"] == Decimal(235) and event["book_qty"] == 0
        assert event["adl_qty"] == 90
        assert env.traders[0].acc.net_position == 0
        assert env.traders[1].acc.net_position == 0
        assert env.traders[0].acc.nav == Decimal(-2150)
        assert _total_nav(env) == TOTAL

    def test_off_is_the_previous_behaviour(self):
        env = _env(liquidation="off")
        self._squeeze(env)
        assert env.liquidate() == []
        assert env.traders[0].acc.net_position == -90


class TestThroughAStep:

    def test_a_liquidated_trader_with_equity_left_keeps_trading(self):
        env = _env()
        _short_90(env)
        _order(env, 2, "limit", "bid", 1, 170.0)
        _order(env, 3, "limit", "ask", 50, 180.0)
        obs, rewards, dones, truncs, infos = env.step(_pass(env))
        info = infos["agent_0"]
        assert info["num_liquidations_step"] == 1
        assert (info["liquidated_book_qty_step"], info["liquidated_adl_qty_step"]) == (50, 40)
        assert infos["agent_1"]["adl_qty_step"] == 40
        assert info["net_position"] == 0 and not dones["agent_0"]
        # The reward spans the whole step, close-out included: prev_nav is the
        # NAV before the step (10,000), not the 3,250 of the mark in between.
        assert info["reward_terms"]["nav_term"] == pytest.approx((3000 - CASH) / CASH)
        assert sum(Decimal(i["NAV"]) for i in infos.values()) == TOTAL
        # The next step it is an ordinary, flat, live trader.
        _, _, dones, _, infos = env.step(_pass(env))
        assert "agent_0" in infos and infos["agent_0"]["num_liquidations_step"] == 0

    def test_a_bankrupt_trader_is_terminated_flat_and_its_nav_stays_put(self):
        env = _env()
        _short_90(env)
        _order(env, 2, "limit", "bid", 1, 230.0)
        _order(env, 3, "limit", "ask", 1, 240.0)
        _, _, dones, _, infos = env.step(_pass(env))
        assert dones["agent_0"] and infos["agent_0"]["net_position"] == 0
        frozen = env.traders[0].acc.nav
        # The market moves on; a flat account cannot move with it.
        _order(env, 3, "limit", "ask", 1, 500.0)
        env.step(_pass(env))
        assert env.traders[0].acc.nav == frozen
        assert _total_nav(env) == TOTAL


class TestADLSplit:

    class _T:
        def __init__(self, ID, pos):
            self.ID = ID
            self.acc = type("A", (), {"net_position": pos})()

    def test_pro_rata_is_exact_in_whole_contracts(self):
        ts = [self._T(1, 60), self._T(2, 30)]
        shares = dict((t.ID, q) for t, q in Liquidation_Helper._pro_rata(ts, 40, 90))
        # 26.67 and 13.33: floors 26 and 13, the residue to the larger remainder.
        assert shares == {1: 27, 2: 13}

    def test_nobody_gives_more_than_they_hold(self):
        ts = [self._T(i, p) for i, p in enumerate((1, 1, 1, 97), start=1)]
        for q in range(1, 101):
            shares = Liquidation_Helper._pro_rata(ts, q, 100)
            assert sum(s for _, s in shares) == q
            assert all(s <= abs(t.acc.net_position) for t, s in shares)


class TestConfig:

    def test_defaults(self):
        env = _env()
        assert env.liquidation == "market_adl"
        assert env.maintenance_margin == Decimal("0.3")

    def test_bad_values_are_refused(self):
        with pytest.raises(ValueError, match="liquidation"):
            _env(liquidation="insurance_fund")
        with pytest.raises(ValueError, match="maintenance_margin"):
            _env(maintenance_margin=1.0)

    def test_train_config_forwards_both_and_compare_can_set_them(self):
        from gym_continuousDoubleAuction.train.compare import parse_overrides
        from gym_continuousDoubleAuction.train.train import TrainConfig

        cfg = dataclasses.replace(
            TrainConfig(),
            **parse_overrides(["liquidation=off", "maintenance_margin=0.1"]),
        )
        assert cfg.env_config["liquidation"] == "off"
        assert cfg.env_config["maintenance_margin"] == 0.1


class TestGradual:
    """`gradual_adl`: the close-out spread over `liquidation_horizon` steps.

    Same squeeze as above - agent_0 short 90 at a mid of 175, agent_3 offering
    50 @ 180 - with a horizon of 4, so the slices are ceil(90/4) = 23, then
    ceil(67/3) = 23, then ceil(44/2) = 22 of which the book has only 4 left,
    then the last 40 by ADL.
    """

    def _squeeze(self, **config):
        env = _env(liquidation="gradual_adl", **config)
        _short_90(env)
        _order(env, 2, "limit", "bid", 1, 170.0)
        _order(env, 3, "limit", "ask", 50, 180.0)
        return env

    def test_a_horizon_of_one_is_market_adl(self):
        results = []
        for mode, extra in (("market_adl", {}), ("gradual_adl", {"liquidation_horizon": 1})):
            env = _env(liquidation=mode, **extra)
            _short_90(env)
            _order(env, 2, "limit", "bid", 1, 170.0)
            _order(env, 3, "limit", "ask", 50, 180.0)
            env.mark_to_mkt()
            (event,) = env.liquidate()
            results.append((event["book_qty"], event["adl_qty"],
                            [t.acc.nav for t in env.traders],
                            [t.acc.net_position for t in env.traders]))
        assert results[0] == results[1]

    def test_it_closes_in_slices_and_adl_takes_the_rest_on_the_last_step(self):
        env = self._squeeze(liquidation_horizon=4)
        book, adl, positions = [], [], []
        for _ in range(4):
            _, _, dones, _, infos = env.step(_pass(env))
            info = infos["agent_0"]
            book.append(info["liquidated_book_qty_step"])
            adl.append(info["liquidated_adl_qty_step"])
            positions.append((info["net_position"], info["liquidation_steps_left"]))
            assert _total_nav(env) == TOTAL
        assert book == [23, 23, 4, 0]
        assert adl == [0, 0, 0, 40]
        assert positions == [(-67, 3), (-44, 2), (-40, 1), (0, 0)]
        assert not dones["agent_0"]

    def test_it_is_counted_once_when_it_starts(self):
        env = self._squeeze(liquidation_horizon=4)
        counts = [env.step(_pass(env))[4]["agent_0"]["num_liquidations_step"] for _ in range(4)]
        assert counts == [1, 0, 0, 0]

    def test_the_account_is_frozen_and_the_mask_shows_it(self):
        env = self._squeeze(liquidation_horizon=4)
        obs, *_ = env.step(_pass(env))
        trader = env.traders[0]
        assert not trader._order_approved("bid", 1, 100.0, env.LOB, "limit")
        assert not trader._order_approved("ask", 1, 100.0, env.LOB, "market")
        from gym_continuousDoubleAuction.envs.exchg.state_helper import MASK_FIELDS
        mask = obs["agent_0"][-len(MASK_FIELDS):]
        assert mask[0] == 1.0 and not any(mask[1:])

    def test_the_freeze_lifts_when_the_position_is_closed(self):
        env = self._squeeze(liquidation_horizon=4)
        for _ in range(4):
            env.step(_pass(env))
        assert env.traders[0].acc.liquidation_steps_left == 0
        assert env.traders[0]._order_approved("bid", 1, 100.0, env.LOB, "limit")

    def test_if_the_equity_runs_out_midway_the_rest_is_closed_at_once(self):
        env = self._squeeze(liquidation_horizon=4)
        env.step(_pass(env))  # first slice: 23 closed, 67 left, frozen
        # agent_3 withdraws its remaining offer and the market gaps to 405.
        _order(env, 3, "cancel", "ask", 1, 0.0)
        _order(env, 2, "limit", "bid", 1, 400.0)
        _order(env, 1, "limit", "ask", 1, 410.0)
        _, _, dones, _, infos = env.step(_pass(env))
        info = infos["agent_0"]
        assert info["net_position"] == 0 and info["liquidation_steps_left"] == 0
        assert info["liquidated_adl_qty_step"] == 67
        assert info["num_liquidations_step"] == 0  # the same liquidation, finished
        assert dones["agent_0"]  # nothing left: terminated, flat
        assert _total_nav(env) == TOTAL

    def test_horizon_must_be_a_positive_whole_number(self):
        for bad in (0, 2.5):
            with pytest.raises(ValueError, match="liquidation_horizon"):
                _env(liquidation="gradual_adl", liquidation_horizon=bad)

    def test_train_config_forwards_the_horizon(self):
        from gym_continuousDoubleAuction.train.compare import parse_overrides
        from gym_continuousDoubleAuction.train.train import TrainConfig

        cfg = dataclasses.replace(
            TrainConfig(),
            **parse_overrides(["liquidation=gradual_adl", "liquidation_horizon=20"]),
        )
        assert cfg.env_config["liquidation"] == "gradual_adl"
        assert cfg.env_config["liquidation_horizon"] == 20
