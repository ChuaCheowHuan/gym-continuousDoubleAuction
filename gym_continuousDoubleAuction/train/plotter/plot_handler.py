import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from gym_continuousDoubleAuction.train.storage.store_handler import get_lv_data

step_window = 100 #int(np.rint(max_step * 0.1))
eps_window = 2 #int(np.rint(num_iters * 0.1))

def _cal_y(the_type, a_list, init_cash, msg2):
    """
    Return y values for different types.
    """
    if the_type == "reward":
        y = np.cumsum(a_list)
    elif the_type == "NAV":
        y = np.cumsum([val - init_cash for val in a_list])
    else:
        if msg2 == "_num_trades_step_list":
            y = pd.Series(a_list).rolling(window=step_window).mean()
        else:
            y = pd.Series(a_list).rolling(window=eps_window).mean()

    return y

def _sel_disc(i, num_trained_agent, msg, msg3):
    """
    Set legend message & line width.
    """
    if i < num_trained_agent:
        disc = msg + str(i) + msg3
        line_width = 5
    else:
        disc = msg + str(i) + '_random'
        line_width = 1

    return disc, line_width

def plot_step_result(init_cash, num_agents, num_trained_agent, the_type, store, msg, msg2, msg3, x_msg, y_msg, title):
    """
    Plot all steps in all episodes for all agents.
    """
    plt.figure(figsize=(20,5))
    plt.xlabel(x_msg)
    plt.ylabel(y_msg)

    for i in range(num_agents):
        key = msg + str(i) + msg2
        col = np.random.uniform(0,1,3)
        flat_list = [item for sublist in store[key] for item in sublist]
        y = _cal_y(the_type, flat_list, init_cash, msg2)
        x=range(len(y))
        disc, line_width = _sel_disc(i, num_trained_agent, msg, msg3)
        plt.plot(x, y, color=col, label=disc, linewidth=line_width) # plotting x, y

    plt.legend()
    plt.title(title)
    plt.show()

def plot_eps_result(init_cash, num_agents, num_trained_agent, the_type, store, msg, msg2, msg3, x_msg, y_msg, title):
    """
    Plot all episodes for all agents.
    """
    plt.figure(figsize=(20,5))
    plt.xlabel(x_msg)
    plt.ylabel(y_msg)

    for i in range(num_agents):
        key = msg + str(i) + msg2
        y = _cal_y(the_type, store[key], init_cash, msg2)
        x=range(len(y))
        col = np.random.uniform(0,1,3)
        disc, line_width = _sel_disc(i, num_trained_agent, msg, msg3)
        plt.plot(x, y, color=col, label=disc, linewidth=line_width) # plotting x, y

    plt.legend()
    plt.title(title)
    plt.show()

def _plot_lv(a_lv_data, lv, start):
    """
    Plot a single level data for all steps.
    """
    col = np.random.uniform(0,1,3)
    x = range(len(a_lv_data))
    y = a_lv_data
    plt.plot(x, y, color=col, label='lvl '+ str(lv-start+1), linewidth=0.3) # , label=disc, linewidth=line_width) # plotting x, y

def _show_lv(lv_start, lv_end, store):
    """
    Display n levels data from lv_start to lv_end-1 for all steps.
    """
    for lv in range(lv_start, lv_end):
        lv_data = get_lv_data(lv, store)
        _plot_lv(lv_data, lv, lv_start)

def _show_obs(start, offset, fig_size, x_msg, y_msg, store, key, title):
    """
    Plot obs data for all steps in all episodes for all agents.
    """
    plt.figure(figsize=fig_size)
    plt.xlabel(x_msg)
    plt.ylabel(y_msg)
    _show_lv(start, start+offset, store[key])
    plt.legend()
    plt.title(title)
    plt.show()

def show_obs(store):
    """
    Display obs for all steps in all episodes from 1 agent from json files.
    """

    bid_size_start = 0
    bid_price_start = 10
    ask_size_start = 20
    ask_price_start = 30
    offset = 10
    fig_size = (25,3)
    x_msg = "step"
    key = "agt_0_obs_list"

    _show_obs(ask_size_start, offset, fig_size, x_msg, "ask size", store, key, 'Ask size for all steps.')
    _show_obs(bid_size_start, offset, fig_size, x_msg, "bid size", store, key, 'Bid size for all steps.')

    _show_obs(ask_price_start, offset, fig_size, x_msg, "ask price", store, key, 'Ask price for all steps.')
    _show_obs(bid_price_start, offset, fig_size, x_msg, "bid price", store, key, 'Bid price for all steps.')
