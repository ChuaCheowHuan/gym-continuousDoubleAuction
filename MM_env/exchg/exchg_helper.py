import numpy as np
import random

from sklearn.utils import shuffle

class Exchg_Helper(object):

    # reset traders LOB observations/states
    def reset_traders_agg_LOB(self):
        states = {}
        for trader in self.agents:
            states[trader.ID] = self.set_agg_LOB()
        return states

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

        print('actions:', actions)

        # seed for reproducible behavior
        shuffle_actions = shuffle(actions, random_state=seed)

        print('shuffle_actions:', shuffle_actions)

        return shuffle_actions

    # called in step function in exchg before randomizing/processing orders
    def set_actions(self, nn_out_acts):
        acts = []
        #for i, nn_out_act in enumerate(nn_out_acts):
        #    act = set_action(self, i, nn_out_act):
        for key, value in nn_out_acts.items():
            act = self.set_action(key, value)
            acts.append(act)
        return acts

    def set_action(self, ID, nn_out_act):

        print('nn_out_act:', nn_out_act)

        act = {}
        act["ID"] = ID
        act["type"], act["side"] = self.set_type_side(round(nn_out_act[0][0]))

        act["size"] = round(nn_out_act[1][0]).item()
        act["price"] = round(nn_out_act[2][0]).item()

        print('act:', act)

        return act

    def set_type_side(self, type_side):
        type = None
        side = None
        if type_side == 0:
            type = None
            side = None
        elif type_side == 1:
            type = 'market'
            side = 'bid'
        elif type_side == 2:
            type = 'market'
            side = 'ask'
        elif type_side == 3:
            type = 'limit'
            side = 'bid'
        else:
            type = 'limit'
            side = 'ask'
        return type, side

    def _test_rand_act(self):
        type_side = np.random.randint(0, 5, size=1) # type_side: None=0, market_bid=1, market_ask=2, limit_bid=3, limit_ask=4
        size = (random.randrange(1, 100, 1)) # size in 100s from 0(min) to 1000(max)
        price = (random.randrange(1, 10, 1)) # price from 1(min) to 100(max)
        type, side = self.set_type_side(type_side)
        return type, side, size, price

    # process actions for all agents
    def do_actions(self, actions):
        for action in actions:
            ID = action.get("ID")
            type = action.get("type")
            side = action.get("side")
            size = action.get("size")
            price = action.get("price")
            trader = self.agents[ID]

            # ********** TEST RANDOM ACTIONS **********
            #type, side, size, price = self._test_rand_act()

            self.trades, self.order_in_book = trader.place_order(type, side, size, price, self.LOB, self.agents)
        return self.trades, self.order_in_book

    def prep_next_state(self):
        self.agg_LOB_aft = self.set_agg_LOB() # LOB state at t+1 after processing LOB

        state_diff = self.state_diff(self.agg_LOB, self.agg_LOB_aft)
        #state_diff = self.agg_LOB_aft

        return state_diff

    def set_next_state(self, next_states, trader, state_input):
        next_states[trader.ID] = state_input
        return next_states

    # reward per t step
    # reward = nav@t+1 - nav@t
    def set_reward(self, rewards, trader):

        rewards[trader.ID] = float(trader.acc.nav - trader.acc.prev_nav)
        #rewards[trader.ID] = float(trader.acc.nav - trader.acc.prev_nav) * (1+trader.ID)

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
        infos[trader.ID] = {}
        return infos

    def set_step_outputs(self, state_input):
        next_states, rewards, dones, infos = {},{},{},{}
        for trader in self.agents:
            next_states = self.set_next_state(next_states, trader, state_input) # dict of tuple of tuples
            rewards = self.set_reward(rewards, trader)
            dones = self.set_done(dones, trader)
            infos = self.set_info(infos, trader)
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

    # price_map is an OrderTree object (SortedDict object)
    # SortedDict object has key & value
    # key is price, value is an OrderList object
    def set_agg_LOB(self):
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
        return [bid_size_list, bid_price_list, ask_size_list, ask_price_list] # list of np.arrays

    def state_diff(self, agg_LOB, agg_LOB_aft):
        state_diff = []
        #state_diff = np.array()
        for (state_row, next_state_row) in zip(agg_LOB, agg_LOB_aft):
            diff = next_state_row - state_row
            list_diff = list(diff)
            state_diff.append(list_diff)
        state_diff = np.array(state_diff)

        print('state_diff.shape:', state_diff.shape)

        return state_diff
