import math
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import ray

#from gym_continuousDoubleAuction.train.storage.store_handler import get_lv_data

fig_size = (25,10)
#step_window = 100 #int(np.rint(max_step * 0.1))
#eps_window = 15 #int(np.rint(num_iters * 0.1))

def _window_size(y):
    return int(np.rint(len(y) * 0.1))

def _process_list(init_cash, agt_id, step_or_eps, data_key):
    g_store = ray.get_actor("g_store")
    store = ray.get(g_store.get_storage.remote())
    l = store[agt_id][step_or_eps][data_key]

    # print(f"before agt_id:{agt_id}, l:{l}")

    if step_or_eps == "step":
        l = [item for sublist in l for item in sublist]
    

        print(f"after agt_id:{agt_id}, l:{l}")


    if data_key == "reward":
        # l = np.cumsum(l)
        pass
    elif data_key == "NAV":
        # l = [val - init_cash for val in l]         # cumulative returns
        # l = [init_cash - val for val in l]         # cumulative returns
        # l = np.cumsum(l)
        # l = -1 * l
        pass
    elif data_key == "num_trades":
        #l = pd.Series(l).rolling(window=_window_size(l)).mean()
        # l = np.cumsum(l)
        pass
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
