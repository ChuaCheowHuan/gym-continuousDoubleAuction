import unittest
import sys
import os
from decimal import Decimal

# Ensure imports work from the test directory
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(current_dir))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from gym_continuousDoubleAuction.envs.account.account import Account

class TestAccountingSystem(unittest.TestCase):
    def setUp(self):
        self.trader_id = "Trader_A"
        self.initial_cash = 1000
        self.acc = Account(self.trader_id, self.initial_cash)

    def test_initialization(self):
        self.assertEqual(self.acc.ID, self.trader_id)
        self.assertEqual(self.acc.cash, Decimal(self.initial_cash))
        self.assertEqual(self.acc.cash_on_hold, Decimal(0))
        self.assertEqual(self.acc.nav, Decimal(self.initial_cash))
        self.assertEqual(self.acc.net_position, 0)
        self.assertEqual(self.acc.VWAP, Decimal(0))

    def test_order_placement_cash_hold(self):
        """Test that placing an order reserves cash."""
        # Simulate placing a Buy order (Limit)
        order = {'price': Decimal(10), 'quantity': Decimal(5)} # Value 50
        
        # In this system, 'order_in_book_init_party' is called when an order enters the book
        self.acc.order_in_book_init_party(order)
        
        self.assertEqual(self.acc.cash, Decimal(950))
        self.assertEqual(self.acc.cash_on_hold, Decimal(50))
        self.assertEqual(self.acc.nav, Decimal(1000)) # NAV shouldn't change just by placing order

    def test_cancel_order_cash_release(self):
        """Test that cancelling an order releases cash."""
        # Use a simple class to mock the Order object which has attributes
        class MockOrder:
            def __init__(self, price, quantity, trade_id):
                self.price = price
                self.quantity = quantity
                self.trade_id = trade_id

        # To place order, we use order_in_book_init_party which expects a DICT (from trader.py flow)
        # But cancel_cash_transfer expects an OBJECT (from order tree flow)
        
        # 1. Place Order (uses Dict)
        order_dict = {'price': Decimal(10), 'quantity': Decimal(5), 'type': 'limit', 'side': 'bid', 'trade_id': self.trader_id}
        self.acc.order_in_book_init_party(order_dict) # Reserve 50
        self.assertEqual(self.acc.cash, Decimal(950))
        
        # 2. Cancel Order (uses Object)
        order_obj = MockOrder(Decimal(10), Decimal(5), self.trader_id)
        self.acc.cancel_cash_transfer(order_obj)
        
        self.assertEqual(self.acc.cash, Decimal(1000))
        self.assertEqual(self.acc.cash_on_hold, Decimal(0))

    def test_modify_order_cash(self):
        """Test modifying order size releases or reserves more cash."""
        class MockOrder:
            def __init__(self, price, quantity, trade_id):
                self.price = price
                self.quantity = quantity
                self.trade_id = trade_id

        # Original Order in Book: 10 @ 5 = 50
        order_in_book = {'price': Decimal(10), 'quantity': Decimal(5)}
        self.acc.order_in_book_init_party(order_in_book) 
        
        # Modify to DECREASE size: 10 @ 2 = 20 (Diff 30)
        new_quote = {'price': Decimal(10), 'quantity': Decimal(2), 'trade_id': self.trader_id, 'side': 'bid'}
        old_order = MockOrder(Decimal(10), Decimal(5), self.trader_id)
        
        self.acc.modify_cash_transfer(new_quote, old_order)
        
        self.assertEqual(self.acc.cash_on_hold, Decimal(20))
        self.assertEqual(self.acc.cash, Decimal(980))
        
        # Modify to INCREASE size: 10 @ 6 = 60 (Diff 40 added)
        new_quote_2 = {'price': Decimal(10), 'quantity': Decimal(6), 'trade_id': self.trader_id, 'side': 'bid'}
        old_order_2 = MockOrder(Decimal(10), Decimal(2), self.trader_id)
        
        self.acc.modify_cash_transfer(new_quote_2, old_order_2)
        
        self.assertEqual(self.acc.cash_on_hold, Decimal(60))
        self.assertEqual(self.acc.cash, Decimal(940))

    def test_long_trade_flow(self):
        """Test full cycle: Buy -> Mark -> Sell (Profit)."""
        # 1. Buy 10 @ 10 (Market Order for simplicity, instantaneous)
        trade_buy = {
            'price': Decimal(10),
            'quantity': Decimal(10),
            'init_party': {'side': 'bid', 'ID': self.trader_id},
            'counter_party': {'ID': 'Other'}
        }
        self.acc.process_acc(trade_buy, 'init_party')
        
        # Check Post-Buy
        self.assertEqual(self.acc.cash, Decimal(900))
        self.assertEqual(self.acc.net_position, 10)
        self.assertEqual(self.acc.VWAP, Decimal(10))
        self.assertEqual(self.acc.position_val, Decimal(100)) # 10 * 10
        self.assertEqual(self.acc.nav, Decimal(1000))

        # 2. Mark to Market (Price goes to 12)
        self.acc.mark_to_mkt(self.trader_id, Decimal(12))
        
        # Profit on 10 units * 2 = 20
        self.assertEqual(self.acc.profit, Decimal(20))
        self.assertEqual(self.acc.nav, Decimal(1020))
        self.assertEqual(self.acc.position_val, Decimal(120)) # 10 * 12 (or 100 raw + 20 profit)

        # 3. Sell 10 @ 12 (Full Exit)
        trade_sell = {
            'price': Decimal(12),
            'quantity': Decimal(10),
            'init_party': {'side': 'ask', 'ID': self.trader_id},
            'counter_party': {'ID': 'Other'}
        }
        self.acc.process_acc(trade_sell, 'init_party')
        
        # Check Post-Sell
        self.assertEqual(self.acc.net_position, 0)
        self.assertEqual(self.acc.VWAP, 0)
        self.assertEqual(self.acc.position_val, 0)
        self.assertEqual(self.acc.cash, Decimal(1020)) # 1000 + 20 Profit
        self.assertEqual(self.acc.nav, Decimal(1020))

    def test_short_trade_partial_fill_fix(self):
        """Test Short Sell -> Mark -> Partial Cover (Verifying the Fix)."""
        # 1. Short 2 @ 100
        trade_short = {
            'price': Decimal(100),
            'quantity': Decimal(2),
            'init_party': {'side': 'ask', 'ID': self.trader_id},
            'counter_party': {'ID': 'Other'}
        }
        self.acc.process_acc(trade_short, 'init_party')
        
        self.assertEqual(self.acc.cash, Decimal(800)) # 1000 - 200 held
        self.assertEqual(self.acc.net_position, -2)
        self.assertEqual(self.acc.VWAP, Decimal(100))
        self.assertEqual(self.acc.position_val, Decimal(200)) # Liability/Collateral abstraction
        self.assertEqual(self.acc.nav, Decimal(1000))

        # 2. Mark to Market (Price drops to 50) - Profit
        self.acc.mark_to_mkt(self.trader_id, Decimal(50))
        
        # Profit: (100 - 50) * 2 = 100
        self.assertEqual(self.acc.profit, Decimal(100))
        self.assertEqual(self.acc.nav, Decimal(1100))
        # PosVal: Raw(200) - Mkt(100) = 100 Profit. Wait.
        # mark_to_mkt code: profit = |pos| * diff. position_val = |pos|*VWAP + profit.
        # Short Profit is Positive? Yes. 100.
        # PosVal = 200 + 100 = 300.
        self.assertEqual(self.acc.position_val, Decimal(300))

        # 3. Partial Cover: Buy 1 @ 50
        trade_cover = {
            'price': Decimal(50),
            'quantity': Decimal(1),
            'init_party': {'side': 'bid', 'ID': self.trader_id},
            'counter_party': {'ID': 'Other'}
        }
        self.acc.process_acc(trade_cover, 'init_party')
        
        # Verify FIX Behaviors:
        # A. VWAP should be CONSTANT (100)
        self.assertEqual(self.acc.VWAP, Decimal(100), "VWAP should remain constant on partial close")
        
        # B. Cash Realization
        # Released Collateral: 1 * 100 = 100
        # Released Profit: 1 * (100 - 50) = 50
        # Total Cash Return: 150
        # New Cash: 800 + 150 = 950
        self.assertEqual(self.acc.cash, Decimal(950), "Cash should include realized profit")
        
        # C. Navigation Conservation
        # Remaining Pos: 1 Unit Short. Entry 100. Mkt 50.
        # PosVal update in _size_decrease:
        # raw = 1*100 = 100. mkt = 1*50 = 50.
        # profit (this tick) = raw - mkt = 50.
        # PosVal = raw + profit = 150.
        self.assertEqual(self.acc.position_val, Decimal(150))
        self.assertEqual(self.acc.nav, Decimal(1100)) # 950 + 150

    def test_short_squeeze_loss(self):
        """Test Short -> Price Up (Loss) -> Cover."""
        # 1. Short 1 @ 100
        trade_short = {
            'price': Decimal(100),
            'quantity': Decimal(1),
            'init_party': {'side': 'ask', 'ID': self.trader_id},
            'counter_party': {'ID': 'Other'}
        }
        self.acc.process_acc(trade_short, 'init_party')
        self.assertEqual(self.acc.cash, Decimal(900))
        self.assertEqual(self.acc.nav, Decimal(1000))
        
        # 2. Price goes to 150 (Loss of 50)
        # Cover 1 @ 150
        trade_cover_loss = {
            'price': Decimal(150),
            'quantity': Decimal(1),
            'init_party': {'side': 'bid', 'ID': self.trader_id},
            'counter_party': {'ID': 'Other'}
        }
        self.acc.process_acc(trade_cover_loss, 'init_party')
        
        # Cash Flow:
        # Cost Basis (Collateral): 100
        # Trade Val (Exit): 150
        # PnL: 100 - 150 = -50
        # Cash Return: 2*100 - 150 = 50. (Collateral 100 - Loss 50 = 50).
        # New Cash: 900 + 50 = 950.
        self.assertEqual(self.acc.cash, Decimal(950))
        self.assertEqual(self.acc.nav, Decimal(950))
        self.assertEqual(self.acc.net_position, 0)

if __name__ == '__main__':
    unittest.main()
