import decimal
import ast
from gym_continuousDoubleAuction.train.helper.helper import str_to_arr

def create_storage(num_agents, prefix, store_suffix):
    """
    Storage for on_train_result callback, use for plotting.
    """
    storage = {}
    for i in range(0, num_agents):
        storage[prefix + str(i) + store_suffix] = []
    return storage

def create_train_policy_list(num_trained_agent, prefix):
    """
    Storage for train_policy_list for declaring train poilicies in trainer config.
    """
    storage = []
    for i in range(0, num_trained_agent):
        storage.append(prefix + str(i))

    print("train_policy_list = ", storage)
    return storage

def get_lv_data(lv, store):
    """
    Get a single level data for all steps.
    """
    lv_data = []
    for val in store: # steps, each step is a obs string
        obs = str_to_arr(val) # convert to 1D array
        lv_data.append(obs[lv])
    return lv_data

def _get_last_eps_steps(the_type, store, key):
    """
    For steps from last episode
    """
    y = []
    for step_str in store[key]:
        step_dict = ast.literal_eval(step_str)
        if the_type == 'NAV':
            y.append(decimal.Decimal(step_dict[the_type]))
        else:
            y.append(step_dict[the_type])
    return y

def get_last_eps_steps(num_agents, the_type, store, prefix, store_suffix):
    """
    For steps from last episode
    """
    y_dict = {}
    for i in range(num_agents):
        key = prefix + str(i) + store_suffix
        y_dict[key] = _get_last_eps_steps(the_type, store, key)
    return y_dict

def get_lv_dict(lv_start, lv_end, store, key):
    """
    Return n levels data from lv_start to lv_end-1 for all steps in a dictionary.
    """
    lv_dict = {}
    for lv in range(lv_start, lv_end):
        lv_data = get_lv_data(lv, store[key])
        #_plot_lv(lv_data, lv, lv_start)
        lv_dict[lv] = lv_data
    return lv_dict
