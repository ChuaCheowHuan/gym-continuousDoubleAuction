import random
import numpy as np

from decimal import Decimal

from .account import Account
from .random_agent import Random_agent

class Trader(Random_agent):
    def __init__(self, ID, cash=0):
        self.ID = ID # trader unique ID
        self.acc = Account(ID, cash)

    def order_approved(self, cash, size, price):
        #if self.acc.cash >= size * price:
        if self.acc.cash >= size * price and self.acc.nav > 0:        
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

    def process_counter_party(self, agents, trade):
        for counter_party in agents: # search for counter_party
            if counter_party.ID == trade.get('counter_party').get('ID'):
                counter_party.acc.process_acc(trade, 'counter_party')

                print('counter_party:', counter_party.ID)
                counter_party.acc.print_acc()

                break

    def process_trades(self, trades, agents):
        for i, trade in enumerate(trades):

            print('i:', i)
            print('trade:', trade)

            trade_val = Decimal(trade.get('quantity')) * trade.get('price')
            # init_party is not counter_party
            if trade.get('counter_party').get('ID') != trade.get('init_party').get('ID'):
                self.process_counter_party(agents, trade)
                self.acc.process_acc(trade, 'init_party')

                print('init_party:', self.ID)
                self.acc.print_acc()

            else: # init_party is also counter_party
                self.acc.init_is_counter_cash_transfer(trade_val)

                print('init_party = counter_party:', self.ID)
                self.acc.print_acc()
        return 0

    # take or execute action
    def place_order(self, type, side, size, price, LOB, agents):
        trades, order_in_book = [],[]
        if(side == None): # do nothing to LOB
            print('side == None')
            return trades, order_in_book
        # normal execution
        if self.order_approved(self.acc.cash, size, price):
            order = self.create_order(type, side, size, price)
            if order == {}: # do nothing to LOB
                return trades, order_in_book
            trades, order_in_book = LOB.process_order(order, False, False)
            if trades != []:
                self.process_trades(trades, agents)
            self.acc.order_in_book_init_party(order_in_book) # if there's any unfilled
            return trades, order_in_book
        else: # not enough cash to place order
            print('Invalid order: order value > cash available.', self.ID)
            return trades, order_in_book
