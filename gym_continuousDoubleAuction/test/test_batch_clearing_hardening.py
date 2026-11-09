"""Tests for batch clearing hardening.

Moved from `test_s4_hardening.py` by issue #361; the class docstrings keep the
original issue numbers.
"""

import ast

import inspect


from decimal import Decimal

import pytest


from gym_continuousDoubleAuction.envs.agent.trader import Trader


from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook


def _q(side, qty, price, tid):
    return {"type": "limit", "side": side, "quantity": qty, "price": price, "trade_id": tid}


import numpy as np  # noqa: E402


def _plain_reference(value):
    """The function as it was before the fast path: the behaviour to preserve."""
    if isinstance(value, np.ndarray):
        if value.ndim == 0:
            return value.item()
        return [_plain_reference(v) for v in value.tolist()]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {k: _plain_reference(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_reference(v) for v in value]
    return value


class TestAFreshBookHasBatchUnaffordable:
    def test_it_is_an_empty_list_before_any_clearing(self):
        assert OrderBook(10).batch_unaffordable == []


class TestBatchClearingChecksItsVolumeWithoutAssert:
    """A bare `assert` disappears under `python -O`, leaving a one-sided trade."""

    def test_clear_batch_contains_no_assert_statement(self):
        tree = ast.parse(
            inspect.getsource(OrderBook.clear_batch).replace("\n    ", "\n", 0).lstrip()
        )
        assert not [n for n in ast.walk(tree) if isinstance(n, ast.Assert)]

    def test_a_mismatch_raises_a_named_error(self, monkeypatch):
        book = OrderBook(10)
        book.begin_batch()
        book.process_order(_q("bid", 10, 102, 0), False, False)
        book.process_order(_q("ask", 10, 98, 1), False, False)
        real = book._auction
        # An auction that claims more volume than the orders can supply: both sides
        # fill 10, the "executable volume" says 15.
        monkeypatch.setattr(
            book, "_auction", lambda *a, **k: (lambda r: (r[0], r[1], r[2] + 5))(real(*a, **k))
        )
        with pytest.raises(RuntimeError, match="sides must match"):
            book.clear_batch(reference_price=100)

    def test_a_normal_batch_still_clears(self):
        book = OrderBook(10)
        book.begin_batch()
        book.process_order(_q("bid", 10, 102, 0), False, False)
        book.process_order(_q("ask", 10, 98, 1), False, False)
        assert len(book.clear_batch(reference_price=100)) == 2


class TestSettleBatchRefusesBeforeItBooksAnything:
    @staticmethod
    def _trade(init, counter, qty=2):
        return {
            "price": Decimal(100),
            "quantity": qty,
            "time": 1,
            "timestamp": 1,
            "init_party": {"ID": init, "side": "bid", "order_id": None, "new_book_quantity": None},
            "counter_party": {
                "ID": counter,
                "side": "ask",
                "order_id": None,
                "new_book_quantity": None,
                "resting": False,
            },
        }

    def test_a_self_pair_late_in_the_list_leaves_the_ledger_untouched(self):
        traders = [Trader(i, 100_000) for i in range(2)]
        before = (traders[0].acc.cash, traders[0].acc.net_position)
        with pytest.raises(ValueError, match="own order"):
            traders[0].settle_batch([self._trade(0, 1), self._trade(0, 0)], None, traders)
        assert (traders[0].acc.cash, traders[0].acc.net_position) == before
        assert traders[1].acc.net_position == 0

    def test_a_clean_list_is_still_booked(self):
        traders = [Trader(i, 100_000) for i in range(2)]
        traders[0].settle_batch([self._trade(0, 1)], None, traders)
        assert traders[0].acc.net_position == 2
