import numpy as np
import random

from gymnasium import spaces
from sklearn.utils import shuffle

class Action_Helper():
    def __init__(self):
        super().__init__()

        self.min_size = 1
        self.mkt_max_size = 100
        self.N = 10
        self.limit_max_size = self.mkt_max_size * self.N
        self.mkt_size_mean_mul = (self.mkt_max_size - self.min_size) / 2 # multiplier for mean size of mkt orders
        self.limit_size_mean_mul = (self.limit_max_size - self.min_size) / 2 # multiplier for mean size of non mkt orders

        # for random price generation
        self.min_tick = 1 # price tick
        self.max_price = 101

    # def act_space(self):
    #     '''
    #     The action space.

    #     Example for 1 agent:
    #         model_out: [0, 3, array([0.47555637], dtype=float32), array([0.5383144], dtype=float32), 5]
    #     '''

    #     return spaces.Tuple((spaces.Discrete(3), # side: none, bid, ask (0 to 2)
    #                          spaces.Discrete(4), # type: market, limit, modify, cancel (0 to 3)
    #                          spaces.Box(low=-1.0, high=1.0, shape=(1,), dtype=np.float32), # array of mean for size selection
    #                          spaces.Box(low=0.0, high=1.0, shape=(1,), dtype=np.float32), # array of sigma for size selection
    #                          spaces.Discrete(12), # price: based on mkt depth from 0 to 11
    #                         ))
    def act_space(self, num_agents):
        '''
        The action space for multiple agents, returned as a dictionary.

        Each agent has its own action tuple:
            - side: Discrete(3) -> 0: none, 1: bid, 2: ask
            - type: Discrete(4) -> 0: market, 1: limit, 2: modify, 3: cancel
            - mean: Box(-1.0, 1.0) -> for size selection
            - sigma: Box(0.0, 1.0) -> for size selection
            - price: Discrete(12) -> from 0 to 11 (based on market depth)

        Args:
            num_agents (int): Number of agents.

        Returns:
            gym.spaces.Dict: Dictionary mapping agent IDs to their action spaces.
        '''

        agent_space = spaces.Tuple((
            spaces.Discrete(3),  # side
            spaces.Discrete(4),  # type
            spaces.Box(low=-1.0, high=1.0, shape=(1,), dtype=np.float32),  # mean
            spaces.Box(low=0.0, high=1.0, shape=(1,), dtype=np.float32),  # sigma
            spaces.Discrete(12),  # price
        ))

        # Create a dictionary mapping for all agents
        space_dict = {f'agent_{i}': agent_space for i in range(num_agents)}

        # return spaces.Dict(space_dict)
        return space_dict

    def set_actions(self, model_outs):
        """
        Set model outputs to actions acceptable by LOB.

        Arguments:
            model_outs: A dictionary of actions from model.

        Returns:
            acts: A list of actions acceptable by LOB.
        """

        acts = []
        for key, value in model_outs.items():
            act = self._set_action_mkt_depth(key, value)
            acts.append(act)

        return acts

    def rand_exec_seq(self, actions, seed):
        """
        Shuffle actions execution sequence.

        Arguments:
            actions: A list of actions acceptable by the LOB.
        """

        return shuffle(actions, random_state=seed) # seed for reproducible behavior

    def do_actions(self, actions):
        """
        Process actions for all agents.

        Arguments:
            actions: A list of actions.

        Returns:
            seq_trades: A list of dictionaries containing trades triggered by
                        the actions.
            seq_order_in_book: A list of dictionaries containing information
                               of unfilled limit orders leftover by the actions.
        """

        seq_trades = []
        seq_order_in_book = []
        for action in actions:
            ID = action.get("ID")
            type = action.get("type")
            side = action.get("side")
            size = action.get("size")
            price = action.get("price")
            trader = self.traders[ID]
            self.trades, self.order_in_book = trader.place_order(type, side, size, price, self.LOB, self.traders)
            seq_trades.append(self.trades)
            seq_order_in_book.append(self.order_in_book)

        return seq_trades, seq_order_in_book

    def _set_action_mkt_depth(self, ID, model_out):
        """
        Sets the action of each agent from the model.

        Arguments:
            ID: agent ID, int.
            model_out: An action for a single agent from the model .

        Returns:
            act: The action of an agent acceptable by the LOB.
        """

        # Assign model output for a single action to their respective fields.
        side = model_out[0]
        type = model_out[1]
        size_mean = model_out[2]
        size_sigma = model_out[3]
        price_code = model_out[4]

        act = {}
        act["ID"] = ID
        act["side"] = self._set_side(side)
        act["type"] = self._set_type(type)

        size = self._set_size(act["type"], self.mkt_size_mean_mul, self.limit_size_mean_mul, size_mean, size_sigma)
        act["size"] = (size + self.min_size) * 1.0 # +self.min_size as size can't be 0, *1 for float

        if act["type"] == 'market':
            act["price"] = -1.0 # -1.0 to indicate market price
        elif act["type"] == 'limit':
            act["price"] = self._set_price(self.min_tick, self.max_price, act["side"], price_code)
        elif act["type"] == 'modify':
            act["price"] = self._set_price(self.min_tick, self.max_price, act["side"], price_code)
        elif act["type"] == 'cancel':
            act["price"] = self._set_price(self.min_tick, self.max_price, act["side"], price_code)
        else:
            act["price"] = 0

        return act

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

    def _set_size(self, type, mkt_size_mean_mul, limit_size_mean_mul, mean, sigma):
        """
        Get size.

        Arguments:
            type: 'market', 'limit', 'modify' or 'cancel'
            mkt_size_mean_mul: Multiplier for mean size of mkt orders.
            limit_size_mean_mul: Multiplier for mean size of mkt orders.
            mean: Mean for the size distribution.
            sigma: Sigma for the size distribution.

        Returns:
            A size sampled from the distribution.
        """
        if type == 'market':
            sample = np.random.normal(mkt_size_mean_mul * mean, sigma, 1)
        else:
            sample = np.random.normal(limit_size_mean_mul * mean, sigma, 1)

        return np.asscalar(np.rint(np.abs(sample)))

    def _set_price(self, min_tick, max_price, side, price_code):
        """
        Set price according to price_code 0 to 11 where price_code 1 to 10
        correspond to a price slot in agg_LOB (mkt depth table) on one side
        (bid or ask).

        If order is on the bid side, 0 & 11 are the border cases where they
        could be 1 tick lower than the lowest bid or 1 tick higher than highest
        bid respectively.

        If order is on the ask side, 0 & 11 are the border cases where they
        could be 1 tick higher than the highest ask or 1 tick lower than the
        lowest ask respectively.

        Arguments:
            min_tick: Minimum price tick, a real number.
            side: 'bid' or 'ask'.
            price_code: 0 to 11, representing the the market depth.

        Returns:
            set_price: Price, a real number.
        """

        if side == 'bid':
            # agg_LOB is [bid_size_list, bid_price_list, ask_size_list, ask_price_list] # list of np.arrays
            price_array = self.agg_LOB[1] # bid prices
            if price_code == 0: # lower by 1 tick or equal to lowest bid
                set_price = self._lower(min_tick, max_price, min(price_array)) # price_array[9] is the lowest bid
            elif price_code == 11: # 1 tick higher than the highest bid
                set_price = self._higher(min_tick, max_price, max(price_array)) # price_array[0] is the highest bid
            else: # price_code between 1 to 10
                set_price = self._within_price_slot(min_tick, side, max_price, price_code, price_array)
        else: # 'ask' side is negative on agg_LOB for both size & price
            price_array = self.agg_LOB[3] # ask prices
            if price_code == 0: # 1 tick higher than the highest ask
                set_price = self._higher(min_tick, max_price, abs(min(price_array))) # price_array[9] is the highest ask
            elif price_code == 11: # lower by 1 tick or equal to lowest ask
                set_price = self._lower(min_tick, max_price, abs(max(price_array))) # price_array[0] is the lowest ask
            else: # price_code between 1 to 10
                set_price = self._within_price_slot(min_tick, side, max_price, price_code, price_array)

        return set_price * 1.0

    def _higher(self, min_tick, max_price, price):
        """
        Sets the price of the order to 1 tick higher or to a random price.

        Arguments:
            min_tick: Minimum price tick, a real number.
            max_price: Maximum price, a real number.
            price: Real number.

        Returns:
            set_price: Price, a real number.
        """

        if price == 0:
            set_price = random.randrange(min_tick, max_price, min_tick)
        else:
            set_price = price + min_tick # one tick higher

        return set_price

    def _lower(self, min_tick, max_price, price):
        """
        Sets the price of the order to 1 tick lower or to a random price.

        Arguments:
            min_tick: Minimum price tick, a real number.
            max_price: Maximum price, a real number.
            price: Real number.

        Returns:
            set_price: Price, a real number.
        """

        if price == 0:
            set_price = random.randrange(min_tick, max_price, min_tick)
        elif price == min_tick: # prevent -ve price
            set_price = min_tick
        else:
            set_price = price - min_tick # one tick lower

        return set_price

    def _within_price_slot(self, min_tick, side, max_price, price_code, price_array):
        """
        Sets the price of the order to a random price or depending on the side,
        1 tick higher or lower.

        Arguments:
            min_tick: Minimum price tick, a real number.
            side: 'bid' or 'ask'
            max_price: Maximum price, a real number.
            price_code: 0 to 11, representing the the market depth.
            price_array: The bid or ask prices in the market depth.

        Returns:
            set_price: Price, a real number.
        """

        set_price = min_tick
        for i, price in enumerate(price_array):
            if price_code == i+1: # price_code is between 1 to 10 while i starts from 0
                if price == 0:
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
