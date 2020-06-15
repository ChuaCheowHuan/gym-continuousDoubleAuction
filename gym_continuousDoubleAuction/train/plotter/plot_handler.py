import math
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import ray

from gym_continuousDoubleAuction.train.storage.store_handler import get_lv_data

fig_size = (25,10)
#step_window = 100 #int(np.rint(max_step * 0.1))
#eps_window = 15 #int(np.rint(num_iters * 0.1))

def _window_size(y):
    return int(np.rint(len(y) * 0.1))

def _cal_y(the_type, a_list, init_cash, store_suffix):
    """
    Return y values for different types.
    """
    if the_type == "reward":
        y = np.cumsum(a_list)
    elif the_type == "NAV":
        y = np.cumsum([val - init_cash for val in a_list])
    else:
        if store_suffix == "_num_trades_step_list" or store_suffix == 'num_trades_dict':
            y = pd.Series(a_list).rolling(window=_window_size(a_list)).mean()
        else:
            y = pd.Series(a_list).rolling(window=_window_size(a_list)).mean()

    return y

def _sel_disc(i, num_trained_agent, prefix, name_suffix):
    """
    Set legend message & line width.
    """
    if i < num_trained_agent:
        disc = prefix + str(i) + name_suffix
        line_width = 5
    else:
        disc = prefix + str(i) + '_random'
        line_width = 1

    return disc, line_width

def plot_steps(init_cash, num_agents, num_trained_agent, the_type, store, prefix, store_suffix, name_suffix, x_msg, y_msg, title):
    """
    Plot all steps in all episodes for all agents.
    """
    plt.figure(figsize=fig_size)
    plt.xlabel(x_msg)
    plt.ylabel(y_msg)

    for i in range(num_agents):
        key = prefix + str(i) + store_suffix
        col = np.random.uniform(0,1,3)
        flat_list = [item for sublist in store[key] for item in sublist]
        y = _cal_y(the_type, flat_list, init_cash, store_suffix)
        x=range(len(y))
        disc, line_width = _sel_disc(i, num_trained_agent, prefix, name_suffix)
        plt.plot(x, y, color=col, label=disc, linewidth=line_width) # plotting x, y

    plt.legend()
    plt.title(title)
    plt.show()

def plot_eps(init_cash, num_agents, num_trained_agent, the_type, store, prefix, store_suffix, name_suffix, x_msg, y_msg, title):
    """
    Plot all episodes for all agents.
    """
    plt.figure(figsize=fig_size)
    plt.xlabel(x_msg)
    plt.ylabel(y_msg)

    for i in range(num_agents):
        key = prefix + str(i) + store_suffix
        y = _cal_y(the_type, store[key], init_cash, store_suffix)
        x=range(len(y))
        col = np.random.uniform(0,1,3)
        disc, line_width = _sel_disc(i, num_trained_agent, prefix, name_suffix)
        plt.plot(x, y, color=col, label=disc, linewidth=line_width) # plotting x, y

    plt.legend()
    plt.title(title)
    plt.show()

def plot_last_eps_steps(y_dict, num_trained_agent, the_type, init_cash, prefix, store_suffix, name_suffix, y_label, title):
    """
    For steps from last episode
    """
    plt.figure(figsize=fig_size)
    plt.xlabel("step")
    plt.ylabel(y_label)
    i=0
    for k,v in y_dict.items():
        #print("{}, {}".format(k, v))
        x=range(len(v))
        y = _cal_y(the_type, v, init_cash, store_suffix)
        #print(y)
        col = np.random.uniform(0,1,3)
        disc, line_width = _sel_disc(i, num_trained_agent, prefix, name_suffix)
        plt.plot(x, y, color=col, label=disc, linewidth=line_width) # plotting x, y
        i+=1

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

def _show_obs(start, offset, x_msg, y_msg, store, key, title):
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
    x_msg = "step"
    key = "agt_0_obs_list"

    _show_obs(ask_size_start, offset, x_msg, "ask size", store, key, 'Ask size for all steps.')
    _show_obs(bid_size_start, offset, x_msg, "bid size", store, key, 'Bid size for all steps.')

    _show_obs(ask_price_start, offset, x_msg, "ask price", store, key, 'Ask price for all steps.')
    _show_obs(bid_price_start, offset, x_msg, "bid price", store, key, 'Bid price for all steps.')

def plot_imb(store, title, y_label):
    plt.figure(figsize=fig_size)
    plt.xlabel("step")
    plt.ylabel(y_label)
    for k,v in store.items():
        x = range(len(v))
        y = v
        col = np.random.uniform(0,1,3)
        plt.plot(x, y, color=col, label='lv_'+str(k), linewidth=0.8)
        #break
    plt.legend()
    plt.title(title)
    plt.show()

def plot_sum_imb(store, title, y_label):
    plt.figure(figsize=fig_size)
    plt.xlabel("step")
    plt.ylabel(y_label)
    y = store
    x = range(len(y))
    col = np.random.uniform(0,1,3)
    plt.axhline(y=0.0, color='black', label='size=0', linewidth=0.5, linestyle='-')
    plt.plot(x, y, color='b', label='sum of all levels', linewidth=0.75)
    y_MA = pd.Series(y).rolling(window=_window_size(y)).mean()
    plt.plot(x, y_MA, color='black', label='MA sum of all levels', linewidth=1)
    plt.legend()
    plt.title(title)
    plt.show()

def subplot_lv(lv_dict, offset, fig_size, title, y_label):
    fig, axs = plt.subplots(10, figsize=(25,25), sharex=True, sharey=True)
    fig.suptitle(title, x=0.5, y=0.1, verticalalignment='top', fontsize=20, fontweight='bold')

    for i, _ in enumerate(axs):
        if title == 'order imbalance' or title == 'midpoint price':
                x = range(len(lv_dict[str(offset)]))
                axs[i].plot(x, lv_dict[str(i + offset)], color=np.random.uniform(0,1,3))
        else:
                x = range(len(lv_dict[offset]))
                axs[i].plot(x, lv_dict[i + offset], color=np.random.uniform(0,1,3))
        axs[i].set(ylabel='lv_' + str(i+1) + y_label)
    axs[i].set(xlabel='step')

def _process_list(init_cash, agt_id, step_or_eps, data_key):
    g_store = ray.util.get_actor("g_store")
    store = ray.get(g_store.get_storage.remote())
    l = store[agt_id][step_or_eps][data_key]
    if step_or_eps == "step":
        l = [item for sublist in l for item in sublist]

    if data_key == "reward":
        l = np.cumsum(l)
    elif data_key == "NAV":
        l = [val - init_cash for val in l]         # cumulative returns
        l = np.cumsum(l)
    elif data_key == "num_trades":
        l = pd.Series(l).rolling(window=_window_size(l)).mean()
        l = np.cumsum(l)
    else:
        l = []

    return l

def plot_storage(num_agents, init_cash, x_label="step", ylabel="reward", fig_size=(25, 10)):
    sq_rt = np.sqrt(num_agents)
    rnd = math.ceil(sq_rt)
    num_del = rnd**2 - num_agents           # num of unused axes to hide.

    fig, _ = plt.subplots(rnd, rnd, figsize=fig_size, sharex=False, sharey=True)
    axes = fig.get_axes()
    for agt_id in range(num_agents):
        pl = _process_list(init_cash, "agt_" + str(agt_id), x_label, ylabel)
        axes[agt_id].plot(range(len(pl)), pl, label='agt_'+str(agt_id), color=np.random.uniform(0,1,3))
        axes[agt_id].legend()
        axes[agt_id].set(xlabel=x_label, ylabel=ylabel)
        #axes[agt_id].label_outer()

    # Hide unused axis.
    for i in range(num_del):
        axes[-(i+1)].set_axis_off()

def plot_LOB_subplot(store, depth, y_label, fig_size=(25,5)):
    #store = [item for sublist in store for item in sublist]
    fig, axs = plt.subplots(depth, figsize=(25,25), sharex=True, sharey=True)
    for i, _ in enumerate(axs):
        x = range(len(store[i]))
        y = store[i]
        axs[i].plot(x, y , color=np.random.uniform(0,1,3))
        axs[i].set(ylabel='lv_' + str(i+1) + y_label)
    axs[i].set(xlabel='step')

def plot_sum_ord_imb(sum_ord_imb_store, y_label, fig_size=(25,5)):
    plt.figure(figsize=fig_size)
    plt.xlabel("step")
    plt.ylabel(y_label)
    x = range(len(sum_ord_imb_store))
    y = sum_ord_imb_store
    plt.plot(x, y, color=np.random.uniform(0,1,3),label=y_label, linewidth=0.7)

    y_MA = pd.Series(y).rolling(window=_window_size(y)).mean()
    plt.plot(x, y_MA, color='black', label='MA', linewidth=1)

    plt.legend()
    plt.show()

def plot_mid_prices(mid_price_store, y_label="mid_prices", fig_size=(25,5)):
    plt.figure(figsize=fig_size)
    plt.xlabel("step")
    plt.ylabel(y_label)
    for i, row in enumerate(mid_price_store):
        x = range(len(row))
        y = row
        plt.plot(x, y, color=np.random.uniform(0,1,3), label="lv_" + str(i+1), linewidth=0.7)

    plt.legend()
    plt.show()    
