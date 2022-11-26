import numpy as np

from decimal import Decimal
from tabulate import tabulate

class Account():
    def __init__(self, ID, cash=0):
        # Agent or trader ID.
        self.ID = ID

        # Initial cash (capital).
        self.init_cash = Decimal(cash)
        # Current cash.
        self.cash = self.init_cash

        # Cash deducted for placing orders (order costs).
        self.order_costs = Decimal(cash)
        
        # Long and short positions.
        self.qty_long = 0
        self.qty_short = 0

        # Contains orders in LOB.
        self.LOB_recs = []
        # Contains trading records.
        self.trade_recs = []

        # nav = cash - cash_on_hold + (long_pos * last_price) + (short_pos * last_price)
        self.nav = self.init_cash
        self.prev_nav = self.nav

        # Length of trade_recs.
        self.num_trades = 0

        # reward = nav_chg or reward = nav_chg / num_trades.
        self.reward = Decimal(cash)

    def _qty(self, recs):
        """
        Compute quantity long, short.
        """
        qty_long = 0
        qty_short = 0
        for rec in recs:
            qty = rec['quantity']
            if rec['side'] == 'bid':
                qty_long += 1
            else:
                qty_short += 1
        
        return qty_long, qty_short

    def _costs(self, recs):
        """
        Compute total costs in recs.
        """
        long_val = 0
        short_val = 0
        for rec in recs:
            val = rec['price'] * Decimal(rec['quantity'])
            if rec['side'] == 'bid':
                long_val += val
            else:
                short_val += val

        return long_val, short_val

    def _update_order_costs(self, recs):      
        long_val, short_val = self._costs(recs)
        self.order_costs = Decimal(long_val + short_val)

    def _update_cash(self, price):
        self.cash = self.init_cash - self.order_costs - (self.qty_long * price) + (self.qty_short * price)

    def _update_nav(self, price):
        self.prev_nav = self.nav
        self.nav = self.cash + self.order_costs - (self.qty_long * price) + (self.qty_short * price)

    def update_acc(self, price):
        price = Decimal(price)
        
        self._update_order_costs(self.LOB_recs)

        self.qty_long, self.qty_short = self._qty(self.trade_recs)
        self.qty_long = Decimal(self.qty_long)
        self.qty_short = Decimal(self.qty_short)

        self._update_cash(price)
        self._update_nav(price)
        self.num_trades = len(self.trade_recs)

    def reset_acc(self, cash=0):
        self.cash = self.init_cash
        self.order_costs = Decimal(0) 
        self.qty_long = 0
        self.qty_short = 0
        self.prev_nav = self.nav
        self.nav = self.init_cash
        self.num_trades = 0
        self.reward = Decimal(0)
        self.LOB_recs = []
        self.trade_recs = []

    def print_acc(self, msg):
        acc = {}
        acc['ID'] = [self.ID]
        acc['cash'] = [self.cash]
        acc['order_costs'] = [self.order_costs]
        acc['prev_nav'] = [self.prev_nav]
        acc['nav'] = [self.nav]
        acc['num_trades'] = [self.num_trades]
        acc['reward'] = [self.reward]
        # acc['trade_recs'] = [self.trade_recs]
        # acc['LOB_recs'] = [self.LOB_recs]

        print(msg, tabulate(acc, headers="keys"))

        return 0
