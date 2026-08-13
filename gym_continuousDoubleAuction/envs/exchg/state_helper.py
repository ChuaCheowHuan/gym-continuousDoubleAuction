import numpy as np
from collections import deque

# Layout of a single observation snapshot.
# The book block is 4 stacked rows of K_ROWS price levels:
#   [bid_price, bid_size, ask_price, ask_size]
# followed by EXTRA_DIM market-level scalars:
#   [log_mid, log1p_spread_ticks]
K_ROWS = 10
BOOK_DIM = 4 * K_ROWS
EXTRA_DIM = 2
SNAPSHOT_DIM = BOOK_DIM + EXTRA_DIM

# Price anchor used before any trade has printed and no two-sided market exists.
# Both the action layer and the observation midpoint fall back to this, so it is
# defined once here rather than as two literals that could drift apart.
DEFAULT_PRICE_ANCHOR = 100.0


class State_Helper(object):

    def __init__(self, n_hist=4, **kwargs):
        self.n_hist = n_hist
        self.obs_history = deque(maxlen=self.n_hist)
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
        n_hist = getattr(self, 'n_hist', 4)
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
        k_rows = K_ROWS
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
            M = float(getattr(self, 'last_price', DEFAULT_PRICE_ANCHOR))
            if M <= 0:
                M = DEFAULT_PRICE_ANCHOR

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
            min_tick = getattr(self, 'min_tick', 1)
            if min_tick <= 0:
                min_tick = 1
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
