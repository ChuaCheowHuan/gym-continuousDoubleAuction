from decimal import Decimal

class Cash_Processor(object):

    def order_in_book_init_party(self, order_in_book):
        # if there's order_in_book for init_party (party2)
        if order_in_book != None and order_in_book != []: # there are new unfilled orders
            order_in_book_val = order_in_book.get('price') * Decimal(order_in_book.get('quantity'))
            self.cash -= order_in_book_val # reduce cash
            self.cash_on_hold += order_in_book_val # increase cash_on_hold

            #print('order_in_book:', order_in_book)

        return 0

    def size_increase_cash_transfer(self, party, trade_val):
        if party == 'init_party':
            self.cash -= trade_val # initial order cash reduction
        else: #counter_party
            self.cash_on_hold -= trade_val # reduce cash_on_hold for initial order cash_on_hold increase
        return 0

    def size_decrease_cash_transfer(self, party, trade_val):
        if party == 'init_party':
            self.cash += trade_val # portion covered goes back to cash
        else: #counter_party
            self.cash += trade_val # increase cash for initial order cash reduction
            self.cash_on_hold -= trade_val # reduce cash_on_hold for initial order cash_on_hold increase
            self.cash += trade_val # portion covered goes back to cash
        return 0

    def size_zero_cash_transfer(self, trade_val):
        # add position_val back to cash minus trade_val, trade_val is handled in size_decrease_cash_transfer
        self.cash += self.position_val - trade_val
        return 0

    # init_party is also counter_party
    def init_is_counter_cash_transfer(self, trade_val):
        self.cash_on_hold -= trade_val
        self.cash += trade_val
        return 0

    def modify_cash_transfer(self, qoute, order):
        order_val = (order.price) * (order.quantity)
        qoute_val = Decimal(qoute['price']) * (qoute['quantity'])
        if order_val >= qoute_val: # reducing size
            diff = order_val - qoute_val
            # deduct from cash_on_hold, return to cash
            self.cash_on_hold -= diff
            self.cash += diff
        else: # order_val < qoute_val, increasing size
            diff = qoute_val - order_val
            # deduct from cash, add to cash_on_hold
            self.cash -= diff
            self.cash_on_hold += diff
        return 0

    def cancel_cash_transfer(self, order):
        order_val = (order.price) * (order.quantity)
        # deduct from cash_on_hold, return to cash
        self.cash_on_hold -= order_val
        self.cash += order_val
        return 0
