import sys
import os
from decimal import Decimal

# Add current path to sys.path to ensure we can import the module
current_dir = os.getcwd()
sys.path.append(current_dir)

# Import the actual classes
from gym_continuousDoubleAuction.envs.account.account import Account

# Test Script
acc = Account("TestTrader", 1000)
print(f"Initial: Cash {acc.cash}, NAV {acc.nav}")

# 1. Open Short 2 @ 100
trade1 = {
    'price': Decimal(100),
    'quantity': Decimal(2),
    'init_party': {'side': 'ask', 'ID':'TestTrader'}, # Selling
    'counter_party': {'ID': 'Other'}
}
print("\n--- Short 2 @ 100 ---")
acc.process_acc(trade1, 'init_party')
print(f"Cash {acc.cash}, PosVal {acc.position_val}, NAV {acc.nav}, VWAP {acc.VWAP}")
# Exp: Cash 800 (1000 - 200), PosVal 200 (Cost), NAV 1000. VWAP 100.

# 2. Mark to Market Price drop to 50
print("\n--- Mark to Market @ 50 ---")
acc.mark_to_mkt("TestTrader", Decimal(50))
print(f"Cash {acc.cash}, PosVal {acc.position_val}, NAV {acc.nav}, VWAP {acc.VWAP}")
# Exp: Cash 800, PosVal 300 (200 Cost + 100 Profit? No. Short 2 @ 100 = 200 Liab. Price 50 = 100 Liab. Profit = 100).
# In this codebase: 'position_val' = |Net| * VWAP + Profit?
# mark_to_mkt:
# price_diff = (VWAP - mkt) * |Net| = (100 - 50) * 2 = 100.
# profit = 100.
# raw_val = |Net| * VWAP = 200.
# position_val = 200 + 100 = 300.
# NAV = 800 + 0 + 300 = 1100. 
# Matches previous run.

# 3. Partial Cover 1 @ 50
trade2 = {
    'price': Decimal(50),
    'quantity': Decimal(1),
    'init_party': {'side': 'bid', 'ID':'TestTrader'}, # Buying to cover
    'counter_party': {'ID': 'Other'}
}
print("\n--- Cover 1 @ 50 ---")
acc.process_acc(trade2, 'init_party')
print(f"Cash {acc.cash}, PosVal {acc.position_val}, NAV {acc.nav}, VWAP {acc.VWAP}")
# Exp (After Fix): 
# VWAP: Should remain 100.
# PnL on 1 unit: (100 - 50) = 50.
# Cash Flow: 2*Cost - Exit = 2*100 - 50 = 150.
# New Cash: 800 + 150 = 950.
# Remaining Pos: 1 Unit.
# Remaining PosVal: 1 * 50 = 50. (Or 1 * VWAP + Profit?). 
# _size_decrease calculates: raw_val (100) + cal_profit(1*50, 100) -> 50.
# So PosVal = 50.
# New NAV: Cash(950) + PosVal(50) = 1000? NO.
# Wait. NAV was 1100.
# If I start with 1000. Made 100 Profit (Unrealized). NAV 1100.
# Convert 50 Profit to Cash (Realized).
# Cash should include the 50 profit.
# New Cash = 950. (Includes 50 profit on 1 unit).
# Remaining unit: Unrealized Profit 50. Liab 50.
# PosVal should represent 1 unit marked to market?
# In this codebase, PosVal = |Net| * VWAP + Profit.
# Profit (from previous mark_to_mkt) was 100? No, profit is reset per tick/step?
# Account lines: "self.profit = Decimal(0)".
# But mark_to_mkt updates prev_nav.
# process_acc -> _size_decrease -> cal_profit.
# mkt_val = 50. raw_val = 100. profit = 100 - 50 = 50.
# PosVal = 100 + (-50? for short) -> Wait.
# cal_profit for short: raw_val (100) - mkt_val (50) = 50.
# PosVal = raw_val (100) + 50 = 150.
# So NAV = 950 + 150 = 1100.
# WAIT. PosVal should be the Asset Value?
# In this systems accounting:
# NAV = Cash + PosVal.
# If I am Short, NAV is Equity.
# So if Cash=950. Equity=1100. Then PosVal must be 150?
# But if I have a Liability of 50.
# And I have Cash 950.
# My Equity should be 900?
# No. Short Selling: Cash proceeds are held.
# Start: Cash 1000. Short 1 @ 100. Cash 900.
# System implies: Cash(900) + PosVal(200, 100 Collateral + 100 Proceeds?) NO.
# System implies PosVal holds the Collateral Value?
# _size_increase: raw_val = 100. mkt_val=100. Profit=0. PosVal=100.
# Cash 900 + PosVal 100 = 1000.
# So PosVal acts as "Collateral Posted" + "Unrealized PnL".
# If price drops to 50:
# raw=100. mkt=50. profit=50. PosVal = 150.
# Cash 900. Total 1050.
# Correct logic:
# I sold for 100. I owe share worth 50.
# My wealth = (1000 - 0) + (100 proceeds - 50 liability) = 1050.
# The system abstracts this as "PosVal".
# So:
# After covering 1:
# Cash 950.
# Remaining 1 unit Short. Entry 100. Mkt 50.
# raw=100. mkt=50. profit=50. PosVal=150.
# NAV = 950 + 150 = 1100.
# THIS MATCHES.
# AND: VWAP should be 100.

# 4. Final Cover 1 @ 50
trade3 = {
    'price': Decimal(50),
    'quantity': Decimal(1),
    'init_party': {'side': 'bid', 'ID':'TestTrader'}, 
    'counter_party': {'ID': 'Other'}
}
print("\n--- Cover 1 @ 50 (Final) ---")
acc.process_acc(trade3, 'init_party')
print(f"Cash {acc.cash}, PosVal {acc.position_val}, NAV {acc.nav}, VWAP {acc.VWAP}")
# Exp:
# Cash: 950 + 150 = 1100.
# PosVal: 0.
# NAV: 1100.
# VWAP: 0.

