import random
import numpy as np
import pandas as pd

from decimal import Decimal

from ..account.account import Account
from .random_agent import Random_agent

from tabulate import tabulate

class Trader(Random_agent):
    def __init__(self, ID, cash=0):
        self.ID = ID # trader unique ID
        self.acc = Account(ID, cash)

    # take or execute action
    def place_order(self, type, side, size, price, LOB, agents):
        trades, order_in_book = [],[]
        if(side == None): # do nothing to LOB
            #print('side == None')
            return trades, order_in_book
        # normal execution
        if self._order_approved(self.acc.cash, size, price):
            order = self._create_order(type, side, size, price)
            if order['type'] == 'market':
                trades, order_in_book = LOB.process_order(order, False, False)
            elif order['type'] == 'limit':
                trades, order_in_book = self._place_limit_order(LOB, order)
            elif order['type'] == 'modify':
                trades, order_in_book = self._modify_limit_order(LOB, order)
            elif order['type'] == 'cancel':
                trades, order_in_book = self._cancel_limit_order(LOB, order)
            else: # order == {} do nothing to LOB
                return trades, order_in_book

            if trades != []:
                self._process_trades(trades, agents)
            self.acc.order_in_book_init_party(order_in_book) # if there's any unfilled
            return trades, order_in_book
        else: # not enough cash to place order
            #print('Invalid order: order value > cash available.', self.ID)
            print("\nOrder NOT approved: -ve NAV for trader_ID {}.\n".format(self.ID))
            return trades, order_in_book

    def _order_approved(self, cash, size, price):
        #if self.acc.cash >= size * price and self.acc.nav > 0:
        if self.acc.nav > 0:
            return True
        else:
            return False

    def _create_order(self, type, side, size, price):
        if type == 'market':
            order = {'type': type,
                     'side': side,
                     'quantity': size,
                     'trade_id': self.ID}
        elif type == 'limit':
            order = {'type': type,
                     'side': side,
                     'quantity': size,
                     'price': price,
                     'trade_id': self.ID}
        elif type == 'modify':
            order = {'type': type,
                     'side': side,
                     'quantity': size,
                     'price': price,
                     'trade_id': self.ID}
        elif type == 'cancel':
            order = {'type': type,
                     'side': side,
                     'quantity': size,
                     'price': price,
                     'trade_id': self.ID}
        else:
            order = {}
        return order

    def _place_limit_order(self, orderBook, qoute):
        trades, order_in_book = [],[]
        order_id, order = self._get_order_ID(orderBook, qoute)
        if order_id == -1:  # no duplicates
            trades, order_in_book = orderBook.process_order(qoute, False, False)
        else:
            trades, order_in_book = self.__modify_limit_order(orderBook, order_id, order, qoute)
        return trades, order_in_book

    def _modify_limit_order(self, orderBook, qoute):
        order_id, order = self._get_order_ID(orderBook, qoute)
        if order_id == -1:  # no found
            trades, order_in_book = [],[]
        else:
            trades, order_in_book = self.__modify_limit_order(orderBook, order_id, order, qoute)
        return trades, order_in_book

    def __modify_limit_order(self, orderBook, order_id, order, qoute):
        qoute['type'] = 'limit'
        qoute['quantity'] = Decimal(qoute['quantity'])
        self.acc.modify_cash_transfer(qoute, order)
        orderBook.modify_order(order_id, qoute)
        return [],[]

    def _cancel_limit_order(self, orderBook, qoute):
        order_id, order = self._get_order_ID(orderBook, qoute)
        if order_id == -1:  # no found
            trades, order_in_book = [],[]
        else:
            orderBook.cancel_order(qoute['side'], order_id)
            self.acc.cancel_cash_transfer(order)
            trades, order_in_book = [],[]
        return trades, order_in_book

    def _get_order_ID(self, orderBook, qoute):
        order_map = self._find_orderTree(orderBook, qoute)
        for order_ID, order in order_map.items():
            if order.price == qoute['price'] and order.trade_id == qoute['trade_id']:
                return order_ID, order
        return -1, None # no found

    def _find_orderTree(self, orderBook, qoute):
        if qoute['side'] == 'bid':
            return orderBook.bids.order_map
        elif qoute['side'] == 'ask':
            return orderBook.asks.order_map
        else:
            return None

    def _process_trades(self, trades, agents):
        trade_list = []
        for i, trade in enumerate(trades):
            trade_val = Decimal(trade.get('quantity')) * trade.get('price')
            # init_party is not counter_party
            if trade.get('counter_party').get('ID') != trade.get('init_party').get('ID'):
                counter_party = self._process_counter_party(agents, trade)
                self.acc.process_acc(trade, 'init_party')
                #self.print_both_accs("\nAffected accounts_0:\n", i, counter_party, init_party=self)
            else: # init_party is also counter_party, balance out limit order in LOB with mkt order.
                self.acc.init_is_counter_cash_transfer(trade_val)
                #self.print_both_accs("\nAffected accounts (init_party = counter_party)_0:\n", i, counter_party=self, init_party=self)

            trade_list.append(self.pack_trade_dict(i, trade))

        #print("\ntrader_ID: {}".format(self.ID))
        #print("\nTRADES_0:\n", pd.DataFrame(trade_list).to_string())

        return 0

    def _process_counter_party(self, agents, trade):
        agent = None
        for counter_party in agents: # search for counter_party
            if counter_party.ID == trade.get('counter_party').get('ID'):
                counter_party.acc.process_acc(trade, 'counter_party')
                agent = counter_party
                break
        return agent

    def pack_trade_dict(self, i, trade):
        trade_dict = {}

        trade_dict['curr_step_Trade_ID'] = i

        trade_dict['timestamp'] = trade['timestamp']
        trade_dict['price'] = trade['price']
        trade_dict['size'] = trade['quantity']
        trade_dict['time'] = trade['time']

        counter_party_dict = trade['counter_party']
        trade_dict['counter_ID'] = counter_party_dict['ID']
        trade_dict['counter_side'] = counter_party_dict['side']
        trade_dict['counter_order_ID'] = counter_party_dict['order_id']
        trade_dict['counter_new_book_size'] = counter_party_dict['new_book_quantity']

        init_party_dict = trade['init_party']
        trade_dict['init_ID'] = init_party_dict['ID']
        trade_dict['init_side'] = init_party_dict['side']
        trade_dict['init_order_ID'] = init_party_dict['order_id']
        trade_dict['init_new_LOB_size'] = init_party_dict['new_book_quantity']

        return trade_dict

    def print_both_accs(self, msg, curr_step_trade_ID, counter_party, init_party):
        acc = {}
        acc['seq_Trade_ID'] = [curr_step_trade_ID, curr_step_trade_ID]
        acc['party'] = ["counter", "init"]
        acc['ID'] = [counter_party.acc.ID, self.acc.ID]
        acc['cash'] = [counter_party.acc.cash, self.acc.cash]
        acc['cash_on_hold'] = [counter_party.acc.cash_on_hold, self.acc.cash_on_hold]
        acc['position_val'] = [counter_party.acc.position_val, self.acc.position_val]
        acc['prev_nav'] = [counter_party.acc.prev_nav, self.acc.prev_nav]
        acc['nav'] = [counter_party.acc.nav, self.acc.nav]
        acc['net_position'] = [counter_party.acc.net_position, self.acc.net_position]
        acc['VWAP'] = [counter_party.acc.VWAP, self.acc.VWAP]
        acc['profit'] = [counter_party.acc.profit, self.acc.profit]
        acc['total_profit'] = [counter_party.acc.total_profit, self.acc.total_profit]
        acc['num_trades'] = [counter_party.acc.num_trades, self.acc.num_trades]

        print(msg, tabulate(acc, headers="keys"))

        return 0
