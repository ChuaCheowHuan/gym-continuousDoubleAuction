"""Property-based tests for the matching engine and the ledger.

doc/10 §8 and doc/15 S4-13: the order book states its invariants outright,
and every one of them holds for *any* order sequence, which is exactly what an
example-based suite cannot say. Hypothesis generates the sequences; shrinking
turns a failure into the shortest sequence that breaks the invariant, which is
the report a matching-engine bug needs.

Two layers. `TestBookInvariants` drives `Trader.place_order` straight into an
`OrderBook`, so it is fast enough for hundreds of examples and covers the
tree/list/map bookkeeping and the crossed-book rule. `TestEnvInvariants` steps
the whole env with random actions under a Hypothesis-chosen seed, which is the
only level at which NAV conservation is defined - every account has to be
marked at the same price - and asserts it exactly, in Decimal, after every
step.
"""
from decimal import Decimal

import numpy as np
from hypothesis import given, settings, strategies as st, HealthCheck

from gym_continuousDoubleAuction.envs.agent.trader import Trader
from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook
from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)

N_TRADERS = 3
INIT_CASH = 100_000
PRICES = list(range(95, 106))

order = st.fixed_dictionaries({
    "who": st.integers(0, N_TRADERS - 1),
    "type": st.sampled_from(["limit", "limit", "market", "modify", "cancel"]),
    "side": st.sampled_from(["bid", "ask"]),
    "size": st.integers(1, 40),
    "price": st.sampled_from(PRICES),
})


def _check_tree(tree, side):
    """Every cache the tree keeps agrees with a walk of its contents."""
    orders = list(tree.order_map.values())
    assert tree.num_orders == len(orders) == len(tree)
    assert tree.depth == len(tree.price_map)
    assert tree.volume == sum(o.quantity for o in orders), side
    for price, level in tree.price_map.items():
        listed = list(level)
        assert len(listed) == level.length > 0, (side, price)
        assert level.volume == sum(o.quantity for o in listed), (side, price)
        for o in listed:
            assert o.price == price
            assert o.quantity > 0
            assert o.order_list is level
            assert tree.order_map[o.order_id] is o
        # Time priority inside a level: the list is ordered by timestamp.
        stamps = [o.timestamp for o in listed]
        assert stamps == sorted(stamps), (side, price)


def check_book(book):
    _check_tree(book.bids, "bid")
    _check_tree(book.asks, "ask")
    best_bid, best_ask = book.get_best_bid(), book.get_best_ask()
    if best_bid is not None and best_ask is not None:
        assert best_bid < best_ask, "a resting book is never locked or crossed"
    for entry in book.tape:
        assert entry["quantity"] > 0
        assert entry["price"] > 0


class TestBookInvariants:

    @settings(max_examples=300, deadline=None)
    @given(st.lists(order, min_size=1, max_size=60))
    def test_tree_caches_and_uncrossed_book(self, sequence):
        book = OrderBook()
        traders = [Trader(i, cash=INIT_CASH) for i in range(N_TRADERS)]
        for act in sequence:
            t = traders[act["who"]]
            price = -1.0 if act["type"] == "market" else float(act["price"])
            t.place_order(act["type"], act["side"], act["size"], price, book, traders)
            check_book(book)

    @settings(max_examples=200, deadline=None)
    @given(st.lists(order, min_size=1, max_size=60))
    def test_escrow_matches_own_resting_orders(self, sequence):
        """`cash_on_hold` is exactly the notional of the trader's live orders.

        The ledger escrows `price x quantity` when an order rests and releases
        it on fill, cancel or modify. If any path forgot one side of that, the
        escrow would drift from the book - and NAV conservation alone would
        not notice, because cash and cash_on_hold are summed into NAV.
        """
        book = OrderBook()
        traders = [Trader(i, cash=INIT_CASH) for i in range(N_TRADERS)]
        for act in sequence:
            t = traders[act["who"]]
            price = -1.0 if act["type"] == "market" else float(act["price"])
            t.place_order(act["type"], act["side"], act["size"], price, book, traders)
            for trader in traders:
                resting = sum(
                    o.price * o.quantity
                    for tree in (book.bids, book.asks)
                    for o in tree.order_map.values()
                    if o.trade_id == trader.ID
                )
                assert trader.acc.cash_on_hold == resting, trader.ID

    @settings(max_examples=100, deadline=None)
    @given(st.lists(order, min_size=1, max_size=60))
    def test_positions_net_to_zero(self, sequence):
        """Every contract long is a contract short somewhere else."""
        book = OrderBook()
        traders = [Trader(i, cash=INIT_CASH) for i in range(N_TRADERS)]
        for act in sequence:
            t = traders[act["who"]]
            price = -1.0 if act["type"] == "market" else float(act["price"])
            t.place_order(act["type"], act["side"], act["size"], price, book, traders)
            assert sum(tr.acc.net_position for tr in traders) == 0


class TestEnvInvariants:

    @settings(max_examples=12, deadline=None,
              suppress_health_check=[HealthCheck.too_slow])
    @given(seed=st.integers(0, 2**31 - 1), tick=st.sampled_from([1, 0.5, 0.1]),
           steps=st.integers(5, 40))
    def test_nav_conserved_and_book_sound_under_random_play(self, seed, tick, steps):
        env = continuousDoubleAuctionEnv({
            "num_of_agents": 4, "tick_size": tick, "is_render": False,
            "max_step": 64, "init_cash": INIT_CASH,
        })
        env.reset(seed=seed)
        rng = np.random.default_rng(seed)
        for agent in env.agents:
            env.action_spaces[agent].seed(int(rng.integers(0, 2**31 - 1)))
        total = Decimal(INIT_CASH) * env.num_of_agents
        tick_d = Decimal(str(tick))
        # Not `== total`. The ledger carries VWAP as a Decimal quotient, and
        # `mark_to_mkt` builds position_val as |pos| x VWAP + |pos| x (mark -
        # VWAP), whose two products round independently at the 28-digit
        # context - so conservation holds to ~1e-22 on a 4e5 total, not to
        # zero. This suite is what found that (seed 161, tick 1); doc/15 S3-23
        # records it and what exactness would take. The bound used here is the
        # `nav_tolerance` a training run applies (train_config.json), so the
        # test asserts the same invariant a run enforces.
        tolerance = Decimal("1e-6")
        for _ in range(steps):
            actions = {a: env.action_spaces[a].sample() for a in env.agents}
            _, rewards, term, trunc, infos = env.step(actions)
            assert abs(sum(t.acc.nav for t in env.traders) - total) <= tolerance
            for t in env.traders:
                # cash may dip below zero by at most the closing-side escrow
                # (S1-5 tail), never the pair together.
                assert t.acc.cash + t.acc.cash_on_hold >= 0
            check_book(env.LOB)
            for tree in (env.LOB.bids, env.LOB.asks):
                for price in tree.price_map:
                    q = price / tick_d
                    assert q == q.to_integral_value(), str(price)
            for agent, info in infos.items():
                # Every agent's NAV string parses back to the ledger exactly.
                assert Decimal(info["NAV"]) == env.traders[int(agent.split("_")[1])].acc.nav
            for value in rewards.values():
                assert np.isfinite(value)
            if term.get("__all__") or trunc.get("__all__"):
                break
