import numpy as np
import random

from gymnasium import spaces
from sklearn.utils import shuffle

from ...config_loader import constant, constants, env_default
from .state_helper import BOOK_ROW_ORDER

# Side/type decoding of the `category` action code. This table is the
# definition: `category_n` in config/tunable_constants.json is checked against
# it at construction, so the two cannot silently disagree.
_CATEGORY_MAP = {
    0: (None, 'market'),   # no action ('market' is inert, nothing is placed)
    1: ('bid', 'market'),
    2: ('bid', 'limit'),
    3: ('bid', 'modify'),
    4: ('bid', 'cancel'),
    5: ('ask', 'market'),
    6: ('ask', 'limit'),
    7: ('ask', 'modify'),
    8: ('ask', 'cancel'),
}


class Action_Helper():
    def __init__(self, min_size=env_default("min_size"),
                 mkt_max_size=env_default("mkt_max_size"),
                 limit_size_multiple=env_default("limit_size_multiple"),
                 tick_size=env_default("tick_size"), **kwargs):
        """
        Arguments:
            min_size: Smallest order size; also the offset added to every
                      sampled size, since a size of 0 is not a valid order.
            mkt_max_size: Upper bound on market order size.
            limit_size_multiple: Limit orders may be this many times larger
                                 than market orders.
            tick_size: Price tick. Order prices are built on this grid.

        Defaults come from `config/env_defaults.json`; the env always passes
        all four explicitly, so they apply only to a bare Action_Helper.
        """
        self.min_size = min_size
        self.mkt_max_size = mkt_max_size
        self.limit_size_multiple = limit_size_multiple
        self.limit_max_size = self.mkt_max_size * self.limit_size_multiple
        self.mkt_size_mean_mul = (self.mkt_max_size - self.min_size) / 2 # multiplier for mean size of mkt orders
        self.limit_size_mean_mul = (self.limit_max_size - self.min_size) / 2 # multiplier for mean size of non mkt orders

        # Action space shape, from config/tunable_constants.json.
        self._act = constants("action_space")
        self._validate_action_space()

        # for random price generation
        #
        # `min_tick` is the `tick_size` env config key. It used to be a second,
        # hardcoded 1 that happened to agree with the configured tick_size, so
        # setting tick_size had no effect on the prices agents can quote.
        self.min_tick = tick_size # price tick
        # Default anchor, overwritten by env.reset.
        self.last_price = float(
            constant("price_anchor_fallbacks", "action_helper_last_price")
        )

        super().__init__(**kwargs)

    def _validate_action_space(self):
        """Fail loudly when the configured action space contradicts the code.

        `category_n` and `price_offset_n` are not free parameters: the first is
        the size of `_CATEGORY_MAP`, the second has to be odd so that a middle
        'join' code exists. Previously these numbers lived only in the JSON as
        documentation, so a change to either was a silent no-op.
        """
        category_n = self._act["category_n"]
        if category_n != len(_CATEGORY_MAP):
            raise ValueError(
                f"tunable_constants.json: action_space.category_n={category_n} "
                f"but the side/type mapping defines {len(_CATEGORY_MAP)} "
                f"categories. Change _CATEGORY_MAP in action_helper.py to match."
            )
        price_offset_n = self._act["price_offset_n"]
        if price_offset_n < 1 or price_offset_n % 2 == 0:
            raise ValueError(
                f"tunable_constants.json: action_space.price_offset_n="
                f"{price_offset_n} must be a positive odd number, so that the "
                f"neutral 'join' offset is the middle code."
            )

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

        Every cardinality and bound below comes from
        `config/tunable_constants.json` -> action_space, except the price code,
        whose cardinality is observation_layout.k_rows.

        Each agent has its own action Dict:
            - category: Discrete(category_n) -> 0: None, 1: Buy Mkt, 2: Buy Lmt, 3: Buy Mod, 4: Buy Can,
                                     5: Sell Mkt, 6: Sell Lmt, 7: Sell Mod, 8: Sell Can
            - size_mean: Box(size_mean_low, size_mean_high)
            - size_sigma: Box(size_sigma_low, size_sigma_high)
            - price: Discrete(k_rows) -> book levels 1 to k_rows
            - price_offset: Discrete(price_offset_n) -> 0: Passive (-1 tick), 1: Join (0 tick), 2: Aggressive (+1 tick)

        Args:
            num_agents (int): Number of agents.

        Returns:
            dict: Dictionary mapping agent IDs to their action spaces.
        '''

        agent_space = spaces.Dict({
            "category": spaces.Discrete(self._act["category_n"]),
            "size_mean": spaces.Box(
                low=self._act["size_mean_low"], high=self._act["size_mean_high"],
                shape=(1,), dtype=np.float32),
            "size_sigma": spaces.Box(
                low=self._act["size_sigma_low"], high=self._act["size_sigma_high"],
                shape=(1,), dtype=np.float32),
            # One code per book level, so this is k_rows - the same depth the
            # observation exposes and the same depth _set_price indexes into.
            "price": spaces.Discrete(self.k_rows),
            "price_offset": spaces.Discrete(self._act["price_offset_n"]),
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
        # Which agents chose to do nothing this step. Recorded here rather than
        # derived by a consumer from `category == 0`, because _CATEGORY_MAP is
        # what defines that and it lives in this module: a reader of `info`
        # should not have to know the action encoding to ask "did this agent
        # pass?". This is the S1-3 detector - a league whose policies collapse
        # to always-pass still clears the promotion threshold, since 0 beats a
        # negative mean, so the collapse is invisible from returns (doc/11 2.2).
        self.pass_agents = set()
        for key, value in model_outs.items():
            act = self._set_action_mkt_depth(key, value)
            if act.get("side") is not None:
                acts.append(act)
            else:
                self.pass_agents.add(key)

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
        price_code = model_out.get("price", 0)
        # Default to the neutral 'join' offset, which is the middle code.
        price_offset = model_out.get("price_offset", self._neutral_price_offset())

        act = {}
        act["ID"] = ID

        # Mapping Category to Side and Type
        # 0: None, 1: Buy Mkt, 2: Buy Lmt, 3: Buy Mod, 4: Buy Can,
        # 5: Sell Mkt, 6: Sell Lmt, 7: Sell Mod, 8: Sell Can
        act["side"], act["type"] = _CATEGORY_MAP[int(category)]

        size = self._set_size(act["type"], self.mkt_size_mean_mul, self.limit_size_mean_mul, size_mean, size_sigma)
        # int, not float. A size is a count of contracts, so int is the type
        # that can represent it exactly; the previous `* 1.0` coerced to float
        # deliberately ("*1 for float") and that single character is why sizes
        # were floats everywhere downstream. Decimal * int is defined, whereas
        # Decimal * float raises TypeError - which is the error the orderbook
        # already carries two local workarounds for, and the one
        # cash_processor's modify path would hit. See doc/11 1.8.
        act["size"] = int(size + self.min_size) # +self.min_size as size can't be 0

        if act["type"] == 'market':
            act["price"] = -1.0 # -1.0 to indicate market price
        else:
            act["price"] = self._set_price(self.min_tick, act["side"], price_code, price_offset)

        return act

    def _neutral_price_offset(self):
        """The 'join' offset code: the middle of the price_offset codes."""
        return self._act["price_offset_n"] // 2

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
        # int(): np.rint already rounds to a whole number, but .item() hands
        # back a Python float (40.0), and np.int64 is not an int subclass, so
        # neither is usable as a size without a further conversion.
        return int(np.rint(np.abs(sample)).item())

    def _set_price(self, min_tick, side, price_code, price_offset=None):
        """
        Set price according to price_code (a book level, 0 to k_rows - 1) and
        price_offset (0 to price_offset_n - 1).

        price_offset, for the default price_offset_n of 3:
            0: Passive (-1 tick from base)
            1: Join (0 tick from base)
            2: Aggressive (+1 tick from base)

        The neutral code is the middle one, so a wider price_offset_n extends
        the range symmetrically: with 5 codes the offsets run -2..+2 ticks.

        Returns:
            set_price: Price, a real number.
        """

        best_bid = self.LOB.get_best_bid()
        best_ask = self.LOB.get_best_ask()

        # Deterministic Reference Price (always use last_price as requested)
        ref_price = self.last_price
        if price_offset is None:
            price_offset = self._neutral_price_offset()
        # maps (0, 1, 2) to (-1, 0, +1) for the default price_offset_n of 3
        offset_multiplier = price_offset - self._neutral_price_offset()

        # level_idx: 0 to k_rows - 1, representing book levels 1 to k_rows
        level_idx = price_code

        # Use unnormalized raw prices array for action price calculation
        agg_LOB_source = getattr(self, 'agg_LOB_raw', self.agg_LOB)
        book = np.array(agg_LOB_source).reshape(self.book_rows, self.k_rows)

        if side == 'bid':
            price_array = book[BOOK_ROW_ORDER.index("bid_price")] # raw bid prices
            p = price_array[level_idx]
            
            # If level is empty, use ghost logic relative to ref_price
            base_price = (ref_price - (level_idx + 1) * min_tick) if p == 0 else abs(p)
            
            # Apply offset: Bid +1 is aggressive, Bid -1 is passive
            set_price = base_price + (offset_multiplier * min_tick)

        else: # 'ask'
            price_array = book[BOOK_ROW_ORDER.index("ask_price")] # raw ask prices
            p = abs(price_array[level_idx])
            
            # If level is empty, use ghost logic relative to ref_price
            base_price = (ref_price + (level_idx + 1) * min_tick) if p == 0 else p
            
            # Apply offset: Ask -1 is aggressive, Ask +1 is passive
            set_price = base_price - (offset_multiplier * min_tick)

        # Final safety checks
        set_price = max(min_tick, set_price)
        return float(set_price)

    def _higher(self, min_tick, price):
        """
        Sets the price of the order to 1 tick higher.
        """
        return price + min_tick

    def _lower(self, min_tick, price):
        """
        Sets the price of the order to 1 tick lower, ensuring it's not below min_tick.
        """
        return max(min_tick, price - min_tick)
