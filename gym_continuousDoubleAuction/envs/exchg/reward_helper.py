import numpy as np
import pandas as pd

class Reward_Helper(object):

    def set_reward(self, rewards, trader):
        """
        reward per t step
        reward = nav@t+1 - nav@t
        """
        # # maximize NAV
        # rewards[trader.ID] = float(trader.acc.nav)

        NAV_chg = float(trader.acc.nav - trader.acc.prev_nav)

        rewards[trader.ID] = NAV_chg

        # # maximize NAV, minimize num of trades (more trades gets penalized).
        # if NAV_chg >= 0:
        #     rewards[trader.ID] = NAV_chg / (trader.acc.num_trades + 1)
        # else:
        #     rewards[trader.ID] = NAV_chg * (trader.acc.num_trades + 1)

        trader.acc.reward = rewards[trader.ID]

        return rewards
