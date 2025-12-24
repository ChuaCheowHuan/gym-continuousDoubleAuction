import unittest
import sys
from decimal import Decimal

# Add parent directory to path to import modules
if "../" not in sys.path:
    sys.path.append("../")
    
from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook

class TestOrderBookDoubleDelete(unittest.TestCase):
    """
    Test case to ensure that modifying an order's price does not cause 
    double-deletion errors (Internal OrderList length becoming -1).
    """
    def setUp(self):
        self.ob = OrderBook()

    def test_modify_order_price_no_double_delete(self):
        # 1. Place a limit order at Price 100
        bid = {
            'type': 'limit', 
            'side': 'bid', 
            'quantity': Decimal('10'), 
            'price': Decimal('100'), 
            'trade_id': 'B1'
        }
        _, quote = self.ob.process_order(bid, from_data=False, verbose=False)
        order_id = quote['order_id']
        
        # 2. Attempt to modify the price to 101
        # This previously triggered update_order() -> remove_order() 
        # then insert_order() -> remove_order_by_id() -> remove_order() causing a ValueError.
        update_data = {
            'side': 'bid', 
            'quantity': Decimal('10'), 
            'price': Decimal('101'), 
            'timestamp': 2
        }
        
        # This should NOT raise ValueError
        try:
            self.ob.modify_order(order_id, update_data)
        except ValueError as e:
            self.fail(f"modify_order raised ValueError: {e}")

if __name__ == "__main__":
    unittest.main()
