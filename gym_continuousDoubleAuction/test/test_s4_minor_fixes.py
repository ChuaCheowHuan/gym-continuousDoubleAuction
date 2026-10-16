"""The S4-minor bugs, one class per issue (#230 to #275).

Each was filed from a review as a small defect with a reproduction, and each
test below fails on the source it was filed against.
"""
from decimal import Decimal

import pytest

from gym_continuousDoubleAuction.envs.account.account import Account, validate_fee_rates
from gym_continuousDoubleAuction.envs.orderbook.order import Order
from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook
from gym_continuousDoubleAuction.envs.orderbook.orderlist import OrderList
from gym_continuousDoubleAuction.envs.orderbook.ordertree import OrderTree


class TestFeeRatesAcceptDecimal:
    """#230: `Account` stores its rates as `Decimal`, and the validator refused them."""

    def test_a_rate_read_back_from_an_account_builds_another(self):
        a = Account(0, 1000, maker_fee_bps=5, taker_fee_bps=10)
        b = Account(1, 1000, maker_fee_bps=a.maker_fee_bps, taker_fee_bps=a.taker_fee_bps)
        assert (b.maker_fee_bps, b.taker_fee_bps) == (Decimal(5), Decimal(10))

    def test_a_decimal_mixes_with_a_float(self):
        validate_fee_rates(Decimal("2.5"), 10.0)

    @pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity"), True, "5", None])
    def test_nonsense_is_still_refused(self, bad):
        with pytest.raises(ValueError, match="maker_fee_bps"):
            validate_fee_rates(bad, 10)

    def test_the_limits_apply_to_a_decimal_too(self):
        with pytest.raises(ValueError, match="within"):
            validate_fee_rates(Decimal("5000"), 10)
        with pytest.raises(ValueError, match="taker_fee_bps must be >= 0"):
            validate_fee_rates(0, Decimal("-1"))
        with pytest.raises(ValueError, match="pays out more"):
            validate_fee_rates(Decimal("-20"), Decimal("10"))


def _order(order_list, order_id, qty=1, price=10):
    quote = {"timestamp": 1, "quantity": Decimal(qty), "price": Decimal(price),
             "order_id": order_id, "trade_id": "t"}
    order = Order(quote, order_list)
    order_list.append_order(order)
    return order


class TestOrderBookBookkeeping:
    """#232: three small defects in `envs/orderbook/`."""

    def test_an_unknown_id_leaves_the_counter_alone(self):
        tree = OrderTree()
        with pytest.raises(KeyError):
            tree.remove_order_by_id(99)
        assert tree.num_orders == 0

    def test_a_supplied_time_of_zero_is_used(self):
        book = OrderBook()
        book.time = 7
        book.cancel_order("bid", 1, time=0)
        assert book.time == 0
        book.time = 7
        book.modify_order(1, {"side": "bid", "price": 1, "quantity": 1}, time=0)
        assert book.time == 0

    def test_a_missing_time_still_advances_the_clock(self):
        book = OrderBook()
        before = book.time
        book.cancel_order("bid", 1)
        assert book.time == before + 1

    def test_an_emptied_list_has_no_head_or_tail(self):
        order_list = OrderList()
        only = _order(order_list, 1)
        order_list.remove_order(only)
        assert len(order_list) == 0
        assert order_list.head_order is None and order_list.tail_order is None
        assert list(order_list) == []
