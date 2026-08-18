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

    def order_in_book_passive_party(self, order_in_book):
        """
        If there are new unfilled orders for this trader(passive party),
        reduce his cash & increase his cash_on_hold.
        """

        # if there's order_in_book for passive party (party2)
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

    # `modify_cash_transfer` used to sit here: it moved
    # `order_val - qoute_val` between cash and cash_on_hold, as the escrow
    # delta of a size change. Nothing called it, and it is deleted rather than
    # wired up because it is only correct where the live path already is.
    #
    # A modify is handled as cancel-and-reprocess: `cancel_cash_transfer`
    # returns the whole old order value to cash, `OrderBook.modify_order`
    # re-runs the quote through `process_limit_order`, and whatever is left
    # resting is re-escrowed by `order_in_book_passive_party`. Net cash movement
    # is `order_val - residual_val`. When the modify does not match,
    # `residual_val == qoute_val` and the two are the same expression - which is
    # why NAV conservation never distinguished them.
    #
    # When it *does* match they diverge, and the deleted function is the wrong
    # one: it has no term for a fill, so it escrows cash against quantity that
    # is no longer resting. Modifying a bid of 10@100 to 10@101 into a resting
    # ask at 101 moves cash_on_hold by -394 on the live path and would have
    # moved it by +10 here. Re-processing is not an implementation detail of
    # modify - it is what lets a modify cross the spread, which this function
    # assumes never happens. See doc/15 S3-20.

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
