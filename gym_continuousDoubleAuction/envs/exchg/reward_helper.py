import numpy as np
import pandas as pd

class Reward_Helper(object):

    def set_reward(self, rewards, trader):
        """
        reward per t step
        reward = nav@t+1 - nav@t
        """

        rewards[trader.ID] = float(trader.acc.nav - trader.acc.prev_nav)

        return rewards
