from decimal import Decimal

from .cash_processor import Cash_Processor
from .calculate import Calculate

from tabulate import tabulate

class Account(Calculate, Cash_Processor):
    """
    Main Account class for an Agent in the Continuous Double Auction Market.
    
    Architecture:
        - Inherits from Calculate (NAV, Profit) and Cash_Processor (Cash, Collateral).
        - Maintains the 'Net Position' (Inventory) of the agent.
        - Enforces logic for:
            a) Opening/Increasing Positions (Locking Collateral).
            b) Closing/Decreasing Positions (Realizing PnL, Releasing Collateral).
            
    Zero-Sum MARL Context:
        - Trading represents a direct wealth transfer between agents.
        - The `process_acc` method ensures that every trade correctly impacts both the 
          Buyer (Init Party) and Seller (Counter Party) in complementary ways.
    """
    def __init__(self, ID, cash=0):
        self.ID = ID
        self.cash = Decimal(cash) # Liquid Capital
        # nav is used to calculate P&L & r per t step
        self.cash_on_hold = Decimal(0) # cash deducted for placing order = cash - value of live order in LOB
        self.position_val = Decimal(0) # Abstract value of holdings (Cost Basis + Unrealized PnL)
        # nav is used to calculate P&L & r per t step
        self.init_nav = Decimal(cash) # starting nav @t = 0
        self.nav = Decimal(cash) # nav @t (nav @ end of a single t-step)
        self.prev_nav = Decimal(cash) # nav @t-1
        # assuming only one ticker (1 type of contract)
        self.net_position = 0 # Inventory: Long (+) or Short (-)
        self.VWAP = Decimal(0) # Volume Weighted Average Price (Cost Basis)
        self.profit = Decimal(0) # profit @ each trade(tick) within a single t step
        self.total_profit = Decimal(0) # profit at the end of a single t-step
        self.num_trades = 0
        self.reward = 0

    def reset_acc(self, ID, cash=0):
        """Reset account state at the start of a new episode."""
        self.ID = ID
        self.cash = Decimal(cash)
        # nav is used to calculate P&L & r per t step
        self.cash_on_hold = Decimal(0) # cash deducted for placing order = cash - value of live order in LOB
        self.position_val = Decimal(0) # value of net_position
        # nav is used to calculate P&L & r per t step
        self.init_nav = Decimal(cash) # starting nav @t = 0
        self.nav = Decimal(cash) # nav @t (nav @ end of a single t-step)
        self.prev_nav = Decimal(cash) # nav @t-1
        # assuming only one ticker (1 type of contract)
        self.net_position = 0 # number of contracts currently holding long (positive) or short (negative)
        self.VWAP = Decimal(0) # VWAP
        self.profit = Decimal(0) # profit @ each trade(tick) within a single t step
        self.total_profit = Decimal(0) # profit at the end of a single t-step
        self.num_trades = 0
        self.reward = 0

    def print_acc(self, msg):
        acc = {}
        acc['ID'] = [self.ID]
        acc['cash'] = [self.cash]
        acc['cash_on_hold'] = [self.cash_on_hold]
        acc['position_val'] = [self.position_val]
        acc['prev_nav'] = [self.prev_nav]
        acc['nav'] = [self.nav]
        acc['net_position'] = [self.net_position]
        acc['VWAP'] = [self.VWAP]
        acc['profit'] = [self.profit]
        acc['total_profit'] = [self.total_profit]
        acc['num_trades'] = [self.num_trades]

        print(msg, tabulate(acc, headers="keys"))
        return 0

    def print_both_accs(self, msg, curr_step_trade_ID, counter_party, init_party):
        """
        Print accounts of both counter_party & init_party.
        """

        acc = {}
        acc['seq_Trade_ID'] = [curr_step_trade_ID, curr_step_trade_ID]
        acc['party'] = ["counter", "init"]
        acc['ID'] = [counter_party.acc.ID, init_party.acc.ID]
        acc['cash'] = [counter_party.acc.cash, init_party.acc.cash]
        acc['cash_on_hold'] = [counter_party.acc.cash_on_hold, init_party.acc.cash_on_hold]
        acc['position_val'] = [counter_party.acc.position_val, init_party.acc.position_val]
        acc['prev_nav'] = [counter_party.acc.prev_nav, init_party.acc.prev_nav]
        acc['nav'] = [counter_party.acc.nav, init_party.acc.nav]
        acc['net_position'] = [counter_party.acc.net_position, init_party.acc.net_position]
        acc['VWAP'] = [counter_party.acc.VWAP, init_party.acc.VWAP]
        acc['profit'] = [counter_party.acc.profit, init_party.acc.profit]
        acc['total_profit'] = [counter_party.acc.total_profit, init_party.acc.total_profit]
        acc['num_trades'] = [counter_party.acc.num_trades, init_party.acc.num_trades]

        print(msg, tabulate(acc, headers="keys"))
        return 0

    def _size_increase(self, trade, position, party, trade_val):
        """
        Increase the net position (Long Buy or Short Sell).
        Updates VWAP (Cost Basis) using a weighted average.
        """
        total_size = abs(self.net_position) + Decimal(trade.get('quantity'))
        # VWAP
        self.VWAP = (abs(self.net_position) * self.VWAP + trade_val) / total_size
        raw_val = total_size * self.VWAP # value acquired with VWAP
        mkt_val = total_size * trade.get('price')
        self.position_val = raw_val + self.cal_profit(position, mkt_val, raw_val)
        self.size_increase_cash_transfer(party, trade_val)
        return 0

    def _covered(self, trade, position):
        """
        Entire position covered (Net Position goes to 0).
        Realize all PnL and reset position stats.
        """

        raw_val = abs(self.net_position) * self.VWAP # value acquired with VWAP
        mkt_val = abs(self.net_position) * trade.get('price')
        self.position_val = raw_val + self.cal_profit(position, mkt_val, raw_val)
        self.size_zero_cash_transfer(mkt_val)
        # reset to 0
        self.position_val = 0
        self.VWAP = 0
        return mkt_val

    def _size_decrease(self, trade, position, party, trade_val):
        """
        Handle partial fill / size decrease (Long Sell or Short Buy).
        
        Key Logic:
            - VWAP (Cost Basis) remains CONSTANT (FIFO/Avg Cost assumption).
            - Portion of Cost Basis is removed.
            - Realized PnL is calculated for the closed portion.
            - Cash is credited with (Collateral + PnL).
        """
        quantity = Decimal(trade.get('quantity'))
        size_left = abs(self.net_position) - quantity
        
        # 1. Calculate Realized PnL & Cash Release
        # Cost Basis of the portion being closed
        cost_basis = quantity * self.VWAP
        
        if position == 'long':
            # Long Close: We sold @ Price.
            # Cash In = Trade Value (Price * Q)
            # PnL = Trade Value - Cost Basis
            cash_release = trade_val 
            # realized_pnl = trade_val - cost_basis (implicit in NAV check)
            
        else: # short
            # Short Cover: We bought @ Price.
            # We posted 'Cost Basis' (Entry Value) as collateral.
            # Cash In = Entry Value + (Entry Value - Trade Value) = 2*Entry - Exit.
            cash_release = (Decimal(2) * cost_basis) - trade_val
            
        # 2. Update Cash
        # If I am counter_party, I placed a Limit Order.
        # If that Limit Order was to BUY (Cover Short):
        # I locked 'LimitPrice * Q' in Cash On Hold.
        # I need to release that.
        
        margin_release = 0
        if party != 'init_party': # counter_party
             margin_release = trade_val # The amount I reserved for this trade
             
        self.realize_pnl_cash_transfer(party, cash_release, margin_release)

        # 3. Update Position Stats
        if size_left > 0:
            raw_val = size_left * self.VWAP
            mkt_val = size_left * trade.get('price')
            
            # Recalculate 'profit' for the remaining portion (Mark to Market)
            self.position_val = raw_val + self.cal_profit(position, mkt_val, raw_val)
            
        else: # size_left == 0
            # _covered was only handling cash transfer and reset. 
            # We already handled cash transfer via realize_pnl_cash_transfer.
            # So just reset stats.
            self.position_val = 0
            self.VWAP = 0
            
        return 0

    def _covered_side_chg(self, trade, position, party):
        """
        Handle flip in position (e.g. Long 5 -> Short 2).
        First cover to 0, then open new position in opposite direction.
        """
        mkt_val = self._covered(trade, position)
        self.size_decrease_cash_transfer(party, mkt_val)
        # deal with remaining size that cause position change
        new_size = Decimal(trade.get('quantity')) - abs(self.net_position)
        self.position_val = new_size * trade.get('price') # traded value
        self.VWAP = trade.get('price')
        self.size_increase_cash_transfer(party, self.position_val)
        return 0

    def _neutral(self, trade_val, trade, party):
        """Opening a new position from neutral (0)."""
        self.position_val += trade_val
        self.VWAP = trade.get('price')
        self.size_increase_cash_transfer(party, trade_val)

    def _net_long(self, trade_val, trade, party):
        """Processing trade when currently Net Long."""
        if trade.get(party).get('side') == 'bid':
            self._size_increase(trade, 'long', party, trade_val)
        else: # ask
            if self.net_position >= trade.get('quantity'): # still long or neutral
                self._size_decrease(trade, 'long', party, trade_val)
            else: # net_position changed to short
                self._covered_side_chg(trade, 'long', party)

    def _net_short(self, trade_val, trade, party):
        """Processing trade when currently Net Short."""
        if trade.get(party).get('side') == 'ask':
            self._size_increase(trade, 'short', party, trade_val)
        else: # bid
            if abs(self.net_position) >= trade.get('quantity'): # still short or neutral
                self._size_decrease(trade, 'short', party, trade_val)
            else: # net_position changed to long
                self._covered_side_chg(trade, 'short', party)

    def _update_net_position(self, side, trade_quantity):
        """Calculates and updates the Scalar Net Position."""
        if self.net_position >= 0: # long or neutral
            if side == 'bid':
                #self.net_position += trade_quantity
                self.net_position = Decimal(self.net_position) + Decimal(trade_quantity)
            else:
                #self.net_position += -trade_quantity
                self.net_position = Decimal(self.net_position) - Decimal(trade_quantity)
        else: # short
            if side == 'ask':
                #self.net_position += -trade_quantity
                self.net_position = Decimal(self.net_position) - Decimal(trade_quantity)
            else:
                #self.net_position += trade_quantity
                self.net_position = Decimal(self.net_position) + Decimal(trade_quantity)
        return 0

    def process_acc(self, trade, party):
        """
        Process a trade event and update the account state.
        
        Args:
            trade (dict): Trade details (Price, Quantity, Counterparties).
            party (str): Perspective to process ('init_party' or 'counter_party').
        
        Flow:
            1. Update PnL and Cash based on existing position (Long/Short/Neutral).
            2. Update Net Position (Inventory).
            3. Recalculate NAV (Wealth).
        """
        self.num_trades += 1
        trade_val = Decimal(trade.get('quantity')) * trade.get('price')
        if self.net_position > 0: #long
            self._net_long(trade_val, trade, party)
        elif self.net_position < 0: # short
            self._net_short(trade_val, trade, party)
        else: # neutral
            self._neutral(trade_val, trade, party)
        self._update_net_position(trade.get(party).get('side'), trade.get('quantity'))
        self.cal_nav()
        return 0
