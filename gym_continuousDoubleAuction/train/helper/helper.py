import numpy as np
import re

def str_to_arr(a_str):
    """
    Remove letters from string & convert string to array.
    """
    letters = '] ['
    regex_str = '[' + letters + ']'
    a_str = re.sub(regex_str, ' ', a_str)
    a_arr = np.fromstring(a_str, dtype=float, sep=' ')
    return a_arr

def ord_imb(bid_size, ask_size):
    ord_imb = []
    for bid_size_row, ask_size_row in zip(bid_size, ask_size):
        ord_imb.append(np.add(bid_size_row, ask_size_row))

    return ord_imb

def sum_ord_imb(ord_imb_store):
    sum_ord_imb_store = np.zeros((1, len(ord_imb_store[0])), float)
    for row in ord_imb_store:
        sum_ord_imb_store = np.add(sum_ord_imb_store, row)

    return sum_ord_imb_store[0]

def mid_price(bid_price, ask_price):
    mid_price = []
    for bid_price_row, ask_price_row in zip(bid_price, ask_price):
        mid_price.append(np.add(bid_price_row, -ask_price_row) / 2)

    return mid_price
