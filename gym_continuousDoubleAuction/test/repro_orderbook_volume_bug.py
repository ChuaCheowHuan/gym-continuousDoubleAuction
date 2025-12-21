import unittest
import sys
from decimal import Decimal

# Add parent directory to path to import modules
if "../" not in sys.path:
    sys.path.append("../")

from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook

class TestVolumeBugRepro(unittest.TestCase):
    """
    Reproducible example for the OrderTree volume bug.
    This demonstrates that OrderTree.volume fails to update during partial fills.
    """
    def setUp(self):
        self.ob = OrderBook()

    def get_calculated_volume(self, side):
        """Manually calculate volume by summing up price levels."""
        tree = self.ob.bids if side == 'bid' else self.ob.asks
        return sum(ol.volume for ol in tree.price_map.values())

    def test_partial_fill_volume_discrepancy(self):
        print("\n--- Testing Partial Fill Volume Sync ---")
        
        # 1. Place a limit ask for 10 units at price 100
        print("Placing Ask: 10 units @ 100")
        self.ob.process_order({
            'type': 'limit', 
            'side': 'ask', 
            'quantity': Decimal('10'), 
            'price': Decimal('100'), 
            'trade_id': 'S1'
        }, False, False)
        
        initial_tree_vol = self.ob.asks.volume
        initial_calc_vol = self.get_calculated_volume('ask')
        
        print(f"Initial OrderTree.volume: {initial_tree_vol}")
        print(f"Initial Calculated volume: {initial_calc_vol}")
        
        self.assertEqual(initial_tree_vol, Decimal('10'))
        self.assertEqual(initial_calc_vol, Decimal('10'))

        # 2. Execute a partial fill: A bid for 4 units at price 100
        print("\nExecuting Partial Fill: Bid 4 units @ 100")
        self.ob.process_order({
            'type': 'limit', 
            'side': 'bid', 
            'quantity': Decimal('4'), 
            'price': Decimal('100'), 
            'trade_id': 'B1'
        }, False, False)
        
        final_tree_vol = self.ob.asks.volume
        final_calc_vol = self.get_calculated_volume('ask')
        
        print(f"Final OrderTree.volume: {final_tree_vol} <--- BUG: This should be 6")
        print(f"Final Calculated volume: {final_calc_vol}")

        # This assertion is expected to FAIL until the bug is fixed
        try:
            self.assertEqual(final_tree_vol, Decimal('6'), "OrderTree.volume is out of sync after partial fill!")
            print("SUCCESS: Volume is in sync.")
        except AssertionError as e:
            print(f"FAILURE: {e}")
            raise

if __name__ == '__main__':
    unittest.main()
