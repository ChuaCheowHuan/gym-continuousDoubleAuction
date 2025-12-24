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
        self.last_price = 100.0 # Default anchor (will be overwritten by env.reset)

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

        Each agent has its own action Dict:
            - category: Discrete(9) -> 0: None, 1: Buy Mkt, 2: Buy Lmt, 3: Buy Mod, 4: Buy Can,
                                     5: Sell Mkt, 6: Sell Lmt, 7: Sell Mod, 8: Sell Can
            - size_mean: Box(-1.0, 1.0)
            - size_sigma: Box(0.0, 1.0)
            - price: Discrete(12)

        Args:
            num_agents (int): Number of agents.

        Returns:
            dict: Dictionary mapping agent IDs to their action spaces.
        '''

        agent_space = spaces.Dict({
            "category": spaces.Discrete(9),
            "size_mean": spaces.Box(low=-1.0, high=1.0, shape=(1,), dtype=np.float32),
            "size_sigma": spaces.Box(low=0.0, high=1.0, shape=(1,), dtype=np.float32),
            "price": spaces.Discrete(12),
        })

        # Create a dictionary mapping for all agents
        space_dict = {f'agent_{i}': agent_space for i in range(num_agents)}

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


        # print(f'do_actions -> actions: {actions}')


        seq_trades = []
        seq_order_in_book = []
        for action in actions:
            ID_str = action.get("ID")
            type = action.get("type")
            side = action.get("side")
            size = action.get("size")
            price = action.get("price")



            ID = int(ID_str.split('_')[1])
            


            trader = self.traders[ID]
            self.trades, self.order_in_book = trader.place_order(type, side, size, price, self.LOB, self.traders)
            seq_trades.append(self.trades)
            seq_order_in_book.append(self.order_in_book)

        return seq_trades, seq_order_in_book

    def _set_action_mkt_depth(self, ID, model_out):
        """
        Sets the action of each agent from the model.

        Arguments:
            ID: agent ID, str.
            model_out: An action Dict for a single agent from the model.

        Returns:
            act: The action of an agent acceptable by the LOB.
        """

        category = model_out["category"]
        size_mean = model_out["size_mean"]
        size_sigma = model_out["size_sigma"]
        price_code = model_out["price"]

        act = {}
        act["ID"] = ID
        
        # Mapping Category to Side and Type
        # 0: None, 1: Buy Mkt, 2: Buy Lmt, 3: Buy Mod, 4: Buy Can,
        # 5: Sell Mkt, 6: Sell Lmt, 7: Sell Mod, 8: Sell Can
        if category == 0:
            act["side"] = None
            act["type"] = 'market' # Default to market for 'None' category, though it won't execute
        elif 1 <= category <= 4:
            act["side"] = 'bid'
            types = {1: 'market', 2: 'limit', 3: 'modify', 4: 'cancel'}
            act["type"] = types[category]
        else: # 5 <= category <= 8
            act["side"] = 'ask'
            types = {5: 'market', 6: 'limit', 7: 'modify', 8: 'cancel'}
            act["type"] = types[category]

        size = self._set_size(act["type"], self.mkt_size_mean_mul, self.limit_size_mean_mul, size_mean, size_sigma)
        act["size"] = (size + self.min_size) * 1.0 # +self.min_size as size can't be 0, *1 for float

        if act["type"] == 'market':
            act["price"] = -1.0 # -1.0 to indicate market price
        else:
            act["price"] = self._set_price(self.min_tick, self.max_price, act["side"], price_code)

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

        # return np.asscalar(np.rint(np.abs(sample)))
        return np.rint(np.abs(sample)).item()

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

        best_bid = self.LOB.get_best_bid()
        best_ask = self.LOB.get_best_ask()

        # Deterministic Reference Price (always use last_price as requested)
        ref_price = self.last_price

        if side == 'bid':
            price_array = np.array(self.agg_LOB).reshape(4, 10)[0] # bid prices
            
            if price_code == 0: # passive
                worst_bid = min(price_array)
                if worst_bid == 0:
                    set_price = ref_price - (11 * min_tick)
                else:
                    set_price = worst_bid - min_tick
            elif price_code == 11: # aggressive
                best_bid_val = max(price_array)
                if best_bid_val == 0:
                    set_price = ref_price + min_tick
                else:
                    set_price = best_bid_val + min_tick
            else: # 1-10
                p = price_array[price_code - 1]
                if p == 0:
                    set_price = ref_price - (price_code * min_tick)
                else:
                    set_price = abs(p) + min_tick
        else: # 'ask'
            price_array = np.array(self.agg_LOB).reshape(4, 10)[2] # ask prices

            if price_code == 0: # passive
                worst_ask = abs(min(price_array))
                if worst_ask == 0:
                    set_price = ref_price + (11 * min_tick)
                else:
                    set_price = worst_ask + min_tick
            elif price_code == 11: # aggressive
                best_ask_val = abs(max(price_array))
                if best_ask_val == 0:
                    set_price = ref_price - min_tick
                else:
                    set_price = best_ask_val - min_tick
            else: # 1-10
                p = abs(price_array[price_code - 1])
                if p == 0:
                    set_price = ref_price + (price_code * min_tick)
                else:
                    set_price = p - min_tick

        # Final safety checks
        set_price = max(min_tick, set_price)
        return float(set_price)

    def _higher(self, min_tick, max_price, price):
        """
        Sets the price of the order to 1 tick higher.
        """
        return price + min_tick

    def _lower(self, min_tick, max_price, price):
        """
        Sets the price of the order to 1 tick lower, ensuring it's not below min_tick.
        """
        return max(min_tick, price - min_tick)
