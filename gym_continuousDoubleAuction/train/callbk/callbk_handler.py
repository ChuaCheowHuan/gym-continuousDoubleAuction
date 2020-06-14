"""
Helper functions that are called in the RLlib's callback.
"""

import numpy as np

def create_step_callbk_list(num_agents, episode, suffix):
    """
    Called in on_episode_start

    user_data dicts at 100000 items max, will auto replace old with new item at 1st index.
    hist_data dicts at 100 items max, will auto replace old with new item at 1st index.
    """
    for i in range(num_agents):
        key = "agt_" + str(i) + suffix
        episode.user_data[key] = []
        episode.hist_data[key] = []

def create_callbk_list(num_agents, episode, suffix):
    """
    Called in on_episode_start
    """
    for i in range(num_agents):
        key = "agt_" + str(i) + suffix
        episode.hist_data[key] = []

def store_user_obs(num_agents, episode, suffix, msg2):
    """
    Called in on_episode_step

    store steps into user_data
    """
    for i in range(num_agents):
        key = "agt_" + str(i) + suffix
        val = episode.last_raw_obs_for(i)
        #val = episode.last_observation_for(i)
        episode.user_data[key].append(val)

def store_user(num_agents, episode, suffix, msg2):
    """
    Called in on_episode_step

    store steps into user_data
    """
    for i in range(num_agents):
        key = "agt_" + str(i) + suffix
        val = episode.last_info_for(i).get(msg2)
        if val is None:     # ISSUE: CHECK THE INFO DICT FROM ENV FOR None.
            continue # goto next agent
            #val = 0.0
        episode.user_data[key].append(float(val))           # stores a step

        #episode.user_data[key].append(str(val))
        #episode.user_data[key].append(unicode(val))

def store_step_hist(num_agents, episode, suffix):
    """
    Called in on_episode_end

    store steps into hist_data
    """
    for i in range(num_agents):
        key = "agt_" + str(i) + suffix
        episode.custom_metrics[key] = np.mean(episode.user_data[key])
        episode.hist_data[key].append(episode.user_data[key]) # stores a list of steps

def store_hist(num_agents, episode, suffix):
    """
    Called in on_episode_end

    store eps into hist_data
    """
    for i in range(num_agents):
        key = "agt_" + str(i) + "_" + suffix
        episode.hist_data[key].append(float(episode.last_info_for(i)[suffix])) # stores only a single value
        #episode.hist_data[key].append(str(episode.last_info_for(i)[msg])) # stores only a single value
        #episode.hist_data[key].append(unicode(episode.last_info_for(i)[msg])) # stores only a single value

def access_sample_batches(MultiAgentBatch_policy_batches):
    """
    Called in on_sample_end

    Access sample batches.

    Notes:
        https://github.com/ray-project/ray/blob/master/rllib/policy/sample_batch.py
    """

    for k,v in MultiAgentBatch_policy_batches.items():
        print("MultiAgentBatch_policy_batches k={}".format(k))
        for r in v.rows():
            for k2,v2 in r.items():
                print("k2={}".format(k2)) # 18 keys
            break
        break # break after 1st policy

def all_steps_store_obs(info, store, prefix, suffix, msg3):
    """
    Called in on_train_results
    """
    i = 0
    for k,v in store.items():
        key = prefix + str(i) + suffix
        v.append(info["result"]["hist_stats"][key]) # stores latest list
        #p_str = msg + str(i) + msg3
        #print(p_str.format(v[-1])) # print last item in v
        i = i + 1

    #print("store", store)

def all_steps_store(info, store, prefix, suffix, msg3):
    """
    Called in on_train_results
    """
    i = 0
    for k,v in store.items():
        key = prefix + str(i) + suffix
        v.append(info["result"]["hist_stats"][key][0]) # stores latest list
        #p_str = msg + str(i) + msg3
        #print(p_str.format(v[-1])) # print last item in v
        i = i + 1

    #print("store", store)

def all_eps_store(info, store, prefix, suffix, msg3):
    """
    Called in on_train_results
    """
    i = 0
    for k,v in store.items():
        key = prefix + str(i) + suffix
        v.append(info["result"]["hist_stats"][key][0]) # stores latest value
        #p_str = msg + str(i) + msg3
        #print(p_str.format(v[-1])) # print last item in v
        i = i + 1

    #print("store", store)
