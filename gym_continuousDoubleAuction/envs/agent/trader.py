import random
import numpy as np

from decimal import Decimal

from ..account.account import Account
from .random_agent import Random_agent

class Trader(Random_agent):
    def __init__(self, ID, cash=0):
        self.ID = ID # unique ID
        self.acc = Account(ID, cash)

    def place_order(self, ord_type, side, size, price, LOB, agents, step):
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
        if side == None: # Do nothing to LOB.
            trades, order_in_book = [], None
        else:
            # Normal execution.
            if self._order_approved(size, price):   # REVISIT: price is -1 for market order.
                order = self._create_order(ord_type, side, size, price)
                trades, order_in_book = self._place_order(order, LOB)

                # There are unfilled qty.
                if order_in_book != None:
                    order_in_book['step'] = step
                    self.acc.LOB_recs.append(order_in_book)

                # If trades took placed in this order.
                if trades != []:
                    self._proc_init_party(agents, trades, step)

             
                for agent in agents:
                    # Update agent account.
                    agent.acc.update_acc(ord_type, order_in_book, trades)

            # Not enough cash to place order.
            else:
                # print(f'Order NOT approved for trader ID: {self.ID}')
                trades, order_in_book = [], None

        return trades, order_in_book

    def _place_order(self, order, LOB):
        if order['type'] == 'market':
            trades, order_in_book = LOB.process_order(order, False, False)
            print(f'market {self.ID} {order}')
        elif order['type'] == 'limit':
            trades, order_in_book = self._place_limit_order(LOB, order)
        elif order['type'] == 'modify':
            trades, order_in_book = self._modify_limit_order(LOB, order)
        elif order['type'] == 'cancel':
            trades, order_in_book = self._cancel_limit_order(LOB, order)
        else: # order == {} do nothing to LOB
            trades, order_in_book = [], None

        return trades, order_in_book

    def _proc_init_party(self, agents, trades, step):
        # self._process_trades(trades, agents)

        # Process for this init trader
        for trade in trades:
            init_d = {
                'step': step, 
                'tick':trade['timestamp'], 
                'party':'init',
                'side':trade['init_party']['side'],
                'price':trade['price'],
                'quantity':trade['quantity'], 
            }
            self.acc.trade_recs.append(init_d)
            self._proc_counter_party(agents, trade, step)
            
    def _proc_counter_party(self, agents, trade, step):
        # Process the counter parties of this trader (at this point, init & counter party could be same trader).
        counter_d = {
            'step': step, 
            'tick':trade['timestamp'], 
            'party':'counter',
            'side':trade['counter_party']['side'],
            'price':trade['price'],
            'quantity':trade['quantity'], 
        }
        for agent in agents:
            if agent.ID == trade['counter_party']['ID']:
                # Add trade rec for agent.
                agent.acc.trade_recs.append(counter_d)
                # Update LOB rec for agent.
                self.__proc_counter_party(agent, trade)
                break         

    def __proc_counter_party(self, agent, trade):
        # Update LOB rec for agent.
        for rec in agent.acc.LOB_recs:
            if rec['order_id'] == trade['counter_party']['order_id']:
                # Update quantity in LOB rec.
                qty = trade['counter_party']['new_book_quantity'] 
                if qty is not None:
                    if isinstance(qty, int) or isinstance(qty, float):
                        if qty > 0:
                            rec['quantity'] = qty
                        # Remove rec from LOB_recs.    
                        else:
                            agent.acc.LOB_recs.remove(rec)
                # Remove rec from LOB_recs.
                else:
                    agent.acc.LOB_recs.remove(rec)

                break

    def _create_order(self, ord_type, side, size, price):
        """
        Create the order dictionary.

        Return:
            order: A dictionary.
        """
        if ord_type == 'market':
            order = {
                'type': ord_type,
                'side': side,
                'quantity': size,
                'trade_id': self.ID}
        elif ord_type in ['limit','modify','cancel']:
            order = {
                'type': ord_type,
                'side': side,
                'quantity': size,
                'price': price,
                'trade_id': self.ID}
        else:
            order = {}

        return order

    # REVISIT: if price is -1 for market order.
    def _order_approved(self, size, price):
        """
        Conditions for order approval.

        Return: boolean.
        """
        if self.acc.cash >= Decimal(size) * Decimal(price):
            return True
        else:
            return False

    def _place_limit_order(self, orderBook, qoute):
        """
        Note:
            process_order if no such order exists in order tree.
            Otherwise, modify the existing limit order.
        """
        trades, order_in_book = [], None
        order_id, order = self._get_order_ID(orderBook, qoute)
        # No such order exist.
        if order_id == -1:  
            trades, order_in_book = orderBook.process_order(qoute, False, False)
        else:
            trades, order_in_book = self.__modify_limit_order(orderBook, order_id, qoute)

        return trades, order_in_book

    def _modify_limit_order(self, orderBook, qoute):
        """
        Note:
            __modify_limit_order if order exists in order tree.
        """
        order_id, order = self._get_order_ID(orderBook, qoute)
        if order_id == -1:  # not found
            trades, order_in_book = [], None
        else:
            trades, order_in_book = self.__modify_limit_order(orderBook, order_id, qoute)

        return trades, order_in_book

    def __modify_limit_order(self, orderBook, order_id, qoute):
        """
        Modify quantity.
        """
        qoute['type'] = 'limit'
        qoute['quantity'] = Decimal(qoute['quantity'])
        orderBook.modify_order(order_id, qoute)

        # Update LOB_recs in this trader's account.
        for rec in self.acc.LOB_recs:
            if rec['order_id'] == order_id:
                rec['quantity'] == qoute['quantity']
                break

        return [], None

    def _cancel_limit_order(self, orderBook, qoute):
        """
        Note:
            If order is found in LOB,
            handle cash transfer accordingly after cancel_order in LOB.
        """
        order_id, order = self._get_order_ID(orderBook, qoute)
        if order_id == -1:  # not found
            trades, order_in_book = [], None
        else:
            orderBook.cancel_order(qoute['side'], order_id)
            trades, order_in_book = [], None

            # Update LOB_recs in this trader's account.
            for rec in self.acc.LOB_recs:
                if rec['order_id'] == order_id:
                    self.acc.LOB_recs.remove(rec)
                    break            

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
