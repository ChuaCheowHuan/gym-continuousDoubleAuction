from .cash_processor import Cash_Processor

class Account(Cash_Processor):
    def __init__(self, ID, cash=0):
        self.ID = ID
        self.cash = cash
        # nav is used to calculate P&L & r per t step
        self.cash_on_hold = 0 # cash deducted for placing order = cash - value of live order in LOB
        self.position_val = 0 # value of net_position
        # nav is used to calculate P&L & r per t step
        self.init_nav = cash # starting nav @t = 0
        self.nav = cash # nav @t (nav @ end of a single t-step)
        self.prev_nav = cash # nav @t-1
        # assuming only one ticker (1 type of contract)
        self.net_position = 0 # number of contracts currently holding long (positive) or short (negative)
        self.VWAP = 0 # VWAP
        self.profit = 0 # profit @ each trade(tick) within a single t step
        self.total_profit = 0 # profit at the end of a single t-step

    def print_acc(self):
        print('ID:', self.ID)
        print('cash:', self.cash)
        print('cash_on_hold:', self.cash_on_hold)
        print('position_val:', self.position_val)
        print('prev_nav:', self.prev_nav)
        print('nav:', self.nav)
        print('net_position:', self.net_position)
        print('VWAP:', self.VWAP)
        print('profit from trade(tick):', self.profit)
        print('total_profit:', self.total_profit)
        return 0

    def cal_nav(self):
        self.nav =  self.cash + self.cash_on_hold + self.position_val
        return self.nav

    def cal_total_profit(self):
        self.total_profit = self.nav - self.init_nav
        return self.total_profit

    def cal_profit(self, position, mkt_val, raw_val):
        if position == 'long':
            self.profit = mkt_val - raw_val
        else:
            self.profit = raw_val - mkt_val
        return self.profit

    def size_increase(self, trade, position, party, trade_val):
        total_size = abs(self.net_position) + (trade.get('quantity'))
        # VWAP
        self.VWAP = (abs(self.net_position) * self.VWAP + trade_val) / total_size
        raw_val = total_size * self.VWAP # value acquired with VWAP
        mkt_val = total_size * trade.get('price')
        self.position_val = raw_val + self.cal_profit(position, mkt_val, raw_val)
        self.size_increase_cash_transfer(party, trade_val)
        return 0

    # entire position covered, net position = 0
    def covered(self, trade, position):
        raw_val = abs(self.net_position) * self.VWAP # value acquired with VWAP
        mkt_val = abs(self.net_position) * trade.get('price')
        self.position_val = raw_val + self.cal_profit(position, mkt_val, raw_val)
        self.size_zero_cash_transfer(mkt_val)
        # reset to 0
        self.position_val = 0
        self.VWAP = 0
        return mkt_val

    def size_decrease(self, trade, position, party, trade_val):
        size_left = abs(self.net_position) - (trade.get('quantity'))
        if size_left > 0:
            self.VWAP = (abs(self.net_position) * self.VWAP - trade_val) / size_left
            raw_val = size_left * self.VWAP # value acquired with VWAP
            mkt_val = size_left * trade.get('price')
            self.position_val = raw_val + self.cal_profit(position, mkt_val, raw_val)
        else: # size_left == 0
            mkt_val = self.covered(trade, position)
        self.size_decrease_cash_transfer(party, trade_val)
        return 0

    def covered_side_chg(self, trade, position, party):
        mkt_val = self.covered(trade, position)
        self.size_decrease_cash_transfer(party, mkt_val)
        # deal with remaining size that cause position change
        new_size = trade.get('quantity') - abs(self.net_position)
        self.position_val = new_size * trade.get('price') # traded value
        self.VWAP = trade.get('price')
        self.size_increase_cash_transfer(party, self.position_val)
        return 0

    def neutral(self, trade_val, trade, party):
        self.position_val += trade_val
        self.VWAP = trade.get('price')
        self.size_increase_cash_transfer(party, trade_val)

    def process_acc(self, trade, party):
        trade_val = trade.get('quantity') * trade.get('price')
        if self.net_position > 0: #long
            if trade.get(party).get('side') == 'bid':
                self.size_increase(trade, 'long', party, trade_val)
            else: # ask
                if self.net_position >= trade.get('quantity'): # still long or neutral
                    self.size_decrease(trade, 'long', party, trade_val)
                else: # net_position changed to short
                    self.covered_side_chg(trade, 'long', party)
        elif self.net_position < 0: # short
            if trade.get(party).get('side') == 'ask':
                self.size_increase(trade, 'short', party, trade_val)
            else: # bid
                if abs(self.net_position) >= trade.get('quantity'): # still short or neutral
                    self.size_decrease(trade, 'short', party, trade_val)
                else: # net_position changed to long
                    self.covered_side_chg(trade, 'short', party)
        else: # neutral
            self.neutral(trade_val, trade, party)
        self.update_net_position(trade.get(party).get('side'), trade.get('quantity'))
        #self.cal_nav()
        #self.cal_total_profit()
        return 0

    def update_net_position(self, side, trade_quantity):
        if self.net_position >= 0: # long or neutral
            if side == 'bid':
                self.net_position += trade_quantity
            else:
                self.net_position += -trade_quantity
        else: # short
            if side == 'ask':
                self.net_position += -trade_quantity
            else:
                self.net_position += trade_quantity
        return 0
