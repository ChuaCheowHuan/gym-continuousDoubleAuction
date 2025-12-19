from decimal import Decimal

from .cash_processor import Cash_Processor
from .calculate import Calculate

from tabulate import tabulate

class Account(Calculate, Cash_Processor):
    def __init__(self, ID, cash=0):
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

    def reset_acc(self, ID, cash=0):
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
        Entire position covered, net position = 0
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
        size_left = abs(self.net_position) - Decimal(trade.get('quantity'))
        if size_left > 0:
            self.VWAP = (abs(self.net_position) * self.VWAP - trade_val) / size_left
            raw_val = size_left * self.VWAP # value acquired with VWAP
            mkt_val = size_left * trade.get('price')
            self.position_val = raw_val + self.cal_profit(position, mkt_val, raw_val)
        else: # size_left == 0
            mkt_val = self._covered(trade, position)
        self.size_decrease_cash_transfer(party, trade_val)
        return 0

    def _covered_side_chg(self, trade, position, party):
        mkt_val = self._covered(trade, position)
        self.size_decrease_cash_transfer(party, mkt_val)
        # deal with remaining size that cause position change
        new_size = Decimal(trade.get('quantity')) - abs(self.net_position)
        self.position_val = new_size * trade.get('price') # traded value
        self.VWAP = trade.get('price')
        self.size_increase_cash_transfer(party, self.position_val)
        return 0

    def _neutral(self, trade_val, trade, party):
        self.position_val += trade_val
        self.VWAP = trade.get('price')
        self.size_increase_cash_transfer(party, trade_val)

    def _net_long(self, trade_val, trade, party):
        if trade.get(party).get('side') == 'bid':
            self._size_increase(trade, 'long', party, trade_val)
        else: # ask
            if self.net_position >= trade.get('quantity'): # still long or neutral
                self._size_decrease(trade, 'long', party, trade_val)
            else: # net_position changed to short
                self._covered_side_chg(trade, 'long', party)

    def _net_short(self, trade_val, trade, party):
        if trade.get(party).get('side') == 'ask':
            self._size_increase(trade, 'short', party, trade_val)
        else: # bid
            if abs(self.net_position) >= trade.get('quantity'): # still short or neutral
                self._size_decrease(trade, 'short', party, trade_val)
            else: # net_position changed to long
                self._covered_side_chg(trade, 'short', party)

    def _update_net_position(self, side, trade_quantity):
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
        self.num_trades += 1
        trade_val = Decimal(trade.get('quantity')) * trade.get('price')
        if self.net_position > 0: #long
            self._net_long(trade_val, trade, party)
        elif self.net_position < 0: # short
            self._net_short(trade_val, trade, party)
        else: # neutral
            self._neutral(trade_val, trade, party)
        self._update_net_position(trade.get(party).get('side'), trade.get('quantity'))
        return 0
