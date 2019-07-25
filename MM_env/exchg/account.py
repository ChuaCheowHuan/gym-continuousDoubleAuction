class Account(object):
    def __init__(self, ID, cash=0, nav=0, cash_on_hold=0, position_val=0, net_position=0, VWAP=0):
        self.ID = ID
        self.cash = cash
        # nav is used to calculate P&L & r per t step
        self.nav = cash # net asset value = cash + equity
        self.cash_on_hold = cash_on_hold # cash deducted for placing order = cash - value of live oreder in LOB)
        self.position_val = net_position * VWAP # value of net_position
        # assuming only one ticker (1 type of contract)
        self.net_position = net_position # number of contracts currently holding long (positive) or short (negative)
        self.VWAP = VWAP # VWAP
        self.profit = 0

    def print_acc(self):
        print('ID:', self.ID)
        print('cash:', self.cash)
        print('cash_on_hold:', self.cash_on_hold)
        print('position_val:', self.position_val)
        print('nav:', self.nav)
        print('net_position:', self.net_position)
        print('VWAP:', self.VWAP)
        print('profit:', self.profit)
        return 0

    def cal_nav(self):
        return self.cash + self.cash_on_hold + self.position_val

    def cal_profit(self, position, mkt_val, raw_val):
        if position == 'long':
            self.profit = mkt_val - raw_val
        else:
            self.profit = raw_val - mkt_val
        return self.profit

    def order_in_book_init_party(self, order_in_book):
        # if there's order_in_book for init_party (party2)
        if order_in_book != None: # there are new unfilled orders
            order_in_book_val = order_in_book.get('price') * order_in_book.get('quantity')
            self.cash -= order_in_book_val # reduce cash
            self.cash_on_hold += order_in_book_val # increase cash_on_hold

            print('order_in_book:', order_in_book)

        return 0

    def size_increase_cash_transfer(self, party, trade_val):
        if party == 'init_party':
            self.cash -= trade_val # initial order cash reduction
        else: #counter_party
            self.cash_on_hold -= trade_val # reduce cash_on_hold for initial order cash_on_hold increase

    def size_decrease_cash_transfer(self, party, trade_val):
        if party == 'init_party':
            self.cash += trade_val # portion covered goes back to cash
        else: #counter_party
            self.cash += trade_val # increase cash for initial order cash reduction
            self.cash_on_hold -= trade_val # reduce cash_on_hold for initial order cash_on_hold increase
            self.cash += trade_val # portion covered goes back to cash

    def size_zero_cash_transfer(self, trade_val):
        # add position_val back to cash minus trade_val, trade_val is handled in size_decrease_cash_transfer
        self.cash += self.position_val - trade_val
        return 0

    def size_increase(self, trade, position, party, trade_val):
        total_size = abs(self.net_position) + (trade.get('quantity'))
        # VWAP
        self.VWAP = (abs(self.net_position) * self.VWAP + trade_val) / total_size
        raw_val = total_size * self.VWAP # value acquired with VWAP
        mkt_val = total_size * trade.get('price')
        self.position_val = raw_val + self.cal_profit(position, mkt_val, raw_val)
        self.size_increase_cash_transfer(party, trade_val)
        return 0

    def size_left(self, net_position, trade_size):
        if abs(net_position) >= trade_size:
            return abs(net_position) - trade_size
        else:
            return trade_size - abs(net_position)

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
        self.nav = self.cal_nav()
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
