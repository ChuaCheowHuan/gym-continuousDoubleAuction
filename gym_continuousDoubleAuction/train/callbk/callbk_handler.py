"""
Helper functions that are called in the RLlib's callback.
"""

import numpy as np

def store_eps_hist_data(episode, key):
    """
    Called in episode_end
    """
    data = episode.user_data[key]
    #data[0] = 0 if data[0] is None else data[0]
    episode.custom_metrics[key] = np.mean(data)
    episode.hist_data[key].append(data) # stores a list of steps

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
