import os
import sys

# Ensure imports work from the test directory
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(current_dir))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from gym_continuousDoubleAuction.envs.account.account import Account

# Test reversal long to short
print("=== test_reversal_long_to_short ===")
acc = Account(ID="Test", cash=2000)
acc.process_acc({'price': 100, 'quantity': 10, 'init_party': {'side': 'bid'}}, 'init_party')
print(f"After buy 10@100: cash={acc.cash}, net_pos={acc.net_position}")
acc.process_acc({'price': 120, 'quantity': 15, 'init_party': {'side': 'ask'}}, 'init_party')
print(f"After sell 15@120: cash={acc.cash}, net_pos={acc.net_position}, VWAP={acc.VWAP}, nav={acc.cal_nav()}")

# Test reversal short to long
print("\n=== test_reversal_short_to_long ===")
acc2 = Account(ID="Test2", cash=2000)
acc2.process_acc({'price': 100, 'quantity': 10, 'init_party': {'side': 'ask'}}, 'init_party')
print(f"After short 10@100: cash={acc2.cash}, net_pos={acc2.net_position}")
acc2.process_acc({'price': 80, 'quantity': 15, 'init_party': {'side': 'bid'}}, 'init_party')
print(f"After buy 15@80: cash={acc2.cash}, net_pos={acc2.net_position}, VWAP={acc2.VWAP}, nav={acc2.cal_nav()}")

# Test short partial cover
print("\n=== test_short_lifecycle partial cover ===")
acc3 = Account(ID="Test3", cash=2000)
acc3.process_acc({'price': 100, 'quantity': 10, 'init_party': {'side': 'ask'}}, 'init_party')
print(f"After short 10@100: cash={acc3.cash}, net_pos={acc3.net_position}")
acc3.process_acc({'price': 80, 'quantity': 10, 'init_party': {'side': 'ask'}}, 'init_party')
print(f"After short 10@80: cash={acc3.cash}, net_pos={acc3.net_position}, VWAP={acc3.VWAP}")
acc3.process_acc({'price': 70, 'quantity': 10, 'init_party': {'side': 'bid'}}, 'init_party')
print(f"After cover 10@70: cash={acc3.cash}, net_pos={acc3.net_position}, VWAP={acc3.VWAP}")

# Test long lifecycle continuation
print("\n=== test_long_lifecycle continuation ===")
acc4 = Account(ID="Test4", cash=2000)
acc4.process_acc({'price': 100, 'quantity': 10, 'init_party': {'side': 'bid'}}, 'init_party')
print(f"After buy 10@100: cash={acc4.cash}, net_pos={acc4.net_position}")
acc4.process_acc({'price': 120, 'quantity': 10, 'init_party': {'side': 'bid'}}, 'init_party')
print(f"After buy 10@120: cash={acc4.cash}, net_pos={acc4.net_position}, VWAP={acc4.VWAP}")
acc4.process_acc({'price': 150, 'quantity': 10, 'init_party': {'side': 'ask'}}, 'init_party')
print(f"After sell 10@150: cash={acc4.cash}, net_pos={acc4.net_position}, VWAP={acc4.VWAP}")
acc4.process_acc({'price': 110, 'quantity': 10, 'init_party': {'side': 'ask'}}, 'init_party')
print(f"After sell 10@110: cash={acc4.cash}, net_pos={acc4.net_position}")
