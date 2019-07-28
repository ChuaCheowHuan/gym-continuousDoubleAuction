# https://github.com/dyn4mik3/OrderBook/blob/master/orderbook/test/example.py

import sys
#sys.path.append("..") # Adds higher directory to python modules path.
if "../" not in sys.path:
    sys.path.append("../")

#from exchg.orderbook.orderbook import OrderBook
from exchg.orderbook import OrderBook

# Create an order book

order_book = OrderBook()

# Create some limit orders

limit_orders = [{'type' : 'limit',
                   'side' : 'ask',
                    'quantity' : 5,
                    'price' : 101,
                    'trade_id' : 100},
                   {'type' : 'limit',
                    'side' : 'ask',
                    'quantity' : 5,
                    'price' : 103,
                    'trade_id' : 101},
                   {'type' : 'limit',
                    'side' : 'ask',
                    'quantity' : 5,
                    'price' : 101,
                    'trade_id' : 102},
                   {'type' : 'limit',
                    'side' : 'ask',
                    'quantity' : 5,
                    'price' : 101,
                    'trade_id' : 103},
                   {'type' : 'limit',
                    'side' : 'bid',
                    'quantity' : 5,
                    'price' : 99,
                    'trade_id' : 100},
                   {'type' : 'limit',
                    'side' : 'bid',
                    'quantity' : 5,
                    'price' : 98,
                    'trade_id' : 101},
                   {'type' : 'limit',
                    'side' : 'bid',
                    'quantity' : 5,
                    'price' : 99,
                    'trade_id' : 102},
                   {'type' : 'limit',
                    'side' : 'bid',
                    'quantity' : 5,
                    'price' : 97,
                    'trade_id' : 103},
                   ]

# Add orders to order book
for order in limit_orders:
    trades, order_in_book = order_book.process_order(order, False, False)

print('trades', trades) # see line 94 in orderbook.py
print('order_in_book', order_in_book) # init party's unfilled orders in LOB
# The current book may be viewed using a print
print(order_book) # print LOB & tape



crossing_limit_order = {'type': 'limit',
                        'side': 'ask',
                        'quantity': 20,
                        'price': 98,
                        'trade_id': 109}

print(crossing_limit_order)
trades, order_in_book = order_book.process_order(crossing_limit_order, False, False)
print("Trade occurs as incoming ask limit crosses best bid")
print('trades', trades)
print('order_in_book', order_in_book)
print(order_book)



# Submitting a limit order that crosses the opposing best price will result in a trade
crossing_limit_order = {'type': 'limit',
                        'side': 'bid',
                        'quantity': 2,
                        'price': 102,
                        'trade_id': 109}

print(crossing_limit_order)
trades, order_in_book = order_book.process_order(crossing_limit_order, False, False)
print("Trade occurs as incoming bid limit crosses best ask")
print('trades', trades)
print('order_in_book', order_in_book)
print(order_book)

# If a limit crosses but is only partially matched, the remaning volume will
# be placed in the book as an outstanding order
big_crossing_limit_order = {'type': 'limit',
                            'side': 'bid',
                            'quantity': 50,
                            'price': 102,
                            'trade_id': 110}
print(big_crossing_limit_order)
trades, order_in_book = order_book.process_order(big_crossing_limit_order, False, False)
print("Large incoming bid limit crosses best ask. Remaining volume is placed in book.")
print('trades', trades)
print('order_in_book', order_in_book)
print(order_book)


# Market Orders

# Market orders only require that a user specifies a side (bid or ask), a quantity, and their unique trade id
market_order = {'type': 'market',
                'side': 'ask',
                'quantity': 40,
                'trade_id': 111}
trades, order_in_book = order_book.process_order(market_order, False, False)
print("A market order takes the specified volume from the inside of the book, regardless of price")
print("A market ask for 40 results in:")
print('trades', trades)
print('order_in_book', order_in_book)
print(order_book)

market_order = {'type': 'market',
                'side': 'bid',
                'quantity': 500,
                'trade_id': 111}
trades, order_in_book = order_book.process_order(market_order, False, False)
print("A market ask for 500 results in:")
print('trades', trades)
print('order_in_book', order_in_book)
print(order_book)
