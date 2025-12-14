from decimal import Decimal

class Cash_Processor(object):
    """
    Handles the cash & cash_on_hold for the trader's account.

    Context:
        In this League-Based MARL environment, agents trade in a Zero-Sum setting.
        To ensure solvency and prevent leverage, the system enforces a 100% Margin Requirement.
    
    Mechanics:
        - When an order is placed (Buy or Short Sell), the full value (Price * Quantity) 
          is moved from 'Cash' to 'Cash on Hold' (Collateral).
        - This prevents the agent from re-using the same funds for multiple orders ("Double Spending").
        - Funds remain locked until the order is Executed (Trade) or Cancelled.
    """

    def order_in_book_init_party(self, order_in_book):
        """
        Lock collateral for a new order placed by the agent.
        
        Args:
            order_in_book (dict): The order details (price, quantity).
            
        Effect:
            Reduces 'cash' and increases 'cash_on_hold' by the full order value.
            This enforces the 100% margin requirement.
        """

        # if there's order_in_book for init_party (party2)
        if order_in_book != None and order_in_book != []: # there are new unfilled orders
            order_in_book_val = order_in_book.get('price') * Decimal(order_in_book.get('quantity'))
            self.cash -= order_in_book_val # reduce cash
            self.cash_on_hold += order_in_book_val # increase cash_on_hold

            #print('order_in_book:', order_in_book)

        return 0

    def size_increase_cash_transfer(self, party, trade_val):
        """
        Handle cash flow when a position size increases (Open/Add).
        
        Args:
            party (str): 'init_party' (Aggressor) or 'counter_party' (Maker).
            trade_val (Decimal): Value of the trade (Price * Quantity).
            
        Effect:
            - Init Party: Cash was free, now deducted (paid).
            - Counter Party: Cash was already on hold (locked limit order), now deducted (used).
        """
        if party == 'init_party':
            self.cash -= trade_val # initial order cash reduction
        else: #counter_party
            self.cash_on_hold -= trade_val # reduce cash_on_hold for initial order cash_on_hold increase
        return 0

    def size_decrease_cash_transfer(self, party, trade_val):
        """
        Handle cash flow when a position size decreases (Close/Reduce).
        
        Args:
            party (str): 'init_party' or 'counter_party'.
            trade_val (Decimal): Value of the trade.
            
        Effect:
            - Returns the cash value of the trade to the agent.
            - Note: For logic involving PnL realization, see `realize_pnl_cash_transfer`.
        """
        if party == 'init_party':
            self.cash += trade_val # portion covered goes back to cash
        else: #counter_party
            self.cash += trade_val # increase cash for initial order cash reduction
            self.cash_on_hold -= trade_val # reduce cash_on_hold for initial order cash_on_hold increase
            self.cash += trade_val # portion covered goes back to cash
        return 0

    def size_zero_cash_transfer(self, trade_val):
        """
        Adjust cash when a position is fully closed (Net Position = 0).
        
        This handles the final cash settlement, adding the entire position value 
        (Cost Basis + PnL) back to cash, ensuring the trade value isn't double-counted.
        """

        self.cash += self.position_val - trade_val
        return 0

    def init_is_counter_cash_transfer(self, trade_val):
        """
        Handle the edge case where an agent trades against themselves.
        
        Effect:
            Just unlocks the cash_on_hold. No net change in wealth 
            (Wealth transfer from self to self).
        """

        self.cash_on_hold -= trade_val
        self.cash += trade_val
        return 0

    def modify_cash_transfer(self, qoute, order):
        """
        Adjust collateral when an existing order in the LOB is modified.
        
        Logic:
            - If size increases: Lock additional collateral.
            - If size decreases: Release excess collateral back to cash.
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
        Release collateral when an order is cancelled.
        
        Effect:
            Moves the full order value from 'cash_on_hold' back to 'cash'.
        """

        order_val = (order.price) * (order.quantity)
        # deduct from cash_on_hold, return to cash
        self.cash_on_hold -= order_val
        self.cash += order_val
        return 0

    def realize_pnl_cash_transfer(self, party, cash_release, margin_release=0):
        """
        Execute explicit cash transfer for Realized PnL events (e.g. Partial Fills).
        
        Crucial for Short Covers and Partial Closes where:
        Cash Return = Principal (Collateral) + Realized Profit (or minus Loss).
        
        Args:
            party (str): 'init_party' or 'counter_party'
            cash_release (Decimal): Total amount to credit to 'cash'.
            margin_release (Decimal): Amount to unblock from 'cash_on_hold'.
        """
        if party == 'init_party':
            self.cash += cash_release
        else: # counter_party
            self.cash_on_hold -= margin_release
            self.cash += cash_release
        return 0
