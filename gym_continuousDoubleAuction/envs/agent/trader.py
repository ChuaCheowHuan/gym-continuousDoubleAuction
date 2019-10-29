import random
import numpy as np

from decimal import Decimal

from ..account.account import Account
from .random_agent import Random_agent

class Trader(Random_agent):
    def __init__(self, ID, cash=0):
        self.ID = ID # trader unique ID
        self.acc = Account(ID, cash)

    # take or execute action
    def place_order(self, type, side, size, price, LOB, agents):
        trades, order_in_book = [],[]
        if(side == None): # do nothing to LOB
            print('side == None')
            return trades, order_in_book
        # normal execution
        if self._order_approved(self.acc.cash, size, price):
            order = self._create_order(type, side, size, price)

            print('********** trader.py, place_order, order:', order)

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
            print('Order NOT approved: -ve NAV.', self.ID)
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
                     #'quantity': Decimal(size),
                     #'price': Decimal(price),
                     'quantity': size,
                     'price': price,
                     'trade_id': self.ID}
        elif type == 'modify':
            order = {'type': type,
                     'side': side,
                     #'quantity': Decimal(size),
                     #'price': Decimal(price),
                     'quantity': size,
                     'price': price,
                     'trade_id': self.ID}
        elif type == 'cancel':
            order = {'type': type,
                     'side': side,
                     #'quantity': Decimal(size),
                     #'price': Decimal(price),
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

            #print('********** orderBook', orderBook)
            print('********** trader.py, _place_limit_order, if order_id == -1:, order:', order)
            print('********** trader.py, _place_limit_order, if order_id == -1:, qoute:', qoute)

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
        print('********** trader.py, start, orderBook.modify_order(order_id, qoute), str(orderBook):\n', str(orderBook))

        #qoute['type'] = 'limit'
        qoute['quantity'] = Decimal(qoute['quantity'])
        self.acc.modify_cash_transfer(qoute, order)

        #order.quantity = qoute['quantity']
        #orderBook.modify_order(order_id, order)
        print('********** trader.py __modify_limit_order order_id', order_id)
        print('********** trader.py __modify_limit_order order', order)
        print('********** trader.py __modify_limit_order qoute', qoute)

        orderBook.modify_order(order_id, qoute)

        print('********** trader.py, end, orderBook.modify_order(order_id, qoute), str(orderBook):\n', str(orderBook))

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
        for i, trade in enumerate(trades):

            print('i:', i)
            print('trade:', trade)

            trade_val = Decimal(trade.get('quantity')) * trade.get('price')
            # init_party is not counter_party
            if trade.get('counter_party').get('ID') != trade.get('init_party').get('ID'):
                self._process_counter_party(agents, trade)
                self.acc.process_acc(trade, 'init_party')

                print('init_party:', self.ID)
                self.acc.print_acc()

            else: # init_party is also counter_party
                self.acc.init_is_counter_cash_transfer(trade_val)

                print('init_party = counter_party:', self.ID)
                self.acc.print_acc()
        return 0

    def _process_counter_party(self, agents, trade):
        for counter_party in agents: # search for counter_party
            if counter_party.ID == trade.get('counter_party').get('ID'):
                counter_party.acc.process_acc(trade, 'counter_party')

                print('counter_party:', counter_party.ID)
                counter_party.acc.print_acc()

                break
