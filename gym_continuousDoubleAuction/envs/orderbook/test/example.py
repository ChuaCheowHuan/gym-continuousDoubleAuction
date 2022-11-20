import sys
if "../" not in sys.path:
    sys.path.append("../")

from gym_continuousDoubleAuction.envs.orderbook import OrderBook


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
    trades, order_id = order_book.process_order(order, False, False)
# The current book may be viewed using a print
print(order_book)
ans = "***Bids***" + "\n" + \
"  size price  trade_id  timestamp  order_id" + "\n" + \
"0    5    99       100          5         5" + "\n" + \
"1    5    99       102          7         7" + "\n" + \
"2    5    98       101          6         6" + "\n" + \
"3    5    97       103          8         8" + "\n" + \
"***Asks***" + "\n" + \
"  size price  trade_id  timestamp  order_id" + "\n" + \
"0    5   101       100          1         1" + "\n" + \
"1    5   101       102          3         3" + "\n" + \
"2    5   101       103          4         4" + "\n" + \
"3    5   103       101          2         2" + "\n" + \
"***tape***" + "\n\n"
assert str(order_book) == ans, "order_book.process_order ERROR."


# Submitting a limit order that crosses the opposing best price will result in a trade
crossing_limit_order = {'type': 'limit',
                        'side': 'bid',
                        'quantity': 2,
                        'price': 102,
                        'trade_id': 109}
print(crossing_limit_order)

trades, order_in_book = order_book.process_order(crossing_limit_order, False, False)
print("Trade occurs as incoming bid limit crosses best ask")
print(trades)
ans = "[ \
    {'timestamp': 9, 'price': Decimal('101'), 'quantity': 2, 'time': 9, \
        'counter_party': {'ID': 100, 'side': 'ask', 'order_id': 1, 'new_book_quantity': Decimal('3')}, \
        'init_party': {'ID': 109, 'side': 'bid', 'order_id': None, 'new_book_quantity': None} \
    } \
]"
assert str(trades) == ans, "order_book.process_order ERROR."

print(order_book)
ans = "***Bids***" + "\n" + \
"  size price  trade_id  timestamp  order_id" + "\n" + \
"0    5    99       100          5         5" + "\n" + \
"1    5    99       102          7         7" + "\n" + \
"2    5    98       101          6         6" + "\n" + \
"3    5    97       103          8         8" + "\n" + \
"***Asks***" + "\n" + \
"  size price  trade_id  timestamp  order_id" + "\n" + \
"0    3   101       100          1         1" + "\n" + \
"1    5   101       102          3         3" + "\n" + \
"2    5   101       103          4         4" + "\n" + \
"3    5   103       101          2         2" + "\n" + \
"***tape***" + "\n" + \
"   size price  timestamp  counter_party_ID  init_party_ID init_party_side" + "\n" + \
"0     2   101          9               100            109             bid" + "\n"
assert str(order_book) == ans, "order_book.process_order ERROR."


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
print(trades)
ans = "[{'timestamp': 10, 'price': Decimal('101'), 'quantity': Decimal('3'), 'time': 10, 'counter_party': {'ID': 100, 'side': 'ask', 'order_id': 1, 'new_book_quantity': None}, 'init_party': {'ID': 110, 'side': 'bid', 'order_id': None, 'new_book_quantity': None}}, {'timestamp': 10, 'price': Decimal('101'), 'quantity': Decimal('5'), 'time': 10, 'counter_party': {'ID': 102, 'side': 'ask', 'order_id': 3, 'new_book_quantity': None}, 'init_party': {'ID': 110, 'side': 'bid', 'order_id': None, 'new_book_quantity': None}}, {'timestamp': 10, 'price': Decimal('101'), 'quantity': Decimal('5'), 'time': 10, 'counter_party': {'ID': 103, 'side': 'ask', 'order_id': 4, 'new_book_quantity': None}, 'init_party': {'ID': 110, 'side': 'bid', 'order_id': None, 'new_book_quantity': None}}]"
assert str(trades) == ans, "order_book.process_order ERROR."

print(order_book)
ans = "***Bids***" + "\n" + \
"  size price  trade_id  timestamp  order_id" + "\n" + \
"0   37   102       110         10        10" + "\n" + \
"1    5    99       100          5         5" + "\n" + \
"2    5    99       102          7         7" + "\n" + \
"3    5    98       101          6         6" + "\n" + \
"4    5    97       103          8         8" + "\n" + \
"***Asks***" + "\n" + \
"  size price  trade_id  timestamp  order_id" + "\n" + \
"0    5   103       101          2         2" + "\n" + \
"***tape***" + "\n" + \
"  size price  timestamp  counter_party_ID  init_party_ID init_party_side" + "\n" + \
"0    5   101         10               103            110             bid" + "\n" + \
"1    5   101         10               102            110             bid" + "\n" + \
"2    3   101         10               100            110             bid" + "\n" + \
"3    2   101          9               100            109             bid" + "\n"
assert str(order_book) == ans, "order_book.process_order ERROR."


# Market Orders

# Market orders only require that a user specifies a side (bid or ask), a quantity, and their unique trade id
market_order = {'type': 'market',
                'side': 'ask',
                'quantity': 40,
                'trade_id': 111}
trades, order_id = order_book.process_order(market_order, False, False)
print("A market order takes the specified volume from the inside of the book, regardless of price")
print("A market ask for 40 results in:")
print(order_book)
ans = "***Bids***" + "\n" + \
"  size price  trade_id  timestamp  order_id" + "\n" + \
"0    2    99       100          5         5" + "\n" + \
"1    5    99       102          7         7" + "\n" + \
"2    5    98       101          6         6" + "\n" + \
"3    5    97       103          8         8" + "\n" + \
"***Asks***" + "\n" + \
"  size price  trade_id  timestamp  order_id" + "\n" + \
"0    5   103       101          2         2" + "\n" + \
"***tape***" + "\n" + \
"  size price  timestamp  counter_party_ID  init_party_ID init_party_side" + "\n" + \
"0    3    99         11               100            111             ask" + "\n" + \
"1   37   102         11               110            111             ask" + "\n" + \
"2    5   101         10               103            110             bid" + "\n" + \
"3    5   101         10               102            110             bid" + "\n" + \
"4    3   101         10               100            110             bid" + "\n" + \
"5    2   101          9               100            109             bid" + "\n"
assert str(order_book) == ans, "order_book.process_order ERROR."
