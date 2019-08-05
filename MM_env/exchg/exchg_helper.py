from .state_helper import State_Helper
from .action_helper import Action_Helper
from .reward_helper import Reward_Helper
from .done_helper import Done_Helper
from .info_helper import Info_Helper

class Exchg_Helper(State_Helper, Action_Helper, Reward_Helper, Done_Helper, Info_Helper):

    # reset traders accounts
    def reset_traders_acc(self):
        for trader in self.agents:
            trader.acc.reset_acc(trader.ID, self.init_cash)

    # update acc for all traders with last price in most recent entry of tape
    def mark_to_mkt(self):
        if len(self.LOB.tape) > 0:
            mkt_price = self.LOB.tape[-1].get('price')
            for trader in self.agents:
                trader.acc.mark_to_mkt(trader.ID, mkt_price)
        return 0

    def set_step_outputs(self, state_input):
        next_states, rewards, dones, infos = {},{},{},{}
        for trader in self.agents:
            next_states = self.set_next_state(next_states, trader, state_input) # dict of tuple of tuples
            rewards = self.set_reward(rewards, trader)
            dones = self.set_done(dones, trader)
            infos = self.set_info(infos, trader)

        # ********** TEST **********
        rewards = self.norm_step_rewards(rewards)

        dones = self.set_all_done(dones)
        return next_states, rewards, dones, infos

    def print_accs(self):
        for trader in self.agents:
            trader.acc.print_acc()
        return 0

    def total_sys_profit(self):
        sum = 0
        for trader in self.agents:
            sum += trader.acc.total_profit
        return sum

    def total_sys_nav(self):
        sum = 0
        for trader in self.agents:
            sum += trader.acc.nav
        return sum
