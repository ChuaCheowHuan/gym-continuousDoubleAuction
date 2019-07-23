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

    def order_in_book_init_party(self, order_in_book):
        # if there's order_in_book for init_party (party2)
        if order_in_book != None: # there are new unfilled orders
            order_in_book_val = order_in_book.get('price') * order_in_book.get('quantity')
            self.cash -= order_in_book_val # reduce cash
            self.cash_on_hold += order_in_book_val # increase cash_on_hold

            print('order_in_book:', order_in_book)

        return 0

    def process_acc(self, trade, party):
        prev_position_val = self.position_val
        curr_position_val = abs(self.net_position) * trade.get('price')
        trade_val = trade.get('quantity') * trade.get('price')

        if self.net_position > 0: #long
            if trade.get(party).get('side') == 'bid':                
                total_size = abs(self.net_position) + (trade.get('quantity'))
                self.net_price = (abs(self.net_position) * self.net_price + trade.get('quantity') * trade.get('price')) / total_size
                curr_position_val = total_size * self.net_price
                curr_mkt_val = total_size * trade.get('price')
                val_diff = curr_mkt_val - curr_position_val# profit
                print('val_diff:', val_diff)
                self.position_val = curr_position_val + val_diff

            else: # ask
                if self.net_position >= trade.get('quantity'): # still long or neutral
                    # val of long left
                    self.position_val = (self.net_position - trade.get('quantity')) * trade.get('price')
                    self.cash += trade_val # portion covered goes back to cash
                else: # net_position changed
                    # val of new short left
                    self.position_val = (trade.get('quantity') - self.net_position) * trade.get('price')
                    self.cash += self.net_position * trade.get('price') # entire position covered goes back to cash
        elif self.net_position < 0: # short
            if trade.get(party).get('side') == 'ask':
                total_size = abs(self.net_position) + (trade.get('quantity'))
                self.net_price = (abs(self.net_position) * self.net_price + trade.get('quantity') * trade.get('price')) / total_size
                curr_position_val = total_size * self.net_price
                curr_mkt_val = total_size * trade.get('price')
                val_diff = curr_position_val - curr_mkt_val # profit
                print('val_diff:', val_diff)
                self.position_val = curr_position_val + val_diff
            else: # bid
                prev_position_price = prev_position_val / abs(self.net_position)
                if abs(self.net_position) >= trade.get('quantity'): # still short or neutral
                    left_over_short = (abs(self.net_position) - trade.get('quantity'))
                    left_over_short_prev_val = left_over_short * prev_position_price
                    left_over_short_curr_val = left_over_short * trade.get('price')
                    left_over_short_val_diff = left_over_short_curr_val - left_over_short_prev_val
                    left_over_short_val = left_over_short_prev_val - left_over_short_val_diff
                    self.position_val = left_over_short_val
                    self.cash += trade_val #trade_val goes back to cash
                else: # net_position changed
                    short_prev_val = abs(self.net_position) * prev_position_price
                    short_curr_val = abs(self.net_position) * trade.get('price')
                    short_val_diff = short_curr_val - short_prev_val
                    short_val = short_prev_val - short_val_diff
                    self.cash += short_val # short_val goes back to cash
                    left_over_long_val = (trade.get('quantity' - abs(self.net_position))) * trade.get('price')
                    self.position_val = left_over_long_val
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
