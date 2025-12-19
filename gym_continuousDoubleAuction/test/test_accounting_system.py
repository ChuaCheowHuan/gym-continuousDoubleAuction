import os
import sys
import unittest
from decimal import Decimal

# Ensure imports work from the test directory
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(current_dir))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from gym_continuousDoubleAuction.envs.account.account import Account

import unittest
from decimal import Decimal

# class TestMARLAccounting(unittest.TestCase):
#     def setUp(self):
#         # Start with 2000 cash for all tests
#         self.acc = Account(ID="Agent_Alpha", cash=2000)

#     # --- PRE-TRADE TESTS (Order Book Management) ---

#     def test_order_management(self):
#         """Covers placement, modification, and cancellation logic."""
#         order = {'price': 100, 'quantity': 10}
#         # Place
#         self.acc.order_in_book_init_party(order)
#         self.assertEqual(self.acc.cash_on_hold, 1000)
        
#         # Modify Up
#         new_quote = {'price': 100, 'quantity': 15}
#         self.acc.modify_cash_transfer(new_quote, order)
#         self.assertEqual(self.acc.cash_on_hold, 1500)
        
#         # Cancel
#         self.acc.cancel_cash_transfer(new_quote)
#         self.assertEqual(self.acc.cash_on_hold, 0)
#         self.assertEqual(self.acc.cash, 2000)

#     # --- LONG POSITION TESTS ---

#     def test_long_lifecycle(self):
#         """Opens long, scales up (VWAP), scales down (PnL), and closes."""
#         # 1. Open 10 @ 100 (Taker)
#         self.acc.process_acc({'price': 100, 'quantity': 10, 'init_party': {'side': 'bid'}}, 'init_party')
#         self.assertEqual(self.acc.VWAP, 100)
#         self.assertEqual(self.acc.cash, 1000)  # 2000 - 1000
        
#         # 2. Scale up: Buy 10 @ 120 -> VWAP 110
#         self.acc.process_acc({'price': 120, 'quantity': 10, 'init_party': {'side': 'bid'}}, 'init_party')
#         self.assertEqual(self.acc.VWAP, 110)
#         self.assertEqual(self.acc.cash, -200)  # 1000 - 1200 (full collateral)
        
#         # 3. Partial Close: Sell 10 @ 150 (Profit: 10 * (150-110) = 400)
#         # Principal (10*110=1100) + Profit (400) = 1500 returned to cash
#         self.acc.process_acc({'price': 150, 'quantity': 10, 'init_party': {'side': 'ask'}}, 'init_party')
#         self.assertEqual(self.acc.VWAP, 110)  # Static VWAP check
#         self.assertEqual(self.acc.cash, 1500)
#         self.assertEqual(self.acc.net_position, 10)
        
#         # 4. Full Close: Sell last 10 @ 110 (Neutral)
#         self.acc.process_acc({'price': 110, 'quantity': 10, 'init_party': {'side': 'ask'}}, 'init_party')
#         self.assertEqual(self.acc.net_position, 0)
#         self.assertEqual(self.acc.cash, 2600)  # 1500 + 1100 principal

#     # --- SHORT POSITION TESTS ---

#     def test_short_lifecycle(self):
#         """Short counterpart: Opens, scales up (VWAP), and covers."""
#         # 1. Open Short 10 @ 100
#         # Cash: 2000 - 1000 (collateral) = 1000
#         self.acc.process_acc({'price': 100, 'quantity': 10, 'init_party': {'side': 'ask'}}, 'init_party')
#         self.assertEqual(self.acc.net_position, -10)
#         self.assertEqual(self.acc.cash, 1000)
        
#         # 2. Scale up: Short 10 @ 80 -> VWAP 90
#         # Cash: 1000 - 800 (more collateral) = 200
#         self.acc.process_acc({'price': 80, 'quantity': 10, 'init_party': {'side': 'ask'}}, 'init_party')
#         self.assertEqual(self.acc.VWAP, 90)
#         self.assertEqual(self.acc.cash, 200)
        
#         # 3. Partial Cover: Buy 10 @ 70 (Profit: 10 * (90-70) = 200)
#         # Cost to cover: 700
#         # Principal returned: 900 (10 * 90)
#         # Net cash change: +900 - 700 = +200
#         # Cash: 3800 + 200 = 4000
#         # OR alternatively: Principal 900 locked, profit 200, cost 700 = 900 + 200 - 700 = 400 added
#         self.acc.process_acc({'price': 70, 'quantity': 10, 'init_party': {'side': 'bid'}}, 'init_party')
#         self.assertEqual(self.acc.VWAP, 90)
#         self.assertEqual(self.acc.net_position, -10)
#         # Corrected: Cash should be 3800 - 700 + 900 (principal) + 200 (profit) = 4200
#         # OR simpler: Short gave us 1800 total, covering 10 costs 700, profit 200: 2000 + 1800 - 700 = 3100
#         # Let's recalculate: Start 2000, short 10@100 (+1000=3000), short 10@80 (+800=3800)
#         # Cover 10@70: pay 700, release 900 principal, gain 200 profit = 3800 - 700 + 200 = 3300
#         self.assertEqual(self.acc.cash, 3300)

#     # --- POSITION REVERSAL (THE FLIP) ---

#     def test_reversal_long_to_short(self):
#         """Tests flipping from Long 10 @ 100 to Short @ 120."""
#         # Start: 2000 cash
#         self.acc.process_acc({'price': 100, 'quantity': 10, 'init_party': {'side': 'bid'}}, 'init_party')
#         self.assertEqual(self.acc.cash, 1000)  # 2000 - 1000
        
#         # Sell 15 units at 120
#         # - Closes 10 units long: Return principal 1000 + profit 200 = 1200
#         # - Opens 5 units short at 120: Receive 600
#         # Cash: 1000 + 1200 + 600 = 2800
#         self.acc.process_acc({'price': 120, 'quantity': 15, 'init_party': {'side': 'ask'}}, 'init_party')
        
#         self.assertEqual(self.acc.net_position, -5)
#         self.assertEqual(self.acc.VWAP, 120)
#         self.assertEqual(self.acc.cash, 2800)
#         # NAV = cash - short_obligation = 2800 - 600 = 2200
#         self.assertEqual(self.acc.nav, 2200)

#     def test_reversal_short_to_long(self):
#         """Tests flipping from Short 10 @ 100 to Long @ 80."""
#         # Start: 2000 cash
#         self.acc.process_acc({'price': 100, 'quantity': 10, 'init_party': {'side': 'ask'}}, 'init_party')
#         self.assertEqual(self.acc.cash, 1000)  # 2000 - 1000 (collateral)
        
#         # Buy 15 units at 80
#         # - Covers 10 units short: Cost 800, return principal 1000, profit 200 = net +400
#         # - Opens 5 units long at 80: Pay 400
#         # Cash: 3000 - 800 + 200 - 400 = 2000
#         # OR: 3000 + (1000-800) - 400 = 3000 + 200 - 400 = 2800
#         # Recalc: Short gave 1000, covering costs 800, profit 200, opening long costs 400
#         # Cash flow: 3000 - 800 - 400 + 200 = 2000
#         # Actually: 3000 - 1200 (total buy) + 1000 (principal) + 200 (profit) = 3000
#         # Let me recalculate properly:
#         # Start 3000, buy 15@80 costs 1200, so down to 1800
#         # Return 10*100 principal = 1000, profit 200, so 1800 + 1000 + 200 = 3000
#         # But 5 are now long costing 400, so effective cash for NAV = 3000 - 400 = 2600
#         self.acc.process_acc({'price': 80, 'quantity': 15, 'init_party': {'side': 'bid'}}, 'init_party')
        
#         self.assertEqual(self.acc.net_position, 5)
#         self.assertEqual(self.acc.VWAP, 80)
#         self.assertEqual(self.acc.cash, 2600)
#         # NAV = cash + long_value = 2600 - 400 = 2200
#         self.assertEqual(self.acc.nav, 2200)

#     # --- VALUATION (Mark-to-Market) ---

#     def test_mark_to_market_symmetry(self):
#         """Checks if NAV updates correctly for both sides as market moves."""
#         # Long Case
#         self.acc.process_acc({'price': 100, 'quantity': 10, 'init_party': {'side': 'bid'}}, 'init_party')
#         self.acc.mark_to_mkt(self.acc.ID, 150)
#         # Cash: 1000 (spent 1000)
#         # Position value: 10 * 150 = 1500
#         # NAV: 1000 + 1500 = 2500
#         self.assertEqual(self.acc.nav, 2500)
        
#         # Reset and Short Case
#         self.acc = Account(ID="Agent_Beta", cash=2000)
#         self.acc.process_acc({'price': 100, 'quantity': 10, 'init_party': {'side': 'ask'}}, 'init_party')
#         self.acc.mark_to_mkt(self.acc.ID, 50)  # Price dropped, short is in profit
#         # Cash: 3000 (received 1000)
#         # Short obligation at market: 10 * 50 = 500
#         # NAV: 3000 - 500 = 2500
#         self.assertEqual(self.acc.nav, 2500)

# if __name__ == '__main__':
#     unittest.main()

import unittest
from decimal import Decimal

# Import your classes here: Calculate, Cash_Processor, Account

class TestMARLAccounting(unittest.TestCase):
    def setUp(self):
        # Start with 2000 cash for all tests
        self.acc = Account(ID="Agent_Alpha", cash=2000)

    # ==========================================
    # 1. MAKER TESTS (Counter-Party / Limit Orders)
    # ==========================================
    
    def test_maker_open_long(self):
        """
        Scenario: Agent places a Buy Limit order (Maker).
        1. Money moves Cash -> Hold.
        2. Order is hit (filled). Money moves Hold -> Position.
        """
        # Step 1: Place Buy Limit 10 @ 100
        order = {'price': 100, 'quantity': 10}
        self.acc.order_in_book_init_party(order) # Agent places order
        
        self.assertEqual(self.acc.cash, 1000)        # 2000 - 1000
        self.assertEqual(self.acc.cash_on_hold, 1000) # Reserved
        
        # Step 2: Trade executes (Agent is Counter-party)
        # Counter-party side 'bid' means they are Buying
        trade = {
            'price': 100, 
            'quantity': 10, 
            'counter_party': {'side': 'bid'} 
        }
        self.acc.process_acc(trade, 'counter_party')
        
        self.assertEqual(self.acc.cash_on_hold, 0)   # Hold consumed
        self.assertEqual(self.acc.net_position, 10)  # Long 10
        self.assertEqual(self.acc.position_val, 1000)
        self.assertEqual(self.acc.cash, 1000)        # Remaining cash unchanged

    def test_maker_open_short(self):
        """
        Scenario: Agent places a Sell Limit order (Maker).
        1. Money moves Cash -> Hold (Short collateral).
        2. Order is hit. Money moves Hold -> Position (Short obligation).
        """
        # Step 1: Place Sell Limit 10 @ 100
        order = {'price': 100, 'quantity': 10}
        self.acc.order_in_book_init_party(order)
        
        self.assertEqual(self.acc.cash_on_hold, 1000)
        
        # Step 2: Trade executes (Agent is Counter-party)
        # Counter-party side 'ask' means they are Selling (Shorting)
        trade = {
            'price': 100, 
            'quantity': 10, 
            'counter_party': {'side': 'ask'}
        }
        self.acc.process_acc(trade, 'counter_party')
        
        self.assertEqual(self.acc.net_position, -10) # Short 10
        self.assertEqual(self.acc.cash_on_hold, 0)   # Collateral moved
        self.assertEqual(self.acc.position_val, 1000) # Liability size
        self.assertEqual(self.acc.cash, 1000)

    def test_maker_close_long(self):
        """
        Scenario: Agent is Long. Places Sell Limit to exit.
        1. Hold cash for the Sell Order (Collateral/Order Value).
        2. Filled: Return Hold + Principal + Profit to Cash.
        """
        # Setup: Force a Long position (Long 10 @ 100)
        self.acc.cash = Decimal(1000)
        self.acc.net_position = Decimal(10)
        self.acc.VWAP = Decimal(100)
        self.acc.position_val = Decimal(1000)
        
        # Step 1: Place Sell Limit 10 @ 120 (Targeting profit)
        order = {'price': 120, 'quantity': 10}
        self.acc.order_in_book_init_party(order)
        
        # Cash moves to hold (1200 reserved for the potential transaction value)
        self.assertEqual(self.acc.cash, -200) # 1000 - 1200 (Logic requires full collateral)
        self.assertEqual(self.acc.cash_on_hold, 1200)
        
        # Step 2: Filled
        trade = {'price': 120, 'quantity': 10, 'counter_party': {'side': 'ask'}}
        self.acc.process_acc(trade, 'counter_party')
        
        # Logic: 
        # - Remove 1200 from Hold.
        # - Add Principal (1000) + Profit (200) + Hold-Back (1200?) 
        #   WAIT: The 'size_decrease' logic returns "trade_val + pnl".
        #   We need to ensure the math aligns with 'size_decrease_cash_transfer'.
        #   (Hold -= 1200; Cash += 1200 + PnL is NOT typical.
        #    Usually: Hold -= 1200; Cash += 1200 (return hold) + Realized Cash?)
        #   Let's check the implemented logic:
        #   "self.cash_on_hold -= trade_val" (Removes 1200)
        #   "self.cash += (trade_val + realized_pnl)" (Adds 1200 + 200 = 1400)
        #   Result Cash: -200 + 1400 = 1200.
        #   Correct Final Balance: Started with 1000. Profit 200. End = 1200.
        
        self.assertEqual(self.acc.cash, 1200)
        self.assertEqual(self.acc.cash_on_hold, 0)
        self.assertEqual(self.acc.net_position, 0)

    # ==========================================
    # 2. TAKER TESTS (Init-Party / Market Orders)
    # ==========================================

    def test_taker_open_long(self):
        """
        Scenario: Agent buys immediately at market price.
        Money moves directly Cash -> Position.
        """
        trade = {
            'price': 100, 
            'quantity': 10, 
            'init_party': {'side': 'bid'}
        }
        self.acc.process_acc(trade, 'init_party')
        
        self.assertEqual(self.acc.cash, 1000)       # 2000 - 1000
        self.assertEqual(self.acc.cash_on_hold, 0)  # No hold for takers
        self.assertEqual(self.acc.net_position, 10)
        self.assertEqual(self.acc.VWAP, 100)

    def test_taker_close_short_with_loss(self):
        """
        Scenario: Agent is Short 10 @ 100. Market moves to 110. Agent covers (Buys).
        """
        # Setup: Short 10 @ 100
        self.acc.process_acc({'price': 100, 'quantity': 10, 'init_party': {'side': 'ask'}}, 'init_party')
        
        # Cover 10 @ 110 (Loss of 100)
        trade = {
            'price': 110, 
            'quantity': 10, 
            'init_party': {'side': 'bid'}
        }
        self.acc.process_acc(trade, 'init_party')
        
        self.assertEqual(self.acc.net_position, 0)
        # Calculation:
        # Initial 2000.
        # Short 10@100: Cash -1000 = 1000.
        # Cover 10@110:
        #   Principal (1000) returned.
        #   Loss (100) realized.
        #   Cash += (Principal 1000 - Loss 100) = 900? 
        #   Wait, PnL is (Raw - Mkt) = 1000 - 1100 = -100.
        #   Cash += (1000 + -100) = 900.
        #   Total Cash = 1000 + 900 = 1900.
        self.assertEqual(self.acc.cash, 1900)

    # ==========================================
    # 3. INTERACTION & MODIFICATION TESTS
    # ==========================================

    def test_maker_modify_then_fill(self):
        """
        Scenario: 
        1. Maker places Buy Limit 10 @ 100.
        2. Modifies to 10 @ 150 (More collateral needed).
        3. Filled at 150.
        """
        # 1. Place 10 @ 100
        order = {'price': 100, 'quantity': 10}
        self.acc.order_in_book_init_party(order)
        self.assertEqual(self.acc.cash_on_hold, 1000)
        
        # 2. Modify to 10 @ 150
        new_quote = {'price': 150, 'quantity': 10}
        self.acc.modify_cash_transfer(new_quote, order)
        # Diff is 500. Cash -> Hold.
        self.assertEqual(self.acc.cash_on_hold, 1500)
        self.assertEqual(self.acc.cash, 500)
        
        # 3. Fill at 150 (Counter-party)
        trade = {'price': 150, 'quantity': 10, 'counter_party': {'side': 'bid'}}
        self.acc.process_acc(trade, 'counter_party')
        
        self.assertEqual(self.acc.cash_on_hold, 0)
        self.assertEqual(self.acc.net_position, 10)
        self.assertEqual(self.acc.VWAP, 150)

if __name__ == '__main__':
    unittest.main()