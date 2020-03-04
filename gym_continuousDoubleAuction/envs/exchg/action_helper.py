import numpy as np
import random
from gym import spaces

from gym import spaces
from sklearn.utils import shuffle

class Action_Helper():
    def __init__(self):
        super(Action_Helper, self).__init__()

        self.size_upper_bound = 1000

    def disc_act(self):
        # Set price according to price_code 0 to 11 where price_code 1 to 10 correspond to slot in agg_LOB (mkt depth table)
        # 0 & 11 are the border cases where they could be the lowest or highest bid respectively
        # if order is on the ask side,
        # 0 & 11 are the border cases where they could be the highest or lowest ask respectively
        '''
        act_space = spaces.Tuple((spaces.Discrete(3), # none, bid, ask (0 to 2)
                                  spaces.Discrete(4), # market, limit, modify, cancel (0 to 3)
                                  spaces.Discrete(100), # size
                                  spaces.Discrete(12), # price based on mkt depth from 0 to 11
                                ))
        '''

        '''
        nn_out_act: [0, 3, array([0.47555637], dtype=float32), array([0.5383144], dtype=float32), 5]
        '''
        act_space = spaces.Tuple((spaces.Discrete(3), # side: none, bid, ask (0 to 2)
                                  spaces.Discrete(4), # type: market, limit, modify, cancel (0 to 3)
                                  spaces.Box(low=-1.0, high=1.0, shape=(1,), dtype=np.float32), # array of mean
                                  spaces.Box(low=0.0, high=1.0, shape=(1,), dtype=np.float32), # array of sigma
                                  spaces.Discrete(12), # price: based on mkt depth from 0 to 11
                                ))

        return act_space

    def rand_exec_seq(self, actions, seed):
        # seed for reproducible behavior
        shuffle_actions = shuffle(actions, random_state=seed)
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

    def get_size(self, size_upper_bound, mean, sigma):
        return np.random.normal(size_upper_bound * mean, sigma, 1)

    # for discrete act space
    def set_action(self, ID, nn_out_act):
        min_size = 1
        min_tick = 1

        act = {}
        act["ID"] = ID

        act["side"] = self._set_side(nn_out_act[0])
        act["type"] = self._set_type(nn_out_act[1])

        act["size"] = (nn_out_act[2] + min_size) * 1.0 # +min_size as size or price can't be 0, *1 for float
        act["price"] = (nn_out_act[3] + min_tick) * 1.0 # +tick_size as size or price can't be 0, *1 for float

        return act

    # for discrete act space based on mkt_depth
    def set_action_mkt_depth(self, ID, nn_out_act):
        min_size = 1
        min_tick = 1
        max_size = 10

        # reduce market order size compare with limit orders (for testing)
        fl_div = random.randrange(min_tick+1, max_size+1, min_tick)
        #fl_div = 10

        side = nn_out_act[0]
        type = nn_out_act[1]
        size_mean = nn_out_act[2]
        size_sigma = nn_out_act[3]
        price_code = nn_out_act[4]

        act = {}
        act["ID"] = ID
        act["side"] = self._set_side(side)
        act["type"] = self._set_type(type)

        size = np.asscalar(np.rint(np.abs(self.get_size(self.size_upper_bound, size_mean, size_sigma))))

        if act["type"] == 'market':
            act["size"] = ((size // fl_div) + min_size) * 1.0 # +min_size as size or price can't be 0, *1 for float
        else:
            act["size"] = (size + min_size) * 1.0 # +min_size as size or price can't be 0, *1 for float

        if act["type"] == 'market':
            # price depends on side if type is market
            #act["price"] = (price_code + min_tick) * 1.0 # +tick_size as size or price can't be 0, *1 for float
            act["price"] = 0 # +tick_size as size or price can't be 0, *1 for float
        elif act["type"] == 'limit':
            act["price"] = self._set_price(min_tick, act["side"], price_code)
        elif act["type"] == 'modify':
            act["price"] = self._set_price(min_tick, act["side"], price_code)
        elif act["type"] == 'cancel':
            act["price"] = self._set_price(min_tick, act["side"], price_code)
        else:
            act["price"] = 0

        return act

    def get_orderTree(self, orderBook, side):
        if side == 'bid':
            orderTree = orderBook.bids
        elif side == 'ask':
            orderTree = orderBook.asks
        else:
            orderTree = None
        return orderTree

    def get_orderList(self, orderTree, price):
        orderList = None

        return orderList

    def get_order(self, orderList, trader_ID):
        order = None

        return order

    def _set_side(self, side):
        if side == 0:
            side = None
        elif side == 1:
            side = 'bid'
        else:
            side = 'ask'
        return side

    def _set_type(self, type):
        if type == 0:
            type = 'market'
        elif type == 1:
            type = 'limit'
        elif type == 2:
            type = 'modify'
        else:
            type = 'cancel'
        return type

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
                set_price = self._lower(min_tick, max_price, min(price_array))
            elif price_code == 11: # higher by 1 tick than highest bid
                # price_array[0] is the highest bid
                set_price = self._higher(min_tick, max_price, max(price_array)) # one tick higher than the highest bid
            else: # price_code between 1 to 10
                set_price = self._within_price_slot(min_tick, side, max_price, price_code, price_array)
        else: # 'ask' side is negative on agg_LOB for both size & price
            price_array = self.agg_LOB[3] # ask price np.array
            if price_code == 0:
                # price_array[9] is the highest ask
                set_price = self._higher(min_tick, max_price, abs(min(price_array))) # one tick higher than the highest ask
            elif price_code == 11:
                # price_array[0] is the lowest ask
                set_price = self._lower(min_tick, max_price, abs(max(price_array)))
            else: # price_code between 1 to 10
                set_price = self._within_price_slot(min_tick, side, max_price, price_code, price_array)

        return set_price * 1.0

    def _higher(self, min_tick, max_price, price):
        if price == 0:
            set_price = random.randrange(min_tick, max_price, min_tick)
        else:
            set_price = price + min_tick # one tick higher than the highest bid
        return set_price

    def _lower(self, min_tick, max_price, price):
        if price == 0:
            set_price = random.randrange(min_tick, max_price, min_tick)
        elif price == min_tick: # prevent -ve price
            set_price = min_tick
        else:
            set_price = price - min_tick
        return set_price

    def _within_price_slot(self, min_tick, side, max_price, price_code, price_array):
        set_price = min_tick
        for i, price in enumerate(price_array):
            if price_code == i+1:
                if price == 0:
                    #set_price = price_code * min_tick
                    set_price = random.randrange(min_tick, max_price, min_tick)

                else: # Is there a better way to do this?

                    #set_price = abs(price)

                    if(side == 'bid'):
                        set_price = abs(price) + min_tick
                    else:
                        if price == min_tick: # prevent -ve price
                            set_price = min_tick
                        else:
                            set_price = abs(price) - min_tick
                break
        return set_price

    # process actions for all agents
    def do_actions(self, actions):
        i = 0
        all_trades = []
        all_order_in_book = []
        for action in actions:
            ID = action.get("ID")
            type = action.get("type")
            side = action.get("side")
            size = action.get("size")
            price = action.get("price")
            trader = self.agents[ID]
            self.trades, self.order_in_book = trader.place_order(type, side, size, price, self.LOB, self.agents)
            all_trades.append(self.trades)
            all_order_in_book.append(self.order_in_book)
            i = i + 1

        #print('do_actions: ', i)

        return all_trades, all_order_in_book
