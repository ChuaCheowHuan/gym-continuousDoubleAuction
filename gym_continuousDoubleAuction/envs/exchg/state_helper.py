import numpy as np
from collections import deque

from ...config_loader import constant, constants, env_default

# Layout of a single observation snapshot, from
# `config/tunable_constants.json` -> observation_layout.
#
# The book block is `book_rows` stacked rows of `k_rows` price levels:
#   [bid_price, bid_size, ask_price, ask_size]
# followed by `extra_dim` market-level scalars:
#   [log_mid, log1p_spread_ticks]
#
# These module-level names are the layout as it was at import time, kept for
# standalone consumers that have no env instance to ask - the visualizers,
# which read a pickled observation, and the tests. Runtime code inside the env
# uses the per-instance attributes set in `__init__` instead, so that a config
# tree swapped in via `$CDA_CONFIG_DIR` takes effect on the next env built
# rather than only on the next interpreter.
def _layout():
    """(k_rows, book_rows, extra_dim) from config."""
    layout = constants("observation_layout")
    return layout["k_rows"], layout["book_rows"], layout["extra_dim"]


K_ROWS, BOOK_ROWS, EXTRA_DIM = _layout()
BOOK_DIM = BOOK_ROWS * K_ROWS
SNAPSHOT_DIM = BOOK_DIM + EXTRA_DIM

#: Order in which `set_agg_LOB` concatenates the book rows. This is the
#: definition of the book block's layout, and what `book_rows` is checked
#: against - it lets consumers name a row instead of indexing a magic number.
BOOK_ROW_ORDER = ("bid_price", "bid_size", "ask_price", "ask_size")


class State_Helper(object):

    def __init__(self, n_hist=env_default("n_hist"), **kwargs):
        self.n_hist = n_hist
        self.obs_history = deque(maxlen=self.n_hist)

        # Observation layout as instance state. book_dim and snapshot_dim are
        # derived here and nowhere else - they are not config keys, because a
        # stored copy could disagree with k_rows.
        self.k_rows, self.book_rows, self.extra_dim = _layout()
        if self.book_rows != len(BOOK_ROW_ORDER):
            raise ValueError(
                f"tunable_constants.json: observation_layout.book_rows="
                f"{self.book_rows} but set_agg_LOB builds "
                f"{len(BOOK_ROW_ORDER)} rows {BOOK_ROW_ORDER}. Change "
                f"set_agg_LOB and BOOK_ROW_ORDER to match."
            )
        self.book_dim = self.book_rows * self.k_rows
        self.snapshot_dim = self.book_dim + self.extra_dim

        # Used when the book has no two-sided market and last_price is unusable.
        self.midpoint_fallback = float(
            constant("price_anchor_fallbacks", "state_helper_midpoint")
        )

        # kwargs is forwarded, not swallowed: the sizing and reward knobs are
        # consumed further along the MRO (Action_Helper, Reward_Helper).
        super().__init__(**kwargs)

    # reset traders LOB observations/states
    def reset_traders_agg_LOB(self):
        """
        Set observation state for all traders with temporal history window.
        Populates shared obs_history deque with n_hist copies of the initial LOB snapshot.
        """
        init_obs = self.set_agg_LOB()
        n_hist = self.n_hist
        self.obs_history = deque([init_obs] * n_hist, maxlen=n_hist)

        stacked_obs = np.concatenate(list(self.obs_history), axis=0).astype(np.float32)
        states = {f'agent_{i}': stacked_obs for i in range(len(self.traders))}
        
        return states
        
    def prep_next_state(self):
        """
        Return:
            stacked_obs: The temporal stacked state of the aggregated LOB after all actions are executed.
        """

        self.agg_LOB_aft = self.set_agg_LOB() # LOB state at t+1 after processing LOB

        self.obs_history.append(self.agg_LOB_aft)

        stacked_obs = np.concatenate(list(self.obs_history), axis=0).astype(np.float32)

        return stacked_obs

    def set_next_state(self, next_states, trader, state_input):
        """
        Set next state.

        Argument:
            next_states: Dictionary.
            trader: A trader object.
            state_input: The state of the aggregated LOB  after all actions are
                         executed

        Returns:
            next_states: Dictionary of states for each trader.
        """

        # next_states[trader.ID] = state_input
        next_states[f'agent_{trader.ID}'] = state_input

        return next_states

    def set_agg_LOB(self):
        """
        Set the aggregated LOB.

        Return: list of np.arrays

        Notes:
            price_map is an OrderTree object (SortedDict object).
            SortedDict object has key & value, key is price, value is an
            OrderList object.
        """
        k_rows = self.k_rows
        bid_price_list = np.zeros(k_rows)
        bid_size_list = np.zeros(k_rows)
        ask_price_list = np.zeros(k_rows)
        ask_size_list = np.zeros(k_rows)

        # LOB bids
        if self.LOB.bids != None and len(self.LOB.bids) > 0:
            # reversed because we want the highest bid as the first entry in the np.array
            for k, set in enumerate(reversed(self.LOB.bids.price_map.items())):
                if k < k_rows:
                    bid_price_list[k] = set[0] # set[0] is price (key)
                    bid_size_list[k] = set[1].volume # set[1] is an OrderList object (value) & volume is total volume of the OrderList object
                else:
                    break
        # LOB asks
        if self.LOB.asks != None and len(self.LOB.asks) > 0:
            # lowest ask is the first entry in the np.array
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
        
        # Raw unnormalized snapshot
        flattened_raw = np.concatenate([bid_price_list, bid_size_list, ask_price_list, ask_size_list]).astype(np.float32)
        self.agg_LOB_raw = flattened_raw

        # Calculate Level 1 midpoint price M
        l1_bid = bid_price_list[0] if bid_price_list[0] > 0 else 0.0
        l1_ask = abs(ask_price_list[0]) if ask_price_list[0] != 0 else 0.0

        if l1_bid > 0 and l1_ask > 0:
            M = (l1_bid + l1_ask) / 2.0
        elif l1_bid > 0:
            M = l1_bid
        elif l1_ask > 0:
            M = l1_ask
        else:
            M = float(getattr(self, 'last_price', self.midpoint_fallback))
            if M <= 0:
                M = self.midpoint_fallback

        # Apply price normalization using symmetric midpoint distance:
        # norm_P_bid = (M - P_bid) / M (non-negative)
        # norm_P_ask = -((abs(P_ask) - M) / M) (negated to maintain negative ask observation sign convention)
        norm_bid_price = np.where(bid_price_list > 0, (M - bid_price_list) / M, 0.0)
        norm_ask_price = np.where(ask_price_list != 0, -((np.abs(ask_price_list) - M) / M), 0.0)

        # Apply volume normalization (sqrt) maintaining observation signs
        norm_bid_size = np.where(bid_size_list > 0, np.sqrt(bid_size_list), 0.0)
        norm_ask_size = np.where(ask_size_list != 0, -np.sqrt(np.abs(ask_size_list)), 0.0)

        # Market-level scalars appended after the book block.
        #
        # log_mid restores the price anchor that midpoint normalization discards:
        # without it a market at price 10 and one at price 100 are indistinguishable,
        # even though min_tick is absolute and so worth 10x more in the former.
        # M is guaranteed > 0 by the fallback chain above, so log() is always defined.
        log_mid = np.log(M)

        # log1p_spread_ticks measures the spread in the same tick units the action
        # space quotes in (min_tick), not the tick_size config, which is dropped on
        # reset. A resting book can never be locked or crossed (a bid at or above the
        # best ask is filled on arrival), so a two-sided book always has a spread of
        # at least 1 tick and therefore log1p >= log1p(1) = 0.693. That leaves 0.0 as
        # an unambiguous sentinel for "no two-sided market".
        if l1_bid > 0 and l1_ask > 0:
            min_tick = getattr(self, 'min_tick', env_default("tick_size"))
            if min_tick <= 0:
                min_tick = env_default("tick_size")
            spread_ticks = (l1_ask - l1_bid) / min_tick
            log1p_spread_ticks = np.log1p(max(0.0, spread_ticks))
        else:
            log1p_spread_ticks = 0.0

        extras = np.array([log_mid, log1p_spread_ticks])

        flattened = np.concatenate([norm_bid_price, norm_bid_size, norm_ask_price, norm_ask_size, extras]).astype(np.float32)

        return flattened
    
    def state_diff(self, agg_LOB, agg_LOB_aft):
        """
        Argument:
            agg_LOB: Aggregated LOB at time step t.
            agg_LOB_aft: Aggregated LOB at time step t+1.

        Returns:
            state_diff: The difference between agg_LOB_aft & agg_LOB.

        Notes:
            state_diff should be used in obs preprocessing if needed
        """
        state_diff = []
        for (state_row, next_state_row) in zip(agg_LOB, agg_LOB_aft):
            diff = next_state_row - state_row
            list_diff = list(diff)
            state_diff.append(list_diff)
        state_diff = np.array(state_diff)

        #print('state_diff.shape:', state_diff.shape)

        return state_diff
