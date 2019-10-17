import numpy as np
import random
from gym import spaces

from gym import spaces
from sklearn.utils import shuffle

class Action_Helper():
    def __init__(self):
        super(Action_Helper, self).__init__()

    def disc_act(self):
        # Set price according to price_code 0 to 11 where price_code 1 to 10 correspond to slot in agg_LOB (mkt depth table)
        # 0 & 11 are the border cases where they could be the lowest or highest bid respectively
        # if order is on the ask side,
        # 0 & 11 are the border cases where they could be the highest or lowest ask respectively
        act_space = spaces.Tuple((spaces.Discrete(5), # none, bid market, ask market, bit limit, ask limit, (0 to 4)
                                  spaces.Discrete(100), # size
                                  spaces.Discrete(12), # price based on mkt depth from 0 to 11
                                ))
        return act_space

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
            #act = self.set_action(key, value) # for discrete act space
            act = self.set_action_mkt_depth(key, value) # for discrete act space based on mkt_depth
            acts.append(act)
        return acts

    # for discrete act space
    def set_action(self, ID, nn_out_act):
        min_size = 1
        min_tick = 1

        print('nn_out_act:', nn_out_act)

        act = {}
        act["ID"] = ID
        act["type"], act["side"] = self.set_type_side((nn_out_act[0]))

        act["size"] = (nn_out_act[1] + min_size) * 1.0 # +min_size as size or price can't be 0, *1 for float
        act["price"] = (nn_out_act[2] + min_tick) * 1.0 # +tick_size as size or price can't be 0, *1 for float

        print('act:', act)

        return act

    # for discrete act space based on mkt_depth
    def set_action_mkt_depth(self, ID, nn_out_act):
        min_size = 1
        min_tick = 1
        fl_div = 10

        print('nn_out_act:', nn_out_act)

        act = {}
        act["ID"] = ID
        act["type"], act["side"] = self.set_type_side((nn_out_act[0]))

        if act["type"] == 'market':
            act["size"] = ((nn_out_act[1] // fl_div) + min_size) * 1.0 # +min_size as size or price can't be 0, *1 for float
        else:
            act["size"] = (nn_out_act[1] + min_size) * 1.0 # +min_size as size or price can't be 0, *1 for float

        if act["type"] == 'market':
            act["price"] = (nn_out_act[2] + min_tick) * 1.0 # +tick_size as size or price can't be 0, *1 for float
        else:
            act["price"] = self._set_price(min_tick, act["side"], nn_out_act[2])

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

    # agg_LOB is [bid_size_list, bid_price_list, ask_size_list, ask_price_list] # list of np.arrays
    # Set price according to price_code 0 to 11 where price_code 1 to 10 correspond to slot in agg_LOB (mkt depth table) on one side
    # if order is on the bid side,
    # 0 & 11 are the border cases where they could be the lowest or highest bid respectively
    # if order is on the ask side,
    # 0 & 11 are the border cases where they could be the highest or lowest ask respectively
    def _set_price(self, min_tick, side, price_code):
        min_tick = 1
        max_price = 101
        if side == 'bid':
            price_array = self.agg_LOB[1] # bid price np.array
            if price_code == 0: # lower by 1 tick or equal to lowest bid
                # price_array[9] is the lowest bid
                set_price = self.lower(min_tick, max_price, min(price_array))
            elif price_code == 11: # higher by 1 tick than highest bid
                # price_array[0] is the highest bid
                set_price = self.higher(min_tick, max_price, max(price_array)) # one tick higher than the highest bid
            else: # price_code between 1 to 10
                set_price = self.within_price_slot(min_tick, price_code, price_array)
        else: # 'ask' side is negative on agg_LOB for both size & price
            price_array = self.agg_LOB[3] # ask price np.array
            if price_code == 0:
                # price_array[9] is the highest ask
                set_price = self.higher(min_tick, max_price, abs(min(price_array))) # one tick higher than the highest ask
            elif price_code == 11:
                # price_array[0] is the lowest ask
                set_price = self.lower(min_tick, max_price, abs(max(price_array)))
            else: # price_code between 1 to 10
                set_price = self.within_price_slot(min_tick, price_code, price_array)

        return set_price * 1.0

    def higher(self, min_tick, max_price, price):
        if price == 0:
            set_price = random.randrange(min_tick, max_price, min_tick)
        else:
            set_price = price + min_tick # one tick higher than the highest bid
        return set_price

    def lower(self, min_tick, max_price, price):
        if price == 0:
            set_price = random.randrange(min_tick, max_price, min_tick)
        elif price == min_tick:
            set_price = min_tick
        else:
            set_price = price - min_tick
        return set_price

    def within_price_slot(self, min_tick, price_code, price_array):
        set_price = min_tick
        for i, price in enumerate(price_array):
            if price_code == i+1:
                if price == 0:
                    set_price = price_code * min_tick
                else:
                    set_price = abs(price)
                break
        return set_price

    # process actions for all agents
    def do_actions(self, actions):
        for action in actions:
            ID = action.get("ID")
            type = action.get("type")
            side = action.get("side")
            size = action.get("size")
            price = action.get("price")
            trader = self.agents[ID]
            self.trades, self.order_in_book = trader.place_order(type, side, size, price, self.LOB, self.agents)
        return self.trades, self.order_in_book
