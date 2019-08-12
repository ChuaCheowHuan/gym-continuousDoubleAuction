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
        act_space = spaces.Tuple((spaces.Discrete(5),
                                  spaces.Discrete(100),
                                  spaces.Discrete(100),
                                ))
        #self.action_space = spaces.MultiDiscrete([5, 100, 100]) # type_side, size, price
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

        print('nn_out_act:', nn_out_act)

        act = {}
        act["ID"] = ID
        act["type"], act["side"] = self.set_type_side((nn_out_act[0]))

        act["size"] = (nn_out_act[1] + 1) * 1.0 # +1 as size or price can't be 0
        act["price"] = (nn_out_act[2] + 1) * 1.0

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
