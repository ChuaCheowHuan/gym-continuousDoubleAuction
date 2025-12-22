import unittest
import sys
from decimal import Decimal

# Add parent directory to path to import modules
if "../" not in sys.path:
    sys.path.append("../")
    
from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook

class TestOrderBookCrossedBook(unittest.TestCase):
    """
    Test case to ensure the OrderBook does not become crossed.
    This was previously a reproduction script for a bug where modify_order
    could result in a crossed book.
    """
    def setUp(self):
        self.ob = OrderBook()

    def test_modify_order_does_not_cross_book(self):
        # 1. Place a limit Ask at price 100
        ask = {
            'type': 'limit', 
            'side': 'ask', 
            'quantity': Decimal('10'), 
            'price': Decimal('100'), 
            'trade_id': 'S1'
        }
        self.ob.process_order(ask, from_data=False, verbose=False)
        
        # 2. Place a limit Bid at price 90
        bid = {
            'type': 'limit', 
            'side': 'bid', 
            'quantity': Decimal('10'), 
            'price': Decimal('90'), 
            'trade_id': 'B1'
        }
        _, quote = self.ob.process_order(bid, from_data=False, verbose=False)
        order_id = quote['order_id']
        
        # 3. Modify the Bid price to 110
        # This price is ABOVE the Ask (100). 
        # In a correct OrderBook, this should trigger a trade immediately
        # or at least not result in a crossed book where best_bid >= best_ask.
        update_data = {
            'side': 'bid', 
            'quantity': Decimal('10'), 
            'price': Decimal('110'), 
            'timestamp': 2
        }
        self.ob.modify_order(order_id, update_data)
        
        best_bid = self.ob.get_best_bid()
        best_ask = self.ob.get_best_ask()
        
        # If the book is not empty on both sides, it should not be crossed
        if best_bid is not None and best_ask is not None:
            self.assertLess(best_bid, best_ask, f"Book is CROSSED: Best Bid ({best_bid}) >= Best Ask ({best_ask})")

if __name__ == "__main__":
    unittest.main()
