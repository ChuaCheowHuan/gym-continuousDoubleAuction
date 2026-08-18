import sys
from decimal import Decimal

# Add parent directory to path to import modules
if "../" not in sys.path:
    sys.path.append("../")

from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook
from gym_continuousDoubleAuction.envs.agent.trader import Trader

class TestModifyOrderAccounting:
    def setup_method(self):
        """Helper for fresh setup before each test."""
        self.ob = OrderBook()
        self.trader_a = Trader('A', cash=Decimal('10000'))
        self.trader_b = Trader('B', cash=Decimal('10000'))
        self.agents = [self.trader_a, self.trader_b]

    def test_scenario_1_price_crosses_book(self):
        """Scenario 1: Price Crosses Book (qty same) (10@90 -> 10@110, Ask@100)"""
        # A: Hold 1000
        self.trader_a.place_order('limit', 'ask', Decimal('10'), Decimal('100'), self.ob, self.agents)
        # B: Hold 900
        self.trader_b.place_order('limit', 'bid', Decimal('10'), Decimal('90'), self.ob, self.agents)
        self.trader_b.place_order('modify', 'bid', Decimal('10'), Decimal('110'), self.ob, self.agents)

        # B spent 10*100=1000. Cash: 10000-1000=9000. Hold: 0. Position: 10.
        assert self.trader_b.acc.cash == Decimal('9000')
        assert self.trader_b.acc.cash_on_hold == Decimal('0')
        assert self.trader_b.acc.net_position == Decimal('10')

    def test_scenario_2_price_change_no_cross(self):
        """Scenario 2: Price Change, No Cross (10@90 -> 10@95)"""
        # B: Hold 900
        self.trader_b.place_order('limit', 'bid', Decimal('10'), Decimal('90'), self.ob, self.agents)
        self.trader_b.place_order('modify', 'bid', Decimal('10'), Decimal('95'), self.ob, self.agents)

        # B now holds 10@95=950. Cash: 10000-950=9050. Hold: 950.
        assert self.trader_b.acc.cash == Decimal('9050')
        assert self.trader_b.acc.cash_on_hold == Decimal('950')

    def test_scenario_3_qty_increase(self):
        """Scenario 3: Qty Increase (10@90 -> 15@90)"""
        # B: Hold 900
        self.trader_b.place_order('limit', 'bid', Decimal('10'), Decimal('90'), self.ob, self.agents)
        self.trader_b.place_order('modify', 'bid', Decimal('15'), Decimal('90'), self.ob, self.agents)

        # B now holds 15@90=1350. Cash: 10000-1350=8650. Hold: 1350.
        assert self.trader_b.acc.cash == Decimal('8650')
        assert self.trader_b.acc.cash_on_hold == Decimal('1350')

    def test_scenario_4_qty_decrease_same_price(self):
        """Scenario 4: Qty Decrease, Same Price (10@90 -> 5@90)"""
        # B: Hold 900
        self.trader_b.place_order('limit', 'bid', Decimal('10'), Decimal('90'), self.ob, self.agents)
        self.trader_b.place_order('modify', 'bid', Decimal('5'), Decimal('90'), self.ob, self.agents)

        # B now holds 5@90=450. Cash: 10000-450=9550. Hold: 450.
        assert self.trader_b.acc.cash == Decimal('9550')
        assert self.trader_b.acc.cash_on_hold == Decimal('450')

    def test_scenario_5_cross_plus_qty_increase(self):
        """Scenario 5: Cross + Qty Increase (10@90 -> 15@110, Ask 10@100)"""
        # A: Hold 1000
        self.trader_a.place_order('limit', 'ask', Decimal('10'), Decimal('100'), self.ob, self.agents)
        # B: Hold 900
        self.trader_b.place_order('limit', 'bid', Decimal('10'), Decimal('90'), self.ob, self.agents)
        self.trader_b.place_order('modify', 'bid', Decimal('15'), Decimal('110'), self.ob, self.agents)

        # Match 10@100 (-1000), Residue 5@110 (-550). Cash: 10000-1000-550=8450.
        assert self.trader_b.acc.cash == Decimal('8450')
        assert self.trader_b.acc.cash_on_hold == Decimal('550')
        assert self.trader_b.acc.net_position == Decimal('10')

    def test_scenario_6_cross_plus_qty_decrease(self):
        """Scenario 6: Cross + Qty Decrease (10@90 -> 5@110, Ask 10@100)"""
        # A: Hold 1000
        self.trader_a.place_order('limit', 'ask', Decimal('10'), Decimal('100'), self.ob, self.agents)
        # B: Hold 900
        self.trader_b.place_order('limit', 'bid', Decimal('10'), Decimal('90'), self.ob, self.agents)
        self.trader_b.place_order('modify', 'bid', Decimal('5'), Decimal('110'), self.ob, self.agents)

        # Match 5@100 (-500). Cash: 10000-500=9500. Hold: 0.
        assert self.trader_b.acc.cash == Decimal('9500')
        assert self.trader_b.acc.cash_on_hold == Decimal('0')
        assert self.trader_b.acc.net_position == Decimal('5')


class TestModifyIsCancelAndReprocess:
    """The escrow-shuffle implementation of modify must not come back.

    `Cash_Processor.modify_cash_transfer` moved `order_val - qoute_val` between
    cash and cash_on_hold - a pure escrow adjustment. It was never called, and
    was deleted rather than wired up because it is only correct where the live
    path already is: when the modify does not match, the residual left resting
    equals the whole new quote, so `cancel_cash_transfer` plus re-escrow comes
    to the same number. When the modify *does* match they diverge, and the
    escrow-shuffle is the wrong one - it has no term for a fill, so it holds
    cash against quantity that is no longer in the book.

    Scenarios 1, 5 and 6 above are what actually constrain this: each crosses
    the book and asserts exact cash, cash_on_hold and net_position afterwards,
    which an escrow-shuffle cannot produce. This test only stops the function
    being reintroduced alongside them. See doc/15 S3-20.
    """

    def test_the_escrow_shuffle_helper_is_gone(self):
        from gym_continuousDoubleAuction.envs.account.cash_processor import (
            Cash_Processor,
        )

        assert not hasattr(Cash_Processor, "modify_cash_transfer"), (
            "modify_cash_transfer is back. A modify is handled as "
            "cancel-and-reprocess so that it can cross the spread; an escrow "
            "delta cannot express a fill. See the six scenarios above."
        )
