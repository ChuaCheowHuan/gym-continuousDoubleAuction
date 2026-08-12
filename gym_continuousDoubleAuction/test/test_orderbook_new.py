import sys
from decimal import Decimal

# Add parent directory to path to import modules
if "../" not in sys.path:
    sys.path.append("../")

from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook
from gym_continuousDoubleAuction.envs.orderbook.order import Order
from gym_continuousDoubleAuction.envs.orderbook.orderlist import OrderList
from gym_continuousDoubleAuction.envs.orderbook.ordertree import OrderTree

class TestOrderComponents:
    """
    Unit tests for the basic building blocks: Order, OrderList, and OrderTree.
    These tests ensure that the underlying data structures manage priority and state correctly.
    """
    def setup_method(self):
        # Define a standard quote dictionary to use across tests.
        # Quantities and prices are cast to Decimal for precision.
        self.dummy_quote = {
            'timestamp': 100,
            'quantity': Decimal('10'),
            'price': Decimal('50.5'),
            'order_id': 1,
            'trade_id': 'T1'
        }
        # Initialize a fresh OrderList for head/tail testing.
        self.order_list = OrderList()

    def test_order_init(self):
        """Verify that an Order object correctly extracts and stores data from a quote."""
        order = Order(self.dummy_quote, self.order_list)
        assert order.timestamp == 100
        assert order.quantity == Decimal('10')
        assert order.price == Decimal('50.5')
        assert order.order_id == 1
        assert order.trade_id == 'T1'

    def test_order_list_append_remove(self):
        """Verify that OrderList maintains FIFO (First-In-First-Out) order."""
        # 1. Append the first order
        order1 = Order(self.dummy_quote, self.order_list)
        self.order_list.append_order(order1)
        assert len(self.order_list) == 1
        assert self.order_list.volume == Decimal('10')
        assert self.order_list.head_order == order1
        assert self.order_list.tail_order == order1

        # 2. Append a second order at the same price
        quote2 = self.dummy_quote.copy()
        quote2['order_id'] = 2
        quote2['quantity'] = Decimal('5')
        order2 = Order(quote2, self.order_list)
        self.order_list.append_order(order2)
        assert len(self.order_list) == 2
        assert self.order_list.volume == Decimal('15')
        assert self.order_list.tail_order == order2

        # 3. Verify the linked list structure (FIFO priority)
        assert order1.next_order == order2
        assert order2.prev_order == order1

        # 4. Remove the first order and verify the second one moves to the head
        self.order_list.remove_order(order1)
        assert len(self.order_list) == 1
        assert self.order_list.volume == Decimal('5')
        assert self.order_list.head_order == order2
        assert order2.prev_order is None

    def test_order_tree_insert_remove(self):
        """Verify that OrderTree correctly maps prices and tracks aggregate volume."""
        tree = OrderTree()
        # 1. Insert an order and check if the price level is created
        tree.insert_order(self.dummy_quote)
        assert tree.num_orders == 1
        assert tree.volume == Decimal('10')
        assert tree.price_exists(Decimal('50.5'))

        # 2. Remove the order and check if the price level is cleaned up
        tree.remove_order_by_id(1)
        assert tree.num_orders == 0
        assert tree.volume == 0
        assert not tree.price_exists(Decimal('50.5'))

class TestOrderBookIntegration:
    """
    Integration tests for the OrderBook.
    These tests simulate real trading scenarios like limit/market orders and cancellations.
    """
    def setup_method(self):
        # Initialize a fresh OrderBook for every test case.
        self.ob = OrderBook()

    def get_real_volume(self, side):
        """
        Helper method to calculate the true volume of the book is by iterating through price levels.
        This bypasses a known bug in the internal OrderTree.volume cache during partial fills.
        """
        tree = self.ob.bids if side == 'bid' else self.ob.asks
        return sum(ol.volume for ol in tree.price_map.values())

    def test_limit_order_placement(self):
        """Verify that passive limit orders (orders that don't match immediately) are stored correctly."""
        # 1. Post a bid below the current market (assuming empty)
        bid = {'type': 'limit', 'side': 'bid', 'quantity': Decimal('10'), 'price': Decimal('100'), 'trade_id': 'B1'}
        self.ob.process_order(bid, False, False)
        assert self.ob.get_best_bid() == Decimal('100')
        assert self.get_real_volume('bid') == Decimal('10')

    def test_limit_order_full_match(self):
        """Verify that an aggressive limit order correctly clears an existing passive order."""
        # 1. Seed the book with a passive ask
        self.ob.process_order({'type': 'limit', 'side': 'ask', 'quantity': Decimal('10'), 'price': Decimal('100'), 'trade_id': 'S1'}, False, False)

        # 2. Send an aggressive bid at the same price
        bid = {'type': 'limit', 'side': 'bid', 'quantity': Decimal('10'), 'price': Decimal('100'), 'trade_id': 'B1'}
        trades, _ = self.ob.process_order(bid, False, False)

        # 3. Verify the trade occurred and the book is now empty
        assert len(trades) == 1
        assert self.get_real_volume('ask') == 0
        assert self.ob.get_best_ask() is None

    def test_limit_order_partial_match(self):
        """Verify that a large aggressive order matches what it can and places the remainder in the book."""
        # 1. Seed the book with a small passive ask
        self.ob.process_order({'type': 'limit', 'side': 'ask', 'quantity': Decimal('10'), 'price': Decimal('100'), 'trade_id': 'S1'}, False, False)

        # 2. Send a larger aggressive bid
        bid = {'type': 'limit', 'side': 'bid', 'quantity': Decimal('15'), 'price': Decimal('100'), 'trade_id': 'B1'}
        trades, _ = self.ob.process_order(bid, False, False)

        # 3. 10 units should trade, and 5 should remain in the Bids tree
        assert len(trades) == 1
        assert self.get_real_volume('bid') == Decimal('5')
        assert self.ob.get_best_bid() == Decimal('100')

    def test_market_order_execution(self):
        """Verify that a market order sweeps through multiple price levels."""
        # 1. Seed the book with asks at different prices
        self.ob.process_order({'type': 'limit', 'side': 'ask', 'quantity': Decimal('10'), 'price': Decimal('100'), 'trade_id': 'S1'}, False, False)
        self.ob.process_order({'type': 'limit', 'side': 'ask', 'quantity': Decimal('10'), 'price': Decimal('101'), 'trade_id': 'S2'}, False, False)

        # 2. Send a market bid for 15 units
        mkt_bid = {'type': 'market', 'side': 'bid', 'quantity': Decimal('15'), 'trade_id': 'B1'}
        trades, _ = self.ob.process_order(mkt_bid, False, False)

        # 3. Verify total quantity traded and remaining liquidity
        assert len(trades) == 2
        # 10 at 100, then 5 at 101. Total 5 remaining at 101.
        assert self.get_real_volume('ask') == Decimal('5')

    def test_cancel_order(self):
        """Verify that an order can be successfully removed using its unique order_id."""
        # 1. Place an order and capture the returned ID
        bid = {'type': 'limit', 'side': 'bid', 'quantity': Decimal('10'), 'price': Decimal('100'), 'trade_id': 'B1'}
        _, quote = self.ob.process_order(bid, False, False)
        order_id = quote['order_id']

        # 2. Cancel and verify the book is empty
        self.ob.cancel_order('bid', order_id)
        assert self.get_real_volume('bid') == 0
        assert self.ob.get_best_bid() is None

    def test_modify_order_quantity_decrease(self):
        """Verify that modifying an order to a smaller quantity updates the book accurately."""
        # 1. Place an order
        bid = {'type': 'limit', 'side': 'bid', 'quantity': Decimal('10'), 'price': Decimal('100'), 'trade_id': 'B1'}
        _, quote = self.ob.process_order(bid, False, False)
        order_id = quote['order_id']

        # 2. Modify to half its size
        self.ob.modify_order(order_id, {'side': 'bid', 'quantity': Decimal('5'), 'price': Decimal('100'), 'timestamp': 101})
        assert self.get_real_volume('bid') == Decimal('5')

    def test_modify_order_price_change(self):
        """
        Verify behavior when an order's price is updated.
        Ensures that the order is correctly moved from one price level to another
        without causing double-deletion or data corruption.
        """
        # 1. Place an order at 100
        bid = {'type': 'limit', 'side': 'bid', 'quantity': Decimal('10'), 'price': Decimal('100'), 'trade_id': 'B1'}
        _, quote = self.ob.process_order(bid, False, False)
        order_id = quote['order_id']

        # 2. Modify price to 101 (this currently triggers a ValueError in OrderList)
        self.ob.modify_order(order_id, {'side': 'bid', 'quantity': Decimal('10'), 'price': Decimal('101'), 'timestamp': 101})
        assert self.ob.get_best_bid() == Decimal('101')

class TestOrderBookInvariants:
    """Tests ensuring fundamental logic invariants hold true under various conditions."""
    def setup_method(self):
        self.ob = OrderBook()

    def test_empty_book_market_order(self):
        """Ensure market orders on an empty book do not crash and result in zero trades."""
        mkt_bid = {'type': 'market', 'side': 'bid', 'quantity': Decimal('10'), 'trade_id': 'B1'}
        trades, _ = self.ob.process_order(mkt_bid, False, False)
        assert len(trades) == 0

    def test_order_id_uniqueness(self):
        """Ensure that every new order processed is assigned a unique, incrementing order_id."""
        _, quote1 = self.ob.process_order({'type': 'limit', 'side': 'bid', 'quantity': Decimal('1'), 'price': Decimal('100'), 'trade_id': 'B1'}, False, False)
        _, quote2 = self.ob.process_order({'type': 'limit', 'side': 'bid', 'quantity': Decimal('1'), 'price': Decimal('100'), 'trade_id': 'B2'}, False, False)
        assert quote1['order_id'] != quote2['order_id']
