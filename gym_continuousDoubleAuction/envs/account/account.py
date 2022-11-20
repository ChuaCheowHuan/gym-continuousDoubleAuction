import numpy as np

from decimal import Decimal
from tabulate import tabulate

class Account():
    def __init__(self, ID, cash=0):
        self.ID = ID
        # Cash (capital)
        self.init_cash = Decimal(cash)
        self.cash = self.init_cash
        # Cash deducted for placing order.
        self.cash_on_hold = Decimal(0)
        # Current position, long (positive) or short (negative).
        self.net_pos = 0 
        self.prev_pos = 0
        self.pos_val = Decimal(0) 
        self.trade_val = Decimal(0) 
        self.profit = Decimal(0) 

        # [
        #   {'step':0, 'tick':0:, 'type':'bid', 'size':10, 'price':5}, 
        #   {'step':0, 'tick':3:, 'type':'bid', 'size':2, 'price':7},
        #   {'step':3, 'tick':2:, 'type':'ask', 'size':6, 'price':4},
        # ]
        self.trade_recs = []
        # [
        #   {'step':0, 'tick':0:, 'size':10, 'price':5, 'order_ID':1}, 
        #   {'step':0, 'tick':3:, 'size':-2, 'price':7, 'order_ID':2}, 
        #   {'step':3, 'tick':2:, 'size':-6, 'price':4, 'order_ID':5}, 
        # ]
        self.LOB_recs = []

        # nav = cash - cash_on_hold + (net_pos * last_price)
        self.nav =self.init_cash
        self.prev_nav = self.nav
        # Length of trade_recs.
        self.num_trades = 0
        # reward = nav or reward = nav / num_trades.
        self.reward = 0

    def _cal_val(self):
        """
        Compute total trade value that belongs to the trader after a new trade occured.
        """
        vals = []
        for rec in self.trade_recs:
            val = rec['price'] * Decimal(rec['quantity'])
            # Trade value is negative when long as in goods are recieved & cash paid out.
            if rec['side'] == 'bid':
                val = val * -1

            vals.append(val)
        
        return np.sum(vals)

    def _cal_costs(self):
        """
        Compute total costs in LOB that belong to the trader after a new trade occured.
        """
        costs = []
        for rec in self.LOB_recs:
            # Cost is always positive regardless of side.
            cost = rec['price'] * Decimal(rec['quantity'])
            # if rec['side'] == 'bid':
            #     cost = cost * -1
            costs.append(cost)

        return np.sum(costs)

    def _cal_net_pos(self):
        """
        Compute net position that belongs to the trader.
        """
        qtys = []
        for rec in self.trade_recs:
            qty = rec['quantity']
            # Trade value is negative when long as in goods are recieved & cash paid out.
            if rec['side'] == 'ask':
                qty *= -1

            qtys.append(int(qty))
        
        return np.sum(qtys)

    def _update_cash(self):
        self.cash = self.init_cash - Decimal(self._update_cash_on_hold()) + self._update_trade_val()

    def _update_cash_on_hold(self):      
        self.cash_on_hold = Decimal(self._cal_costs())

        return self.cash_on_hold

    def _update_trade_val(self):
        self.trade_val = Decimal(self._cal_val())

        return self.trade_val

    def _update_net_pos(self):
        self.prev_pos = self.net_pos
        self.net_pos = self._cal_net_pos()

    def _update_pos_val(self, price):
        # self.pos_val = self.net_pos * price
        self.pos_val = Decimal(float(self.net_pos)) * price

        return self.pos_val

    def _update_profit(self, price):
        print(price)

        trade_val = np.abs(self.trade_val)
        pos_val = np.abs(self._update_pos_val(price))
        self.profit = pos_val - trade_val
        if self.net_pos < 0:
            self.profit = self.profit * -1

    def _update_nav(self, price):
        self.prev_nav = self.nav

        self._update_profit(price)

        self.nav = self.cash + self.cash_on_hold - self.trade_val + self.profit

    def update_acc(self, price):
        self._update_cash()
        self._update_net_pos()
        self._update_nav(price)
        self.num_trades = len(self.trade_recs)

        # print(self.ID, self.cash, self.cash_on_hold, self.pos_val, self.net_pos, self.prev_nav, self.nav)

    def reset_acc(self, cash=0):
        self.cash = self.init_cash
        self.cash_on_hold = Decimal(0) 
        self.net_pos = 0 
        self.prev_pos = 0
        self.pos_val = Decimal(0) 
        self.trade_val = Decimal(0) 
        self.profit = Decimal(0) 
        self.nav = self.init_cash
        self.prev_nav = self.nav
        self.num_trades = 0
        self.reward = 0

    def print_acc(self, msg):
        acc = {}
        acc['ID'] = [self.ID]
        acc['cash'] = [self.cash]
        acc['cash_on_hold'] = [self.cash_on_hold]
        acc['net_pos'] = [self.net_pos]
        acc['pos_val'] = [self.pos_val]
        acc['trade_val'] = [self.trade_val]
        acc['prev_nav'] = [self.prev_nav]
        acc['nav'] = [self.nav]
        acc['num_trades'] = [self.num_trades]
        acc['reward'] = [self.reward]
        # acc['trade_recs'] = [self.trade_recs]
        # acc['LOB_recs'] = [self.LOB_recs]

        print(msg, tabulate(acc, headers="keys"))

        return 0

    # def print_both_accs(self, msg, curr_step_trade_ID, counter_party, init_party):
    #     """
    #     Print accounts of both counter_party & init_party.
    #     """
    #     acc = {}
    #     acc['seq_Trade_ID'] = [curr_step_trade_ID, curr_step_trade_ID]
    #     acc['party'] = ["counter", "init"]
    #     acc['ID'] = [counter_party.acc.ID, init_party.acc.ID]
    #     acc['cash'] = [counter_party.acc.cash, init_party.acc.cash]
    #     acc['cash_on_hold'] = [counter_party.acc.cash_on_hold, init_party.acc.cash_on_hold]
    #     acc['net_position'] = [counter_party.acc.net_pos, init_party.acc.net_pos]
    #     acc['position_val'] = [counter_party.acc.pos_val, init_party.acc.pos_val]
    #     acc['prev_nav'] = [counter_party.acc.prev_nav, init_party.acc.prev_nav]
    #     acc['nav'] = [counter_party.acc.nav, init_party.acc.nav]
    #     acc['num_trades'] = [counter_party.acc.num_trades, init_party.acc.num_trades]

    #     print(msg, tabulate(acc, headers="keys"))

    #     return 0
