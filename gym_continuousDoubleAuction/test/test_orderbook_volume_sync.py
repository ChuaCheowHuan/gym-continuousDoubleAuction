import unittest
import sys
from decimal import Decimal

# Add parent directory to path to import modules
if "../" not in sys.path:
    sys.path.append("../")

from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook

class TestOrderBookVolumeSync(unittest.TestCase):
    """
    Test case to ensure that OrderTree.volume remains in sync with 
    the actual sum of order volumes, especially after partial fills.
    """
    def setUp(self):
        self.ob = OrderBook()

    def get_calculated_volume(self, side):
        """Manually calculate volume by summing up price levels."""
        tree = self.ob.bids if side == 'bid' else self.ob.asks
        return sum(ol.volume for ol in tree.price_map.values())

    def test_partial_fill_volume_sync(self):
        # 1. Place a limit ask for 10 units at price 100
        self.ob.process_order({
            'type': 'limit', 
            'side': 'ask', 
            'quantity': Decimal('10'), 
            'price': Decimal('100'), 
            'trade_id': 'S1'
        }, False, False)
        
        initial_tree_vol = self.ob.asks.volume
        initial_calc_vol = self.get_calculated_volume('ask')
        
        self.assertEqual(initial_tree_vol, Decimal('10'))
        self.assertEqual(initial_calc_vol, Decimal('10'))

        # 2. Execute a partial fill: A bid for 4 units at price 100
        self.ob.process_order({
            'type': 'limit', 
            'side': 'bid', 
            'quantity': Decimal('4'), 
            'price': Decimal('100'), 
            'trade_id': 'B1'
        }, False, False)
        
        final_tree_vol = self.ob.asks.volume
        final_calc_vol = self.get_calculated_volume('ask')
        
        # Verify both values are 6 and they match each other
        self.assertEqual(final_calc_vol, Decimal('6'), "Manual calculation shows volume should be 6")
        self.assertEqual(final_tree_vol, Decimal('6'), "OrderTree.volume should be 6 after partial fill")

if __name__ == '__main__':
    unittest.main()
