"""Self-match prevention, and a mark that a single participant cannot set.

doc/15 S2-5. Two mechanisms, and it takes both:

* A trader could cross its own resting order. The fill printed to the tape,
  and `mark_to_mkt` marked *every* account off the last print - so one
  self-traded contract at a chosen price re-priced the whole market, including
  the self-trader's own reward. Measured before the fix: 1,000 NAV moved by a
  single 1-lot print. It was free, too: `_process_trades` sends a self-trade
  down a path that never calls `process_acc`, so neither `num_trades` nor
  `num_trades_step` incremented and `trade_penalty` never charged for it.

* Prevention alone is not enough, because the *resting leg* of the attempt
  survives. With the mark falling back to a one-sided quote, that lone order
  became the mark and moved every account anyway. So the midpoint is used only
  when the book is genuinely two-sided.

Prevention lives in `Trader`, not in `OrderBook.process_order_list` where a
`trade_id` skip would be the natural place for it, because `envs/orderbook/` is
off-limits to changes (doc/15 S3-4).
"""
from decimal import Decimal

import pytest

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook
from gym_continuousDoubleAuction.envs.agent.trader import Trader


class TestSelfMatchPrevention:
    def setup_method(self):
        self.book = OrderBook()
        self.a = Trader(ID=1, cash=1_000_000)
        self.b = Trader(ID=2, cash=1_000_000)
        self.agents = [self.a, self.b]

    def test_crossing_your_own_bid_prints_nothing(self):
        self.a.place_order('limit', 'bid', 10, 100, self.book, self.agents)

        trades, _residue = self.a.place_order(
            'limit', 'ask', 10, 100, self.book, self.agents)

        assert trades == []
        assert len(self.book.tape) == 0
        assert len(self.book.bids) == 0, "the resting leg is withdrawn"

    def test_crossing_your_own_ask_prints_nothing(self):
        self.a.place_order('limit', 'ask', 10, 100, self.book, self.agents)

        trades, _residue = self.a.place_order(
            'limit', 'bid', 10, 100, self.book, self.agents)

        assert trades == []
        assert len(self.book.tape) == 0

    def test_a_market_order_sweeps_none_of_its_own_orders(self):
        self.a.place_order('limit', 'ask', 10, 100, self.book, self.agents)
        self.a.place_order('limit', 'ask', 10, 101, self.book, self.agents)

        trades, _residue = self.a.place_order(
            'market', 'bid', 20, -1, self.book, self.agents)

        assert trades == []
        assert len(self.book.asks) == 0, "a market order is in every level's path"

    def test_only_the_orders_actually_crossed_are_withdrawn(self):
        """A resting order the incoming price does not reach is left alone."""
        self.a.place_order('limit', 'ask', 10, 100, self.book, self.agents)
        self.a.place_order('limit', 'ask', 10, 200, self.book, self.agents)

        self.a.place_order('limit', 'bid', 10, 150, self.book, self.agents)

        remaining = sorted(o.price for o in self.book.asks.order_map.values())
        assert remaining == [Decimal(200)], "only the ask at 100 was crossed"

    def test_another_trader_still_matches_normally(self):
        """The guard against a fix that suppresses genuine trades."""
        self.a.place_order('limit', 'ask', 10, 100, self.book, self.agents)

        trades, _residue = self.b.place_order(
            'limit', 'bid', 10, 100, self.book, self.agents)

        assert len(trades) == 1
        assert len(self.book.tape) == 1
        assert self.a.acc.net_position == -10
        assert self.b.acc.net_position == 10

    def test_withdrawing_returns_the_escrow(self):
        """The withdrawn bid's escrow is released, not stranded.

        It does not fall to zero: the incoming ask finds an empty book and
        rests, so the same 1,000 is re-escrowed against it. What the assertions
        pin is that it moved rather than being counted twice, and that the
        round trip is NAV-neutral.
        """
        self.a.place_order('limit', 'bid', 10, 100, self.book, self.agents)
        assert self.a.acc.cash_on_hold == Decimal(1000)
        nav_before = self.a.acc.cal_nav()

        self.a.place_order('limit', 'ask', 10, 100, self.book, self.agents)

        assert self.a.acc.cash_on_hold == Decimal(1000), "held against the ask now"
        assert len(self.book.bids) == 0 and len(self.book.asks) == 1
        assert self.a.acc.cal_nav() == nav_before, "withdrawal is NAV-neutral"

    def test_withdrawing_without_a_replacement_frees_the_escrow(self):
        """The same round trip where nothing rests afterwards."""
        self.a.place_order('limit', 'bid', 10, 100, self.book, self.agents)
        self.b.place_order('limit', 'bid', 10, 120, self.book, self.agents)
        nav_before = self.a.acc.cal_nav()

        # a's own bid at 100 is withdrawn as crossed, and the ask then fills
        # against b's bid at 120 - so nothing of a's is left resting.
        self.a.place_order('limit', 'ask', 10, 100, self.book, self.agents)

        assert len(self.book.tape) == 1, "it traded with b, not with itself"

        assert self.a.acc.cash_on_hold == Decimal(0)
        assert self.a.acc.cal_nav() == nav_before

    def test_a_cancel_withdraws_nothing_on_the_far_side(self):
        """A cancel crosses nothing, so it must not disturb the other side."""
        self.a.place_order('limit', 'bid', 10, 100, self.book, self.agents)
        self.a.place_order('limit', 'ask', 10, 200, self.book, self.agents)

        self.a.place_order('cancel', 'bid', 10, 100, self.book, self.agents)

        assert len(self.book.bids) == 0
        assert len(self.book.asks) == 1, "the ask was never in the cancel's path"


class TestMarkPriceCannotBeSetByOneParticipant:
    def _env(self, **overrides):
        config = {"num_of_agents": 2, "max_step": 50, "is_render": False}
        config.update(overrides)
        env = continuousDoubleAuctionEnv(config)
        env.reset(seed=1)
        return env

    def _open_a_position(self, env):
        """Leave trader 0 long 100 and trader 1 short 100, both at 50."""
        a, b = env.traders
        b.place_order('limit', 'ask', 100, 50.0, env.LOB, env.traders)
        a.place_order('limit', 'bid', 100, 50.0, env.LOB, env.traders)
        env.mark_to_mkt()
        assert a.acc.net_position == 100
        return a, b

    def test_a_self_cross_moves_nobody_s_nav(self):
        """The measured exploit, end to end. It used to move 1,000."""
        env = self._env()
        a, b = self._open_a_position(env)
        a_nav, b_nav = a.acc.nav, b.acc.nav

        a.place_order('limit', 'ask', 1, 60.0, env.LOB, env.traders)
        a.place_order('limit', 'bid', 1, 60.0, env.LOB, env.traders)
        env.mark_to_mkt()

        assert a.acc.nav == a_nav
        assert b.acc.nav == b_nav

    def test_a_lone_quote_is_not_the_mark(self):
        """Prevention leaves the resting leg behind; the mark must ignore it.

        Without the two-sided requirement this alone moved 1,000 NAV.
        """
        env = self._env()
        a, b = self._open_a_position(env)
        a_nav, b_nav = a.acc.nav, b.acc.nav

        a.place_order('limit', 'bid', 1, 60.0, env.LOB, env.traders)
        env.mark_to_mkt()

        assert env.LOB.get_best_ask() is None, "precondition: a one-sided book"
        assert a.acc.nav == a_nav
        assert b.acc.nav == b_nav

    def test_a_two_sided_market_marks_at_the_midpoint(self):
        env = self._env()
        a, b = self._open_a_position(env)

        a.place_order('limit', 'bid', 1, 40.0, env.LOB, env.traders)
        b.place_order('limit', 'ask', 1, 60.0, env.LOB, env.traders)

        assert env.mark_price() == Decimal(50)

    def test_last_mode_reproduces_the_previous_behaviour(self):
        env = self._env(mark_price_source="last")
        self._open_a_position(env)

        assert env.mark_price() == env.LOB.tape[-1]["price"]

    def test_an_unknown_source_is_refused(self):
        with pytest.raises(ValueError, match="mark_price_source"):
            continuousDoubleAuctionEnv({"mark_price_source": "vwap"})

    def test_nav_is_conserved_under_the_midpoint_mark(self):
        env = self._env()
        a, b = self._open_a_position(env)
        total = Decimal(env.init_cash) * 2

        a.place_order('limit', 'bid', 1, 45.0, env.LOB, env.traders)
        b.place_order('limit', 'ask', 1, 55.0, env.LOB, env.traders)
        env.mark_to_mkt()

        assert a.acc.nav + b.acc.nav == total
