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

    def neutral_cash_transfer(self, party, trade_val):
        if party == 'counter_party':
            self.cash_on_hold -= trade_val
        if party == 'init_party':
            self.cash -= trade_val

    def size_increase(self, trade, position, party, trade_val):
        total_size = abs(self.net_position) + (trade.get('quantity'))
        # VWAP
        self.VWAP = (abs(self.net_position) * self.VWAP + trade_val) / total_size
        raw_val = total_size * self.VWAP # value acquired with VWAP
        mkt_val = total_size * trade.get('price')
        self.position_val = raw_val + self.cal_profit(position, mkt_val, raw_val)
        self.neutral_cash_transfer(party, trade_val)
        return 0

    def size_left(self, net_position, trade_size):
        if abs(net_position) >= trade_size:
            return abs(net_position) - trade_size
        else:
            return trade_size - abs(net_position)

    # ********** BUG (works for size_left > 0 only, fails if size_left == 0), counter_party cash_on_hold not deducted issue **********
    def size_decrease_0(self, trade, position, party, trade_val):
        size_left = abs(self.net_position) - (trade.get('quantity'))
        #  VWAP = (on_false, on_true)[condition]
        self.VWAP = (0, (abs(self.net_position) * self.VWAP - trade_val) / size_left)[size_left > 0]
        #self.VWAP = (abs(self.net_position) * self.VWAP - trade_val) / size_left
        raw_val = size_left * self.VWAP # value acquired with VWAP
        mkt_val = size_left * trade.get('price')
        self.position_val = raw_val + self.cal_profit(position, mkt_val, raw_val)
        self.cash += trade_val # portion covered goes back to cash
        return 0
    # ********** NEED TESTING **********
    def size_decrease(self, trade, position, party, trade_val):
        size_left = abs(self.net_position) - (trade.get('quantity'))
        if size_left > 0:
            self.VWAP = (abs(self.net_position) * self.VWAP - trade_val) / size_left
            raw_val = size_left * self.VWAP # value acquired with VWAP
            mkt_val = size_left * trade.get('price')
            self.position_val = raw_val + self.cal_profit(position, mkt_val, raw_val)
            self.cash += trade_val # portion covered goes back to cash
        else: # size_left == 0
            self.position_val = 0
            self.VWAP = 0
            self.cash += trade_val

        if party == 'init_party':
            #self.cash_on_hold -= trade_val
            self.cash += trade_val # portion covered goes back to cash
        if party == 'counter_party':
            self.cash_on_hold -= trade_val
            #self.cash += trade_val # portion covered goes back to cash

        return 0

    # ********** NEED TESTING **********
    def covered_side_chg(self, trade, position, party, trade_val):
        size_left = self.size_left(abs(self.net_position), trade.get('quantity'))
        raw_val = abs(self.net_position) * self.VWAP # val of long left
        mkt_val = abs(self.net_position) * trade.get('price')
        covered_val = raw_val + self.cal_profit(position, mkt_val, raw_val)
        self.VWAP = trade.get('price')
        self.position_val = size_left * trade.get('price')
        #self.cash += abs(self.net_position) * trade.get('price') # portion covered goes back to cash
        self.cash += covered_val # portion covered goes back to cash
        self.neutral_cash_transfer(party, trade_val)
        return 0

    def neutral(self, trade_val, trade, party):
        self.position_val += trade_val
        self.VWAP = trade.get('price')
        self.neutral_cash_transfer(party, trade_val)

    def process_acc(self, trade, party):
        trade_val = trade.get('quantity') * trade.get('price')

        if self.net_position > 0: #long
            if trade.get(party).get('side') == 'bid':
                self.size_increase(trade, 'long', party, trade_val)
            else: # ask
                if self.net_position >= trade.get('quantity'): # still long or neutral
                    self.size_decrease(trade, 'long', party, trade_val)
                else: # net_position changed to short
                    self.covered_side_chg(trade, 'long', party, trade_val)
        elif self.net_position < 0: # short
            if trade.get(party).get('side') == 'ask':
                self.size_increase(trade, 'short', party, trade_val)
            else: # bid
                if abs(self.net_position) >= trade.get('quantity'): # still short or neutral
                    self.size_decrease(trade, 'short', party, trade_val)
                else: # net_position changed to long
                    self.covered_side_chg(trade, 'short', party, trade_val)
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
