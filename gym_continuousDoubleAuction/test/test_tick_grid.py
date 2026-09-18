"""Prices the action layer produces sit on the tick grid, for any tick.

doc/15 S3-4 (the float-grid caveat). `_set_price` read resting prices out of a
float32 snapshot and added its offset in float, so on any non-integer tick the
book was keyed on prices one float-ulp off the level the agent meant:
100.0999984741211 for a level at 100.1, 100.19999999999999 for 100.1 + 0.1.
Each became a fresh price-map entry, and `Trader._get_order_ID` - which
compared the book's Decimal against the action's float - never found its own
order, so cancels were silent no-ops and a re-quote at the same price rested a
second order instead of upserting. Measured before the fix, at tick_size 0.1:
one new level per step from an agent quoting the same level every step.
"""
from decimal import Decimal

import numpy as np
import pytest

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)


def _env(tick):
    env = continuousDoubleAuctionEnv({
        "num_of_agents": 2,
        "tick_size": tick,
        "is_render": False,
        "max_step": 64,
        "initial_price_min": 100,
        "initial_price_max": 100,
    })
    env.reset(seed=1)
    return env


def _act(category, price=0, offset=1, mean=0.5):
    return {
        "category": category,
        "size_mean": np.array([mean], dtype=np.float32),
        "size_sigma": np.array([0.0], dtype=np.float32),
        "price": price,
        "price_offset": offset,
    }


_PASS = _act(0)


def _on_grid(price, tick):
    q = Decimal(str(price)) / Decimal(str(tick))
    return q == q.to_integral_value()


class TestSetPriceIsOnTheGrid:

    @pytest.mark.parametrize("tick", [1, 0.5, 0.1, 0.05, 0.01, 0.3, 0.0001])
    def test_ghost_levels_every_level_and_offset(self, tick):
        env = _env(tick)
        for side in ("bid", "ask"):
            for level in range(env.k_rows):
                for offset in range(env._act["price_offset_n"]):
                    price = env._set_price(env.min_tick, side, level, offset)
                    assert _on_grid(price, tick), (side, level, offset, price)
                    assert price >= tick

    @pytest.mark.parametrize("tick", [0.1, 0.05, 0.3])
    def test_resting_levels_read_back_on_grid(self, tick):
        """The level path: a price read out of the snapshot, not the anchor."""
        env = _env(tick)
        # Rest one bid and one ask, then quote at level 0 on both sides.
        env.step({"agent_0": _act(2, price=0, offset=1),
                  "agent_1": _act(6, price=0, offset=1)})
        assert env.LOB.get_best_bid() is not None
        assert env.LOB.get_best_ask() is not None
        for side in ("bid", "ask"):
            for offset in range(env._act["price_offset_n"]):
                price = env._set_price(env.min_tick, side, 0, offset)
                assert _on_grid(price, tick), (side, offset, price)

    def test_raw_snapshot_holds_prices_exactly(self):
        env = _env(0.1)
        env.step({"agent_0": _act(2, price=0, offset=1), "agent_1": _PASS})
        env.set_agg_LOB()
        assert env.agg_LOB_raw.dtype == np.float64
        best = float(env.LOB.get_best_bid())
        assert env.agg_LOB_raw[0] == best


class TestFractionalTickBookStaysConsistent:

    def test_requoting_the_same_level_upserts(self):
        env = _env(0.1)
        for _ in range(5):
            env.step({"agent_0": _act(2, price=0, offset=1), "agent_1": _PASS})
        assert len(env.LOB.bids) == 1, [str(p) for p in env.LOB.bids.price_map]
        assert len(env.LOB.bids.price_map) == 1
        assert _on_grid(env.LOB.get_best_bid(), 0.1)

    def test_cancel_finds_the_order_at_a_fractional_price(self):
        env = _env(0.1)
        env.step({"agent_0": _act(2, price=0, offset=1), "agent_1": _PASS})
        assert len(env.LOB.bids) == 1
        trader = env.traders[0]
        escrowed = trader.acc.cash_on_hold
        assert escrowed > 0
        # Cancel at the same level: the price it computes must match the
        # Decimal the book stored.
        env.step({"agent_0": _act(4, price=0, offset=1), "agent_1": _PASS})
        assert len(env.LOB.bids) == 0
        assert trader.acc.cash_on_hold == Decimal(0)
        assert trader.acc.num_rejected_step == 0

    def test_nav_is_conserved_under_random_play(self):
        env = _env(0.1)
        rng = np.random.default_rng(0)
        for agent in env.agents:
            env.action_spaces[agent].seed(int(rng.integers(0, 2**31)))
        total0 = sum(t.acc.nav for t in env.traders)
        for _ in range(60):
            actions = {a: env.action_spaces[a].sample() for a in env.agents}
            _, _, term, trunc, _ = env.step(actions)
            if term.get("__all__") or trunc.get("__all__"):
                break
        assert sum(t.acc.nav for t in env.traders) == total0
        for price in list(env.LOB.bids.price_map) + list(env.LOB.asks.price_map):
            assert _on_grid(price, 0.1), str(price)
