"""A fill never takes cash below zero: sweeps priced in full, batches re-cleared.

doc/15 S2-14. `Trader._order_approved` priced a market order's opening size at the
best opposite price, but a sweep pays every level it takes, so an order the
trader could not afford was approved (cash 1,000, buy 10 against 1 @ 100 and
9 @ 200: cash -900). Under `step_clearing: "batch"` the same gap is wider: the
check runs when an order is queued and the price is only known at clearing, one
uniform price that can sit above the price the order was checked at - for a
market order, for a limit sell opening a short (a short pays its notional in
cash), and for a resting ask that fills above the limit its escrow was posted
at. Measured under random play with fees off: 22 of 12,000 agent-steps
ended with `cash + cash_on_hold` below zero, worst -82.

Sequential clearing now prices the sweep level by level. Batch clearing asks the
env, once it has a clearing price, whether each order's owner can pay for it;
those who cannot sit out (a new order is counted as rejected) and the auction
runs again without them, until everyone left can pay.
"""
from decimal import Decimal

import pytest

from gym_continuousDoubleAuction.envs.agent.trader import Trader
from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook


def _book(cash=1000, n=3, **kw):
    lob = OrderBook()
    traders = [Trader(i, cash if i == 0 else 10 ** 7, **kw) for i in range(n)]
    return lob, traders


def _sell_into(lob, traders, seller, levels):
    """`seller` rests asks at (price, size) levels."""
    for price, size in levels:
        traders[seller].place_order("limit", "ask", size, price, lob, traders)


class TestTheSweepIsPricedLevelByLevel:

    def test_the_documented_overdraw_is_refused(self):
        lob, t = _book(cash=1000)
        _sell_into(lob, t, 1, [(100, 1), (200, 9)])
        # 1 @ 100 + 9 @ 200 = 1,900; the touch alone said 1,000.
        assert not t[0]._order_approved("bid", 10, -1.0, lob, "market")
        t[0].place_order("market", "bid", 10, -1.0, lob, t)
        assert t[0].acc.cash == 1000 and t[0].acc.num_rejected_step == 1

    def test_the_exact_cost_is_approved_and_a_unit_less_is_not(self):
        lob, t = _book(cash=1900)
        _sell_into(lob, t, 1, [(100, 1), (200, 9)])
        assert t[0]._order_approved("bid", 10, -1.0, lob, "market")
        t[0].acc.cash = Decimal(1899)
        assert not t[0]._order_approved("bid", 10, -1.0, lob, "market")

    def test_a_sweep_that_stays_at_the_touch_costs_the_touch(self):
        lob, t = _book(cash=1000)
        _sell_into(lob, t, 1, [(100, 10), (200, 10)])
        assert t[0]._order_approved("bid", 10, -1.0, lob, "market")

    def test_a_thin_book_costs_only_what_it_can_fill(self):
        """A market order for more than the book holds lapses; it pays for what fills."""
        lob, t = _book(cash=1000)
        _sell_into(lob, t, 1, [(100, 5)])
        assert t[0]._order_approved("bid", 50, -1.0, lob, "market")

    def test_the_traders_own_orders_are_not_part_of_the_sweep(self):
        """Self-match prevention cancels them first, so the sweep skips them."""
        lob, t = _book(cash=800)
        _sell_into(lob, t, 0, [(100, 5)])           # its own ask, cancelled on arrival
        _sell_into(lob, t, 1, [(150, 5)])
        # Priced at the touch (100) it would be 500; the real sweep is 5 @ 150.
        assert not t[0]._order_approved("bid", 5, -1.0, lob, "market")
        t[0].acc.cash = Decimal(1000)
        assert t[0]._order_approved("bid", 5, -1.0, lob, "market")

    def test_only_the_opening_part_of_a_flip_is_charged(self):
        lob, t = _book(cash=10 ** 7)
        t[0].place_order("limit", "bid", 4, 100, lob, t)
        t[1].place_order("market", "ask", 4, -1.0, lob, t)      # t[0] long 4
        assert t[0].acc.net_position == 4
        lob2, u = _book(cash=10 ** 7)
        # Short 4 means the first 4 contracts of a buy only close; 6 open.
        u[1].place_order("limit", "bid", 4, 100, lob2, u)
        u[0].place_order("market", "ask", 4, -1.0, lob2, u)     # u[0] short 4
        assert u[0].acc.net_position == -4
        _sell_into(lob2, u, 2, [(100, 4), (120, 6)])
        u[0].acc.cash = Decimal(719)
        assert not u[0]._order_approved("bid", 10, -1.0, lob2, "market")   # 6 @ 120 = 720
        u[0].acc.cash = Decimal(720)
        assert u[0]._order_approved("bid", 10, -1.0, lob2, "market")

    def test_an_empty_book_falls_back_to_the_last_print(self):
        lob, t = _book(cash=1000)
        assert t[0]._order_approved("bid", 5, -1.0, lob, "market") in (True, False)   # no crash


def _env(**cfg):
    base = {"num_of_agents": 3, "init_cash": 10 ** 6, "is_render": False, "max_step": 40,
            "step_clearing": "batch", "initial_price_min": 100, "initial_price_max": 100,
            "liquidation": "off"}
    base.update(cfg)
    env = continuousDoubleAuctionEnv(base)
    env.reset(seed=1)
    return env


def _clear(env, orders, reference=100):
    """Queue `orders` (trader, type, side, size, price) and clear them as `do_actions` would."""
    env.LOB.begin_batch()
    for trader, kind, side, size, price in orders:
        trader.place_order(kind, side, size, price, env.LOB, env.traders)
    return env._clear_batch_and_settle(reference)


def _whole(env):
    return all(t.acc.cash + t.acc.cash_on_hold >= 0 for t in env.traders)


def _uncrossed(env):
    """No resting bid at or above a resting ask: the book a next batch can trust."""
    bid, ask = env.LOB.get_best_bid(), env.LOB.get_best_ask()
    return bid is None or ask is None or bid < ask


class TestABatchIsReClearedWithoutWhatItsOwnersCannotPay:

    def _asks(self, env):
        a1 = env.traders[1]
        a1.place_order("limit", "ask", 5, 100, env.LOB, env.traders)
        a1.place_order("limit", "ask", 5, 110, env.LOB, env.traders)

    def test_a_market_buy_that_clears_above_its_touch_price_sits_out(self):
        env = _env()
        self._asks(env)
        buyer = env.traders[0]
        buyer.acc.cash = Decimal(920)            # 9 @ 100 = 900 passes the check; 9 clears at 110 = 990
        _clear(env, [(buyer, "market", "bid", 9, -1.0)])
        assert buyer.acc.cash == 920 and buyer.acc.net_position == 0
        assert buyer.acc.num_rejected_step == 1
        assert env.LOB.asks.volume == 10          # the book is untouched
        assert _whole(env)

    def test_the_same_order_with_the_cash_fills(self):
        env = _env()
        self._asks(env)
        buyer = env.traders[0]
        buyer.acc.cash = Decimal(990)
        _clear(env, [(buyer, "market", "bid", 9, -1.0)])
        assert buyer.acc.net_position == 9 and buyer.acc.num_rejected_step == 0
        assert _whole(env)

    def test_dropping_one_order_re_clears_the_rest_at_their_own_price(self):
        env = _env()
        self._asks(env)
        buyer, other = env.traders[0], env.traders[2]
        buyer.acc.cash = Decimal(920)
        # With the market buy in, the auction clears at 110; without it, at 100.
        _clear(env, [(buyer, "market", "bid", 9, -1.0), (other, "limit", "bid", 3, 100)])
        assert buyer.acc.net_position == 0
        assert other.acc.net_position == 3
        assert all(t["price"] == 100 for t in env.LOB.tape if t["quantity"] == 3)
        assert _whole(env)

    def test_a_new_limit_sell_opening_a_short_that_clears_higher_sits_out(self):
        """A short pays its notional in cash, at the price it clears at."""
        env = _env()
        env.traders[1].place_order("limit", "bid", 10, 110, env.LOB, env.traders)
        seller = env.traders[0]
        seller.acc.cash = Decimal(1000)           # 10 @ 100 passes; the auction clears at 108
        _clear(env, [(seller, "limit", "ask", 10, 100)], reference=108)
        # It could not pay for the short at 108, so it sits out. It must not rest
        # at 100 under a resting bid at 110, which would cross the book: it lapses,
        # and counts as rejected like any order the cash check turns away.
        assert seller.acc.net_position == 0 and seller.acc.num_rejected_step == 1
        assert env.LOB.asks.volume == 0
        assert seller.acc.cash == 1000 and seller.acc.cash_on_hold == 0
        assert _uncrossed(env) and _whole(env)

    def test_a_resting_ask_that_cannot_cover_a_better_fill_sits_out(self):
        env = _env()
        seller, buyer = env.traders[0], env.traders[1]
        seller.acc.cash = Decimal(1000)
        seller.place_order("limit", "ask", 10, 100, env.LOB, env.traders)    # escrows 1,000
        assert seller.acc.cash == 0
        _clear(env, [(buyer, "market", "bid", 10, -1.0)], reference=108)
        assert seller.acc.net_position == 0       # it would owe 80 more than it has
        assert env.LOB.asks.volume == 10          # still resting
        assert _whole(env)

    def test_a_limit_left_over_by_a_sitting_out_ask_does_not_cross_it(self):
        """The new bid at 105 finds no supply once the ask at 98 sits out, and
        resting at 105 would sit above that ask."""
        env = _env()
        seller, buyer = env.traders[0], env.traders[1]
        seller.acc.cash = Decimal(1000)
        seller.place_order("limit", "ask", 10, 98, env.LOB, env.traders)     # escrows 980
        _clear(env, [(buyer, "limit", "bid", 10, 105)], reference=104)
        assert seller.acc.net_position == 0 and buyer.acc.net_position == 0
        assert env.LOB.asks.volume == 10           # the ask stays
        assert env.LOB.bids.volume == 0            # the bid lapses instead of crossing it
        assert _uncrossed(env) and _whole(env)

    def test_the_next_batch_can_still_clear_after_an_order_sat_out(self):
        """A crossed resting book used to raise in the next batch's pairing."""
        env = _env()
        seller, buyer = env.traders[0], env.traders[1]
        seller.acc.cash = Decimal(1000)
        seller.place_order("limit", "ask", 10, 98, env.LOB, env.traders)
        _clear(env, [(buyer, "limit", "bid", 10, 105)], reference=104)
        _clear(env, [(env.traders[2], "limit", "bid", 5, 100)], reference=99)
        assert _uncrossed(env) and _whole(env)

    def test_a_resting_ask_with_the_cash_still_gets_the_better_price(self):
        env = _env()
        seller, buyer = env.traders[0], env.traders[1]
        seller.acc.cash = Decimal(1100)
        seller.place_order("limit", "ask", 10, 100, env.LOB, env.traders)
        _clear(env, [(buyer, "market", "bid", 10, -1.0)], reference=108)
        assert seller.acc.net_position == -10
        assert _whole(env)

    def test_a_clearing_nobody_objects_to_is_unchanged(self):
        env = _env()
        a, b = env.traders[0], env.traders[1]
        results = _clear(env, [(a, "limit", "bid", 5, 102), (b, "limit", "ask", 5, 98)])
        assert a.acc.net_position == 5 and b.acc.net_position == -5
        assert sum(t.acc.nav for t in env.traders) == Decimal(3) * Decimal(env.init_cash)
        assert results is not None


#: Seeds whose random play overdrew cash before the fix (found by scanning 160
#: seeded episodes of 4 agents at 3,000 cash), plus a few that did not.
OVERDREW = {"sequential": [34, 114, 142], "batch": [20, 49, 58, 112, 119]}


class TestNoFillEverOverdrawsCash:
    """Random play at thin cash, on seeds that overdrew before the fix.

    An overdraw is `cash + cash_on_hold < 0` for any trader. Every cause is
    covered: a sweep priced at the touch, a batch price above the one an order
    was checked at (S2-14), and the loss a cover realises into cash when a short
    has been squeezed past its collateral (S2-15, which used to show as a
    trader that had been under water and was left out of this count). The book
    must also never be crossed.
    """

    @pytest.mark.parametrize("clearing", ["sequential", "batch"])
    @pytest.mark.parametrize("fee", [0, 100])
    def test_random_play_at_thin_cash(self, clearing, fee):
        overdrawn = 0
        for seed in OVERDREW[clearing] + [0, 1, 2]:
            env = continuousDoubleAuctionEnv({
                "num_of_agents": 4, "init_cash": 3000, "max_step": 80, "step_clearing": clearing,
                "initial_price_min": 20, "initial_price_max": 60, "liquidation": "off",
                "maker_fee_bps": fee, "taker_fee_bps": fee})
            env.reset(seed=seed)
            for a in env.agents:
                env.action_spaces[a].seed(seed)
            while True:
                _, _, dones, truncs, _ = env.step(
                    {a: env.action_spaces[a].sample() for a in env.agents})
                for t in env.traders:
                    if t.acc.cash + t.acc.cash_on_hold < 0:
                        overdrawn += 1
                assert env.fees_collected + sum(t.acc.nav for t in env.traders) \
                    == Decimal(4) * Decimal(env.init_cash)
                assert _uncrossed(env), f"seed {seed}: the book is crossed"
                if dones["__all__"] or truncs["__all__"]:
                    break
        assert overdrawn == 0


def _underwater_short(cash_after, entry=10, squeezed_to=30, lots=10):
    """A trader short `lots` at `entry` after the price has squeezed to `squeezed_to`.

    The short posted `lots x entry` as collateral, so its position is worth
    `2 x lots x entry - lots x squeezed_to` - negative once the price passes
    twice the entry. Covering it settles that value into cash.
    """
    lob = OrderBook()
    t = [Trader(0, 10 ** 6), Trader(1, 10 ** 7), Trader(2, 10 ** 7)]
    t[1].place_order("limit", "bid", lots, entry, lob, t)
    t[0].place_order("market", "ask", lots, -1.0, lob, t)            # t0 short at `entry`
    assert t[0].acc.net_position == -lots
    t[2].place_order("limit", "ask", 3 * lots, squeezed_to, lob, t)  # liquidity to cover into
    t[0].acc.mark_to_mkt(t[0].ID, Decimal(squeezed_to))
    t[0].acc.cash = Decimal(cash_after)
    return lob, t


class TestClosingALosingShortNeedsTheCashForTheLoss:
    """doc/15 S2-15. Covering a short past its collateral realises a negative
    `position_val` into cash; the check let the cover through unreserved."""

    def test_the_position_really_is_under_water(self):
        lob, t = _underwater_short(cash_after=100)
        assert t[0].acc.position_val == Decimal(-100)

    def test_a_full_cover_without_the_cash_for_the_loss_is_refused(self):
        lob, t = _underwater_short(cash_after=99)
        assert not t[0]._order_approved("bid", 10, 30, lob, "limit")
        assert not t[0]._order_approved("bid", 10, -1.0, lob, "market")
        t[0].place_order("market", "bid", 10, -1.0, lob, t)
        assert t[0].acc.net_position == -10 and t[0].acc.num_rejected_step == 1

    def test_the_cash_for_the_loss_is_enough(self):
        lob, t = _underwater_short(cash_after=100)
        assert t[0]._order_approved("bid", 10, 30, lob, "limit")
        t[0].place_order("market", "bid", 10, -1.0, lob, t)
        assert t[0].acc.net_position == 0
        assert t[0].acc.cash + t[0].acc.cash_on_hold >= 0

    def test_a_partial_cover_moves_no_loss_and_needs_no_cash(self):
        """The loss stays in the remaining lots' value until the position is flat."""
        lob, t = _underwater_short(cash_after=0)
        assert t[0]._order_approved("bid", 9, -1.0, lob, "market")

    def test_a_flip_needs_the_loss_and_the_new_position(self):
        lob, t = _underwater_short(cash_after=249)
        assert not t[0]._order_approved("bid", 15, -1.0, lob, "market")   # 100 + 5 x 30 = 250
        t[0].acc.cash = Decimal(250)
        assert t[0]._order_approved("bid", 15, -1.0, lob, "market")

    def test_a_short_not_past_its_collateral_costs_nothing_to_cover(self):
        lob, t = _underwater_short(cash_after=0, squeezed_to=15)      # worth 2 x 100 - 150 = 50 > 0
        assert t[0]._order_approved("bid", 10, -1.0, lob, "market")

    def test_a_long_never_has_a_loss_to_reserve(self):
        lob = OrderBook()
        t = [Trader(0, 10 ** 6), Trader(1, 10 ** 7)]
        t[1].place_order("limit", "ask", 10, 100, lob, t)
        t[0].place_order("market", "bid", 10, -1.0, lob, t)
        t[1].place_order("limit", "bid", 10, 1, lob, t)               # price collapses
        t[0].acc.mark_to_mkt(t[0].ID, Decimal(1))
        t[0].acc.cash = Decimal(0)
        assert t[0]._order_approved("ask", 10, -1.0, lob, "market")

    def test_a_batch_cover_that_clears_above_its_price_sits_out(self):
        """A market cover is checked at the clearing price, where the loss is larger."""
        env = _env()
        short = env.traders[0]
        env.traders[1].place_order("limit", "bid", 10, 10, env.LOB, env.traders)
        short.place_order("market", "ask", 10, -1.0, env.LOB, env.traders)
        env.traders[2].place_order("limit", "ask", 5, 29, env.LOB, env.traders)
        env.traders[2].place_order("limit", "ask", 5, 40, env.LOB, env.traders)
        short.acc.mark_to_mkt(short.ID, Decimal(29))
        short.acc.cash = Decimal(110)       # 10 @ 29 -> loss 90; 5 @ 29 + 5 @ 40 clears at 40 -> 200
        _clear(env, [(short, "market", "bid", 10, -1.0)], reference=40)
        assert short.acc.net_position == -10 and short.acc.num_rejected_step == 1
        assert _whole(env) and _uncrossed(env)
