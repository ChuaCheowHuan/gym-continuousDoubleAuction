
import sys
from decimal import Decimal

# Add parent directory to path to import modules
if "../" not in sys.path:
    sys.path.append("../")
    
from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook

def reproduce_crossed_book():
    print("--- Starting Crossed Book Reproduction Script ---")
    
    ob = OrderBook()
    
    # 1. Place a limit Ask at price 100
    # This creates the "sell" side of the book.
    ask = {
        'type': 'limit', 
        'side': 'ask', 
        'quantity': Decimal('10'), 
        'price': Decimal('100'), 
        'trade_id': 'S1'
    }
    print("Step 1: Placing limit Ask at 100...")
    ob.process_order(ask, from_data=False, verbose=False)
    
    # 2. Place a limit Bid at price 90
    # This is below the ask, so no trade happens.
    bid = {
        'type': 'limit', 
        'side': 'bid', 
        'quantity': Decimal('10'), 
        'price': Decimal('90'), 
        'trade_id': 'B1'
    }
    print("Step 2: Placing limit Bid at 90...")
    _, quote = ob.process_order(bid, from_data=False, verbose=False)
    order_id = quote['order_id']
    
    print(f"Current Best Bid: {ob.get_best_bid()}, Best Ask: {ob.get_best_ask()}")

    # 3. Modify the Bid price to 110
    # This price is ABOVE the Ask (100). 
    # In a correct OrderBook, this should trigger a trade immediately.
    print("\nStep 3: Modifying Bid price from 90 to 110 (Crossing the Ask at 100)...")
    update_data = {
        'side': 'bid', 
        'quantity': Decimal('10'), 
        'price': Decimal('110'), 
        'timestamp': 2
    }
    ob.modify_order(order_id, update_data)
    
    best_bid = ob.get_best_bid()
    best_ask = ob.get_best_ask()
    
    print(f"Resulting Best Bid: {best_bid}")
    print(f"Resulting Best Ask: {best_ask}")
    
    if best_bid is not None and best_ask is not None and best_bid >= best_ask:
        print("\nBUG REPRODUCED: The book is CROSSED.")
        print("Reason: modify_order moved the bid to 110 but did not check for matches against the Ask at 100.")
    else:
        print("\nBug not found or already fixed.")

if __name__ == "__main__":
    reproduce_crossed_book()
