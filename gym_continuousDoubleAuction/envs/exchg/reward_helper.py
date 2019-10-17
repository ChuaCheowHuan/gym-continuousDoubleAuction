import numpy as np
import pandas as pd

class Reward_Helper(object):

    # reward per t step
    # reward = nav@t+1 - nav@t
    def set_reward(self, rewards, trader):
        rewards[trader.ID] = float(trader.acc.nav - trader.acc.prev_nav)
        return rewards
