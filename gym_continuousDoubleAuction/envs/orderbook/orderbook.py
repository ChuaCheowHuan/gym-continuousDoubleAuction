import sys
import math

import pandas as pd
#import json

from itertools import chain

from collections import deque # a faster insert/pop queue
from six.moves import cStringIO as StringIO
from decimal import Decimal

from .ordertree import OrderTree

class OrderBook(object):
    def __init__(self, tick_size = 0.0001, tape_display_length=10):
        self.tape = deque(maxlen=None) # Index[0] is most recent trade
        self.bids = OrderTree()
        self.asks = OrderTree()
        self.last_tick = None
        self.last_timestamp = 0
        self.tick_size = tick_size
        self.time = 0
        self.next_order_id = 0
        self.tape_display_length = tape_display_length

    def update_time(self):
        self.time += 1

    def process_order(self, quote, from_data, verbose):
        order_type = quote['type']
        order_in_book = None
        if from_data:
            self.time = quote['timestamp']
        else:
            self.update_time()
            quote['timestamp'] = self.time
        if quote['quantity'] <= 0:
            sys.exit('process_order() given order of quantity <= 0')
        if not from_data:
            self.next_order_id += 1
        if order_type == 'market':
            trades = self.process_market_order(quote, verbose)
        elif order_type == 'limit':
            
            
            
            # quote['price'] = Decimal(quote['price'])
            quote['price'] = Decimal(str(quote['price']))



            trades, order_in_book = self.process_limit_order(quote, from_data, verbose)
        else:
            sys.exit("order_type for process_order() is neither 'market' or 'limit'")
        return trades, order_in_book

    def process_order_list(self, side, order_list, quantity_still_to_trade, quote, verbose):
        '''
        Takes an OrderList (stack of orders at one price) and an incoming order and matches
        appropriate trades given the order's quantity.
        '''
        trades = [] # local only
        quantity_to_trade = quantity_still_to_trade
        while len(order_list) > 0 and quantity_to_trade > 0:
            head_order = order_list.get_head_order()
            traded_price = head_order.price
            counter_party = head_order.trade_id
            new_book_quantity = None
            if quantity_to_trade < head_order.quantity:
                traded_quantity = quantity_to_trade
                # Do the transaction
                # original line but produce error on RLlib,
                # cause: TypeError: unsupported operand type(s) for -: 'decimal.Decimal' and 'float'
                #new_book_quantity = head_order.quantity - quantity_to_trade
                new_book_quantity = head_order.quantity - Decimal(quantity_to_trade)
                head_order.update_quantity(new_book_quantity, head_order.timestamp)
                if side == 'bid':
                    self.bids.volume -= Decimal(traded_quantity)
                else:
                    self.asks.volume -= Decimal(traded_quantity)
                quantity_to_trade = 0
            elif quantity_to_trade == head_order.quantity:
                traded_quantity = quantity_to_trade
                if side == 'bid':
                    self.bids.remove_order_by_id(head_order.order_id)
                else:
                    self.asks.remove_order_by_id(head_order.order_id)
                quantity_to_trade = 0
            else: # quantity to trade is larger than the head order
                traded_quantity = head_order.quantity
                if side == 'bid':
                    self.bids.remove_order_by_id(head_order.order_id)
                else:
                    self.asks.remove_order_by_id(head_order.order_id)
                #quantity_to_trade -= traded_quantity
                quantity_to_trade = Decimal(quantity_to_trade) - traded_quantity
            if verbose:
                print(("TRADE: Time - {}, Price - {}, Quantity - {}, TradeID - {}, Matching TradeID - {}".format(self.time, traded_price, traded_quantity, counter_party, quote['trade_id'])))

            transaction_record = {'timestamp': self.time,
                                  'price': traded_price,
                                  'quantity': traded_quantity,
                                  'time': self.time}
            """
            if side == 'bid': # counter_party's side
                transaction_record['party1'] = [counter_party, 'bid', head_order.order_id, new_book_quantity]
                transaction_record['party2'] = [quote['trade_id'], 'ask', None, None]
            else:
                transaction_record['party1'] = [counter_party, 'ask', head_order.order_id, new_book_quantity]
                transaction_record['party2'] = [quote['trade_id'], 'bid', None, None]
            """
            if side == 'bid': # counter_party's side
                transaction_record['counter_party'] = {'ID': counter_party,
                                                'side': 'bid',
                                                'order_id': head_order.order_id,
                                                'new_book_quantity': new_book_quantity}
                transaction_record['init_party'] = {'ID': quote['trade_id'],
                                                'side': 'ask',
                                                'order_id': None,
                                                'new_book_quantity': None}
            else:
                transaction_record['counter_party'] = {'ID': counter_party,
                                                'side': 'ask',
                                                'order_id': head_order.order_id,
                                                'new_book_quantity': new_book_quantity}
                transaction_record['init_party'] = {'ID': quote['trade_id'],
                                                'side': 'bid',
                                                'order_id': None,
                                                'new_book_quantity': None}

            self.tape.append(transaction_record)
            trades.append(transaction_record) # appending indicates a trade done, order filled
        return quantity_to_trade, trades

    def process_market_order(self, quote, verbose):
        trades = []
        quantity_to_trade = quote['quantity']
        side = quote['side']
        if side == 'bid':
            while quantity_to_trade > 0 and self.asks:
                best_price_asks = self.asks.min_price_list()
                quantity_to_trade, new_trades = self.process_order_list('ask', best_price_asks, quantity_to_trade, quote, verbose)
                trades += new_trades
        elif side == 'ask':
            while quantity_to_trade > 0 and self.bids:
                best_price_bids = self.bids.max_price_list()
                quantity_to_trade, new_trades = self.process_order_list('bid', best_price_bids, quantity_to_trade, quote, verbose)
                trades += new_trades
        else:
            sys.exit('process_market_order() recieved neither "bid" nor "ask"')
        return trades

    def process_limit_order(self, quote, from_data, verbose):
        order_in_book = None
        trades = []
        quantity_to_trade = quote['quantity']
        side = quote['side']
        price = quote['price']
        if side == 'bid':
            while (self.asks and price >= self.asks.min_price() and quantity_to_trade > 0):
                best_price_asks = self.asks.min_price_list()
                quantity_to_trade, new_trades = self.process_order_list('ask', best_price_asks, quantity_to_trade, quote, verbose)
                trades += new_trades
            # If volume remains, need to update the book with new quantity
            if quantity_to_trade > 0:
                if not from_data:
                    quote['order_id'] = self.next_order_id
                quote['quantity'] = quantity_to_trade
                self.bids.insert_order(quote)
                order_in_book = quote
        elif side == 'ask':
            while (self.bids and price <= self.bids.max_price() and quantity_to_trade > 0):
                best_price_bids = self.bids.max_price_list()
                quantity_to_trade, new_trades = self.process_order_list('bid', best_price_bids, quantity_to_trade, quote, verbose)
                trades += new_trades
            # If volume remains, need to update the book with new quantity
            if quantity_to_trade > 0:
                if not from_data:
                    quote['order_id'] = self.next_order_id
                quote['quantity'] = quantity_to_trade
                self.asks.insert_order(quote)
                order_in_book = quote
        else:
            sys.exit('process_limit_order() given neither "bid" nor "ask"')
        return trades, order_in_book

    def cancel_order(self, side, order_id, time=None):
        if time:
            self.time = time
        else:
            self.update_time()
        if side == 'bid':
            if self.bids.order_exists(order_id):
                self.bids.remove_order_by_id(order_id)
        elif side == 'ask':
            if self.asks.order_exists(order_id):
                self.asks.remove_order_by_id(order_id)
        else:
            sys.exit('cancel_order() given neither "bid" nor "ask"')

    def modify_order(self, order_id, order_update, time=None):

        if time:
            self.time = time
        else:
            self.update_time()

        side = order_update['side']
        order_update['order_id'] = order_id
        order_update['timestamp'] = self.time

        # Find the existing order to compare parameters
        if side == 'bid':
            if not self.bids.order_exists(order_id):
                return [], None
            original_order = self.bids.get_order(order_id)
            tree = self.bids
        elif side == 'ask':
            if not self.asks.order_exists(order_id):
                return [], None
            original_order = self.asks.get_order(order_id)
            tree = self.asks
        else:
            sys.exit('modify_order() given neither "bid" nor "ask"')

        original_price = original_order.price
        original_quantity = original_order.quantity
        
        # Ensure price and quantity are Decimals for type-safety in underlying logic
        order_update['price'] = Decimal(str(order_update['price']))
        order_update['quantity'] = Decimal(str(order_update['quantity']))
        
        new_price = order_update['price']
        new_quantity = order_update['quantity']

        # Scenario 4: Quantity decrease at same price -> Keep priority
        if new_price == original_price and new_quantity <= original_quantity:
            tree.update_order(order_update)
            return [], order_update

        # All other scenarios: Remove and re-process to ensure matching and correct priority
        trade_id = original_order.trade_id
        tree.remove_order_by_id(order_id)

        # Prepare quote for re-processing
        quote = {
            'type': 'limit',
            'side': side,
            'quantity': new_quantity,
            'price': new_price,
            'trade_id': trade_id,
            'timestamp': self.time,
            'order_id': order_id
        }

        # process_limit_order handles matching and returns trades, order_in_book
        return self.process_limit_order(quote, from_data=True, verbose=False)

    # def modify_order(self, order_id, order_update, time=None):
    #     if time:
    #         self.time = time
    #     else:
    #         self.update_time()

    #     side = order_update['side']
    #     order_update['order_id'] = order_id
    #     order_update['timestamp'] = self.time

    #     # To ensure the matching engine is triggered, we remove the existing order
    #     # and re-process it as a new limit order with the updated parameters.
    #     if side == 'bid':
    #         if self.bids.order_exists(order_id):
    #             order = self.bids.get_order(order_id)
    #             trade_id = order.trade_id
    #             self.bids.remove_order_by_id(order_id)
    #         else:
    #             return None, None
    #     elif side == 'ask':
    #         if self.asks.order_exists(order_id):
    #             order = self.asks.get_order(order_id)
    #             trade_id = order.trade_id
    #             self.asks.remove_order_by_id(order_id)
    #         else:
    #             return None, None
    #     else:
    #         sys.exit('modify_order() given neither "bid" nor "ask"')

    #     # Prepare the quote for re-processing.
    #     # We use Decimal(str(...)) to ensure precision consistent with process_order.
    #     quote = {
    #         'type': 'limit',
    #         'side': side,
    #         'quantity': Decimal(str(order_update['quantity'])),
    #         'price': Decimal(str(order_update['price'])),
    #         'trade_id': trade_id,
    #         'timestamp': self.time,
    #         'order_id': order_id
    #     }

    #     # process_limit_order will handle matching and updating the tape.
    #     # from_data=True ensures we keep the same order_id.
    #     return self.process_limit_order(quote, from_data=True, verbose=False)

    # def get_volume_at_price(self, side, price):
    #     price = Decimal(price)
    #     if side == 'bid':
    #         volume = 0
    #         if self.bids.price_exists(price):
    #             volume = self.bids.get_price(price).volume
    #         return volume
    #     elif side == 'ask':
    #         volume = 0
    #         if self.asks.price_exists(price):
    #             volume = self.asks.get_price(price).volume
    #         return volume
    #     else:
    #         sys.exit('get_volume_at_price() given neither "bid" nor "ask"')

    def get_best_bid(self):
        return self.bids.max_price()

    def get_worst_bid(self):
        return self.bids.min_price()

    def get_best_ask(self):
        return self.asks.min_price()

    def get_worst_ask(self):
        return self.asks.max_price()

    def tape_dump(self, filename, filemode, tapemode):
        dumpfile = open(filename, filemode)
        for tapeitem in self.tape:
            dumpfile.write('Time: %s, Price: %s, Quantity: %s\n' % (tapeitem['time'],
                                                                    tapeitem['price'],
                                                                    tapeitem['quantity']))
        dumpfile.close()
        if tapemode == 'wipe':
            self.tape = []

    # for print(order_book)
    # print LOB & tape
    def __str__0(self):
        tempfile = StringIO()

        tempfile.write("***Bids***\n")
        if self.bids != None and len(self.bids) > 0:
            # price_map is sorted dict, key is price, value is orderlist
            for key, value in reversed(self.bids.price_map.items()):
                tempfile.write('%s' % value)
        tempfile.write("\n***Asks***\n")
        if self.asks != None and len(self.asks) > 0:
            for key, value in self.asks.price_map.items():
                tempfile.write('%s' % value)

        tempfile.write("\n***tape***\n")
        tempfile.write('Q' +
        " @ " + '$' +
        " (" + 't' +
        ") " + 'c' +
        "/" + 'i' +
        " " + 'side' +
        "\n")
        if self.tape != None and len(self.tape) > 0:
            num = 0
            for entry in reversed(self.tape):
                if num < self.tape_display_length: # get last num of entries
                    #tempfile.write(str(entry['quantity']) + " @ " + str(entry['price']) + " (" + str(entry['timestamp']) + ") " + str(entry['party1'][0]) + "/" + str(entry['party2'][0]) + "\n")
                    tempfile.write(str(entry['quantity']) +
                    " @ " + str(entry['price']) +
                    " (" + str(entry['timestamp']) +
                    ") " + str(entry['counter_party']['ID']) +
                    "/" + str(entry['init_party']['ID']) +
                    " " + str(entry['init_party']['side']) +
                    "\n")
                    num += 1
                else:
                    break
        tempfile.write("\n")

        return tempfile.getvalue()

    def __str__(self):
        tempfile = StringIO()

        #tempfile.write(self.__str__0() + "\n")

        tempfile.write("***Bids***\n")
        if self.bids != None and len(self.bids) > 0:
            # price_map is sorted dict, key is price, value is orderlist
            all_bids = []
            for key, value in reversed(self.bids.price_map.items()):
                all_bids.append(value.to_list())

            flat_bids = list(self._flatten(all_bids)) # flat list of dicts
            df_bid = pd.DataFrame(flat_bids)
            tempfile.write(df_bid.to_string())

        tempfile.write("\n***Asks***\n")
        if self.asks != None and len(self.asks) > 0:
            all_asks = []
            for key, value in self.asks.price_map.items():
                all_asks.append(value.to_list())

            flat_ask = list(self._flatten(all_asks)) # flat list of dicts
            df_ask = pd.DataFrame(flat_ask)
            tempfile.write(df_ask.to_string())

        tempfile.write("\n***tape***\n")
        if self.tape != None and len(self.tape) > 0:
            num = 0
            all_TS = []
            for entry in reversed(self.tape):
                if num < self.tape_display_length: # get last num of entries
                    TS = {}
                    TS["size"] = entry['quantity']
                    TS["price"] = entry['price']
                    TS["timestamp"] = entry['timestamp']
                    TS["counter_party_ID"] = entry['counter_party']['ID']
                    TS["init_party_ID"] = entry['init_party']['ID']
                    TS["init_party_side"] = entry['init_party']['side']
                    #tempfile.write(str(TS) + "\n")
                    all_TS.append(TS)

                    num += 1
                else:
                    break

            all_TS_df = pd.DataFrame(all_TS)
            tempfile.write(all_TS_df.to_string())

        tempfile.write("\n")

        return tempfile.getvalue()

    def _flatten(self, list_of_lists):
        "Flatten one level of nesting"
        return chain.from_iterable(list_of_lists)
