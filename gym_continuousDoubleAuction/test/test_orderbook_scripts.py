"""The two orderbook demo scripts, as tests (issue #210).

`envs/orderbook/test/example.py` and `genOrders.py` were standalone scripts that pytest did not
collect and CI did not run. `example.py` had rotted: it asserted the book's printed form
and tape repr, which had changed, and nobody noticed. `genOrders.py` used Python 2
(`choice(d.keys())`) and so could not run its modify and cancel branches.

Here the worked example asserts what the book *does* (who trades with whom, at what price,
what is left) rather than how it prints, and the random driver is a seeded shadow model:
it keeps its own picture of the resting orders from the trade records alone, and the book
has to agree with it.
"""

import random
from decimal import Decimal

import pytest

from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook


def _resting(tree):
    """`{order_id: (price, quantity, trade_id)}` for one side of the book."""
    return {oid: (o.price, int(o.quantity), o.trade_id) for oid, o in tree.order_map.items()}


def _level(tree, price):
    """The orders at a price level, in time priority, as `(trade_id, quantity)`."""
    return [(o.trade_id, int(o.quantity)) for o in tree.price_map[Decimal(price)]]


def _limit(side, quantity, price, trade_id):
    return {
        "type": "limit",
        "side": side,
        "quantity": quantity,
        "price": price,
        "trade_id": trade_id,
    }


class TestTheWorkedExample:
    """The sequence `example.py` walked through, with the outcomes it expected."""

    @pytest.fixture
    def book(self):
        book = OrderBook()
        for order in [
            _limit("ask", 5, 101, 100),
            _limit("ask", 5, 103, 101),
            _limit("ask", 5, 101, 102),
            _limit("ask", 5, 101, 103),
            _limit("bid", 5, 99, 100),
            _limit("bid", 5, 98, 101),
            _limit("bid", 5, 99, 102),
            _limit("bid", 5, 97, 103),
        ]:
            trades, _ = book.process_order(order, False, False)
            assert trades == []
        return book

    def test_resting_orders_queue_by_price_then_time(self, book):
        assert _level(book.asks, 101) == [(100, 5), (102, 5), (103, 5)]
        assert _level(book.bids, 99) == [(100, 5), (102, 5)]
        assert (book.get_best_bid(), book.get_best_ask()) == (99, 101)
        assert list(book.asks.prices) == [101, 103] and list(book.bids.prices) == [97, 98, 99]

    def test_a_crossing_limit_trades_at_the_resting_price(self, book):
        trades, resting = book.process_order(_limit("bid", 2, 102, 109), False, False)
        assert resting is None  # fully filled: nothing rests
        assert len(trades) == 1
        trade = trades[0]
        assert trade["price"] == 101 and trade["quantity"] == 2  # not its own limit of 102
        assert trade["init_party"]["ID"] == 109 and trade["counter_party"]["ID"] == 100
        assert trade["counter_party"]["new_book_quantity"] == 3
        assert _level(book.asks, 101) == [(100, 3), (102, 5), (103, 5)]

    def test_an_oversized_limit_sweeps_the_level_in_time_order_and_rests_the_rest(self, book):
        book.process_order(_limit("bid", 2, 102, 109), False, False)
        trades, resting = book.process_order(_limit("bid", 50, 102, 110), False, False)
        assert [(t["counter_party"]["ID"], int(t["quantity"])) for t in trades] == [
            (100, 3),
            (102, 5),
            (103, 5),
        ]
        assert {t["price"] for t in trades} == {101}
        assert resting is not None and int(resting["quantity"]) == 37
        assert _level(book.bids, 102) == [(110, 37)]
        assert list(book.asks.prices) == [103]  # the 101 level is gone

    def test_a_market_order_walks_down_the_book_best_price_first(self, book):
        book.process_order(_limit("bid", 2, 102, 109), False, False)
        book.process_order(_limit("bid", 50, 102, 110), False, False)
        trades, _ = book.process_order(
            {"type": "market", "side": "ask", "quantity": 40, "trade_id": 111}, False, False
        )
        assert [(int(t["quantity"]), t["price"], t["counter_party"]["ID"]) for t in trades] == [
            (37, 102, 110),
            (3, 99, 100),
        ]
        assert _level(book.bids, 99) == [(100, 2), (102, 5)]  # trade 100 keeps its place
        assert list(book.bids.prices) == [97, 98, 99]

    def test_the_tape_records_every_trade_newest_first(self, book):
        book.process_order(_limit("bid", 2, 102, 109), False, False)
        book.process_order(_limit("bid", 50, 102, 110), False, False)
        assert [(int(t["quantity"]), t["init_party"]["ID"]) for t in book.tape] == [
            (2, 109),
            (3, 110),
            (5, 110),
            (5, 110),
        ]


class _Shadow:
    """A picture of the book built only from what the book reported."""

    def __init__(self):
        self.orders = {"bid": {}, "ask": {}}

    def settle(self, incoming_side, trades, resting):
        opposite = "ask" if incoming_side == "bid" else "bid"
        for trade in trades:
            counter = trade["counter_party"]
            assert counter["side"] == opposite
            order_id = counter["order_id"]
            assert order_id in self.orders[opposite], "a trade against an order we never saw rest"
            new_quantity = counter["new_book_quantity"]
            if new_quantity is None:
                del self.orders[opposite][order_id]
            else:
                self.orders[opposite][order_id]["quantity"] = int(new_quantity)
        if resting:
            self.orders[incoming_side][resting["order_id"]] = {
                "price": Decimal(str(resting["price"])),
                "quantity": int(resting["quantity"]),
            }

    def expect(self, book):
        for side, tree in (("bid", book.bids), ("ask", book.asks)):
            actual = {
                oid: {"price": p, "quantity": q} for oid, (p, q, _t) in _resting(tree).items()
            }
            assert actual == self.orders[side], side


def _drive(seed, steps=300):
    rng = random.Random(seed)
    book, shadow = OrderBook(), _Shadow()

    def place(side, price_range):
        quote = _limit(side, rng.randint(1, 50), rng.randint(*price_range), rng.randint(0, 5))
        trades, resting = book.process_order(quote, False, False)
        shadow.settle(side, trades, resting)

    for _ in range(steps):
        action = rng.choice("AAAXMC")
        side = rng.choice(["bid", "ask"])
        passive = (90, 99) if side == "bid" else (101, 110)
        crossing = (101, 110) if side == "bid" else (90, 99)
        if action == "A":
            place(side, passive)
        elif action == "C":
            place(side, crossing)
        elif action == "X" and shadow.orders[side]:
            order_id = rng.choice(sorted(shadow.orders[side]))
            book.cancel_order(side, order_id)
            del shadow.orders[side][order_id]
        elif action == "M" and shadow.orders[side]:
            order_id = rng.choice(sorted(shadow.orders[side]))
            current = shadow.orders[side][order_id]
            update = {
                "side": side,
                "price": current["price"],
                "quantity": rng.randint(1, 50),
                "trade_id": 0,
            }
            trades, resting = book.modify_order(order_id, update)
            shadow.orders[side].pop(order_id, None)
            shadow.settle(side, trades, resting)
        shadow.expect(book)
        if book.bids and book.asks:
            assert book.get_best_bid() < book.get_best_ask(), "the book is crossed"
    return book


class TestAShadowModelAgreesWithTheBook:
    @pytest.mark.parametrize("seed", range(25))
    def test_random_adds_crosses_modifies_and_cancels(self, seed):
        book = _drive(seed)
        for tree in (book.bids, book.asks):
            assert tree.num_orders == len(tree.order_map)
            assert tree.volume == sum(o.quantity for o in tree.order_map.values())

    def test_the_driver_exercises_every_branch(self):
        """A shadow model that never trades or modifies would agree trivially."""
        traded = 0
        for seed in range(25):
            book = _drive(seed, steps=120)
            traded += len(book.tape)
        assert traded > 100
