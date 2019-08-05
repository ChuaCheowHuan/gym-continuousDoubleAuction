import numpy as np
import pandas as pd

class Reward_Helper(object):

    # reward per t step
    # reward = nav@t+1 - nav@t
    def set_reward(self, rewards, trader):
        rewards[trader.ID] = float(trader.acc.nav - trader.acc.prev_nav)
        return rewards

    # ********** TEST **********
    # ********** TODO **********
    # store and use min, max reward
    """
    import numpy as np

    a = np.random.rand(3,2)

    # Normalised [0,1]
    # np.ptp is peak-to-peak
    b = (a - np.min(a))/np.ptp(a)

    # Normalised [0,255] as integer
    c = 255*(a - np.min(a))/np.ptp(a).astype(int)

    # Normalised [-1,1]
    d = 2.*(a - np.min(a))/np.ptp(a)-1

    # standardization
    e = (a - np.mean(a)) / np.std(a)
    """
    def norm_step_rewards(self, rewards):
        print('rewards:', rewards)

        # rewards is python dictionary
        pd_series = pd.Series(rewards)
        rewards_arr = pd_series.values # extract values as numpy array
        if np.ptp(rewards_arr).astype(int) == 0:
            normalized_rewards_arr = np.zeros_like(rewards_arr)
        else:
            normalized_rewards_arr = 255*(rewards_arr - np.min(rewards_arr)) / np.ptp(rewards_arr).astype(int)

        df = pd.DataFrame(normalized_rewards_arr)
        normalized_rewards_dict = dict(zip(df.index, df.values.tolist()))
        print('normalized_rewards_dict:', normalized_rewards_dict)

        normalized_rewards_dict = self.rm_list_in_dict(normalized_rewards_dict)

        return normalized_rewards_dict

    def rm_list_in_dict(self, dict):
        result_dict = {}
        for key, val in dict.items():
            result_dict[key] = val[0]
        print('result_dict:', result_dict)

        return result_dict
