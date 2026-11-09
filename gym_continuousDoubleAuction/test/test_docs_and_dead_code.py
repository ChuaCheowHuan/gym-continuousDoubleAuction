"""Tests for docs and dead code.

Moved from `test_s4_hardening.py` by issue #361; the class docstrings keep the
original issue numbers.
"""

import ast

import inspect


from gym_continuousDoubleAuction.envs.account.account import Account


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


class TestTidiedDocsAndDeadCode:
    def test_the_record_docstring_does_not_claim_to_set_a_flag(self):
        doc = OrderBook._record.__doc__
        assert "sets no flag" in " ".join(doc.split())

    def test_process_order_list_carries_no_commented_out_block(self):
        source = inspect.getsource(OrderBook.process_order_list)
        assert "party1" not in source and "party2" not in source

    def test_size_decrease_does_not_assign_an_unused_value(self):
        tree = ast.parse(
            inspect.getsource(Account._size_decrease).replace("    ", "", 1).lstrip()
            if False
            else "def f():\n" + inspect.getsource(Account._size_decrease)
        )
        assigned = {
            t.id
            for n in ast.walk(tree)
            if isinstance(n, ast.Assign)
            for t in n.targets
            if isinstance(t, ast.Name)
        }
        # `mkt_val` is used in the branch that computes the position value, and was
        # assigned and dropped in the other; the else branch must not assign it.
        else_branch = [n for n in ast.walk(tree) if isinstance(n, ast.If)][0].orelse
        assert "mkt_val" not in {
            t.id
            for n in else_branch
            if isinstance(n, ast.Assign)
            for t in n.targets
            if isinstance(t, ast.Name)
        }
        assert "mkt_val" in assigned
