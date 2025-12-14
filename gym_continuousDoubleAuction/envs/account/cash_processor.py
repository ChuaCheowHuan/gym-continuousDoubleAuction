from decimal import Decimal

class Cash_Processor(object):
    """
    Handles the cash & cash_on_hold for the trader's account.

    note:
        When the trader places an order, certain amount of cash
        (the order's value) is placed on hold so that his amount of cash will
        decrease accordingly.
        This is to prevent the trader having the ability to keep placing orders
        as if he has an unlimited amount of cash.
    """

    def order_in_book_init_party(self, order_in_book):
        """
        If there are new unfilled orders for this trader(init_party),
        reduce his cash & increase his cash_on_hold.
        """

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
        """
        add position_val back to cash minus trade_val, trade_val is handled in size_decrease_cash_transfer
        """

        self.cash += self.position_val - trade_val
        return 0

    def init_is_counter_cash_transfer(self, trade_val):
        """
        init_party is also counter_party.
        """

        self.cash_on_hold -= trade_val
        self.cash += trade_val
        return 0

    def modify_cash_transfer(self, qoute, order):
        """
        Update account of trader accordingly if his orders in LOB changes.

        note:
            Changes in LOB orders refer to changes in size.
            If size decrease, deduct from cash_on_hold, return to cash.
            If size increase, deduct from cash, add to cash_on_hold.
        """

        order_val = (order.price) * (order.quantity)



        qoute_val = Decimal(str(qoute['price'])) * qoute['quantity']
        
        
        
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
        """
        Update account of trader accordingly if his order in LOB is cancelled.

        note:
            deduct from cash_on_hold, return to cash.
        """

        order_val = (order.price) * (order.quantity)
        # deduct from cash_on_hold, return to cash
        self.cash_on_hold -= order_val
        self.cash += order_val
        return 0

    def realize_pnl_cash_transfer(self, party, cash_release, margin_release=0):
        """
        Update cash after a position close (partial or full).
        
        Args:
            party (str): 'init_party' or 'counter_party'
            cash_release (Decimal): Total cash to return to 'cash' (Principal + PnL)
            margin_release (Decimal): Amount to release from 'cash_on_hold' (only for counter_party limit orders)
        """
        if party == 'init_party':
            self.cash += cash_release
        else: # counter_party
            self.cash_on_hold -= margin_release
            self.cash += cash_release
        return 0
