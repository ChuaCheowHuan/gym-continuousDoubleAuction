"""The ledger's type policy, enforced rather than assumed.

    prices    -> Decimal
    money     -> Decimal
    sizes     -> int
    signals   -> float   (reward and drawdown; RLlib requires float rewards)

The point is not tidiness. Two concrete failures motivated it:

  * `Decimal * float` raises TypeError, while `Decimal * int` is fine. The
    orderbook carries two local workarounds for exactly that error
    (`orderbook.py:76-79` and `:99-100`, both commented with the traceback),
    and `cash_processor.py:78` would raise it on the modify path.
  * A field that changes type partway through an episode breaks every consumer
    that checks it. `net_position` was int until the first fill and Decimal
    after; `VWAP` was Decimal until a position went flat and int after.

Code in `envs/orderbook/` is deliberately not changed (doc/11 1.8). It stores
sizes as Decimal internally, so the boundary is normalised on the way out by
`trader._normalise_trade_sizes` - these tests pin that boundary, since it is
what makes the policy hold everywhere else.
"""
import os
import sys
from decimal import Decimal

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.envs.agent.trader import _normalise_trade_sizes

NUM_AGENTS = 4
INIT_CASH = 1000000

MONEY_FIELDS = ["cash", "cash_on_hold", "position_val", "init_nav", "nav",
                "prev_nav", "max_nav", "profit", "total_profit"]
PRICE_FIELDS = ["VWAP"]
SIZE_FIELDS = ["net_position", "num_trades", "num_trades_step",
               "num_passive_fills_step", "order_step_placed"]
SIGNAL_FIELDS = ["reward", "drawdown"]


@pytest.fixture(scope="module")
def stepped_env():
    env = continuousDoubleAuctionEnv({
        "num_of_agents": NUM_AGENTS,
        "init_cash": INIT_CASH,
        "tick_size": 1,
        "tape_display_length": 100000,
        "max_step": 100,
    })
    env.reset()
    snapshots = []
    for _ in range(40):
        actions = {
            f"agent_{i}": env.action_spaces[f"agent_{i}"].sample()
            for i in range(NUM_AGENTS)
        }
        _, _, terminateds, truncateds, _ = env.step(actions)
        snapshots.append([
            {f: getattr(t.acc, f) for f in
             MONEY_FIELDS + PRICE_FIELDS + SIZE_FIELDS + SIGNAL_FIELDS}
            for t in env.traders
        ])
        if terminateds.get("__all__") or truncateds.get("__all__"):
            break
    return env, snapshots


def _every(snapshots, fields):
    for step in snapshots:
        for acc in step:
            for field in fields:
                yield field, acc[field]


class TestAccountTypes:

    def test_money_is_decimal(self, stepped_env):
        _, snapshots = stepped_env
        for field, value in _every(snapshots, MONEY_FIELDS):
            assert isinstance(value, Decimal), (
                f"{field} is {type(value).__name__}: money must be Decimal"
            )

    def test_prices_are_decimal(self, stepped_env):
        """VWAP is an average fill price. It used to be assigned a bare 0 when a
        position went flat, so it read back as an int for the rest of the run."""
        _, snapshots = stepped_env
        for field, value in _every(snapshots, PRICE_FIELDS):
            assert isinstance(value, Decimal), (
                f"{field} is {type(value).__name__}: prices must be Decimal"
            )

    def test_sizes_are_int(self, stepped_env):
        _, snapshots = stepped_env
        for field, value in _every(snapshots, SIZE_FIELDS):
            assert isinstance(value, int) and not isinstance(value, bool), (
                f"{field} is {type(value).__name__}: sizes must be int"
            )

    def test_learning_signals_are_float(self, stepped_env):
        """The deliberate exception: RLlib requires float rewards, and drawdown
        feeds the reward. These are signals, not money."""
        _, snapshots = stepped_env
        for field, value in _every(snapshots, SIGNAL_FIELDS):
            assert isinstance(value, float), (
                f"{field} is {type(value).__name__}: signals must be float"
            )

    def test_no_field_changes_type_across_the_episode(self, stepped_env):
        """The failure this policy exists to prevent: a field whose type depends
        on whether a trade has happened yet."""
        _, snapshots = stepped_env
        types = {}
        for field, value in _every(
            snapshots, MONEY_FIELDS + PRICE_FIELDS + SIZE_FIELDS + SIGNAL_FIELDS
        ):
            types.setdefault(field, set()).add(type(value).__name__)
        unstable = {f: t for f, t in types.items() if len(t) > 1}
        assert not unstable, f"fields changing type mid-episode: {unstable}"


class TestBookBoundary:
    """The orderbook is untouched, so its output is normalised on the way out."""

    def test_prices_out_of_the_book_are_decimal(self, stepped_env):
        env, _ = stepped_env
        assert env.LOB.tape, "no trades on the tape"
        for entry in env.LOB.tape:
            assert isinstance(entry["price"], Decimal)

    def test_sizes_reaching_the_account_are_int(self, stepped_env):
        """What the account consumes, after normalisation - not what the book
        stores internally, which stays Decimal and is not our business."""
        env, _ = stepped_env
        for entry in env.LOB.tape:
            assert Decimal(str(entry["quantity"])) % 1 == 0, (
                "a non-integral size would make the int() coercion at the "
                "boundary a silent truncation"
            )

    def test_normalise_converts_decimal_sizes(self):
        trades = [
            {"quantity": Decimal("35"), "price": Decimal("10")},
            {"quantity": 12, "price": Decimal("10")},
        ]
        _normalise_trade_sizes(trades)
        assert [t["quantity"] for t in trades] == [35, 12]
        assert all(isinstance(t["quantity"], int) for t in trades)

    def test_normalise_refuses_a_fractional_size(self):
        """Silent truncation would corrupt the ledger; this must be loud."""
        with pytest.raises(ValueError, match="non-integral trade size"):
            _normalise_trade_sizes([{"quantity": Decimal("1.5")}])

    def test_normalise_tolerates_a_trade_without_a_size(self):
        trades = [{"price": Decimal("10")}]
        _normalise_trade_sizes(trades)
        assert "quantity" not in trades[0]


class TestBookIngress:
    """Sizes must be int *going in*, not only coming back out.

    These exist because of a mutation test: restoring the old
    `(size + min_size) * 1.0` float coercion in action_helper left every other
    test in this file passing. `_normalise_trade_sizes` absorbs float sizes on
    the way out so completely that the account never notices - which is good,
    but it means the egress tests cannot see an ingress regression.

    Ingress matters on its own: `cash_processor.py:78` computes
    `Decimal(str(price)) * qoute['quantity']` on the modify path, which is a
    TypeError with a float size and fine with an int. That path is not reached
    by the trades the egress tests inspect.
    """

    def test_set_actions_emits_int_sizes(self, stepped_env):
        env, _ = stepped_env
        model_outs = {
            f"agent_{i}": env.action_spaces[f"agent_{i}"].sample()
            for i in range(NUM_AGENTS)
        }
        for act in env.set_actions(model_outs):
            size = act["size"]
            assert isinstance(size, int) and not isinstance(size, bool), (
                f"size {size!r} is {type(size).__name__}: sizes must enter the "
                f"book as int, or cash_processor's modify path raises TypeError"
            )

    def test_sizes_reaching_the_book_are_int(self, stepped_env):
        """Wrap the book's front door and check every order that arrives."""
        env, _ = stepped_env
        seen = []
        original = env.LOB.process_order

        def recording(quote, *args, **kwargs):
            seen.append(quote.get("quantity"))
            return original(quote, *args, **kwargs)

        env.LOB.process_order = recording
        try:
            for _ in range(10):
                actions = {
                    f"agent_{i}": env.action_spaces[f"agent_{i}"].sample()
                    for i in range(NUM_AGENTS)
                }
                _, _, terminateds, truncateds, _ = env.step(actions)
                if terminateds.get("__all__") or truncateds.get("__all__"):
                    break
        finally:
            env.LOB.process_order = original

        assert seen, "no orders reached the book"
        offenders = [q for q in seen
                     if q is not None and not isinstance(q, int)]
        assert not offenders, (
            f"{len(offenders)} of {len(seen)} orders entered the book with a "
            f"non-int size, e.g. {offenders[0]!r}"
        )


class TestArithmeticIsWellDefined:
    """The mixes that must work, and the one that must not be reachable."""

    def test_decimal_times_int_is_defined(self):
        assert Decimal("10") * 3 == Decimal("30")

    def test_decimal_times_float_raises(self):
        """Documents *why* sizes are int: this is the error the orderbook has
        two workarounds for, and it is a TypeError at runtime, not a warning."""
        with pytest.raises(TypeError):
            Decimal("10") * 3.0

    def test_a_position_valuation_stays_decimal(self, stepped_env):
        """int size x Decimal price must give Decimal money, every step."""
        env, _ = stepped_env
        for trader in env.traders:
            value = trader.acc.net_position * trader.acc.VWAP
            assert isinstance(value, Decimal)
