import random
import numpy as np
import pandas as pd

from decimal import Decimal

from ..account.account import Account
from .random_agent import Random_agent

class Trader(Random_agent):
    def __init__(self, ID, cash=0):
        self.ID = ID # trader unique ID
        self.acc = Account(ID, cash)

    def place_order(self, type, side, size, price, LOB, agents):
        """
        Execute an action.

        Return:
            trades: list
            order_in_book: list

        Notes:
            If side is None, do nothing. Otherwise, if the order is approved,
            create the order & execute it. If trades took placed in this order,
            process the trades. Update the (init_party) trader's account if
            there's any unfilled.
        """

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

            if trades != []: # if trades took placed in this order
                self._process_trades(trades, agents)

            self.acc.order_in_book_init_party(order_in_book) # if there's any unfilled
            return trades, order_in_book

        else: # not enough cash to place order
            #print('Invalid order: order value > cash available.', self.ID)
            print("\nOrder NOT approved: -ve NAV for trader_ID {}.\n".format(self.ID))
            return trades, order_in_book

    def _order_approved(self, cash, size, price):
        """
        Conditions for order approval.

        Return: boolean.
        """

        #if self.acc.cash >= size * price and self.acc.nav > 0:
        if self.acc.nav > 0:
            return True
        else:
            return False

    def _create_order(self, type, side, size, price):
        """
        Create the order dictionary.

        Return:
            order: A dictionary.
        """

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
        """
        Note:
            process_order if no such order exists in order tree.
            Otherwise, modify the existing limit order.
        """

        trades, order_in_book = [],[]
        order_id, order = self._get_order_ID(orderBook, qoute)
        if order_id == -1:  # no such order exist
            trades, order_in_book = orderBook.process_order(qoute, False, False)
        else:
            trades, order_in_book = self.__modify_limit_order(orderBook, order_id, order, qoute)

        return trades, order_in_book

    def _modify_limit_order(self, orderBook, qoute):
        """
        Note:
            __modify_limit_order if order exists in order tree.
        """

        order_id, order = self._get_order_ID(orderBook, qoute)
        if order_id == -1:  # not found
            trades, order_in_book = [],[]
        else:
            trades, order_in_book = self.__modify_limit_order(orderBook, order_id, order, qoute)

        return trades, order_in_book

    def __modify_limit_order(self, orderBook, order_id, order, qoute):
        """
        Note:
            Handle cash transfer accordingly before modifying order then,
            modify_order in LOB.
        """

        qoute['type'] = 'limit'
        qoute['quantity'] = Decimal(qoute['quantity'])
        self.acc.modify_cash_transfer(qoute, order)
        orderBook.modify_order(order_id, qoute)

        return [],[]

    def _cancel_limit_order(self, orderBook, qoute):
        """
        Note:
            If order is found in LOB,
            handle cash transfer accordingly after cancel_order in LOB.
        """

        order_id, order = self._get_order_ID(orderBook, qoute)
        if order_id == -1:  # not found
            trades, order_in_book = [],[]
        else:
            orderBook.cancel_order(qoute['side'], order_id)
            self.acc.cancel_cash_transfer(order)
            trades, order_in_book = [],[]

        return trades, order_in_book

    def _get_order_ID(self, orderBook, qoute):
        """
        Find the order in the order tree.

        Note:
            If order already exist, return
                order_ID, order.
            If no such order in order tree, return
                -1, None.
        """

        order_map = self._find_orderTree(orderBook, qoute)
        for order_ID, order in order_map.items():
            if order.price == qoute['price'] and order.trade_id == qoute['trade_id']:
                return order_ID, order # order already exist

        return -1, None # no such order in order tree.

    def _find_orderTree(self, orderBook, qoute):
        """
        Get 1 of the 2 LOB trees.

        returns: Either the bid or ask tree or None.
        """

        if qoute['side'] == 'bid':
            return orderBook.bids.order_map
        elif qoute['side'] == 'ask':
            return orderBook.asks.order_map
        else:
            return None

    def _process_trades(self, trades, agents):
        """
        Process trades for the init_party & counter_party.

        Notes:
            It's possible that the init_party is also the counter_party.
        """

        for i, trade in enumerate(trades):
            trade_val = Decimal(trade.get('quantity')) * trade.get('price')

            # init_party is not counter_party
            if trade.get('counter_party').get('ID') != trade.get('init_party').get('ID'):
                counter_party = self._process_counter_party(agents, trade)
                self.acc.process_acc(trade, 'init_party')

                #self.acc.print_both_accs("\nAffected accounts_0:\n", i, counter_party, init_party=self)

            else: # init_party is also counter_party, balance out limit order in LOB with mkt order.
                self.acc.init_is_counter_cash_transfer(trade_val)

                #self.acc.print_both_accs("\nAffected accounts (init_party = counter_party)_0:\n", i, counter_party=self, init_party=self)

            #print('trades:', trades)

        return 0

    def _process_counter_party(self, agents, trade):
        """
        Find & return the counter_party.

        return:
            agent: A trader object.
        """

        agent = None
        for counter_party in agents: # search for counter_party
            if counter_party.ID == trade.get('counter_party').get('ID'):
                counter_party.acc.process_acc(trade, 'counter_party')
                agent = counter_party
                break

        return agent
