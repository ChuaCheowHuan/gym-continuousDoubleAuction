"""Phase 2 of doc/15 S3-24: a modify or cancel is aimed by slot.

Slot k names the agent's k-th own resting order on the named side, counted
from the touch - best price first, oldest first within a level, the order the
own-book observation lists them in. Slot 0 is "all on this side" for a cancel
and "the oldest" (the pre-slot FIFO rule) for a modify. A slot past the count
is a counted miss. Price no longer aims a cancel at all; a limit still matches
by price, which is the upsert rule.
"""
from decimal import Decimal

import numpy as np

from gym_continuousDoubleAuction.envs.agent.trader import Trader
from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.envs.exchg.action_helper import (
    ACTION_KEYS,
    ACTION_LAYOUT_VERSION,
)
from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook


def _three_bids():
    """One trader with bids at 100, 99 and 98 (slots 1, 2, 3 from the touch)."""
    book = OrderBook()
    t = Trader(ID=1, cash=10_000)
    for price in (98, 100, 99):  # placed out of price order on purpose
        t.place_order('limit', 'bid', 1, price, book, [t])
    return book, t


def _prices(book, side):
    tree = book.bids if side == 'bid' else book.asks
    return sorted(int(p) for p in tree.price_map)


class TestCancelBySlot:

    def test_slot_1_is_the_touch(self):
        book, t = _three_bids()
        t.place_order('cancel', 'bid', 1, 0, book, [t], slot=1)
        assert _prices(book, 'bid') == [98, 99]
        assert t.acc.num_unmatched_step == 0

    def test_slot_3_is_the_deepest(self):
        book, t = _three_bids()
        t.place_order('cancel', 'bid', 1, 0, book, [t], slot=3)
        assert _prices(book, 'bid') == [99, 100]

    def test_slot_0_cancels_every_own_order_on_the_side(self):
        book, t = _three_bids()
        other = Trader(ID=2, cash=10_000)
        other.place_order('limit', 'bid', 1, 100, book, [t, other])
        t.place_order('cancel', 'bid', 1, 0, book, [t, other], slot=0)
        assert len(book.bids) == 1, "the other trader's bid survives"
        assert t.acc.cash == Decimal(10_000) and t.acc.cash_on_hold == Decimal(0)
        assert t.acc.num_unmatched_step == 0

    def test_slot_past_the_count_clamps_to_the_deepest(self):
        """Never a dead slot while there is something to act on - see the
        `order_slot` note in tunable_constants.json for the measurement."""
        book, t = _three_bids()
        t.place_order('cancel', 'bid', 1, 0, book, [t], slot=4)
        assert _prices(book, 'bid') == [99, 100], "slot 4 of three orders is the 98"
        assert t.acc.num_unmatched_step == 0

    def test_slot_0_with_nothing_resting_is_a_miss(self):
        book, t = OrderBook(), Trader(ID=1, cash=1000)
        t.place_order('cancel', 'ask', 1, 0, book, [t], slot=0)
        assert t.acc.num_unmatched_step == 1

    def test_asks_count_from_the_touch_too(self):
        book, t = OrderBook(), Trader(ID=1, cash=10_000)
        for price in (103, 101, 102):
            t.place_order('limit', 'ask', 1, price, book, [t])
        t.place_order('cancel', 'ask', 1, 0, book, [t], slot=1)
        assert _prices(book, 'ask') == [102, 103]

    def test_oldest_first_within_a_level(self):
        book, t = OrderBook(), Trader(ID=1, cash=10_000)
        t.place_order('limit', 'bid', 1, 100, book, [t])
        # A second order at the same price is an upsert, so use two levels
        # collapsed by a modify instead: rest at 99, then move it to 100.
        t.place_order('limit', 'bid', 2, 99, book, [t])
        t.place_order('modify', 'bid', 2, 100, book, [t], slot=2)  # the 99 -> 100
        level = book.bids.price_map[Decimal('100')]
        assert level.length == 2
        first, second = list(level)
        t.place_order('cancel', 'bid', 1, 0, book, [t], slot=1)
        remaining = list(book.bids.price_map[Decimal('100')])
        assert remaining == [second], "slot 1 was the older order at the touch"

    def test_cancel_releases_the_escrow_of_exactly_that_order(self):
        book, t = _three_bids()
        before = t.acc.cash_on_hold
        t.place_order('cancel', 'bid', 1, 0, book, [t], slot=2)  # the 99
        assert t.acc.cash_on_hold == before - Decimal(99)


class TestModifyBySlot:

    def test_slot_0_is_the_oldest_order(self):
        book, t = _three_bids()  # oldest is the 98
        t.place_order('modify', 'bid', 1, 97, book, [t], slot=0)
        assert _prices(book, 'bid') == [97, 99, 100]

    def test_slot_k_moves_the_kth_from_the_touch(self):
        book, t = _three_bids()
        t.place_order('modify', 'bid', 1, 95, book, [t], slot=1)  # the 100
        assert _prices(book, 'bid') == [95, 98, 99]

    def test_slot_past_the_count_clamps_to_the_deepest(self):
        book, t = _three_bids()
        t.place_order('modify', 'bid', 1, 95, book, [t], slot=4)  # the 98
        assert _prices(book, 'bid') == [95, 99, 100]
        assert t.acc.num_unmatched_step == 0

    def test_empty_side_is_the_only_miss(self):
        book, t = _three_bids()
        t.place_order('modify', 'ask', 1, 105, book, [t], slot=1)
        assert t.acc.num_unmatched_step == 1
        assert len(book.asks) == 0

    def test_cash_check_counts_the_slotted_orders_release(self):
        """A modify spends the escrow of the order it replaces (S2-13) - the
        one the slot names, not the oldest."""
        book, t = OrderBook(), Trader(ID=1, cash=200)
        t.place_order('limit', 'bid', 1, 100, book, [t])
        t.place_order('limit', 'bid', 1, 99, book, [t])
        assert t.acc.cash == Decimal(1)
        # Re-price the 100 to 101: 101 <= 1 cash + 100 released.
        t.place_order('modify', 'bid', 1, 101, book, [t], slot=1)
        assert t.acc.num_rejected_step == 0
        assert _prices(book, 'bid') == [99, 101]


class TestActionSpace:

    def test_order_slot_head(self):
        env = continuousDoubleAuctionEnv({"num_of_agents": 2, "is_render": False})
        space = env.action_spaces["agent_0"]
        assert tuple(space.spaces) == ACTION_KEYS
        assert space["order_slot"].n == env.max_own_orders + 1 == 5
        assert ACTION_LAYOUT_VERSION == 2

    def test_absent_slot_decodes_as_zero(self):
        env = continuousDoubleAuctionEnv({"num_of_agents": 1, "is_render": False})
        env.reset(seed=0)
        act = env._set_action_mkt_depth("agent_0", {
            "category": 4, "size_mean": np.array([0.0], dtype=np.float32),
            "size_sigma": np.array([0.0], dtype=np.float32), "price": 0,
            "price_offset": 1,
        })
        assert act["slot"] == 0

    def test_env_routes_the_slot(self):
        env = continuousDoubleAuctionEnv({
            "num_of_agents": 1, "is_render": False, "max_step": 16,
            "initial_price_min": 100, "initial_price_max": 100, "tick_size": 0.1,
        })
        env.reset(seed=2)

        def act(category, price=0, offset=1, slot=0):
            return {"agent_0": {
                "category": category, "size_mean": np.array([0.2], dtype=np.float32),
                "size_sigma": np.array([0.0], dtype=np.float32), "price": price,
                "price_offset": offset, "order_slot": slot,
            }}

        env.step(act(2, 0, 1))          # bid at the level-0 ghost price
        env.step(act(2, 0, 0))          # a second bid one tick below
        assert len(env.LOB.bids) == 2
        _, _, _, _, infos = env.step(act(4, slot=2))   # cancel the deeper one
        assert len(env.LOB.bids) == 1
        assert infos["agent_0"]["num_unmatched_step"] == 0
        assert env.LOB.get_best_bid() == max(env.LOB.bids.price_map)
        _, _, _, _, infos = env.step(act(8, slot=3))   # no asks at all: a miss
        assert infos["agent_0"]["num_unmatched_step"] == 1
        assert len(env.LOB.bids) == 1
        _, _, _, _, infos = env.step(act(4, slot=0))   # all bids
        assert len(env.LOB.bids) == 0
        assert infos["agent_0"]["num_unmatched_step"] == 0


class TestRandomPlayHitRate:

    def test_slot_aiming_beats_price_aiming(self):
        """Under uniformly random play a cancel used to land 7% of the time it
        was issued (doc/16 16.19). Aimed by a clamped slot it lands whenever
        the agent has an order on that side - about a third of issued cancels,
        against 7% before, since random play often has nothing resting;
        pin a floor well below that so the test is about the mechanism, not
        the seed.
        """
        env = continuousDoubleAuctionEnv({"num_of_agents": 4, "is_render": False, "max_step": 300})
        env.reset(seed=11)
        rng = np.random.default_rng(11)
        for a in env.agents:
            env.action_spaces[a].seed(int(rng.integers(0, 2**31)))
        issued = hit = 0
        for _ in range(300):
            acts = {a: env.action_spaces[a].sample() for a in env.agents}
            _, _, term, trunc, infos = env.step(acts)
            for a, act in acts.items():
                if int(act["category"]) in (4, 8):
                    issued += 1
                    hit += infos[a]["num_unmatched_step"] == 0
            if term.get("__all__") or trunc.get("__all__"):
                break
        assert issued > 100
        assert hit / issued > 0.25, f"{hit}/{issued}"
