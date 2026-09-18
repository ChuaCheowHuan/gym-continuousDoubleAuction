"""Zero means one thing: the occupancy rows and the last-trade reference (S3-14).

doc/15 S3-14. `0.0` in a price cell used to mean three things - an absent
level, a quote resting exactly at the reference price, and the lone best quote
of a one-sided book, whose own price was the reference. Measured under random
play before the fix, 1.2% of occupied price cells read 0.0 at the shipped
config and 22% at a thin-book stress config, and 7.8% (32%) of steps had a
one-sided book (doc/16 section 16.23).

Two changes close it. Every snapshot carries a `bid_occupied` and an
`ask_occupied` row, 1.0 where the level holds an order; and the reference
price of a one-sided book is the last trade rather than the lone quote, which
is also the chain `Exchg_Helper.mark_price` uses, so what the agent sees and
what it is marked at agree.
"""
import numpy as np
import pytest

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.envs.exchg.state_helper import (
    BOOK_ROW_ORDER,
    OBSERVATION_LAYOUT_VERSION,
)

BID_OCC = BOOK_ROW_ORDER.index("bid_occupied")
ASK_OCC = BOOK_ROW_ORDER.index("ask_occupied")


def _env(**overrides):
    config = {
        "num_of_agents": 2,
        "max_step": 40,
        "is_render": False,
        "initial_price_min": 100,
        "initial_price_max": 100,
    }
    config.update(overrides)
    config.setdefault("book_mode", "levels")
    env = continuousDoubleAuctionEnv(config)
    env.reset(seed=1)
    return env


def _pass(env):
    return {agent: {"category": 0, "order_slot": 0, "price": 0, "price_offset": 1,
                    "size_mean": np.zeros(1, dtype=np.float32),
                    "size_sigma": np.zeros(1, dtype=np.float32)}
            for agent in env.agents}


def _rows(env, frame):
    """The book block of one snapshot as a (book_rows, k_rows) grid."""
    return np.asarray(frame[:env.book_dim]).reshape(env.book_rows, env.k_rows)


def _newest(env, obs, agent="agent_0"):
    o = obs[agent]
    return o[(env.n_hist - 1) * env.snapshot_dim:env.n_hist * env.snapshot_dim]


class TestLayout:

    def test_six_book_rows_and_the_version(self):
        env = _env()
        assert BOOK_ROW_ORDER[4:] == ("bid_occupied", "ask_occupied")
        assert env.book_rows == 6
        assert env.snapshot_dim == 6 * env.k_rows + env.extra_dim
        assert OBSERVATION_LAYOUT_VERSION == 5

    def test_raw_snapshot_carries_the_rows(self):
        env = _env()
        a, b = env.traders
        a.place_order('limit', 'bid', 10, 98.0, env.LOB, env.traders)
        a.place_order('limit', 'bid', 10, 97.0, env.LOB, env.traders)
        b.place_order('limit', 'ask', 10, 102.0, env.LOB, env.traders)
        env.set_agg_LOB()
        raw = _rows(env, env.agg_LOB_raw)
        assert raw[BID_OCC].tolist() == [1, 1] + [0] * (env.k_rows - 2)
        assert raw[ASK_OCC].tolist() == [1] + [0] * (env.k_rows - 1)


class TestOccupancy:

    def test_occupancy_equals_size_present(self):
        """The row is exactly `size > 0`, per level, on both sides, every step."""
        env = _env(num_of_agents=4, max_step=40)
        env.reset(seed=3)
        while True:
            obs, _, dones, truncs, _ = env.step(
                {agent: env.action_spaces[agent].sample() for agent in env.agents}
            )
            grid = _rows(env, _newest(env, obs))
            for size_row, occ_row in (("bid_size", "bid_occupied"), ("ask_size", "ask_occupied")):
                sizes = grid[BOOK_ROW_ORDER.index(size_row)]
                occ = grid[BOOK_ROW_ORDER.index(occ_row)]
                assert set(np.unique(occ)) <= {0.0, 1.0}
                np.testing.assert_array_equal(occ, (sizes > 0).astype(np.float32))
            if dones["__all__"] or truncs["__all__"]:
                break

    def test_an_absent_level_and_a_quote_at_the_reference_differ(self):
        """The case the row exists for: both price cells read 0.0, and only the
        occupancy row tells them apart."""
        env = _env()
        a, _ = env.traders
        env.last_price = 98.0
        a.place_order('limit', 'bid', 10, 98.0, env.LOB, env.traders)  # one-sided, at the last trade
        obs, _, _, _, _ = env.step(_pass(env))
        grid = _rows(env, _newest(env, obs))
        bid_price = grid[BOOK_ROW_ORDER.index("bid_price")]
        assert bid_price[0] == 0.0 and bid_price[1] == 0.0
        assert grid[BID_OCC][0] == 1.0 and grid[BID_OCC][1] == 0.0

    def test_older_frames_keep_their_own_occupancy(self):
        """Occupancy is a property of the frame it was taken in, not of the
        newest book: a level that emptied still reads occupied in the frame
        where it was full."""
        env = _env()
        a, b = env.traders
        a.place_order('limit', 'bid', 10, 98.0, env.LOB, env.traders)
        env.step(_pass(env))
        # Lift the bid: the level is gone in the newest frame.
        b.place_order('limit', 'ask', 10, 98.0, env.LOB, env.traders)
        obs, _, _, _, _ = env.step(_pass(env))
        o = obs["agent_0"]
        older = _rows(env, o[(env.n_hist - 2) * env.snapshot_dim:(env.n_hist - 1) * env.snapshot_dim])
        newest = _rows(env, _newest(env, obs))
        assert older[BID_OCC][0] == 1.0
        assert newest[BID_OCC][0] == 0.0

    def test_bounds_cover_the_rows(self):
        env = _env()
        space = env.observation_spaces["agent_0"]
        k = env.k_rows
        for frame in range(env.n_hist):
            base = frame * env.snapshot_dim
            for row in (BID_OCC, ASK_OCC):
                sl = slice(base + row * k, base + (row + 1) * k)
                assert (space.low[sl] == 0.0).all() and (space.high[sl] == 1.0).all()


class TestReferencePrice:

    def test_two_sided_book_uses_the_midpoint(self):
        env = _env()
        a, b = env.traders
        env.last_price = 50.0
        a.place_order('limit', 'bid', 10, 98.0, env.LOB, env.traders)
        b.place_order('limit', 'ask', 10, 102.0, env.LOB, env.traders)
        env.set_agg_LOB()
        assert env.mid_price() == 100.0

    def test_one_sided_book_uses_the_last_trade(self):
        """The lone quote then reads its distance from the print, not 0.0."""
        env = _env()
        a, _ = env.traders
        env.last_price = 100.0
        a.place_order('limit', 'bid', 10, 95.0, env.LOB, env.traders)
        obs, _, _, _, _ = env.step(_pass(env))
        assert env.mid_price() == 100.0
        grid = _rows(env, _newest(env, obs))
        assert grid[BOOK_ROW_ORDER.index("bid_price")][0] == pytest.approx(0.05, abs=1e-6)

    def test_one_sided_book_with_no_print_uses_the_quote(self):
        env = _env()
        a, _ = env.traders
        env.last_price = 0.0
        a.place_order('limit', 'ask', 10, 63.0, env.LOB, env.traders)
        env.set_agg_LOB()
        assert env.mid_price() == 63.0

    def test_the_chain_matches_the_mark_price(self):
        """On a one-sided book with a print, what the agent sees and what it is
        marked at are the same number (doc/15 S2-5 narrowed the mark first)."""
        env = _env()
        a, b = env.traders
        a.place_order('limit', 'bid', 10, 100.0, env.LOB, env.traders)
        b.place_order('limit', 'ask', 10, 100.0, env.LOB, env.traders)  # prints at 100
        a.place_order('limit', 'bid', 10, 90.0, env.LOB, env.traders)   # one-sided now
        env.set_agg_LOB()
        assert float(env.last_price) == 100.0
        assert env.mid_price() == float(env.mark_price()) == 100.0

    def test_empty_book_still_falls_through_to_the_constant(self):
        env = _env()
        env.last_price = 0.0
        env.set_agg_LOB()
        assert env.mid_price() == env.midpoint_fallback
