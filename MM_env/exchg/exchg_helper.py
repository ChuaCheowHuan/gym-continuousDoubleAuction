import numpy as np

from sklearn.utils import shuffle

class Exchg_Helper(object):

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

    def rand_exec_seq(self, actions, seed):
        # seed for reproducible behavior
        actions = shuffle(actions, random_state=seed)
        return actions

    # process actions for all agents
    def do_actions(self, actions):
        for action in actions:
            # use dict
            ID = action.get("ID")
            type = action.get("type")
            side = action.get("side")
            size = action.get("size")
            price = action.get("price")
            trader = self.agents[ID]
            self.trades, self.order_in_book = trader.place_order(type, side, size, price, self.LOB, self.agents)
        return self.trades, self.order_in_book

    def prep_next_state(self):
        self.LOB_NEXT_STATE = self.LOB_state() # LOB state at t+1 after processing LOB
        state_diff = self.state_diff(self.LOB_STATE, self.LOB_NEXT_STATE)
        return state_diff

    def set_step_outputs(self, state_input):
        next_states, rewards, dones, infos = {},{},{},{}
        for trader in self.agents:
            next_states = self.set_next_state(next_states, trader, state_input)
            rewards = self.set_reward(rewards, trader)
            dones = self.set_done(dones, trader)
            infos = self.set_info(infos, trader)
        dones = self.set_all_done(dones)
        return next_states, rewards, dones, infos

    def set_next_state(self, next_states, trader, state_input):
        next_states[trader.ID] = state_input
        return next_states

    # reward per t step
    # reward = nav@t+1 - nav@t
    def set_reward(self, rewards, trader):
        rewards[trader.ID] = trader.acc.nav - trader.acc.prev_nav
        return rewards

    def set_done(self, dones, trader):
        if trader.acc.nav <= 0: # when trader is broke, he's done ;)
            dones[trader.ID] = 1
            self.done_set.add(trader.ID) # done_set is a set while done is a dictionary
        else:
            dones[trader.ID] = 0
        return dones

    def set_all_done(self, dones):
        dones["__all__"] = len(self.done_set) == len(self.agents) # set to 1 if length are equal
        if self.t_step > self.max_step-1:
            dones["__all__"] = 1 # set to 1 if episode is completed
        return dones

    def set_info(self, infos, trader):
        #info = trader.acc.nav - trader.acc.prev_nav
        infos[trader.ID] = ''
        return infos

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

    # price_map is an OrderTree object (SortedDict object)
    # SortedDict object has key & value
    # key is price, value is an OrderList object
    def LOB_state(self):
        k_rows = 10
        bid_price_list = np.zeros(k_rows)
        bid_size_list = np.zeros(k_rows)
        ask_price_list = np.zeros(k_rows)
        ask_size_list = np.zeros(k_rows)

        # LOB
        if self.LOB.bids != None and len(self.LOB.bids) > 0:
            for k, set in enumerate(reversed(self.LOB.bids.price_map.items())):
                if k < k_rows:
                    bid_price_list[k] = set[0] # set[0] is price (key)
                    bid_size_list[k] = set[1].volume # set[1] is an OrderList object (value)
                else:
                    break

        if self.LOB.asks != None and len(self.LOB.asks) > 0:
            for k, set in enumerate(self.LOB.asks.price_map.items()):
                if k < k_rows:
                    ask_price_list[k] = -set[0]
                    ask_size_list[k] = -set[1].volume
                else:
                    break
        # tape
        if self.LOB.tape != None and len(self.LOB.tape) > 0:
            num = 0
            for entry in reversed(self.LOB.tape):
                if num < self.LOB.tape_display_length: # get last n entries
                    #tempfile.write(str(entry['quantity']) + " @ " + str(entry['price']) + " (" + str(entry['timestamp']) + ") " + str(entry['party1'][0]) + "/" + str(entry['party2'][0]) + "\n")
                    num += 1
                else:
                    break
        return (bid_size_list, bid_price_list, ask_size_list, ask_price_list)

    def state_diff(self, LOB_state, LOB_next_state):
        state_diff = []
        for (state_row, next_state_row) in zip(LOB_state, LOB_next_state):
            state_diff.append(next_state_row - state_row)
        return state_diff
