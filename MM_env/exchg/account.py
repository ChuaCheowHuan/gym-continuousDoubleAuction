class Account(object):
    def __init__(self, cash=0, nav=0, cash_on_hold=0, position_val=0, net_position=0):
        self.cash = cash
        # nav is used to calculate P&L & r per t step
        self.nav = cash # net asset value = cash + equity
        self.cash_on_hold = cash_on_hold # cash deducted for placing order = cash - value of live oreder in LOB)
        self.position_val = position_val # value of net_position
        # assuming only one ticker (1 type of contract)
        self.net_position = net_position # number of contracts currently holding long (positive) or short (negative)

    def cal_nav(self):
        return self.cash + self.cash_on_hold + self.position_val

    def order_in_book_init_party(self, order_in_book):
        # if there's order_in_book for init_party (party2)
        if order_in_book != None: # there are new unfilled orders
            order_in_book_val = order_in_book.get('price') * order_in_book.get('quantity')
            self.cash -= order_in_book_val # reduce cash
            self.cash_on_hold += order_in_book_val # increase cash_on_hold
        return 0

    # position different from trade side, eg: long & ask
    def position_diff_side(self, trade):
        if abs(self.net_position) >= trade.get('quantity'): # still same net position or neutral
            self.cash += trade.get('quantity') * trade.get('price') # entire position covered goes back to cash
            self.position_val = (abs(self.net_position) - trade.get('quantity')) * trade.get('price')
        else: # net position changed after the trade
            self.cash += abs(self.net_position) * trade.get('price') # portion covered goes back to cash
            self.position_val = (trade.get('quantity') - abs(self.net_position)) * trade.get('price') # remaining trade_val goes to position_val
        return 0

    # update cash, cash_on_hold, position_val for init_party (party2)
    def process_init_party(self, trade):
        prev_position_val = self.position_val
        prev_position_price = prev_position_val / self.net_position
        curr_position_val = abs(self.net_position) * trade.get('price')
        trade_val = trade.get('quantity') * trade.get('price')
        # if price decrease, diff is negative
        position_val_diff = curr_position_val - prev_position_val
        short_position_val = prev_position_val - position_val_diff

        if self.net_position >= 0: #long
            if trade.get(party).get('side') == 'bid':
                curr_position_val = abs(self.net_position) * trade.get('price')
                self.position_val = curr_position_val + trade_val
                self.cash -= trade_val
            else: # ask
                if net_position >= trade_size: # still long or neutral
                    # val of long left
                    self.position_val = (self.net_position - trade.get('quantity')) * trade.get('price')
                    self.cash += trade_val # portion covered goes back to cash
                else: # net_position changed
                    # val of new short left
                    self.position_val = (trade.get('quantity') - self.net_position) * trade.get('price')
                    self.cash += self.net_position * trade.get('price') # entire position covered goes back to cash
        elif self.net_position < 0: # short
            if side == 'ask':
                position_val = short_position_val + trade_val
            else: # bid
                if abs(net_position) >= trade_size: # still short or neutral
                    left_over_short_prev_val = (abs(self.net_position) - trade.get('quantity')) * prev_position_price
                    left_over_short_curr_val = (abs(self.net_position) - trade.get('quantity')) * trade.get('price')
                    left_over_short_val_diff = left_over_short_curr_val - left_over_short_prev_val
                    left_over_short_val = left_over_short_prev_val - left_over_short_val_diff
                    self.position_val = left_over_short_val
                    cash += trade_val #trade_val goes back to cash
                else: # net_position changed
                    short_prev_val = abs(self.net_position) * prev_position_price
                    short_curr_val = abs(self.net_position) * trade.get('price')
                    short_val_diff = short_curr_val - short_prev_val
                    short_val = short_prev_val - short_val_diff
                    cash += short_val # short_val goes back to cash
                    left_over_long_val = (trade.get('quantity' - abs(self.net_position))) * trade.get('price')
                    self.position_val = left_over_long_val
        else: # neutral
            self.cash -= trade_val
            self.position_val += trade_val

        self.update_net_position(trade.get('init_party').get('side'), trade.get('quantity'))
        return 0

    # update cash, cash_on_hold, position_val for counter_party (party1)
    def process_counter_party(self, trade, party, side):
        if trade.get(party).get('side') == side:

            self.position_val += trade.get('quantity') * trade.get('price') # increase position_val

        else:
            self.position_diff_side(trade)

        self.cash_on_hold -= trade.get('price') * trade.get('quantity') # reduce cash_on_hold
        return 0

    def counter_party(self, agents, trade, trade_val):
        for counter_party in agents: # search for counter_party
            if counter_party.ID == trade.get('counter_party').get('ID'):
                if counter_party.acc.net_position > 0: # long
                    counter_party.acc.process_counter_party(trade, 'counter_party', 'bid')
                elif counter_party.acc.net_position < 0: # short
                    counter_party.acc.process_counter_party(trade, 'counter_party', 'ask')
                else: # neutral
                    counter_party.acc.cash_on_hold -= trade_val
                    counter_party.acc.position_val += trade_val
                counter_party.acc.update_net_position(trade.get('counter_party').get('side'), trade.get('quantity'))
                break
        return 0

    def init_party(self, trade, order_in_book, trade_val):
        if self.net_position > 0: # long
            self.process_init_party(trade, order_in_book, 'init_party', 'bid')
        elif self.net_position < 0: # short
            self.process_init_party(trade, order_in_book, 'init_party', 'ask')
        else: # neutral
            self.cash -= trade_val
            self.position_val += trade_val
        self.update_net_position(trade.get('init_party').get('side'), trade.get('quantity'))
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
