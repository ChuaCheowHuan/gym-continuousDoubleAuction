
import unittest
import sys
import numpy as np
from decimal import Decimal

# Add parent directory to path to import modules
if "../" not in sys.path:
    sys.path.append("../")
    
from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook

def reproduce_bug():
    print("--- Starting Reproduction Script ---")
    
    # 1. Initialize the OrderBook
    ob = OrderBook()
    
    # 2. Place a limit order at Price 100
    # This creates an OrderList at price 100 with length 1.
    bid = {
        'type': 'limit', 
        'side': 'bid', 
        'quantity': Decimal('10'), 
        'price': Decimal('100'), 
        'trade_id': 'B1'
    }
    print("Step 1: Placing initial order at price 100...")
    _, quote = ob.process_order(bid, from_data=False, verbose=False)
    order_id = quote['order_id']
    print(f"Order created with ID: {order_id}")
    
    # 3. Attempt to modify the price to 101
    # This will trigger update_order() -> remove_order() (length becomes 0)
    # Then it calls insert_order() -> remove_order_by_id() -> remove_order() (length becomes -1)
    print("\nStep 2: Modifying price from 100 to 101...")
    update_data = {
        'side': 'bid', 
        'quantity': Decimal('10'), 
        'price': Decimal('101'), 
        'timestamp': 2
    }
    
    try:
        ob.modify_order(order_id, update_data)
        print("Success! (If you see this, the bug is fixed)")
    except ValueError as e:
        print(f"\nCaught Expected Error: {e}")
        print("Trace explanation: The length of the internal OrderList became -1 due to double-deletion.")

if __name__ == "__main__":
    reproduce_bug()
