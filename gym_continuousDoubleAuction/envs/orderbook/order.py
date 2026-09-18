from decimal import Decimal

class Order(object):
    '''
    Orders represent the core piece of the exchange. Every bid/ask is an Order.
    Orders are doubly linked and have helper functions (next_order, prev_order)
    to help the exchange fullfill orders with quantities larger than a single
    existing Order.
    '''
    def __init__(self, quote, order_list):
        self.timestamp = int(quote['timestamp']) # integer representing the timestamp of order creation
        self.quantity = Decimal(quote['quantity']) # decimal representing amount of thing - can be partial amounts
        self.price = Decimal(quote['price']) # decimal representing price (currency)
        self.order_id = int(quote['order_id'])
        self.trade_id = quote['trade_id']
        # doubly linked list to make it easier to re-order Orders for a particular price point
        self.next_order = None
        self.prev_order = None
        self.order_list = order_list

    def update_quantity(self, new_quantity, new_timestamp):
        """Change the resting quantity, keeping or losing queue priority.

        A size *increase* is a new commitment and goes to the back of the
        queue, so it takes the new timestamp. A size *decrease* keeps its place
        - and now keeps its timestamp too. It used to take the new one while
        staying at the head, which left a level's list out of timestamp order
        (found by the Hypothesis suite: stamps `[16, 12]` at one price) and
        made `Trader._get_order_ID`'s "oldest order" FIFO rule for a modify
        pick the wrong order after a partial cancel. The timestamp is the
        priority time, so it moves exactly when the priority does.
        """
        new_quantity = Decimal(new_quantity)
        if new_quantity > self.quantity:
            if self.order_list.tail_order != self:
                self.order_list.move_to_tail(self) # move to the end
            self.timestamp = new_timestamp
        self.order_list.volume -= (self.quantity - new_quantity) # update volume
        self.quantity = new_quantity

    def __str__(self):
        order = {}
        order["size"] = self.quantity
        order["price"] = self.price
        order["trade_id"] = self.trade_id
        order["timestamp"] = self.timestamp
        order["order_id"] = self.order_id

        return str(order)
