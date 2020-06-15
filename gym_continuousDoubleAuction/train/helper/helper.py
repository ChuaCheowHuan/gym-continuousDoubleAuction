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

def size_imb(bid_size_lv_dict, ask_size_lv_dict):
    """
    Return the size imbalance (bid size + (-ask size)) for each step in each level in a dictionary.
    """
    size_imb = {}
    for i, (bid_size_k, ask_size_k) in enumerate(zip(bid_size_lv_dict, ask_size_lv_dict)):
        size_imb[str(i)] = np.add(bid_size_lv_dict[bid_size_k], ask_size_lv_dict[ask_size_k])
    return size_imb

def midpt_price(bid_price_lv_dict, ask_price_lv_dict):
    """
    Return the mid point price (bid price - (-ask price)) / 2 for each step in each level in a dictionary.
    """
    midpt_price = {}
    for i, (bid_price_k, ask_price_k) in enumerate(zip(bid_price_lv_dict, ask_price_lv_dict)):
        midpt_price[str(i)] = np.divide(np.subtract(bid_price_lv_dict[bid_price_k], ask_price_lv_dict[ask_price_k]), 2)
    return midpt_price

def sum_all_lv(store):
    """
    Return list that contains sum of all levels.
    """
    res = []
    for i in range(len(store[str(0)])):
        res.append(0)
    for k,v in store.items():
        res = np.add(v, res)
    return res



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
