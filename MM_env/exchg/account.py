class Account(object):
    def __init__(self, cash=0, nav=0, cash_on_hold=0, position_val=0, net_position=0, net_price=0):
        self.cash = cash
        # nav is used to calculate P&L & r per t step
        self.nav = cash # net asset value = cash + equity
        self.cash_on_hold = cash_on_hold # cash deducted for placing order = cash - value of live oreder in LOB)
        self.position_val = net_position * net_price # value of net_position
        # assuming only one ticker (1 type of contract)
        self.net_position = net_position # number of contracts currently holding long (positive) or short (negative)
        self.net_price = net_price # VWAP

    def print_acc(self):
        print('cash', self.cash)
        print('cash_on_hold', self.cash_on_hold)
        print('position_val', self.position_val)
        print('nav', self.nav)
        print('net_position', self.net_position)
        return 0

    def cal_nav(self):
        return self.cash + self.cash_on_hold + self.position_val

    def cal_profit(self, position, mkt_val, raw_val):
        if position == 'long':
            return mkt_val - raw_val
        else:
            return raw_val - mkt_val

    def order_in_book_init_party(self, order_in_book):
        # if there's order_in_book for init_party (party2)
        if order_in_book != None: # there are new unfilled orders
            order_in_book_val = order_in_book.get('price') * order_in_book.get('quantity')
            self.cash -= order_in_book_val # reduce cash
            self.cash_on_hold += order_in_book_val # increase cash_on_hold

            print('order_in_book:', order_in_book)

        return 0

    def same_side(self, trade, position):
        total_size = abs(self.net_position) + (trade.get('quantity'))
        self.net_price = (abs(self.net_position) * self.net_price + trade.get('quantity') * trade.get('price')) / total_size
        raw_val = total_size * self.net_price
        mkt_val = total_size * trade.get('price')
        self.position_val = raw_val + self.cal_profit(position, mkt_val, raw_val)
        return 0

    def size_left(self, net_position, trade_size):
        if net_position >= trade_size:
            return abs(net_position) - trade_size
        else:
            return trade_size - abs(net_position)

    def covered(self, trade, position):
        size_left = self.size_left(abs(self.net_position), trade.get('quantity'))
        raw_val = size_left * self.net_price # val of long left
        mkt_val = size_left * trade.get('price')
        self.position_val = raw_val + self.cal_profit(position, mkt_val, raw_val)

        self.cash += trade.get('quantity') * trade.get('price') # portion covered goes back to cash
        return 0

    def covered_side_chg(self, trade, position):
        size_left = self.size_left(abs(self.net_position), trade.get('quantity'))

        raw_val = abs(self.net_position) * self.net_price # val of long left
        mkt_val = abs(self.net_position) * trade.get('price')
        covered_val = raw_val + self.cal_profit(position, mkt_val, raw_val)

        self.position_val = size_left * trade.get('price')
        #self.cash += abs(self.net_position) * trade.get('price') # portion covered goes back to cash
        self.cash += covered_val # portion covered goes back to cash
        return 0

    def process_acc(self, trade, party):
        trade_val = trade.get('quantity') * trade.get('price')

        if self.net_position > 0: #long
            if trade.get(party).get('side') == 'bid':
                self.same_side(trade, 'long')
            else: # ask
                if self.net_position >= trade.get('quantity'): # still long or neutral
                    self.covered(trade, 'long')
                else: # net_position changed to short
                    self.covered_side_chg(trade, 'long')
        elif self.net_position < 0: # short
            if trade.get(party).get('side') == 'ask':
                self.same_side(trade, 'short')
            else: # bid
                if abs(self.net_position) >= trade.get('quantity'): # still short or neutral
                    self.covered(trade, 'short')
                else: # net_position changed to long
                    self.covered_side_chg(trade, 'short')
        else: # neutral
            self.position_val += trade_val
            self.net_price = trade.get('price')

        if party == 'counter_party':
            self.cash_on_hold -= trade_val
        if party == 'init_party':
            self.cash -= trade_val

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
