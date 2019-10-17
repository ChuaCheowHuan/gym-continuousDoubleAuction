import numpy as np
import random
from gym import spaces

from .norm_action import Norm_Action

from gym import spaces
from sklearn.utils import shuffle

class Action_Helper(Norm_Action):
    def __init__(self):
        super(Action_Helper, self).__init__()

    def disc_act(self):
        #self.action_space = spaces.MultiDiscrete([5, 100, 100]) # type_side, size, price
        """
        act_space = spaces.Tuple((spaces.Discrete(5), # none, bid market, ask market, bit limit, ask limit
                                  spaces.Discrete(100), # size
                                  spaces.Discrete(100), # price
                                ))
        """
        # Set price according to price_code 0 to 11 where price_code 1 to 10 correspond to slot in agg_LOB (mkt depth table)
        # 0 & 11 are the border cases where they could be the lowest or highest bid respectively
        # if order is on the ask side,
        # 0 & 11 are the border cases where they could be the highest or lowest ask respectively
        act_space = spaces.Tuple((spaces.Discrete(5), # none, bid market, ask market, bit limit, ask limit, (0 to 4)
                                  spaces.Discrete(100), # size
                                  spaces.Discrete(12), # price based on mkt depth from 0 to 11
                                ))
        return act_space

    def cont_act(self):
        act_space = spaces.Tuple((spaces.Box(low=0.0, high=4.0, shape=(1,)),
                                  spaces.Box(low=1.0, high=1000.0, shape=(1,)),
                                  spaces.Box(low=1.0, high=100.0, shape=(1,)),
                                ))
        """
        # hybrid or parametric action space
        act_space = spaces.Tuple((spaces.Discrete(5),
                                  spaces.Box(low=1.0, high=999.0, shape=(1,)),
                                  spaces.Box(low=1.0, high=999.0, shape=(1,)),
                                ))
        """
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
            act = self.set_action(key, value)
            acts.append(act)
        return acts

    # ********** TEST **********
    # for cont act space norm nn outputs
    def set_action_t(self, ID, nn_out_act):

        print('nn_out_act:', nn_out_act)

        # ********** TEST **********
        type_side, size, price = self.norm_vals(nn_out_act)

        print('type_side, size, price:', type_side, size, price)

        act = {}
        act["ID"] = ID
        act["type"], act["side"] = self.set_type_side(round(type_side))

        size = round(size)#.item()
        price = round(price)#.item()
        if size <= 0:
            size = 1
        if price <= 0:
            price = 1

        act["size"] = size
        act["price"] = price

        print('act:', act)

        return act
    # for cont act space
    def set_action_c(self, ID, nn_out_act):

        print('nn_out_act:', nn_out_act)

        act = {}
        act["ID"] = ID
        act["type"], act["side"] = self.set_type_side(round(nn_out_act[0][0]))

        act["size"] = round(nn_out_act[1][0]).item()
        act["price"] = round(nn_out_act[2][0]).item()

        print('act:', act)

        return act
    # for discrete act space
    def set_action(self, ID, nn_out_act):
        min_size = 1
        min_tick = 1

        print('nn_out_act:', nn_out_act)

        act = {}
        act["ID"] = ID
        act["type"], act["side"] = self.set_type_side((nn_out_act[0]))

        #act["size"] = (nn_out_act[1] + min_size) * 1.0 # +min_size as size or price can't be 0, *1 for float
        if act["type"] == 'market':
            act["size"] = ((nn_out_act[1] // 10) + min_size) * 1.0 # +min_size as size or price can't be 0, *1 for float
        else:
            act["size"] = (nn_out_act[1] + min_size) * 1.0 # +min_size as size or price can't be 0, *1 for float

        if act["type"] == 'market':
            act["price"] = (nn_out_act[2] + min_tick) * 1.0 # +tick_size as size or price can't be 0, *1 for float
        else:
            act["price"] = self._set_price(min_tick, act["side"], nn_out_act[2])

        print('act:', act)

        return act
    # rand disc or cont act for testing
    def set_action_r(self, ID, nn_out_act):

        print('nn_out_act:', nn_out_act)

        type_side, size, price = nn_out_act
        act = {}
        act["ID"] = ID
        act["type"], act["side"] = self.set_type_side(type_side)
        act["size"] = size
        act["price"] = price

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

    """
    # agg_LOB is [bid_size_list, bid_price_list, ask_size_list, ask_price_list] # list of np.arrays
    # Set price according to price_code 0 to 11 where price_code 1 to 10 correspond to slot in agg_LOB (mkt depth table) on one side
    # if order is on the bid side,
    # 0 & 11 are the border cases where they could be the lowest or highest bid respectively
    # if order is on the ask side,
    # 0 & 11 are the border cases where they could be the highest or lowest ask respectively
    def _set_price(self, min_tick, side, price_code):
        if side == 'bid':
            price_array = self.agg_LOB[1] # bid price np.array
            if price_code == 0: # lower by 1 tick or equal to lowest bid
                # price_array[9] is the lowest bid
                if price_array[9] == 0 or price_array[9] == min_tick:
                    set_price = min_tick
                else:
                    set_price = price_array[9] - min_tick # one tick lower than the lowest bid
            elif price_code == 11: # higher by 1 tick than highest bid
                # price_array[0] is the highest bid
                set_price = price_array[0] + min_tick # one tick higher than the highest bid
            else: # price_code between 1 to 10
                set_price = self.within_price_slot(min_tick, price_code, price_array)
        else: # 'ask' side
            price_array = self.agg_LOB[3] # ask price np.array
            if price_code == 0:
                # price_array[9] is the highest ask
                set_price = abs(price_array[9]) + min_tick # one tick higher than the highest ask
            elif price_code == 11:
                # price_array[0] is the lowest ask
                if abs(price_array[0]) == 0 or abs(price_array[0]) == min_tick:
                    set_price = min_tick
                else:
                    set_price = abs(price_array[0]) - min_tick # one tick lower than the lowest ask
            else: # price_code between 1 to 10
                set_price = self.within_price_slot(min_tick, price_code, price_array)

        return set_price*1.0
    """
    # agg_LOB is [bid_size_list, bid_price_list, ask_size_list, ask_price_list] # list of np.arrays
    # Set price according to price_code 0 to 11 where price_code 1 to 10 correspond to slot in agg_LOB (mkt depth table) on one side
    # if order is on the bid side,
    # 0 & 11 are the border cases where they could be the lowest or highest bid respectively
    # if order is on the ask side,
    # 0 & 11 are the border cases where they could be the highest or lowest ask respectively
    def _set_price(self, min_tick, side, price_code):
        if side == 'bid':
            price_array = self.agg_LOB[1] # bid price np.array
            if price_code == 0: # lower by 1 tick or equal to lowest bid
                # price_array[9] is the lowest bid
                if min(price_array) == 0:
                    set_price = random.randrange(1, 101, 1)
                elif min(price_array) == min_tick:
                    set_price = min_tick
                else:
                    set_price = min(price_array) - min_tick # one tick lower than the lowest bid
            elif price_code == 11: # higher by 1 tick than highest bid
                # price_array[0] is the highest bid
                set_price = max(price_array) + min_tick # one tick higher than the highest bid
            else: # price_code between 1 to 10
                set_price = self.within_price_slot(min_tick, price_code, price_array)
        else: # 'ask' side is negative on agg_LOB for both size & price
            price_array = self.agg_LOB[3] # ask price np.array
            if price_code == 0:
                # price_array[9] is the highest ask
                set_price = abs(min(price_array)) + min_tick # one tick higher than the highest ask
            elif price_code == 11:
                # price_array[0] is the lowest ask
                if abs(max(price_array)) == 0:
                    set_price = random.randrange(1, 101, 1)
                elif abs(max(price_array)) == min_tick:
                    set_price = min_tick
                else:
                    set_price = abs(max(price_array)) - min_tick # one tick lower than the lowest ask
            else: # price_code between 1 to 10
                set_price = self.within_price_slot(min_tick, price_code, price_array)

        return set_price*1.0

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

    # for debugging
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
