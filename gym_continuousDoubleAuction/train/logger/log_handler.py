import json
import os

calbk_counter = 0
file_num = 0

def log_json(agt_id, eps_id, sample_obj, write_dir):
    """
    Output as training data as json files.
    """

    global file_num
    file_name = str(file_num) + '_' + str(agt_id) + '_' + str(eps_id)
    tmp_dict = {}
    tmp_dict["eps"] = {}
    for i,r in enumerate(sample_obj.rows()): # each row is a step dictionary
        tmp_dict["eps"][str(i)] = {}
        for k,v in r.items():
            tmp_dict["eps"][str(i)][k] = str(v)

        with open(write_dir + file_name + '.txt', 'w') as outfile:
            json.dump(tmp_dict, outfile, indent=3) # write to file in json format:
    file_num = file_num + 1

def _load_json(agent_ID, max_step, obs_store, act_store, data):
    """
    Load 1 json file (1 episode) to memory for 1 agent
    """
    key_obs = 'agt' + '_' + agent_ID + '_obs_list'
    key_act = 'agt' + '_' + agent_ID + '_act_list'
    for i in range(max_step):
        obs_store[key_obs].append(data["eps"][str(i)]["obs"])
        act_store[key_act].append(data["eps"][str(i)]["actions"])

        #print("{}, obs_store = {}".format(key_obs, obs_store[key_obs][i]))
        #print("{}, act_store = {}".format(key_act, act_store[key_act][i]))
        #if i == 1:
        #    break

def load_json(write_dir, max_step, obs_store, act_store):
    """
    Load all json files to memory.
    """
    for file_name in os.listdir(write_dir):
        print(file_name)
        if file_name.endswith('.txt'):
            with open(os.path.join(write_dir, file_name)) as json_file:
                data = json.load(json_file)
                split_words = file_name.split('_')
                #print("split_words", split_words)
                agent_ID = split_words[1]

                _load_json(agent_ID, max_step, obs_store, act_store, data)

def log_eps(write_eps_dir, file_name, store):
    """
    Log episode data from trainer callback.
    """
    with open(write_eps_dir + file_name + '.txt', 'w') as outfile:
        json.dump(store, outfile, indent=3) # write to file in json format:

def load_eps(write_eps_dir, store):
    """
    Load episode data to memory storage.
    """
    for file_name in os.listdir(write_eps_dir):
        #print(file_name)
        if file_name == 'reward.txt':
            with open(os.path.join(write_eps_dir, file_name)) as json_file:
                store = json.load(json_file)
                #print(store)
