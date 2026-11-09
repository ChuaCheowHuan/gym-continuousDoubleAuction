"""Tests for account refactor.

Moved from `test_refactors.py` by issue #361; the class docstrings keep the
original issue numbers.
"""

import ast

import inspect


from decimal import Decimal


from gym_continuousDoubleAuction.envs.account.account import STEP_COUNTERS, Account


def _stored(function):
    """The attribute names a function assigns on `self`."""
    tree = ast.parse(inspect.getsource(function).lstrip())
    return {
        n.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Attribute)
        and isinstance(n.ctx, ast.Store)
        and isinstance(n.value, ast.Name)
        and n.value.id == "self"
    }


class TestAccountIsInitialisedInOnePlace:
    """#255: `__init__` and `reset_acc` assigned the same 29 attributes twice."""

    def test_a_reset_account_equals_a_fresh_one(self):
        fresh = Account(3, 5000, 2, 5)
        used = Account(3, 5000, 2, 5)
        used.cash, used.net_position, used.realised_pnl = Decimal(1), 9, Decimal(7)
        used.num_trades_step, used.fill_qty_step, used.reward_terms = 4, 2, {"x": 1.0}
        used.liquidation_steps_left, used.max_nav = 3, Decimal(10**9)
        used.reset_acc(3, 5000)
        assert vars(used) == vars(fresh)

    def test_a_reset_keeps_the_fee_rates(self):
        acc = Account(0, 1000, 2, 5)
        acc.reset_acc(0, 1000)
        assert (acc.maker_fee_bps, acc.taker_fee_bps) == (Decimal(2), Decimal(5))

    def test_reset_reads_the_configured_cash_when_none_is_given(self):
        acc = Account(0, 10)
        acc.reset_acc(0)
        assert acc.cash == Account(1).cash

    def test_the_step_counters_are_exactly_the_per_step_attributes_reset_creates(self):
        listed = {name for name, _zero in STEP_COUNTERS}
        created = {
            n for n in _stored(Account.reset_acc) if n.endswith("_step") or n == "order_step_placed"
        }
        assert listed == created

    def test_clearing_zeroes_them_and_nothing_else(self):
        acc = Account(0, 1000)
        for name, _zero in STEP_COUNTERS:
            setattr(acc, name, 7)
        acc.liquidation_steps_left, acc.num_trades = 4, 9
        acc.clear_step_counters()
        assert all(getattr(acc, name) == zero for name, zero in STEP_COUNTERS)
        assert isinstance(acc.fill_value_step, Decimal)
        assert acc.liquidation_steps_left == 4 and acc.num_trades == 9
