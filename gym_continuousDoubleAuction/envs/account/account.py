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

        # nav at the tick lvl with an env step.
        self.nav = self.init_cash
        self.prev_nav = self.nav

        # nav (step lvl) after an env step.
        self.step_nav = self.init_cash
        self.prev_step_nav = self.step_nav

        # Length of trade_recs.
        self.num_trades = 0

        # reward = nav_chg or reward = nav_chg / num_trades.
        # self.reward = Decimal(cash)
        self.reward = Decimal(0)

        self.order_costs = Decimal(0)

        self.inv_costs_long = Decimal(0)
        self.inv_costs_short = Decimal(0) 
        self.inv_costs = Decimal(0) 

        self.inv_val_chg_long = Decimal(0) 
        self.inv_val_chg_short = Decimal(0) 
        self.inv_val_chg = Decimal(0) 

    # REVISIT: compute qty not number of recs.
    def _qty(self, recs):
        """
        Compute quantity long, short.
        """
        qty_long = Decimal(0) 
        qty_short = Decimal(0) 
        for rec in recs:
            qty = Decimal(rec['quantity'])
            if rec['side'] == 'bid':
                qty_long += qty
            else:
                qty_short += qty
        
        return qty_long, qty_short

    def _costs(self, recs):
        """
        Compute total costs in recs.
        """
        long_val = 0
        short_val = 0
        for rec in recs:
            val = rec['price'] * Decimal(rec['quantity'])
            print(f"rec['price']: {rec['price']}")
            print(f"rec['quantity']: {rec['quantity']}")

            if rec['side'] == 'bid':
                long_val += val
            else:
                short_val += val

        return long_val, short_val

    def _update_order_costs(self, recs):      
        """Cost of orders in orderbook at prices placed."""
        long_val, short_val = self._costs(recs)
        self.order_costs = long_val + short_val
        print(f'_update_order_costs: {long_val}, {short_val}, {self.order_costs}')

    def _inv_cost(self, recs):
        """Inventory cost at commited price."""
        self.inv_costs_long, self.inv_costs_short = self._costs(recs)
        self.inv_costs = self.inv_costs_long + self.inv_costs_short
        print(f'_inv_cost: {self.inv_costs_long}, {self.inv_costs_short}, {self.inv_costs}')

    def _inv_val(self, price):
        """Change of inventory value at current price."""
        long_val = self.qty_long * price
        short_val = self.qty_short * price

        self.inv_val_chg_long = long_val - self.inv_costs_long
        self.inv_val_chg_short = -(short_val - self.inv_costs_short)

        self.inv_val_chg = self.inv_val_chg_long + self.inv_val_chg_short 
        print(f'_inv_val: {self.inv_val_chg_long}, {self.inv_val_chg_short}, {self.inv_val_chg}, {self.qty_long}, {self.qty_short}, {price}')

    def _update_cash(self):
        self.cash = self.init_cash - self.order_costs - self.inv_costs

    def _update_nav(self):
        self.prev_nav = self.nav
        # self.inv_costs + self.inv_val_chg = current inventory value.
        self.nav = self.cash + self.order_costs + (self.inv_costs + self.inv_val_chg)

    def update_acc(self, ord_type, order_in_book, trades):
        print(f'ID: {self.ID}')
        
        self._update_order_costs(self.LOB_recs)

        self.qty_long, self.qty_short = self._qty(self.trade_recs)
        self.qty_long = Decimal(self.qty_long)
        self.qty_short = Decimal(self.qty_short)

        self._inv_cost(self.trade_recs)
        self._update_cash()

        if trades != []:
            self._inv_val(trades[-1]['price'])

        self._update_nav()
        
        self.num_trades = len(self.trade_recs)

    def reset_acc(self, cash=0):
        self.cash = self.init_cash
        self.order_costs = Decimal(0) 
        self.qty_long = 0
        self.qty_short = 0
        self.nav = self.init_cash
        self.prev_nav = self.nav
        self.num_trades = 0
        self.reward = Decimal(0)
        self.LOB_recs = []
        self.trade_recs = []

        self.step_nav = self.init_cash
        self.prev_step_nav = self.step_nav

        self.order_costs = Decimal(0)

        self.inv_costs_long = Decimal(0)
        self.inv_costs_short = Decimal(0) 
        self.inv_costs = Decimal(0) 

        self.inv_val_chg_long = Decimal(0) 
        self.inv_val_chg_short = Decimal(0) 
        self.inv_val_chg = Decimal(0) 

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

    def cmp_step_nav(self, price):
        """Compute nav at the env step level after each env step."""
        # print(price)
        # print(type(price))
        price = Decimal(price)
        # self.qty_long = Decimal(self.qty_long)
        # self.qty_short = Decimal(self.qty_short)
        if price > Decimal(0):
            self.prev_step_nav = self.step_nav
            self._inv_val(price)
            self.step_nav = self.cash + self.order_costs + (self.inv_costs + self.inv_val_chg)
