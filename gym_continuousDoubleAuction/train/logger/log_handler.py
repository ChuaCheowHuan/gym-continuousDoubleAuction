import numpy as np
import json
import gzip
import os

import ray
        
class NpEncoder(json.JSONEncoder):
    """
    Your codes .... 
    json.dumps(data, cls=NpEncoder)
    """
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        else:
            return super(NpEncoder, self).default(obj)

def create_dir(path):
    try:
        os.mkdir(path)
    except OSError:
        print ("Folder creation failed or folder already exists: %s" % path)
    else:
        print ("Folder created: %s" % path)

def log_g_store(log_g_store_dir, num_agents, experiment_id):
    """
    Store g_store as json file.
    Store only last episode for step data.
    Store all episodes for episodic data.
    """
    g_store = ray.util.get_actor("g_store")
    store = ray.get(g_store.get_storage.remote())

    file_name = str(experiment_id)

    tmp_dict = ray.get(g_store.create_storage.remote(num_agents)) 

    for agt_key, _ in store.items():
               
        tmp_dict[agt_key]["step"]["obs"] = store[str(agt_key)]["step"]["obs"][-1]
        tmp_dict[agt_key]["step"]["act"] = store[agt_key]["step"]["act"][-1] 
        tmp_dict[agt_key]["step"]["reward"] = store[agt_key]["step"]["reward"][-1] 
        tmp_dict[agt_key]["step"]["NAV"] = store[agt_key]["step"]["NAV"][-1] 
        tmp_dict[agt_key]["step"]["num_trades"] = store[agt_key]["step"]["num_trades"][-1]
        tmp_dict[agt_key]["eps"]["policy_reward"] = store[agt_key]["eps"]["policy_reward"]
        tmp_dict[agt_key]["eps"]["reward"] = store[agt_key]["eps"]["reward"]
        tmp_dict[agt_key]["eps"]["NAV"] = store[agt_key]["eps"]["NAV"] 
        tmp_dict[agt_key]["eps"]["num_trades"] = store[agt_key]["eps"]["num_trades"]

    #with open(write_dir + file_name + '.dat', 'w') as outfile:
    #   json.dump(tmp_dict, outfile, indent=3) # write to file in json format:
    with gzip.GzipFile(log_g_store_dir + file_name + '.gzip', 'w') as fout:
        fout.write(json.dumps(tmp_dict, cls=NpEncoder).encode('utf-8'))

def load_g_store(log_g_store_dir, num_agents, experiment_id):
    """
    Load json file to g_store.
    """
    g_store = ray.util.get_actor("g_store")
    tmp_dict = ray.get(g_store.create_storage.remote(num_agents)) 

    for file_name in os.listdir(log_g_store_dir):
        print(file_name)
        if file_name.endswith(str(experiment_id) + '.gzip'):

            #with open(os.path.join(log_g_store_dir, file_name)) as json_file:
            #    data = json.load(json_file)

            with gzip.GzipFile(log_g_store_dir + file_name, 'r') as fin:
                data = json.loads(fin.read().decode('utf-8'))

                for agt_key, _ in data.items():
                    tmp_dict[agt_key]["step"]["obs"].append(data[agt_key]["step"]["obs"])
                    tmp_dict[agt_key]["step"]["act"].append(data[agt_key]["step"]["act"])
                    tmp_dict[agt_key]["step"]["reward"].append(data[agt_key]["step"]["reward"])
                    tmp_dict[agt_key]["step"]["NAV"].append(data[agt_key]["step"]["NAV"])
                    tmp_dict[agt_key]["step"]["num_trades"].append(data[agt_key]["step"]["num_trades"])
                    tmp_dict[agt_key]["eps"]["policy_reward"].append(data[agt_key]["eps"]["policy_reward"])
                    tmp_dict[agt_key]["eps"]["reward"].append(data[agt_key]["eps"]["reward"])
                    tmp_dict[agt_key]["eps"]["NAV"].append(data[agt_key]["eps"]["NAV"])
                    tmp_dict[agt_key]["eps"]["num_trades"].append(data[agt_key]["eps"]["num_trades"])

    ray.get(g_store.set_storage.remote(tmp_dict))        
