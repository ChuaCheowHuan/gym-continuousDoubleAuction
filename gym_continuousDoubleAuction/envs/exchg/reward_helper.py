import numpy as np
import pandas as pd

class Reward_Helper(object):

    def set_reward(self, rewards, trader):
        """
        reward per t step
        reward = nav@t+1 - nav@t
        """
        NAV_chg = float(trader.acc.nav - trader.acc.prev_nav)

        # # maximize NAV
        # rewards[trader.ID] = float(trader.acc.nav)

        rewards[trader.ID] = NAV_chg

        # # maximize NAV, minimize num of trades (more trades gets penalized).
        # if NAV_chg >= 0:
        #     rewards[trader.ID] = NAV_chg / (trader.acc.num_trades + 1)
        # else:
        #     rewards[trader.ID] = NAV_chg * (trader.acc.num_trades + 1)

        trader.acc.reward = rewards[trader.ID]

        # print(
        #     trader.acc.ID, 
        #     trader.acc.cash, trader.acc.cash_on_hold,
        #     trader.acc.pos_val, trader.acc.net_pos, 
        #     trader.acc.prev_nav, trader.acc.nav)

        # if len(rewards) == 4 and sum(rewards.values()) != 400000.0:
        #     print(rewards)
        #     print(sum(rewards.values()))
        #     print(trader.acc.print_acc(str(trader.ID)))

        #     import sys
        #     sys.exit("")


        return rewards
