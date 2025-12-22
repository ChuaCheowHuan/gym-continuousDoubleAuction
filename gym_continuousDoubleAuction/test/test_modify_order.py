import sys
from decimal import Decimal
import pandas as pd

# Add parent directory to path to import modules
if "../" not in sys.path:
    sys.path.append("../")
    
from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook
from gym_continuousDoubleAuction.envs.agent.trader import Trader

def test_accounting():
    print("--- Starting Full 6-Scenario Accounting Verification ---")
    
    # helper for reset
    def get_fresh_setup():
        ob = OrderBook()
        trader_a = Trader('A', cash=Decimal('10000'))
        trader_b = Trader('B', cash=Decimal('10000'))
        return ob, trader_a, trader_b, [trader_a, trader_b]

    # Scenario 1: Price Crosses Book (qty same)
    print("\n--- Scenario 1: Price Crosses (10@90 -> 10@110, Ask@100) ---")
    ob, a, b, agents = get_fresh_setup()
    a.place_order('limit', 'ask', Decimal('10'), Decimal('100'), ob, agents) # A: Hold 1000
    b.place_order('limit', 'bid', Decimal('10'), Decimal('90'), ob, agents)  # B: Hold 900
    b.place_order('modify', 'bid', Decimal('10'), Decimal('110'), ob, agents)
    # B spent 10*100=1000. Cash: 10000-1000=9000. Hold: 0. Position: 10.
    print(f"DEBUG Scenario 1: B Cash={b.acc.cash}, Hold={b.acc.cash_on_hold}, Pos={b.acc.net_position}")
    assert b.acc.cash == Decimal('9000')
    assert b.acc.cash_on_hold == Decimal('0')
    assert b.acc.net_position == Decimal('10')
    print("Scenario 1 Passed.")

    # Scenario 2: Price Change, No Cross (10@90 -> 10@95)
    print("\n--- Scenario 2: Price Move, No Cross (10@90 -> 10@95) ---")
    ob, a, b, agents = get_fresh_setup()
    b.place_order('limit', 'bid', Decimal('10'), Decimal('90'), ob, agents)  # B: Hold 900
    b.place_order('modify', 'bid', Decimal('10'), Decimal('95'), ob, agents)
    # B now holds 10@95=950. Cash: 10000-950=9050. Hold: 950.
    assert b.acc.cash == Decimal('9050')
    assert b.acc.cash_on_hold == Decimal('950')
    print("Scenario 2 Passed.")

    # Scenario 3: Qty Increase (10@90 -> 15@90)
    print("\n--- Scenario 3: Qty Increase (10@90 -> 15@90) ---")
    ob, a, b, agents = get_fresh_setup()
    b.place_order('limit', 'bid', Decimal('10'), Decimal('90'), ob, agents)  # B: Hold 900
    b.place_order('modify', 'bid', Decimal('15'), Decimal('90'), ob, agents)
    # B now holds 15@90=1350. Cash: 10000-1350=8650. Hold: 1350.
    assert b.acc.cash == Decimal('8650')
    assert b.acc.cash_on_hold == Decimal('1350')
    print("Scenario 3 Passed.")

    # Scenario 4: Qty Decrease, Same Price (10@90 -> 5@90)
    print("\n--- Scenario 4: Qty Decrease (10@90 -> 5@90) ---")
    ob, a, b, agents = get_fresh_setup()
    b.place_order('limit', 'bid', Decimal('10'), Decimal('90'), ob, agents)  # B: Hold 900
    b.place_order('modify', 'bid', Decimal('5'), Decimal('90'), ob, agents)
    # B now holds 5@90=450. Cash: 10000-450=9550. Hold: 450.
    assert b.acc.cash == Decimal('9550')
    assert b.acc.cash_on_hold == Decimal('450')
    print("Scenario 4 Passed.")

    # Scenario 5: Cross + Qty Increase (10@90 -> 15@110, Ask 10@100)
    print("\n--- Scenario 5: Cross + Qty Increase (10@90 -> 15@110) ---")
    ob, a, b, agents = get_fresh_setup()
    a.place_order('limit', 'ask', Decimal('10'), Decimal('100'), ob, agents) # A: Hold 1000
    b.place_order('limit', 'bid', Decimal('10'), Decimal('90'), ob, agents)  # B: Hold 900
    b.place_order('modify', 'bid', Decimal('15'), Decimal('110'), ob, agents)
    # Match 10@100 (-1000), Residue 5@110 (-550). Cash: 10000-1000-550=8450.
    assert b.acc.cash == Decimal('8450')
    assert b.acc.cash_on_hold == Decimal('550')
    assert b.acc.net_position == Decimal('10')
    print("Scenario 5 Passed.")

    # Scenario 6: Cross + Qty Decrease (10@90 -> 5@110, Ask 10@100)
    print("\n--- Scenario 6: Cross + Qty Decrease (10@90 -> 5@110) ---")
    ob, a, b, agents = get_fresh_setup()
    a.place_order('limit', 'ask', Decimal('10'), Decimal('100'), ob, agents) # A: Hold 1000
    b.place_order('limit', 'bid', Decimal('10'), Decimal('90'), ob, agents)  # B: Hold 900
    b.place_order('modify', 'bid', Decimal('5'), Decimal('110'), ob, agents)
    # Match 5@100 (-500). Cash: 10000-500=9500. Hold: 0.
    assert b.acc.cash == Decimal('9500')
    assert b.acc.cash_on_hold == Decimal('0')
    assert b.acc.net_position == Decimal('5')
    print("Scenario 6 Passed.")

    print("\nALL 6 SCENARIOS PASSED!")

if __name__ == "__main__":
    test_accounting()
