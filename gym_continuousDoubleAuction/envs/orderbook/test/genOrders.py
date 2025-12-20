#! /usr/bin/python
from __future__ import print_function
from random import *

import sys
if "../" not in sys.path:
    sys.path.append("../")

from gym_continuousDoubleAuction.envs.orderbook import OrderBook


def generate_new_buy(trade_id):
    return {'type' : 'limit',
           'side' : 'bid',
           'quantity' : randint(1,1000),
           'price' : randint(900,1050),
           'trade_id' : trade_id}

def generate_cross_buy(trade_id):
    return {'type' : 'limit',
            'side' : 'bid',
            'quantity' : randint(1,1000),
            'price' : randint(1055,1200),
            'trade_id' : trade_id}

def generate_new_sell(trade_id):
    return {'type' : 'limit',
            'side' : 'ask',
            'quantity' : randint(1,1000),
            'price' : randint(1055,1200),
            'trade_id' : trade_id}

def generate_cross_sell(trade_id):
    return {'type' : 'limit',
            'side' : 'ask',
            'quantity' : randint(1,1000),
            'price' : randint(900,1050),
            'trade_id' : trade_id}

def treat_trades(trades, side):
    if not trades:
        return
    if side == 'B':
        for j in range(len(trades)):
            trade = trades[j]
            assert (trade['counter_party']['side'] == 'ask'), 'counter_party should be ask'
            new_quantity = None
            orderId = trade['counter_party']['order_id']
            assert (orderId != None), 'counter_party should have order_id'
            new_quantity = trade['counter_party']['new_book_quantity']
            order = sells[orderId]
            if new_quantity == None:
                del sells[orderId]
            else:
                order['quantity'] = new_quantity
    else:
        for j in range(len(trades)):
            trade = trades[j]
            assert (trade['counter_party']['side'] == 'bid'), 'counter_party should be bid'
            new_quantity = None
            orderId = trade['counter_party']['order_id']
            assert (orderId != None), 'counter_party should have order_id'
            new_quantity = trade['counter_party']['new_book_quantity']
            order = buys[orderId]
            if new_quantity == None:
                del buys[orderId]
            else:
                order['quantity'] = new_quantity

def prefill(nb_orders_prefilled, verbose = False):
    for trade_id in range(nb_orders_prefilled):
        trades,neworder = order_book.process_order(generate_new_buy(trade_id), False, verbose)
        assert (trades == []), 'No trade at this stage'
        assert (neworder != []), 'Expect new order'
        buys[neworder['order_id']]=neworder
        trades,neworder = order_book.process_order(generate_new_sell(trade_id), False, verbose)
        assert (trades == []), 'No trade at this stage'
        assert (neworder != []), 'Expect new order'
        sells[neworder['order_id']]=neworder

def testCases(trade_id, action, side, verbose = False):
    if action == 'A':
        if side == 'B':
            trades,neworder = order_book.process_order(generate_new_buy(trade_id), False, verbose)
            treat_trades(trades, side)
            if neworder:
                buys[neworder['order_id']]=neworder
        else:
            trades,neworder = order_book.process_order(generate_new_sell(trade_id), False, verbose)
            treat_trades(trades, side)
            if neworder:
                sells[neworder['order_id']]=neworder
    elif action == 'M':
        if side == 'B':
            if len(buys):
                order = buys[choice(buys.keys())]
                order['quantity'] = randint(1,1000)

                print('order', order)

                order_book.modify_order(order['order_id'], order)

                print('order', order)

        else:
            if len(sells):
                order = sells[choice(sells.keys())]
                order['quantity'] = randint(1,1000)
                order_book.modify_order(order['order_id'], order)
    elif action == 'X':
        if side == 'B':
            if len(buys):
                key = choice(buys.keys())
                order = buys[key]
                del buys[key]
                order_book.cancel_order('bid', order['order_id'])
        else:
            if len(sells):
                key = choice(sells.keys())
                order = sells[key]
                del sells[key]
                order_book.cancel_order('ask', order['order_id'])
    elif action == 'C':
        if side == 'B':
            trades,neworder = order_book.process_order(generate_cross_buy(trade_id), False, verbose)
            treat_trades(trades, side)
            if neworder:
                buys[neworder['order_id']]=neworder
        else:
            trades,neworder = order_book.process_order(generate_cross_sell(trade_id), False, verbose)
            treat_trades(trades, side)
            if neworder:
                sells[neworder['order_id']]=neworder


buys = {}
sells = {}
order_book = OrderBook()

# nb buys and sells to prefill orderbook
prefill(10)

#print(order_book)


#usage:
# 1/ trade_id
# 2/ choice('AMXC') : A (new), M (modify), X (cancel), C (cross)
# 3/ choice('BS') : B (buy), S (sell)
for trade_id in range(10, 100):
    testCases(trade_id, choice('C'), choice('BS'), False)

print(order_book)
ans = "***Bids***" + "\n" + \
"  size price  trade_id  timestamp  order_id" + "\n" + \
"0   33   906        98        109       109" + "\n" + \
"1  201  1041        63         74        74" + "\n" + \
"2  733  1043        77         88        88" + "\n" + \
"3  680  1046        99        110       110" + "\n" + \
"4  716  1048        80         91        91" + "\n" + \
"5  438  1165         4         10        10" + "\n" + \
"6  394  1166         0          2         2" + "\n" + \
"7  355  1182         3          8         8" + "\n" + \
"***Asks***" + "\n\n" + \
"***tape***" + "\n" + \
"  size price  timestamp  counter_party_ID  init_party_ID init_party_side" + "\n" + \
"0    1  1041        108                63             97             bid" + "\n" + \
"1  254  1040        108                76             97             bid" + "\n" + \
"2   69  1035        108                95             97             bid" + "\n" + \
"3  310  1035        107                95             96             bid" + "\n" + \
"4  683   942        107                94             96             bid" + "\n" + \
"5   29  1040        104                76             93             bid" + "\n" + \
"6   75  1040        103                76             92             bid" + "\n" + \
"7  402  1040        102                76             91             bid" + "\n" + \
"8  231  1040        101                76             90             bid" + "\n" + \
"9  145  1032        101                81             90             bid" + "\n"
# Can't test this yet as output is randomly generated.
#assert str(order_book) == ans, "order_book.process_order ERROR."


# quit()
