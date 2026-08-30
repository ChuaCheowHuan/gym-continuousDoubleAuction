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
    """(k_rows, book_rows, extra_dim, private_dim) from config."""
    layout = constants("observation_layout")
    return (layout["k_rows"], layout["book_rows"], layout["extra_dim"],
            layout["private_dim"])


K_ROWS, BOOK_ROWS, EXTRA_DIM, PRIVATE_DIM = _layout()
BOOK_DIM = BOOK_ROWS * K_ROWS
SNAPSHOT_DIM = BOOK_DIM + EXTRA_DIM

#: Order in which `set_agg_LOB` concatenates the book rows. This is the
#: definition of the book block's layout, and what `book_rows` is checked
#: against - it lets consumers name a row instead of indexing a magic number.
BOOK_ROW_ORDER = ("bid_price", "bid_size", "ask_price", "ask_size")

#: Order of the per-agent private block `set_private_state` builds, and the
#: single definition of what it contains. `private_dim` in
#: tunable_constants.json must equal its length; __init__ checks that, on the
#: same rule as `book_rows` above.
#:
#: This block is why the reward is learnable at all. It is
#: f(nav, prev_nav, max_nav, ...) and every one of those was unobservable, so
#: two agents holding opposite positions received the byte-identical vector and
#: needed opposite actions - which a policy, being a function of its
#: observation, cannot do (finding S1-2). `drawdown` matters especially: it is
#: a path functional over the whole episode, so no amount of recurrence could
#: have recovered it from a stream that never showed it.
#:
#: Every entry is normalised to O(1) and bounded, because these sit in the same
#: vector as the book block and feed the same `tanh` MLP - an unbounded private
#: field would saturate it exactly as the raw sizes do (S2-2).
PRIVATE_FIELDS = (
    "position",        # tanh(net_position / limit_max_size), signed, in (-1, 1)
    "position_val",    # mark-to-market exposure / init_nav, signed
    "cash",            # free cash / init_nav
    "cash_on_hold",    # cash escrowed against live orders / init_nav
    "nav",             # nav / init_nav, so 1.0 at reset
    "drawdown",        # (nav - max_nav) / init_nav, <= 0
    "vwap_vs_mid",     # (M - VWAP) / M when a position is open, else 0
    "realised_pnl",    # total_profit / init_nav
    "time_left",       # 1 - t_step / max_step, in [0, 1]
)


class State_Helper(object):

    def __init__(self, n_hist=env_default("n_hist"),
                 initial_price_min=env_default("initial_price_min"),
                 initial_price_max=env_default("initial_price_max"),
                 position_scale=env_default("position_scale"),
                 **kwargs):
        self.n_hist = n_hist
        self.obs_history = deque(maxlen=self.n_hist)

        # Centre of the `log_mid` feature: the log of the geometric mean of the
        # price-anchor range. `log_mid` restores the absolute price level that
        # midpoint normalisation throws away, but uncentred it is a near
        # constant - measured at 4.55..4.64 over a 400-step rollout, a standing
        # +4.6 bias into a `tanh` first layer while every price feature around
        # it has a standard deviation of 0.04. Centred on the range the anchor
        # is actually drawn from, it spans about -1.15..+1.15 instead and
        # carries the same information. Geometric rather than arithmetic mean
        # because the quantity is a logarithm: it puts the two ends of the
        # range symmetrically about zero.
        low = max(float(initial_price_min), 1e-12)
        high = max(float(initial_price_max), low)
        self.log_mid_centre = float(np.log(np.sqrt(low * high)))

        # Divisor of the private `position` field. Deliberately not
        # `limit_max_size`, which is what this used to be: that is a *sizing*
        # parameter - it scales the mean of the Gaussian `_set_size` draws from
        # and bounds nothing - whereas inventory accumulates over many fills.
        # Measured over 7,200 agent-steps of random play, |net_position| has a
        # median of 372 but a p90 of 1,195 and a maximum of 1,831, so
        # `limit_max_size` of 1,000 put 13.2% of steps into `tanh` saturation.
        self.position_scale = float(position_scale)
        if self.position_scale <= 0:
            raise ValueError(
                f"position_scale must be > 0; got {position_scale!r}."
            )

        # Observation layout as instance state. book_dim and snapshot_dim are
        # derived here and nowhere else - they are not config keys, because a
        # stored copy could disagree with k_rows.
        self.k_rows, self.book_rows, self.extra_dim, self.private_dim = _layout()
        if self.book_rows != len(BOOK_ROW_ORDER):
            raise ValueError(
                f"tunable_constants.json: observation_layout.book_rows="
                f"{self.book_rows} but set_agg_LOB builds "
                f"{len(BOOK_ROW_ORDER)} rows {BOOK_ROW_ORDER}. Change "
                f"set_agg_LOB and BOOK_ROW_ORDER to match."
            )
        if self.private_dim != len(PRIVATE_FIELDS):
            raise ValueError(
                f"tunable_constants.json: observation_layout.private_dim="
                f"{self.private_dim} but set_private_state builds "
                f"{len(PRIVATE_FIELDS)} fields {PRIVATE_FIELDS}. Change "
                f"set_private_state and PRIVATE_FIELDS to match."
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

        # Per agent, not one shared array: the book prefix is identical for
        # everyone but the private tail is not, and returning the same object
        # to every agent is the S1-2 defect this method used to embody. Built
        # through `set_next_state` so the reset observation is assembled by
        # exactly the same code as every later one - a reset that laid the two
        # blocks out differently would be invisible until a policy trained on
        # it behaved oddly at step 0.
        states = {}
        for trader in self.traders:
            # No step has completed at reset, so `time_left` is a full 1.0.
            states = self.set_next_state(states, trader, stacked_obs,
                                         elapsed_steps=0)

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

    def _l1_prices(self):
        """(best bid, best ask) from the raw snapshot, 0.0 where a side is empty.

        Reads `agg_LOB_raw`, which `set_agg_LOB` stores before it needs either
        value. Asks are held negated - the sign encodes the side - so the ask
        comes back through `abs`.
        """
        raw = self.agg_LOB_raw
        bid = float(raw[0])
        ask = float(raw[2 * self.k_rows])
        return (bid if bid > 0 else 0.0), (abs(ask) if ask != 0 else 0.0)

    def mid_price(self):
        """The Level-1 midpoint `M`, always strictly positive.

        The fallback chain, in order: both sides present, bid only, ask only,
        then the last traded price, then `midpoint_fallback`. Guaranteeing a
        positive result is what lets every division and logarithm downstream -
        the price normalisation, `log_mid`, the private block's `vwap_vs_mid` -
        be written without a guard of its own.

        See doc/05 2.1.
        """
        l1_bid, l1_ask = self._l1_prices()

        if l1_bid > 0 and l1_ask > 0:
            return (l1_bid + l1_ask) / 2.0
        if l1_bid > 0:
            return l1_bid
        if l1_ask > 0:
            return l1_ask

        M = float(getattr(self, 'last_price', self.midpoint_fallback))
        return M if M > 0 else self.midpoint_fallback

    def set_private_state(self, trader, elapsed_steps=None):
        """This trader's private block: `private_dim` floats, all O(1).

        Everything here is normalised by the trader's own `init_nav` or is
        already a ratio, so the block is on the same scale as the normalised
        book and cannot saturate the `tanh` MLP the way raw sizes do (S2-2).
        `PRIVATE_FIELDS` names the entries in order and is the definition of
        the layout; this function must build them in that order.

        Read straight off the account rather than through `info`: `set_info`
        computes the same quantities for logging, but it runs *after* this in
        `set_step_outputs` and formats for JSON. Sharing the values would make
        the observation depend on the logging path, which is exactly the
        coupling doc/11 warns about.

        Args:
            trader: The trader whose private state to encode.
            elapsed_steps: Steps completed, for `time_left`. None means "read it
                off the env", which is `t_step + 1` because `step()` has not
                incremented yet - see the note at that line. `reset` passes 0.

        Returns:
            `(private_dim,)` float32.
        """
        if elapsed_steps is None:
            elapsed_steps = self.t_step + 1
        acc = trader.acc

        # Guarded on the same rule as `Reward_Helper.set_reward`: a
        # non-positive starting NAV makes every ratio here undefined, and
        # silently emitting inf/nan into the observation is worse than failing.
        scale = float(acc.init_nav)
        if scale <= 0:
            raise ValueError(
                f"Trader {trader.ID} has init_nav={scale}, so its private "
                "state cannot be normalised. init_cash must be > 0 (see "
                "env_defaults.json)."
            )

        # Position as a bounded fraction of a reference inventory. tanh rather
        # than a clip: an agent at 3x that size and one at 30x should not
        # encode identically, and tanh keeps the difference while staying in
        # (-1, 1).
        #
        # `position_scale`, not `limit_max_size`: see __init__. The latter
        # bounds nothing and is a per-order quantity, while inventory
        # accumulates across fills, so it put 13.2% of agent-steps into
        # saturation.
        position = np.tanh(float(acc.net_position) / self.position_scale)

        # Cost basis relative to the current midpoint - the direction and size
        # of the open position's unrealised move, in the same fractional units
        # the book prices use. Zero when flat.
        #
        # `entry_vwap`, not `VWAP`: the latter has realised P&L rolled into it
        # by `_size_decrease` and can go negative (long 2 @ 100, sell 1 @ 250
        # gives -50), at which point the `> 0` guard below returned 0.0 - the
        # encoding for *flat* - while the agent still held a position. Measured
        # on 2.5% of open-position agent-steps. `entry_vwap` is the price
        # actually paid for the lots still held, so it is positive whenever
        # there is a position and the guard means what it says.
        midpoint = float(self.mid_price())
        vwap = float(acc.entry_vwap)
        vwap_vs_mid = (midpoint - vwap) / midpoint if vwap > 0 else 0.0

        # `t_step + 1`, not `t_step`. `step()` increments it *after*
        # `set_step_outputs` has built the observations, so at the moment this
        # runs `t_step` still names the step being finished rather than the one
        # about to start. Reading it raw made the reset observation and the one
        # after the first step both report 1.0, and the terminal observation
        # report `1/max_step` remaining instead of 0.
        #
        # The reset path has no completed step, so it passes `elapsed_steps=0`
        # explicitly and gets the 1.0 it should.
        #
        # `max_step` can be 0 in a degenerate config; treat that as "no time
        # left" rather than dividing by it.
        elapsed = (float(elapsed_steps) / float(self.max_step)
                   if self.max_step else 1.0)

        private = np.array([
            position,
            float(acc.position_val) / scale,
            float(acc.cash) / scale,
            float(acc.cash_on_hold) / scale,
            float(acc.nav) / scale,
            # <= 0 by construction: max_nav is the running peak.
            (float(acc.nav) - float(acc.max_nav)) / scale,
            vwap_vs_mid,
            float(acc.total_profit) / scale,
            max(0.0, 1.0 - elapsed),
        ], dtype=np.float32)

        if len(private) != self.private_dim:
            raise ValueError(
                f"set_private_state built {len(private)} fields but "
                f"private_dim is {self.private_dim}."
            )
        return private

    def set_next_state(self, next_states, trader, state_input,
                       elapsed_steps=None):
        """
        Set next state.

        The book prefix is shared - it is the same public order book for
        everyone, computed once per step by `prep_next_state` - and only the
        private tail differs per agent. That split is why `state_input` is
        still passed in rather than rebuilt here.

        Argument:
            next_states: Dictionary.
            trader: A trader object.
            state_input: The stacked, shared book observation after all actions
                         are executed.

        Returns:
            next_states: Dictionary of states for each trader.
        """
        next_states[f'agent_{trader.ID}'] = np.concatenate(
            [state_input, self.set_private_state(trader, elapsed_steps)]
        ).astype(np.float32)

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

        # Calculate Level 1 midpoint price M. Both this and `mid_price` read
        # the raw snapshot just stored above, so there is one definition of the
        # fallback chain rather than a copy in each caller - it decides what
        # every price in the observation is measured against, and two copies
        # could disagree about an empty or one-sided book.
        l1_bid, l1_ask = self._l1_prices()
        M = self.mid_price()

        # Apply price normalization using symmetric midpoint distance:
        # norm_P_bid = (M - P_bid) / M (non-negative)
        # norm_P_ask = -((abs(P_ask) - M) / M) (negated to maintain negative ask observation sign convention)
        norm_bid_price = np.where(bid_price_list > 0, (M - bid_price_list) / M, 0.0)
        norm_ask_price = np.where(ask_price_list != 0, -((np.abs(ask_price_list) - M) / M), 0.0)

        # Volume normalization: sqrt of the level volume as a fraction of a
        # reference size, keeping the observation's sign convention.
        #
        # The division is the fix for doc/15 S2-2. Raw `sqrt(V)` reached +-47
        # against +-0.58 for the normalised prices beside it - a 220x spread in
        # standard deviation (9.0 vs 0.04) into a `tanh` first layer with no
        # `MeanStdFilter` anywhere, so size features saturated and dominated
        # while price features contributed almost nothing. `limit_max_size` is
        # the reference because it is the scale orders are drawn on, and it
        # lands the result where a bounded activation can use it: measured over
        # 9,565 populated levels, sqrt(V / limit_max_size) has a median of 0.52,
        # a p99 of 0.94 and a maximum of 1.32.
        size_scale = float(self.limit_max_size)
        norm_bid_size = np.where(
            bid_size_list > 0, np.sqrt(bid_size_list / size_scale), 0.0)
        norm_ask_size = np.where(
            ask_size_list != 0,
            -np.sqrt(np.abs(ask_size_list) / size_scale), 0.0)

        # Market-level scalars appended after the book block.
        #
        # log_mid restores the price anchor that midpoint normalization discards:
        # without it a market at price 10 and one at price 100 are indistinguishable,
        # even though min_tick is absolute and so worth 10x more in the former.
        # M is guaranteed > 0 by the fallback chain above, so log() is always defined.
        #
        # Centred on `log_mid_centre` - see __init__ for why. The information is
        # unchanged: the centre is a constant of the configuration, not of the
        # episode, so subtracting it is a shift the network would otherwise have
        # to learn to undo before the feature could do anything.
        log_mid = np.log(M) - self.log_mid_centre

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
