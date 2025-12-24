import unittest
import sys
from decimal import Decimal

# Add parent directory to path to import modules
if "../" not in sys.path:
    sys.path.append("../")
    
from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook
from gym_continuousDoubleAuction.envs.agent.trader import Trader

class TestModifyOrderAccounting(unittest.TestCase):
    def setUp(self):
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
        self.assertEqual(self.trader_b.acc.cash, Decimal('9000'))
        self.assertEqual(self.trader_b.acc.cash_on_hold, Decimal('0'))
        self.assertEqual(self.trader_b.acc.net_position, Decimal('10'))

    def test_scenario_2_price_change_no_cross(self):
        """Scenario 2: Price Change, No Cross (10@90 -> 10@95)"""
        # B: Hold 900
        self.trader_b.place_order('limit', 'bid', Decimal('10'), Decimal('90'), self.ob, self.agents)
        self.trader_b.place_order('modify', 'bid', Decimal('10'), Decimal('95'), self.ob, self.agents)
        
        # B now holds 10@95=950. Cash: 10000-950=9050. Hold: 950.
        self.assertEqual(self.trader_b.acc.cash, Decimal('9050'))
        self.assertEqual(self.trader_b.acc.cash_on_hold, Decimal('950'))

    def test_scenario_3_qty_increase(self):
        """Scenario 3: Qty Increase (10@90 -> 15@90)"""
        # B: Hold 900
        self.trader_b.place_order('limit', 'bid', Decimal('10'), Decimal('90'), self.ob, self.agents)
        self.trader_b.place_order('modify', 'bid', Decimal('15'), Decimal('90'), self.ob, self.agents)
        
        # B now holds 15@90=1350. Cash: 10000-1350=8650. Hold: 1350.
        self.assertEqual(self.trader_b.acc.cash, Decimal('8650'))
        self.assertEqual(self.trader_b.acc.cash_on_hold, Decimal('1350'))

    def test_scenario_4_qty_decrease_same_price(self):
        """Scenario 4: Qty Decrease, Same Price (10@90 -> 5@90)"""
        # B: Hold 900
        self.trader_b.place_order('limit', 'bid', Decimal('10'), Decimal('90'), self.ob, self.agents)
        self.trader_b.place_order('modify', 'bid', Decimal('5'), Decimal('90'), self.ob, self.agents)
        
        # B now holds 5@90=450. Cash: 10000-450=9550. Hold: 450.
        self.assertEqual(self.trader_b.acc.cash, Decimal('9550'))
        self.assertEqual(self.trader_b.acc.cash_on_hold, Decimal('450'))

    def test_scenario_5_cross_plus_qty_increase(self):
        """Scenario 5: Cross + Qty Increase (10@90 -> 15@110, Ask 10@100)"""
        # A: Hold 1000
        self.trader_a.place_order('limit', 'ask', Decimal('10'), Decimal('100'), self.ob, self.agents)
        # B: Hold 900
        self.trader_b.place_order('limit', 'bid', Decimal('10'), Decimal('90'), self.ob, self.agents)
        self.trader_b.place_order('modify', 'bid', Decimal('15'), Decimal('110'), self.ob, self.agents)
        
        # Match 10@100 (-1000), Residue 5@110 (-550). Cash: 10000-1000-550=8450.
        self.assertEqual(self.trader_b.acc.cash, Decimal('8450'))
        self.assertEqual(self.trader_b.acc.cash_on_hold, Decimal('550'))
        self.assertEqual(self.trader_b.acc.net_position, Decimal('10'))

    def test_scenario_6_cross_plus_qty_decrease(self):
        """Scenario 6: Cross + Qty Decrease (10@90 -> 5@110, Ask 10@100)"""
        # A: Hold 1000
        self.trader_a.place_order('limit', 'ask', Decimal('10'), Decimal('100'), self.ob, self.agents)
        # B: Hold 900
        self.trader_b.place_order('limit', 'bid', Decimal('10'), Decimal('90'), self.ob, self.agents)
        self.trader_b.place_order('modify', 'bid', Decimal('5'), Decimal('110'), self.ob, self.agents)
        
        # Match 5@100 (-500). Cash: 10000-500=9500. Hold: 0.
        self.assertEqual(self.trader_b.acc.cash, Decimal('9500'))
        self.assertEqual(self.trader_b.acc.cash_on_hold, Decimal('0'))
        self.assertEqual(self.trader_b.acc.net_position, Decimal('5'))

if __name__ == "__main__":
    unittest.main()

