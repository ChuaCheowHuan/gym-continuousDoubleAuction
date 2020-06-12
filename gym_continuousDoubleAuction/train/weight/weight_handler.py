import numpy as np

def get_trained_policies_name(policies, num_trained_agent):
    """
    Get index of the max reward of the trained policies in most recent episode.
    """

    train_policies_name = []
    i = 0
    for k,v in policies.items():
        if i < num_trained_agent:
            train_policies_name.append(k)
        i = i + 1
    return train_policies_name

def get_max_reward_ind(info, train_policies_name):
    """
    Get index of the max reward of the trained policies in most recent episode.
    """

    recent_policies_rewards = []
    for name in train_policies_name:
        key = 'policy_' + str(name) + '_reward'
        v = info['result']['hist_stats'][key]
        recent_policies_rewards.append(v[0])

    max_reward_ind = np.argmax(recent_policies_rewards)
    return max_reward_ind

def _cp_weight(trainer, src, dest):
    """
    Copy weights of source policy to destination policy.
    """

    P0key_P1val = {}
    for (k,v), (k2,v2) in zip(trainer.get_policy(dest).get_weights().items(),
                              trainer.get_policy(src).get_weights().items()):
        P0key_P1val[k] = v2

    trainer.set_weights({dest:P0key_P1val,
                         src:trainer.get_policy(src).get_weights()})

    for (k,v), (k2,v2) in zip(trainer.get_policy(dest).get_weights().items(),
                              trainer.get_policy(src).get_weights().items()):
        assert (v == v2).all()

def cp_weight(trainer, train_policies_name, max_reward_policy_name):
    """
    Copy weights of winning policy to weights of other trained policies.
    Winning is defined as getting max reward in the current episode.
    """

    for name in train_policies_name:
        if name != max_reward_policy_name:
            _cp_weight(trainer, max_reward_policy_name, name)
