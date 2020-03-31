from gym_continuousDoubleAuction.train.helper.helper import str_to_arr

def get_lv_data(lv, store):
    """
    Get a single level data for all steps.
    """
    lv_data = []
    for val in store: # steps, each step is a obs string
        obs = str_to_arr(val) # convert to 1D array
        lv_data.append(obs[lv])
    return lv_data

def create_storage(num_agents, msg, msg2):
    """
    Storage for on_train_result callback, use for plotting.
    """
    storage = {}
    for i in range(0, num_agents):
        storage[msg + str(i) + msg2] = []
    return storage

def create_train_policy_list(num_trained_agent, msg):
    """
    Storage for train_policy_list for declaring train poilicies in trainer config.
    """
    storage = []
    for i in range(0, num_trained_agent):
        storage.append(msg + str(i))

    print("train_policy_list = ", storage)

    return storage
