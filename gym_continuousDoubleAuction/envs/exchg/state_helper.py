import numpy as np
from collections import deque
from itertools import islice

from ...config_loader import constant, constants, env_default

# Layout of a single observation snapshot, from
# `config/tunable_constants.json` -> observation_layout.
#
# The book block is `book_rows` stacked rows of `k_rows` price levels:
#   [bid_price, bid_size, ask_price, ask_size]
# followed by the `extra_dim` market-level scalars `EXTRA_FIELDS` names below.
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

#: The market-level scalars appended after the book block, in order. Same rule
#: as BOOK_ROW_ORDER and PRIVATE_FIELDS: `extra_dim` in tunable_constants.json
#: must equal its length, and __init__ checks that.
#:
#: The last four exist because the observation used to carry **no information
#: about executions at all** (doc/15 S2-7): `set_agg_LOB` iterated the tape,
#: incremented a counter and threw it away, the loop body being a commented-out
#: `write` copy-pasted from `OrderBook.__str__`. In a continuous double auction
#: aggressive order flow is the most predictive public signal there is - more so
#: than the resting book, which is largely stale intentions - and an agent could
#: not see the last traded price, the direction of a trade, or that a trade had
#: happened.
#:
#: `mid_return` is the other half of that, and belongs to S2-6: it is the change
#: in the very quantity every price in the frame is divided by, so an agent can
#: tell a book that moved from a midpoint that moved.
EXTRA_FIELDS = (
    "log_mid",             # log(M_frame) - log_mid_centre
    "log1p_spread_ticks",  # log1p(spread / min_tick), 0.0 if not two-sided
    "mid_return",          # M_frame / M_previous_frame - 1
    "signed_volume",       # (buy-initiated - sell-initiated) qty / limit_max_size
    "log1p_trade_count",   # log1p(trades since the previous frame)
    "trade_direction",     # initiator side of the last trade: +1 buy, -1 sell, 0 none
)

#: Offsets of the frame-local values a raw frame carries after its book block.
#: A raw frame is `[book (book_rows*k_rows) | M | spread_ticks | mid_return |
#: signed_volume | trade_count | trade_direction]`. `M` and `spread_ticks` are
#: raw here and become `log_mid` / `log1p_spread_ticks` at normalisation time;
#: the rest pass through untouched, being frame-local already.
_FRAME_M = 0
_FRAME_SPREAD_TICKS = 1
_FRAME_MID_RETURN = 2
_FRAME_SIGNED_VOLUME = 3
_FRAME_TRADE_COUNT = 4
_FRAME_TRADE_DIRECTION = 5
_FRAME_EXTRAS = 6

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
#: The per-agent fields that do not depend on book depth, in order. These are
#: the nine the private block started with; `private_fields` appends the
#: depth-dependent own-book block after them.
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
BASE_PRIVATE_FIELDS = (
    "position",        # tanh(net_position / position_scale), signed, in (-1, 1)
    "position_val",    # mark-to-market exposure / init_nav, signed
    "cash",            # free cash / init_nav
    "cash_on_hold",    # cash escrowed against live orders / init_nav
    "nav",             # nav / init_nav, so 1.0 at reset
    "drawdown",        # (nav - max_nav) / init_nav, <= 0
    "vwap_vs_mid",     # (M - VWAP) / M when a position is open, else 0
    "realised_pnl",    # total_profit / init_nav
    "time_left",       # 1 - t_step / max_step, in [0, 1]
)

#: The two own-order counts that follow the own-book sizes, and the feedback
#: flag that follows them. See `private_fields`.
OWN_COUNT_FIELDS = (
    "own_bid_count",   # this agent's resting bids / max_own_orders, clipped to 1
    "own_ask_count",   # this agent's resting asks / max_own_orders, clipped to 1
)
FEEDBACK_FIELDS = (
    "unmatched_last_step",  # 1.0 if the agent's last modify/cancel named no order
)


def own_book_fields(k_rows):
    """Names of the own-book sizes: bids at levels 0..k-1, then asks."""
    return (
        tuple(f"own_bid_size_{k}" for k in range(k_rows))
        + tuple(f"own_ask_size_{k}" for k in range(k_rows))
    )


def private_fields(k_rows):
    """The private block's layout at a given book depth, in order.

    `[base (9) | own bid sizes (k) | own ask sizes (k) | own counts (2) |
    unmatched_last_step (1)]`. The own-book block is the S1-2 tail closed
    (doc/15 S3-24 phase 1): the agent used to see how much cash it had
    escrowed but not where, so a cancel was a guess about state the policy
    was never shown - measured at a 7% hit rate under random play. Level k of
    the own book is level k of the public book in the same snapshot, on the
    same `sqrt(V / limit_max_size)` scale and with asks negative, so a
    tokenising encoder can carry own size as two more channels of each level
    token (see `train/model/encoders/tokenize.py`). The counts cover orders
    deeper than the book shows; the flag is phase 3 - the consequence of a
    dead action, in the next observation rather than only in a log.

    `observation_layout.private_dim` in tunable_constants.json must equal
    `len(private_fields(k_rows))`; `State_Helper.__init__` checks that.
    """
    return BASE_PRIVATE_FIELDS + own_book_fields(k_rows) + OWN_COUNT_FIELDS + FEEDBACK_FIELDS


def own_book_offset():
    """Index within the private block where `own_bid_size_0` sits."""
    return len(BASE_PRIVATE_FIELDS)


#: The private block at the import-time layout, for consumers with no env to
#: ask - the visualizers and the tests. Runtime code uses
#: `self.private_fields`, built from the instance's `k_rows`.
PRIVATE_FIELDS = private_fields(K_ROWS)
OWN_BOOK_OFFSET = own_book_offset()

#: Bumped whenever the observation vector's layout changes shape or meaning,
#: so a checkpoint records which layout its weights were trained against and a
#: restore into a different one fails by name rather than by tensor shape
#: (doc/15 S4-19). 1 was the 193-float layout with a 9-field private block;
#: 2 added the own-book block and the feedback flag (216 floats at defaults).
OBSERVATION_LAYOUT_VERSION = 2


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
        if self.extra_dim != len(EXTRA_FIELDS):
            raise ValueError(
                f"tunable_constants.json: observation_layout.extra_dim="
                f"{self.extra_dim} but set_agg_LOB builds "
                f"{len(EXTRA_FIELDS)} scalars {EXTRA_FIELDS}. Change "
                f"set_agg_LOB and EXTRA_FIELDS to match."
            )
        # Built from this instance's depth, not the import-time constant, so a
        # config tree swapped in under `$CDA_CONFIG_DIR` gets the block for
        # ITS k_rows.
        self.private_fields = private_fields(self.k_rows)
        if self.private_dim != len(self.private_fields):
            raise ValueError(
                f"tunable_constants.json: observation_layout.private_dim="
                f"{self.private_dim} but set_private_state builds "
                f"{len(self.private_fields)} fields at k_rows={self.k_rows} "
                f"(9 base + 2*k_rows own-book + 2 counts + 1 flag). Set "
                f"private_dim to {len(self.private_fields)} or change "
                f"private_fields() to match."
            )
        # Normaliser of the own-order counts, and the cardinality of the
        # `order_slot` action head minus one - the same key, so what the agent
        # is shown and what it can aim at agree.
        self.max_own_orders = int(constant("action_space", "max_own_orders"))
        if self.max_own_orders < 1:
            raise ValueError("action_space.max_own_orders must be >= 1")
        self.book_dim = self.book_rows * self.k_rows
        self.snapshot_dim = self.book_dim + self.extra_dim

        # Where the tape had reached, and what the midpoint was, when the last
        # frame was committed to `obs_history`. Trade flow and `mid_return` are
        # both differences against the previous *committed* frame, and
        # `set_agg_LOB` runs twice per step - once pre-action for the render
        # path - so neither may advance these. `prep_next_state` does, because
        # it is the one place a frame enters the history.
        self._tape_cursor = 0
        self._prev_frame_mid = None

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
        Populates the shared obs_history deque with n_hist copies of the
        initial RAW frame.
        """
        self._tape_cursor = 0
        self._prev_frame_mid = None

        self.agg_LOB = self.set_agg_LOB()
        n_hist = self.n_hist
        self.obs_history = deque([self.agg_LOB_frame] * n_hist, maxlen=n_hist)
        self._prev_frame_mid = float(self.agg_LOB_frame[self.book_dim + _FRAME_M])

        stacked_obs = self._stack(float(self._prev_frame_mid))

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
            stacked_obs: The temporal stacked state of the aggregated LOB after
            all actions are executed, every frame normalised by the CURRENT
            midpoint.

        The deque holds **raw** frames and the whole stack is normalised once,
        here, by `M_t`. It used to hold frames that had each already been
        normalised by their own midpoint, so frames t-3..t carried denominators
        M_{t-3}..M_t and could not meaningfully be differenced - which is the
        entire purpose of stacking them. That is doc/15 S2-6.

        Concretely: a bid resting at 90 while the midpoint moves 100 -> 96 used
        to read 0.100 in one frame and 0.063 in the next. The order had not
        moved; its denominator had. It now reads 0.0625 in both, while
        `log_mid` still differs across the two frames (0.0 -> -0.0408) and
        `mid_return` records the move as -0.04 - so nothing is lost, it is
        simply no longer smeared through every price in the book.
        """

        self.agg_LOB_aft = self.set_agg_LOB() # LOB state at t+1 after processing LOB

        self.obs_history.append(self.agg_LOB_frame)

        # Only here, because only here does a frame enter the history. See the
        # note on `_tape_cursor` in __init__.
        self._tape_cursor = len(self.LOB.tape)
        M_t = float(self.agg_LOB_frame[self.book_dim + _FRAME_M])
        self._prev_frame_mid = M_t

        return self._stack(M_t)

    def _stack(self, M_t):
        """Every frame in the history, normalised by `M_t`, end to end."""
        return np.concatenate(
            [self._normalise_frame(frame, M_t) for frame in self.obs_history],
            axis=0,
        ).astype(np.float32)

    def _normalise_frame(self, frame, M_t):
        """One raw frame as `snapshot_dim` normalised floats.

        Prices are measured against `M_t` - the midpoint of the newest frame,
        not of this one - so the same absolute price reads the same in every
        frame of the stack. `log_mid` keeps each frame's OWN midpoint, which is
        what lets an agent recover the level it was at; the frame is normalised
        against a common denominator, not stripped of its own.
        """
        k = self.k_rows
        book = frame[:self.book_dim]
        extras = frame[self.book_dim:]

        bid_price = book[0:k]
        bid_size = book[k:2 * k]
        ask_price = book[2 * k:3 * k]
        ask_size = book[3 * k:4 * k]

        norm_bid_price = np.where(bid_price > 0, (M_t - bid_price) / M_t, 0.0)
        norm_ask_price = np.where(
            ask_price != 0, -((np.abs(ask_price) - M_t) / M_t), 0.0)

        # Sizes carry no dependence on the midpoint, so they normalise the same
        # way in every frame. See set_agg_LOB for why they are divided.
        size_scale = float(self.limit_max_size)
        norm_bid_size = np.where(
            bid_size > 0, np.sqrt(bid_size / size_scale), 0.0)
        norm_ask_size = np.where(
            ask_size != 0, -np.sqrt(np.abs(ask_size) / size_scale), 0.0)

        M_frame = float(extras[_FRAME_M])
        spread_ticks = float(extras[_FRAME_SPREAD_TICKS])

        scalars = np.array([
            np.log(M_frame) - self.log_mid_centre,
            np.log1p(max(0.0, spread_ticks)) if spread_ticks > 0 else 0.0,
            extras[_FRAME_MID_RETURN],
            extras[_FRAME_SIGNED_VOLUME],
            np.log1p(max(0.0, float(extras[_FRAME_TRADE_COUNT]))),
            extras[_FRAME_TRADE_DIRECTION],
        ])

        return np.concatenate([
            norm_bid_price, norm_bid_size, norm_ask_price, norm_ask_size,
            scalars,
        ]).astype(np.float32)

    def _trade_flow(self):
        """Execution flow since the last frame entered the history.

        Returns `(signed_volume, trade_count, direction)`, all raw.

        `signed_volume` signs each fill by its **initiator's** side, which is
        what makes it order flow rather than volume: a trade whose aggressor
        bought is +q, one whose aggressor sold is -q. That is the quantity
        microstructure research finds most predictive of short-horizon returns,
        and the observation carried nothing of it at all (doc/15 S2-7).

        Does not advance `_tape_cursor` - `prep_next_state` does, because
        `set_agg_LOB` runs twice per step and only one of those commits a frame.
        """
        tape = self.LOB.tape
        total = len(tape)
        if total <= self._tape_cursor:
            return 0.0, 0, 0.0

        signed = 0.0
        count = 0
        direction = 0.0
        for entry in islice(tape, self._tape_cursor, total):
            quantity = float(entry.get('quantity', 0) or 0)
            initiator = (entry.get('init_party') or {}).get('side')
            sign = 1.0 if initiator == 'bid' else -1.0
            signed += sign * quantity
            direction = sign
            count += 1

        return signed, count, direction

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

        base = np.array([
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

        own_bid, own_ask, n_bid, n_ask = self.own_book(trader)
        cap = float(self.max_own_orders)
        tail = np.array([
            min(1.0, n_bid / cap),
            min(1.0, n_ask / cap),
            # Read before `set_step_outputs` zeroes the counter, so this is the
            # step just finished: did this agent's modify/cancel name nothing?
            1.0 if acc.num_unmatched_step > 0 else 0.0,
        ], dtype=np.float32)

        private = np.concatenate([base, own_bid, own_ask, tail]).astype(np.float32)

        if len(private) != self.private_dim:
            raise ValueError(
                f"set_private_state built {len(private)} fields but "
                f"private_dim is {self.private_dim}."
            )
        return private

    def own_book(self, trader):
        """This trader's resting size at each public level, and its order counts.

        Returns `(own_bid, own_ask, n_bid, n_ask)`: two `(k_rows,)` float32
        arrays on the public book's `sqrt(V / limit_max_size)` scale, asks
        negative, zero where the trader has nothing at that level (or the
        level is empty); and the trader's resting order count per side over
        the whole book, not only the shown depth.

        Reads the live book, not the snapshot: `set_private_state` runs after
        `prep_next_state` in `set_step_outputs`, so the book here is the one
        the newest snapshot was taken from, and level k here is level k there.
        Own orders deeper than `k_rows` are in the counts but not the sizes,
        the same way the public book hides them.
        """
        k = self.k_rows
        size_scale = float(self.limit_max_size)
        own_bid = np.zeros(k, dtype=np.float32)
        own_ask = np.zeros(k, dtype=np.float32)

        def fill(tree, levels, out, sign):
            for level, (_price, order_list) in enumerate(levels):
                if level >= k:
                    break
                qty = 0
                for order in order_list:
                    if order.trade_id == trader.ID:
                        qty += int(order.quantity)
                if qty:
                    out[level] = sign * np.sqrt(qty / size_scale)

        fill(self.LOB.bids, reversed(self.LOB.bids.price_map.items()), own_bid, 1.0)
        fill(self.LOB.asks, self.LOB.asks.price_map.items(), own_ask, -1.0)

        n_bid = sum(1 for o in self.LOB.bids.order_map.values() if o.trade_id == trader.ID)
        n_ask = sum(1 for o in self.LOB.asks.order_map.values() if o.trade_id == trader.ID)
        return own_bid, own_ask, n_bid, n_ask

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
        # Raw unnormalized snapshot. float64, not float32: `_set_price`
        # reads resting prices out of this array to quote at a book level, and
        # float32 cannot hold 100.1 (it reads back 100.0999984741211). The
        # emitted observation is cast to float32 at emission, in `_stack`; the
        # raw array is the one consumer that needs the price exact.
        flattened_raw = np.concatenate([bid_price_list, bid_size_list, ask_price_list, ask_size_list]).astype(np.float64)
        self.agg_LOB_raw = flattened_raw

        # Calculate Level 1 midpoint price M. Both this and `mid_price` read
        # the raw snapshot just stored above, so there is one definition of the
        # fallback chain rather than a copy in each caller - it decides what
        # every price in the observation is measured against, and two copies
        # could disagree about an empty or one-sided book.
        l1_bid, l1_ask = self._l1_prices()
        M = self.mid_price()

        # Spread in the tick units the action space quotes in (min_tick), not the
        # tick_size config, which is dropped on reset. A resting book can never be
        # locked or crossed (a bid at or above the best ask is filled on arrival), so
        # a two-sided book always has a spread of at least 1 tick and therefore
        # log1p >= log1p(1) = 0.693. That leaves 0.0 as an unambiguous sentinel for
        # "no two-sided market".
        if l1_bid > 0 and l1_ask > 0:
            min_tick = getattr(self, 'min_tick', env_default("tick_size"))
            if min_tick <= 0:
                min_tick = env_default("tick_size")
            spread_ticks = (l1_ask - l1_bid) / min_tick
        else:
            spread_ticks = 0.0

        # Motion of the denominator every price in this frame is divided by.
        # 0.0 on the first frame, where there is no previous midpoint - the same
        # value a market that did not move reports, which is the right reading
        # of "nothing has changed yet".
        if self._prev_frame_mid:
            mid_return = M / float(self._prev_frame_mid) - 1.0
        else:
            mid_return = 0.0

        # Execution flow since the previous frame. This is what the old tape
        # loop was supposed to produce: it iterated `reversed(self.LOB.tape)`,
        # incremented a counter and discarded it, its body a commented-out
        # `write` copy-pasted from `OrderBook.__str__`, so the observation
        # carried zero information about trades (doc/15 S2-7).
        signed_volume, trade_count, trade_direction = self._trade_flow()

        # The raw frame, which is what `obs_history` stores. Normalisation is
        # deferred to emission so that one midpoint normalises the whole stack
        # - see `prep_next_state`.
        self.agg_LOB_frame = np.concatenate([
            flattened_raw,
            np.array([
                M,
                spread_ticks,
                mid_return,
                signed_volume / float(self.limit_max_size),
                float(trade_count),
                trade_direction,
            ]),
        ]).astype(np.float32)

        # The current frame, normalised against its own midpoint. At emission
        # time that is `M_t`, so the newest frame of a stack is identical
        # either way; this keeps `set_agg_LOB`'s contract - "return the
        # normalised snapshot" - for the render path and its callers.
        return self._normalise_frame(self.agg_LOB_frame, M)
    
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
