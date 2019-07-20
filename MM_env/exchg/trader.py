import random
import numpy as np

class Trader(object):
    def __init__(self, ID, cash=0, nav=0, cash_on_hold=0, position_val=0, live_order=[], trade_rec=[], net_position=0, net_price=0):
        self.ID = ID # trader unique ID
        self.cash = cash

        # nav is used to calculate P&L & r per t step
        self.nav = cash # net asset value = cash + equity

        self.cash_on_hold = cash_on_hold # cash deducted for placing order = cash - value of live oreder in LOB)
        self.position_val = position_val # value of net_position

        self.live_order = live_order # live order in LOB
        self.trade_rec = trade_rec # record of trades executed

        # assuming only one ticker (1 type of contract)
        self.net_position = net_position # number of contracts currently holding long (positive) or short (negative)
        self.net_price = net_price # net_price paid for net_position (VWAP)

    def cal_nav(self):
        return self.cash + self.cash_on_hold + self.position_val

    # order_size is size of order currently executed, positive for long, negative for short
    def cal_net_position(self, net_position, order_size):
        return net_position + order_size
    """
    # decides if net_price remain unchanged or replace net_price with new order_price
    # order is the current order being filled
    def cal_net_price(self, net_position, net_price, order_size, order_price):
        if net_position == 0:
            net_price = order_price
        # use VWAP for net_price
        elif net_position > 0 and order_size > 0:
            net_price = ((net_position * net_price) + (order_size * order_price)) / (net_position + order_size)
        elif net_position < 0 and order_size < 0:
            net_price = ((net_position * net_price) + (order_size * order_price)) / (net_position + order_size)
        elif net_position > 0 and order_size < 0: # net is long, new order is short
            if abs(net_position) > abs(order_size): # more long than short
                net_price = net_price
            elif abs(net_position) < abs(order_size): # more short than long
                net_price = order_price
            else: # even long & short, cancel out
                net_price = 0
        elif net_position < 0 and order_size > 0:
            if abs(net_position) > abs(order_size): # more long than short
                net_price = net_price
            elif abs(net_position) < abs(order_size): # more short than long
                net_price = order_price
            else: # even long & short, cancel out
                net_price = 0
        else:
            net_price = 0

        return net_price
    """
    # decides if net_price remain unchanged or replace net_price with new order_price
    # order is the current order being filled
    def cal_net_price(self, net_position, net_price, order_size, order_price):
        if net_position == 0:
            net_price = order_price
        # use VWAP for net_price
        elif (net_position > 0 and order_size > 0) or (net_position < 0 and order_size < 0):
            net_price = ((net_position * net_price) + (order_size * order_price)) / (net_position + order_size)
        elif (net_position > 0 and order_size < 0) or (net_position < 0 and order_size > 0): # net is long, new order is short
            if abs(net_position) > abs(order_size): # more long than short
                net_price = net_price
            elif abs(net_position) < abs(order_size): # more short than long
                net_price = order_price
            else: # even long & short, cancel out
                net_price = 0
        else:
            net_price = 0

        return net_price

    # negative profit is loss
    def cal_profit(self, net_position, net_price, last_price):
        return (last_price - net_price) * net_position

    # position_val @ current t step
    def cal_position_val(self, net_position, net_price, profit):
        return abs(net_position * net_price) + profit

    # chk if enough cash to create order
    # size is order size
    # price is order price
    def order_approved(self, cash, size, price):
        if self.cash >= size * price:        
            return True
        else:
            return False

    def create_order(self, type, side, size, price):
        if type == 'market':
            order = {'type': 'market',
                     'side': side,
                     'quantity': size,
                     'trade_id': self.ID}
        elif type == 'limit':
            order = {'type': 'limit',
                     'side': side,
                     'quantity': size,
                     'price': price,
                     'trade_id': self.ID}
        else:
            order = {}

        return order

    # pass action to step
    def select_random_action(self):
        #type = np.random.randint(0, 1, size=1) # type, draw 1 int, 0(market) to 1(limit)
        type = random.choice(['market','limit'])
        #type = random.choice(['limit'])
        #side = np.random.randint(-1, 1, size=1) # side, draw 1 int, -1(ask), 0(None), 1(bid)
        side = random.choice(['bid',None,'ask'])
        size = random.randrange(1, 100, 100) # size in 100s from 0(min) to 1000(max)
        price = random.randrange(1, 10, 1) # price from 1(min) to 100(max)

        action = {"type": type,
                  "side": side,
                  "size": size,
                  "price": price}

        return action


if __name__ == "__main__":

    ID = 1
    nav = 10000
    cash = 10000
    cash_on_hold = 0
    position_val = 0
    live_order = []
    trade_rec = []
    net_position = 0
    net_price = 0

    t1 = Trader(ID, nav, cash, cash_on_hold, position_val, live_order, trade_rec, net_position, net_price)
    print(t1)

    t1.nav = t1.cal_nav(cash, position_val)
    print(t1.nav)

    order_size = 100
    order_size = -100
    t1.net_position = t1.cal_net_position(net_position, order_size)
    print(t1.net_position)

    net_position = 0
    net_price = 0
    order_price = 3
    order_size = 200
    t1.net_price = t1.cal_net_price(net_position, net_price, order_size, order_price)
    print(t1.net_price)
    net_position = 100
    net_price = 3
    order_price = 1
    order_size = -200
    t1.net_price = t1.cal_net_price(net_position, net_price, order_size, order_price)
    print(t1.net_price)
