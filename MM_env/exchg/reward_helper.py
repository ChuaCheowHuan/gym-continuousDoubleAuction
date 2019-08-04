class Reward_Helper(object):

    # reward per t step
    # reward = nav@t+1 - nav@t
    def set_reward(self, rewards, trader):
        rewards[trader.ID] = float(trader.acc.nav - trader.acc.prev_nav)
        return rewards

    # ********** TODO **********
    def norm_rewards(self, rewards):
        #for r in rewards:

        return rewards
