"""Pluggable matching in the book: the allocation rule and batch clearing.

doc/06 section 8. Two knobs on `OrderBook`. `matching_rule` decides how the
quantity reaching one price level is split among the orders resting there:
`fifo` (price-time priority, the default) or `pro_rata` (in proportion to
size, largest-remainder rounded, residue in time order). Batch clearing
(`begin_batch` / `clear_batch`) queues a step's new market and limit orders
and clears them against the book at one uniform price - the volume-maximising
price, then the smallest imbalance, then the one closest to the reference - so
that where the step's shuffle put an order decides nothing unless the order
is marginal. Leftover limits rest; leftover markets lapse.
"""
from decimal import Decimal

import pytest

from gym_continuousDoubleAuction.envs.agent.trader import Trader
from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook


def _q(side, qty, price=None, tid=0):
    d = {"type": "limit" if price is not None else "market", "side": side,
         "quantity": qty, "trade_id": tid}
    if price is not None:
        d["price"] = price
    return d


def _fills(trades):
    return [(str(t["price"]), int(t["quantity"]), t["init_party"]["ID"], t["counter_party"]["ID"]) for t in trades]


def _level_volume(tree):
    return sum((Decimal(o.quantity) for ol in tree.price_map.values() for o in ol), Decimal(0))


class TestAllocationRule:

    def test_the_rule_is_validated_and_keyword_only(self):
        with pytest.raises(ValueError, match="matching_rule"):
            OrderBook(10, matching_rule="lottery")
        with pytest.raises(TypeError):
            OrderBook(10, "pro_rata")  # positional: the old dead tick argument's slot
        assert OrderBook(10).matching_rule == "fifo"

    def test_fifo_fills_the_oldest_first(self):
        b = OrderBook(10)
        b.process_order(_q("ask", 30, 100, 1), False, False)
        b.process_order(_q("ask", 10, 100, 2), False, False)
        trades, _ = b.process_order(_q("bid", 20, 100, 3), False, False)
        assert _fills(trades) == [("100", 20, 3, 1)]
        assert _level_volume(b.asks) == 20 == b.asks.volume

    def test_pro_rata_splits_in_proportion(self):
        b = OrderBook(10, matching_rule="pro_rata")
        b.process_order(_q("ask", 30, 100, 1), False, False)
        b.process_order(_q("ask", 10, 100, 2), False, False)
        trades, _ = b.process_order(_q("bid", 20, 100, 3), False, False)
        assert _fills(trades) == [("100", 15, 3, 1), ("100", 5, 3, 2)]
        assert _level_volume(b.asks) == 20 == b.asks.volume

    def test_pro_rata_rounds_by_largest_remainder_in_time_order(self):
        """20 contracts into 30 / 10 at 5 incoming: floors 3 and 1, residue 1
        to the older order -> 4 and 1. Exact total, whole contracts."""
        b = OrderBook(10, matching_rule="pro_rata")
        b.process_order(_q("ask", 30, 100, 1), False, False)
        b.process_order(_q("ask", 10, 100, 2), False, False)
        trades, _ = b.process_order(_q("bid", 5, 100, 3), False, False)
        assert _fills(trades) == [("100", 4, 3, 1), ("100", 1, 3, 2)]

    def test_a_small_order_behind_a_large_one_gets_a_share(self):
        """The property pro-rata exists for, and fifo denies."""
        fifo, pro = OrderBook(10), OrderBook(10, matching_rule="pro_rata")
        for b in (fifo, pro):
            b.process_order(_q("ask", 100, 50, 1), False, False)
            b.process_order(_q("ask", 5, 50, 2), False, False)
        f, _ = fifo.process_order(_q("bid", 21, 50, 3), False, False)
        p, _ = pro.process_order(_q("bid", 21, 50, 3), False, False)
        assert [t["counter_party"]["ID"] for t in f] == [1]
        assert _fills(p) == [("50", 20, 3, 1), ("50", 1, 3, 2)]

    def test_sweeping_a_level_is_the_same_under_both(self):
        for rule in ("fifo", "pro_rata"):
            b = OrderBook(10, matching_rule=rule)
            b.process_order(_q("ask", 3, 100, 1), False, False)
            b.process_order(_q("ask", 4, 100, 2), False, False)
            trades, oib = b.process_order(_q("bid", 10, 100, 3), False, False)
            assert _fills(trades) == [("100", 3, 3, 1), ("100", 4, 3, 2)]
            assert int(oib["quantity"]) == 3 and b.asks.volume == 0


class TestBatchClearing:

    def test_a_crossing_pair_clears_at_the_reference_inside_the_interval(self):
        b = OrderBook(10)
        b.begin_batch()
        assert b.process_order(_q("bid", 10, 102, 0), False, False) == ([], None)
        assert b.process_order(_q("ask", 10, 98, 1), False, False) == ([], None)
        res = b.clear_batch(reference_price=100)
        assert [(tid, _fills(tr), oib) for tid, tr, oib in res] == [(0, [("100", 10, 0, 1)], None), (1, [], None)]
        assert res[0][1][0]["counter_party"]["resting"] is False
        assert len(b.tape) == 1 and b.get_best_bid() is None and b.get_best_ask() is None

    def test_the_reference_outside_the_interval_picks_the_nearest_end(self):
        b = OrderBook(10)
        b.begin_batch()
        b.process_order(_q("bid", 10, 102, 0), False, False)
        b.process_order(_q("ask", 10, 98, 1), False, False)
        res = b.clear_batch(reference_price=110)
        assert _fills(res[0][1]) == [("102", 10, 0, 1)]

    def test_a_batch_order_against_the_book_makes_the_resting_order_the_counter_party(self):
        b = OrderBook(10)
        b.process_order(_q("ask", 10, 101, 1), False, False)
        b.begin_batch()
        b.process_order(_q("bid", 15, 103, 0), False, False)
        (tid, trades, oib), = b.clear_batch(reference_price=100)
        assert tid == 0 and _fills(trades) == [("101", 10, 0, 1)]
        assert trades[0]["counter_party"]["resting"] is True
        assert str(oib["price"]) == "103" and int(oib["quantity"]) == 5   # the leftover rests
        assert b.get_best_bid() == Decimal("103") and b.asks.volume == 0

    def test_the_marginal_level_is_rationed_resting_first_then_fifo(self):
        b = OrderBook(10)
        b.process_order(_q("bid", 5, 100, 1), False, False)          # resting
        b.begin_batch()
        b.process_order(_q("bid", 5, 100, 2), False, False)
        b.process_order(_q("bid", 5, 100, 3), False, False)
        b.process_order(_q("ask", 8, 100, 4), False, False)
        res = {tid: (tr, oib) for tid, tr, oib in b.clear_batch(reference_price=100)}
        assert _fills(res[4][0]) == [("100", 5, 4, 1)]                # resting bid first, ask is init
        assert _fills(res[2][0]) == [("100", 3, 2, 4)]                # then the oldest batch bid
        assert int(res[2][1]["quantity"]) == 2 and int(res[3][1]["quantity"]) == 5
        assert b.bids.volume == 7 == _level_volume(b.bids) and b.asks.volume == 0

    def test_the_marginal_batch_orders_follow_the_matching_rule(self):
        b = OrderBook(10, matching_rule="pro_rata")
        b.begin_batch()
        b.process_order(_q("bid", 30, 100, 1), False, False)
        b.process_order(_q("bid", 10, 100, 2), False, False)
        b.process_order(_q("ask", 20, 100, 3), False, False)
        res = {tid: tr for tid, tr, _ in b.clear_batch(reference_price=100)}
        assert sum(int(t["quantity"]) for t in res[1]) == 15
        assert sum(int(t["quantity"]) for t in res[2]) == 5

    def test_position_in_the_batch_decides_nothing_off_the_margin(self):
        """Three buys strictly above the clearing price against one ask: the
        same fills whatever order they were queued in."""
        def run(order):
            b = OrderBook(10)
            b.process_order(_q("ask", 30, 100, 9), False, False)
            b.begin_batch()
            for tid in order:
                b.process_order(_q("bid", 10, 100 + tid, tid), False, False)
            return {tid: sum(int(t["quantity"]) for t in tr) for tid, tr, _ in b.clear_batch(100)}
        assert run([1, 2, 3]) == run([3, 1, 2]) == run([2, 3, 1]) == {1: 10, 2: 10, 3: 10}

    def test_no_cross_rests_everything(self):
        b = OrderBook(10)
        b.begin_batch()
        b.process_order(_q("bid", 5, 99, 0), False, False)
        b.process_order(_q("ask", 5, 101, 1), False, False)
        res = b.clear_batch(reference_price=100)
        assert all(tr == [] for _, tr, _ in res)
        assert b.get_best_bid() == Decimal("99") and b.get_best_ask() == Decimal("101")

    def test_market_orders_alone_clear_at_the_reference_and_lapse(self):
        b = OrderBook(10)
        b.begin_batch()
        b.process_order(_q("bid", 5, None, 0), False, False)
        b.process_order(_q("ask", 3, None, 1), False, False)
        res = {tid: (tr, oib) for tid, tr, oib in b.clear_batch(reference_price=100)}
        assert _fills(res[0][0]) == [("100", 3, 0, 1)]
        assert res[0][1] is None and res[1][1] is None and len(b.bids) == 0

    def test_a_modify_in_a_batch_is_deferred_too(self):
        b = OrderBook(10)
        _, resting = b.process_order(_q("bid", 5, 99, 0), False, False)
        b.process_order(_q("ask", 5, 101, 1), False, False)
        b.begin_batch()
        # Re-price the bid across the spread: sequentially it would fill now.
        assert b.modify_order(resting["order_id"], {"side": "bid", "quantity": 5, "price": 101,
                                                     "trade_id": 0}) == ([], None)
        assert b.get_best_bid() is None
        res = {tid: tr for tid, tr, _ in b.clear_batch(reference_price=100)}
        assert _fills(res[0]) == [("101", 5, 0, 1)]

    def test_settlement_conserves_nav_and_books_both_batch_parties(self):
        book = OrderBook(10)
        traders = [Trader(i, 100_000) for i in range(3)]
        book.begin_batch()
        for t, args in zip(traders, (("limit", "bid", 10, 102.0), ("limit", "ask", 4, 98.0), ("market", "ask", 3, -1.0))):
            assert t.place_order(*args, book, traders) == ([], None)
        for tid, trades, oib in book.clear_batch(reference_price=100):
            traders[tid].settle_batch(trades, oib, traders)
        assert [t.acc.net_position for t in traders] == [7, -4, -3]
        assert sum(t.acc.nav for t in traders) == Decimal(300_000)
        # 7 bought at the reference 100, 3 left escrowed at 102.
        assert traders[0].acc.cash == Decimal(100_000 - 700 - 306)
        assert traders[0].acc.cash_on_hold == Decimal(306)
        assert traders[1].acc.cash_on_hold == 0 and traders[2].acc.cash_on_hold == 0


class TestPriceImprovementEscrow:
    """A resting order filled at a better price than its limit in a batch.

    The sequential engine fills a resting order at its own price, so the
    escrow it posted is exactly what its fill releases. A batch clears at one
    price, so a resting bid at 102 fills at 100 and a resting ask at 98 at 100;
    the escrow has to be re-based to the trade price before the release, or
    `cash_on_hold` drifts - it went a few contracts negative on 3.4% of
    agent-steps under batch random play, which the observation bounds' clip
    counter caught (doc/16 section 16.26).
    """

    def _cleared(self, side, limit, size=5):
        book = OrderBook(10)
        rester, taker, other = (Trader(i, 100_000) for i in range(3))
        traders = [rester, taker, other]
        rester.place_order("limit", side, size, float(limit), book, traders)
        assert rester.acc.cash_on_hold == Decimal(limit) * size
        book.begin_batch()
        # The taker crosses aggressively from the other side; `other` quotes
        # the far side so the reference 100 is inside the clearing interval.
        opposite = "ask" if side == "bid" else "bid"
        taker.place_order("limit", opposite, size, 100.0 if side == "bid" else 100.0, book, traders)
        for tid, trades, oib in book.clear_batch(reference_price=100):
            traders[tid].settle_batch(trades, oib, traders)
        return book, rester, taker, traders

    def test_resting_bid_filled_below_its_limit(self):
        book, rester, taker, traders = self._cleared("bid", 102)
        assert [Decimal(str(t["price"])) for t in book.tape] == [Decimal(100)]
        assert rester.acc.cash_on_hold == 0
        assert rester.acc.net_position == 5
        assert rester.acc.cash == Decimal(100_000 - 500)      # paid the clearing price, not the limit
        assert sum(t.acc.nav for t in traders) == Decimal(300_000)

    def test_resting_ask_filled_above_its_limit(self):
        book, rester, taker, traders = self._cleared("ask", 98)
        assert [Decimal(str(t["price"])) for t in book.tape] == [Decimal(100)]
        assert rester.acc.cash_on_hold == 0                    # the case that went negative
        assert rester.acc.net_position == -5
        assert sum(t.acc.nav for t in traders) == Decimal(300_000)
        for t in traders:
            assert t.acc.cash_on_hold >= 0

    def test_random_batch_play_never_takes_escrow_negative(self):
        from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
            continuousDoubleAuctionEnv,
        )
        env = continuousDoubleAuctionEnv({"num_of_agents": 4, "max_step": 128, "is_render": False,
                                          "step_clearing": "batch"})
        for seed in range(3):
            env.reset(seed=300 + seed)
            while True:
                _, _, dones, truncs, infos = env.step(
                    {agent: env.action_spaces[agent].sample() for agent in env.agents}
                )
                for t in env.traders:
                    assert t.acc.cash_on_hold >= 0, (seed, t.ID, t.acc.cash_on_hold)
                for info in infos.values():
                    assert info["num_obs_clipped_step"] == 0
                if dones["__all__"] or truncs["__all__"]:
                    break
