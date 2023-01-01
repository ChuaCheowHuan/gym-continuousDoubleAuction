import numpy as np

class Reward_Helper(object):

    def set_reward(self, rewards, trader, price):
        """
        reward per t step
        reward = nav@t+1 - nav@t
        """
        # print(price)
        # print(type(price))
        trader.acc.cmp_step_nav(price)

        # # maximize NAV
        # rewards[trader.ID] = float(trader.acc.nav)

        NAV_chg = float(trader.acc.step_nav - trader.acc.prev_step_nav)

        # print(f"{trader.ID} {trader.acc.step_nav} {trader.acc.prev_step_nav} {NAV_chg}")

        rewards[trader.ID] = NAV_chg

        # # maximize NAV, minimize num of trades (more trades gets penalized).
        # if NAV_chg >= 0:
        #     rewards[trader.ID] = NAV_chg / (trader.acc.num_trades + 1)
        # else:
        #     rewards[trader.ID] = NAV_chg * (trader.acc.num_trades + 1)

        trader.acc.reward = rewards[trader.ID]

        return rewards
