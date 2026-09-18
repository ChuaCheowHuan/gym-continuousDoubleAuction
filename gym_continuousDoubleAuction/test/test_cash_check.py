import sys
from decimal import Decimal

# Add parent directory to path to import modules
if "../" not in sys.path:
    sys.path.append("../")

from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook
from gym_continuousDoubleAuction.envs.agent.trader import Trader

class TestCashCheck:
    def setup_method(self):
        self.order_book = OrderBook()
        # Initialize traders
        self.trader_A = Trader(ID=1, cash=100) # Only $100
        self.agents = [self.trader_A]

    def test_limit_buy_insufficient_cash(self):
        """Should block Limit Buy if cash < (size * price)"""
        # Value = 150, Cash = 100
        trades, order_in_book = self.trader_A.place_order('limit', 'bid', 1, 150, self.order_book, self.agents)
        assert len(trades) == 0
        assert order_in_book == []
        assert self.trader_A.acc.cash == Decimal(100)

    def test_limit_buy_sufficient_cash(self):
        """Should approve Limit Buy if cash >= (size * price)"""
        # Value = 50, Cash = 100
        trades, order_in_book = self.trader_A.place_order('limit', 'bid', 1, 50, self.order_book, self.agents)
        assert self.trader_A.acc.cash == Decimal(50)

    def test_market_buy_insufficient_cash(self):
        """Should block Market Buy if cash < best ask"""
        # Seed the book with an expensive offer
        self.trader_expensive = Trader(ID=9, cash=1000)
        self.trader_expensive.place_order('limit', 'ask', 1, 200, self.order_book, [self.trader_expensive])

        # Trader A tries to market buy. Best ask is 200, Cash is 100.
        trades, order_in_book = self.trader_A.place_order('market', 'bid', 1, -1, self.order_book, self.agents)
        assert len(trades) == 0
        assert self.trader_A.acc.cash == Decimal(100)

    def test_cover_short_no_cash(self):
        """Should allow covering a short position even with 0 cash"""
        # Setup: Forced short position
        self.trader_A.acc.cash = Decimal(0)
        self.trader_A.acc.net_position = -1
        self.trader_A.acc.position_val = Decimal(100)
        self.trader_A.acc.VWAP = Decimal(100)
        self.trader_A.acc.cal_nav() # NAV = 100

        # Best ask is 100
        self.trader_B = Trader(ID=2, cash=1000)
        self.trader_B.place_order('limit', 'ask', 1, 100, self.order_book, [self.trader_B])

        # Try to buy (cover)
        trades, order_in_book = self.trader_A.place_order('market', 'bid', 1, -1, self.order_book, [self.trader_A, self.trader_B])
        assert len(trades) == 1
        assert self.trader_A.acc.net_position == 0
        assert self.trader_A.acc.cash == Decimal(100) # Margin returned

    def test_sell_long_no_cash(self):
        """Should allow selling long inventory even with 0 cash"""
        self.trader_A.acc.cash = Decimal(0)
        self.trader_A.acc.net_position = 1
        self.trader_A.acc.position_val = Decimal(100)
        self.trader_A.acc.VWAP = Decimal(100)
        self.trader_A.acc.cal_nav()

        # Try to sell (market)
        trades, order_in_book = self.trader_A.place_order('market', 'ask', 1, -1, self.order_book, self.agents)
        # Should be blocked by LOB (empty bids) but _order_approved should be True
        # In this case, since the book is empty, trades will be empty, which is fine.
        # But cash should still be 0 (no trade happened)
        assert self.trader_A.acc.cash == Decimal(0)

        # Now add a bid and try again
        self.trader_B = Trader(ID=2, cash=1000)
        self.trader_B.place_order('limit', 'bid', 1, 100, self.order_book, [self.trader_B])
        trades, order_in_book = self.trader_A.place_order('market', 'ask', 1, -1, self.order_book, [self.trader_A, self.trader_B])
        assert len(trades) == 1
        assert self.trader_A.acc.cash == Decimal(100)

    def test_position_flip_insufficient_cash(self):
        """Test Case: Long 10, Sell 20 - Insufficient cash for the flip (short) portion"""
        # Setup: Agent A is Long 10 @ 100, but only has $50 extra cash
        self.trader_A.acc.cash = Decimal(50)
        self.trader_A.acc.net_position = 10
        self.trader_A.acc.position_val = Decimal(1000)
        self.trader_A.acc.VWAP = Decimal(100)
        self.trader_A.acc.cal_nav() # NAV = 1050

        # We need some bids in the book to test market sell
        self.trader_B = Trader(ID=2, cash=5000)
        self.trader_B.place_order('limit', 'bid', 20, 100, self.order_book, [self.trader_B])

        # Agent A tries to Sell 20.
        # 10 shares close long (Free). 10 shares open short (Needs $1000).
        # Agent A only has $50. Should be BLOCKED.
        trades, order_in_book = self.trader_A.place_order('market', 'ask', 20, -1, self.order_book, [self.trader_A, self.trader_B])

        assert len(trades) == 0, "Order should be blocked due to insufficient cash for the flip portion"
        assert self.trader_A.acc.cash == Decimal(50)
        assert self.trader_A.acc.net_position == 10

    def test_price_estimation_fallback_to_tape(self):
        """Verify that _order_approved tracks the MOST RECENT trade price (drift)."""
        # 1. Setup multi-trade scenario
        self.trader_B = Trader(ID=2, cash=5000)

        # Trade 1 @ 100
        self.trader_A.acc.cash = Decimal(1000)
        self.trader_B.place_order('limit', 'ask', 1, 100, self.order_book, [self.trader_A, self.trader_B])
        self.trader_A.place_order('market', 'bid', 1, -1, self.order_book, [self.trader_A, self.trader_B])
        assert self.order_book.tape[-1]['price'] == 100

        # Trade 2 @ 200
        self.trader_B.place_order('limit', 'ask', 1, 200, self.order_book, [self.trader_A, self.trader_B])
        self.trader_A.place_order('market', 'bid', 1, -1, self.order_book, [self.trader_A, self.trader_B])
        assert self.order_book.tape[-1]['price'] == 200

        # 2. Book is now empty. Tape's last price is 200.
        assert self.order_book.get_best_ask() is None

        # 3. Give Trader A exactly $150.
        # This is MORE than Trade 1 ($100) but LESS than Trade 2 ($200).
        self.trader_A.acc.cash = Decimal(150)

        # 4. Try Market Buy.
        # If it incorrectly uses Trade 1, it will PASS.
        # If it correctly uses Trade 2 (latest), it will FAIL.
        trades, _ = self.trader_A.place_order('market', 'bid', 1, -1, self.order_book, self.agents)
        assert len(trades) == 0, "Should use the LATEST price (200) and reject because 150 < 200"


class TestCancelAndModifyNeverTrapCash:
    """doc/15 S2-13: a cancel, or a modify that frees escrow, is not a new order.

    `_order_approved` used to cash-check every order type against `cash`
    alone. A trader with all its cash escrowed in resting orders could then
    neither cancel them nor shrink them - the refusal counted in
    `num_rejected_step` and the order stayed live. These pin the fix: a cancel
    is always approved, and a modify or limit-upsert may spend the escrow the
    order it replaces gives back.
    """

    def setup_method(self):
        self.book = OrderBook()
        self.t = Trader(ID=1, cash=1000)
        self.agents = [self.t]
        # Rest a bid for every unit of cash: 10 @ 100.
        self.t.place_order('limit', 'bid', 10, 100, self.book, self.agents)
        assert self.t.acc.cash == Decimal(0)
        assert self.t.acc.cash_on_hold == Decimal(1000)

    def test_cancel_with_zero_free_cash_is_approved(self):
        self.t.place_order('cancel', 'bid', 10, 100, self.book, self.agents)
        assert self.t.acc.num_rejected_step == 0
        assert len(self.book.bids) == 0, "the cancel must reach the book"
        assert self.t.acc.cash == Decimal(1000)
        assert self.t.acc.cash_on_hold == Decimal(0)

    def test_cancel_ignores_its_own_size_and_price(self):
        # A cancel's size is meaningless; a huge one must not be cash-checked.
        self.t.place_order('cancel', 'bid', 10 ** 6, 100, self.book, self.agents)
        assert self.t.acc.num_rejected_step == 0
        assert len(self.book.bids) == 0

    def test_shrinking_modify_with_zero_free_cash_is_approved(self):
        self.t.place_order('modify', 'bid', 5, 100, self.book, self.agents)
        assert self.t.acc.num_rejected_step == 0
        assert self.book.bids.volume == Decimal(5)
        assert self.t.acc.cash == Decimal(500)
        assert self.t.acc.cash_on_hold == Decimal(500)

    def test_repricing_modify_spends_the_released_escrow(self):
        # Same notional at a lower price: 10 @ 90 = 900 <= 0 cash + 1000 released.
        self.t.place_order('modify', 'bid', 10, 90, self.book, self.agents)
        assert self.t.acc.num_rejected_step == 0
        assert self.book.get_best_bid() == Decimal(90)
        assert self.t.acc.cash == Decimal(100)
        assert self.t.acc.cash_on_hold == Decimal(900)

    def test_modify_beyond_cash_plus_released_is_still_refused(self):
        # 20 @ 100 = 2000 > 0 cash + 1000 released.
        self.t.place_order('modify', 'bid', 20, 100, self.book, self.agents)
        assert self.t.acc.num_rejected_step == 1
        assert self.book.bids.volume == Decimal(10), "refused modify leaves the order as it was"
        assert self.t.acc.cash == Decimal(0)
        assert self.t.acc.cash_on_hold == Decimal(1000)

    def test_limit_upsert_at_same_price_spends_the_released_escrow(self):
        # A limit at a price this trader already rests at is an upsert.
        self.t.place_order('limit', 'bid', 10, 100, self.book, self.agents)
        assert self.t.acc.num_rejected_step == 0
        assert len(self.book.bids) == 1
        assert self.book.bids.volume == Decimal(10)
        assert self.t.acc.cash == Decimal(0)
        assert self.t.acc.cash_on_hold == Decimal(1000)

    def test_bankrupt_trader_still_cannot_act(self):
        # The NAV gate stays ahead of the cancel shortcut: a trader at or
        # below zero NAV is terminated and its orders are pulled by
        # `cancel_all_orders`, not by an action.
        self.t.acc.nav = Decimal(0)
        self.t.place_order('cancel', 'bid', 10, 100, self.book, self.agents)
        assert self.t.acc.num_rejected_step == 1
        assert len(self.book.bids) == 1
