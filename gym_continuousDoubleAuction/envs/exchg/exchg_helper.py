import numpy as np
import pandas as pd

from .state_helper import State_Helper
from .action_helper import Action_Helper
from .reward_helper import Reward_Helper
from .done_helper import Done_Helper
from .info_helper import Info_Helper

from ..orderbook.orderbook import OrderBook
from ...config_loader import env_default
from ...logging_setup import get_logger

from tabulate import tabulate

logger = get_logger(__name__)

class Exchg_Helper(State_Helper, Action_Helper, Reward_Helper, Done_Helper, Info_Helper):
    #: Accepted values of the `mark_price_source` config key.
    MARK_PRICE_SOURCES = ("mid", "last")

    def __init__(self, init_cash=env_default("init_cash"),
                 tick_size=env_default("tick_size"),
                 tape_display_length=env_default("tape_display_length"),
                 n_hist=env_default("n_hist"),
                 mark_price_source=env_default("mark_price_source"),
                 matching_rule=env_default("matching_rule"),
                 step_clearing=env_default("step_clearing"),
                 **kwargs):
        # tick_size goes on to Action_Helper as well: it is the tick the action
        # space quotes on, not just a property of the book.
        super().__init__(n_hist=n_hist, tick_size=tick_size, **kwargs)

        # The matching regime (doc/06 section 8): how a price level is shared
        # out, and whether a step's crossing orders clear on arrival or at one
        # uniform price. Validated here so a typo fails at construction.
        if matching_rule not in OrderBook.MATCHING_RULES:
            raise ValueError(
                f"matching_rule must be one of {OrderBook.MATCHING_RULES}; got {matching_rule!r}."
            )
        if step_clearing not in self.STEP_CLEARINGS:
            raise ValueError(
                f"step_clearing must be one of {self.STEP_CLEARINGS}; got {step_clearing!r}."
            )
        self.matching_rule = matching_rule
        self.step_clearing = step_clearing

        # The configured tick. The book itself takes no tick - it never read
        # the one it used to be handed - so this is kept for callers that ask
        # the env what grid it quotes on; the live copy the action layer uses
        # is `Action_Helper.min_tick`, set from the same key.
        self.tick_size = tick_size

        self.tape_display_length = tape_display_length
        self.LOB = self.new_order_book() # limit order book
        self.agg_LOB = {} # aggregated or consolidated LOB
        self.agg_LOB_raw = {} # unnormalized raw aggregated LOB
        self.agg_LOB_aft = {} # aggregated or consolidated LOB after processing orders

        self.seq_trades = [] # list of trade lists
        self.seq_order_in_book = [] # list of new order_in_book dicts

        self.init_cash = init_cash

        if mark_price_source not in self.MARK_PRICE_SOURCES:
            raise ValueError(
                f"mark_price_source={mark_price_source!r} is not one of "
                f"{self.MARK_PRICE_SOURCES}. See env_defaults.json."
            )
        self.mark_price_source = mark_price_source

        self.model_actions = None
        self.LOB_actions = None
        self.shuffled_actions = None

        # Top of book at the last `set_market_snapshot`; None until a step.
        self.best_bid = None
        self.best_ask = None
        self.spread = None

    #: `sequential`: each order matches on arrival in the step's shuffled
    #: order. `batch`: the step's new orders clear together at one price.
    STEP_CLEARINGS = ("sequential", "batch")

    def new_order_book(self):
        """A fresh book under this env's matching rule; `reset` builds one per episode."""
        return OrderBook(self.tape_display_length, matching_rule=self.matching_rule)

    def do_actions(self, actions):
        """Process the step's actions under `step_clearing` (doc/06 section 8).

        `sequential` is `Action_Helper.do_actions`: each order matches on
        arrival, in shuffled order. `batch` opens the book's batch first, so
        every new market or limit order (and a modify's re-entered quote) is
        queued while cancels and the cash checks run as usual, then clears the
        queue at one uniform price and settles each trader's result through
        `Trader.settle_batch`. The per-action trade lists are aligned with the
        shuffled actions either way, which is what the render path expects.
        """
        # Where this step's order ids start, for anything that wants to tell
        # a new order from a resting one after the fact (the measurements do).
        self.step_first_order_id = self.LOB.next_order_id + 1
        if self.step_clearing != "batch":
            return super().do_actions(actions)

        self.LOB.begin_batch()
        seq_trades, seq_order_in_book = super().do_actions(actions)
        # The reference is the pre-batch book's, the same one the agents saw.
        results = {tid: (trades, oib)
                   for tid, trades, oib in self.LOB.clear_batch(reference_price=self.reference_price())}
        for tid, (trades, oib) in results.items():
            self.traders[tid].settle_batch(trades, oib, self.traders)
        for i, action in enumerate(actions):
            tid = int(action["ID"].split("_")[1])
            if tid in results:
                seq_trades[i], seq_order_in_book[i] = results[tid]
        return seq_trades, seq_order_in_book

    def reset_traders_acc(self):
        """
        Reset traders accounts.
        """

        for trader in self.traders:
            trader.acc.reset_acc(trader.ID, self.init_cash)

    def mark_price(self):
        """The price every account is marked at this step, or None.

        `mark_price_source` picks the chain:

        * ``"mid"`` - the L1 midpoint of a **two-sided** book, then the last
          tape print, then a one-sided quote. This is the default and the
          reason is doc/15 S2-5: the mark used to be the last print alone, so
          one trade at a chosen price re-marked every account in the market. A
          midpoint cannot be moved by printing a trade; it moves only when
          someone *quotes*, and a quote that moves it is one anybody else can
          hit.
        * ``"last"`` - the last tape print alone, which is the previous
          behaviour, kept so a run can reproduce it.

        **The two-sided requirement is the load-bearing part**, not an edge
        case. `State_Helper.mid_price` falls back to whichever side is present,
        because the observation needs a positive number to normalise against.
        Doing that here would hand back the manipulation by another route: a
        lone resting bid far from the market would *be* the mark, so an agent
        could re-price every account by quoting a price nobody has traded at
        and cancelling it next step. Measured, before this fallback was
        narrowed: a 1-lot self-cross whose resting leg survived moved 1,000
        NAV even though self-match prevention had stopped the print. Falling
        back to the last trade instead means moving the mark takes a real
        two-sided market - and by the time one exists, moving the mid means
        posting a better quote that someone can lift.

        Read off `LOB.get_best_bid()` / `get_best_ask()` rather than through
        `State_Helper.mid_price()`, which is the same shape of chain over
        `agg_LOB_raw`. That snapshot is taken *before* the step's orders are
        processed, so at mark time it is one step stale; the book itself is
        not. Decimal throughout, because this is a price and it goes straight
        into the ledger.
        """
        best_bid = self.LOB.get_best_bid()
        best_ask = self.LOB.get_best_ask()

        if self.mark_price_source == "mid":
            if best_bid is not None and best_ask is not None:
                return (best_bid + best_ask) / 2

        if len(self.LOB.tape) > 0:
            return self.LOB.tape[-1].get('price')

        # No trade has ever printed, so nobody holds a position and the mark
        # cannot move anyone's NAV. A one-sided quote is as good an answer as
        # exists, and it keeps `mark_to_mkt` from being a no-op that leaves
        # `prev_nav` stale.
        if self.mark_price_source == "mid":
            if best_bid is not None:
                return best_bid
            if best_ask is not None:
                return best_ask

        return None

    def mark_to_mkt(self):
        """
        Mark every trader's account at `mark_price`.

        `last_price` keeps tracking the last *traded* price whatever the mark
        source is: it is the ghost-level anchor `Action_Helper._set_price`
        quotes around and the final fallback of `State_Helper.mid_price`, and
        both of those want "where did this market last actually trade".
        """
        if len(self.LOB.tape) > 0:
            self.last_price = float(self.LOB.tape[-1].get('price')) # anchor

        mkt_price = self.mark_price()
        if mkt_price is None:
            return 0

        for trader in self.traders:
            trader.acc.mark_to_mkt(trader.ID, mkt_price)

        return 0

    def set_market_snapshot(self):
        """Record top of book and the spread for this step.

        The spread was previously computed nowhere durable: `state_helper`
        derives `log1p(spread_ticks)` for the observation and discards the raw
        number, so the single most-used market-quality metric never reached a
        log (doc/11 2.2).

        `None` rather than 0.0 when a side is empty. The observation needs a
        finite sentinel and uses 0.0 for "no two-sided market"; a log does not,
        and 0.0 there would be indistinguishable from a genuinely crossed-to-
        touching book - the ambiguity doc/15 S3-14 is about. `None` encodes as
        JSON null.
        """
        # Decimal, as the book already reports them: these are prices, and
        # prices stay Decimal until something serialises them (doc/11 1.8).
        self.best_bid = self.LOB.get_best_bid()
        self.best_ask = self.LOB.get_best_ask()
        if self.best_bid is not None and self.best_ask is not None:
            self.spread = self.best_ask - self.best_bid
        else:
            self.spread = None

        return 0

    def set_step_outputs(self, state_input):
        """
        Set outputs for each step.

        Arguments:
            state_input: The aggregated LOB after actions executions.

        Return:
            next_states, rewards, dones, infos
        """

        # Once per step, not once per trader: the book is the same for all of
        # them, and set_info reads it off self the way it already reads
        # last_price.
        self.set_market_snapshot()

        next_states, rewards, dones, infos = {},{},{},{}
        for trader in self.traders:
            # A trader terminated on an earlier step is not scored again. It
            # still holds an account (the NAV-conservation check sums every
            # trader, live or not), it simply stops producing transitions -
            # see `Done_Helper.set_done` and doc/15 S2-4.
            if not self.is_live(trader):
                continue

            next_states = self.set_next_state(next_states, trader, state_input) # dict of tuple of tuples
            rewards = self.set_reward(rewards, trader)
            # After the reward, so the step on which an agent goes bankrupt
            # still carries the observation and reward of its terminal
            # transition, which is what a learner needs to bootstrap it.
            dones = self.set_done(dones, trader)
            infos = self.set_info(infos, trader)

            # Reset per-step counters after reward is calculated
            trader.acc.num_trades_step = 0
            trader.acc.num_passive_fills_step = 0
            trader.acc.order_step_placed = 0
            trader.acc.num_rejected_step = 0
            trader.acc.num_unmatched_step = 0
            trader.acc.num_obs_clipped_step = 0

        dones, truncateds = self.set_all_done(dones)

        return next_states, rewards, dones, truncateds, infos

    # The print_* methods below keep their names - they are the render path,
    # called only from `_render` - but write to the logger at DEBUG rather than
    # to stdout. `render()` checks that DEBUG is enabled before calling any of
    # them, so the tabulate and DataFrame work here does not happen for output
    # that would be dropped.

    def print_table(self, msg, data):
        """
        Tabulate data for display.
        If data is a 1D numpy array holding a flat LOB snapshot, reshape the book
        block into a `book_rows`-column table headed by BOOK_ROW_ORDER, then
        log any trailing market-level scalars on their own line.
        """
        if isinstance(data, np.ndarray) and data.ndim == 1 and data.size >= self.obs_book_dim:
            book = data[:self.obs_book_dim]
            extras = data[self.obs_book_dim:]
            # shape (cells, rows): each row of the table is one level or one
            # tick offset, depending on `book_mode`.
            reshaped = book.reshape(len(self.obs_book_rows), self.obs_book_cells).T
            headers = list(self.obs_book_rows)
            logger.debug("%s %s", msg, tabulate(reshaped, headers=headers))
            if extras.size == self.extra_dim:
                logger.debug(
                    "log_mid = %.6f; log1p_spread_ticks = %.6f",
                    extras[0], extras[1],
                )
        else:
            logger.debug("%s %s", msg, tabulate(data))
        return 0

    def print_order_in_book_all_seq(self, all_order_in_book):
        for act_seq_num, order_in_book in enumerate(all_order_in_book):
            if order_in_book is not None and order_in_book != []:
                logger.debug(
                    "order_in_book (act_seq_num): %s\n%s",
                    act_seq_num, tabulate([order_in_book], headers="keys"),
                )

    def print_trades_all_seq(self, all_trades):
        for act_seq_num, trades in enumerate(all_trades):
            self._print_trades(act_seq_num, trades)

    def _print_trades(self, act_seq_num, trades):
        """
        Prints trades executed by the action in this sequence in this current t-step.

        Arguments:
            act_seq_num: The order in which the action is executed in this
                         shuffled sequence in this current t-step.

        Returns:
            str: The output string.
        """

        trade_list = []
        for i, trade in enumerate(trades):
            trade_dict = self._pack_trade_dict(i, trade)
            trade_list.append(trade_dict)

        df_trade_list = pd.DataFrame(trade_list)

        if df_trade_list.empty == True:
            str = ""
        else:
            str = "TRADES (act_seq_num): {}\n".format(act_seq_num) + df_trade_list.to_string()
            logger.debug(str)

        return str

    def _pack_trade_dict(self, i, trade):
        """
        Repack trade into 1 dim dict.

        Arguments:
            i: The sequence of all actions by all traders(agents) in current t-step
            trade: A dictionary with nested dicts.

        Returns:
            trade_dict: A dictionary.
        """

        trade_dict = {}

        trade_dict['seq_Trade_ID'] = i # seq means all actions by all traders(agents) in current t-step

        trade_dict['timestamp'] = trade['timestamp']
        trade_dict['price'] = trade['price']
        trade_dict['size'] = trade['quantity']
        trade_dict['time'] = trade['time']

        counter_party_dict = trade['counter_party']
        trade_dict['counter_ID'] = counter_party_dict['ID']
        trade_dict['counter_side'] = counter_party_dict['side']
        trade_dict['counter_order_ID'] = counter_party_dict['order_id']
        trade_dict['counter_new_book_size'] = counter_party_dict['new_book_quantity']

        init_party_dict = trade['init_party']
        trade_dict['init_ID'] = init_party_dict['ID']
        trade_dict['init_side'] = init_party_dict['side']
        trade_dict['init_order_ID'] = init_party_dict['order_id']
        trade_dict['init_new_LOB_size'] = init_party_dict['new_book_quantity']

        return trade_dict

    def print_mark_to_mkt(self, msg):
        """
        Log mark_to_mkt info for all traders(agents).
        """

        rows = "\n".join(
            'ID: {}; profit: {}'.format(trader.ID, trader.acc.profit)
            for trader in self.traders
        )
        logger.debug("%s\n%s", msg, rows)

        return 0

    def print_accs(self, msg):
        """
        Print account info for all traders(agents).
        """

        acc = {}

        ID_list = []
        cash_list = []
        cash_on_hold_list = []
        position_val_list = []
        prev_nav_list = []
        nav_list = []
        net_position_list = []
        VWAP_list = []
        profit_list = []
        total_profit_list = []
        num_trades_list = []

        for trader in self.traders:
            ID_list.append(trader.acc.ID)
            cash_list.append(trader.acc.cash)
            cash_on_hold_list.append(trader.acc.cash_on_hold)
            position_val_list.append(trader.acc.position_val)
            prev_nav_list.append(trader.acc.prev_nav)
            nav_list.append(trader.acc.nav)
            net_position_list.append(trader.acc.net_position)
            VWAP_list.append(trader.acc.VWAP)
            profit_list.append(trader.acc.profit)
            total_profit_list.append(trader.acc.total_profit)
            num_trades_list.append(trader.acc.num_trades)

        acc['ID'] = ID_list
        acc['cash'] = cash_list
        acc['cash_on_hold'] = cash_on_hold_list
        acc['position_val'] = position_val_list
        acc['prev_nav'] = prev_nav_list
        acc['nav'] = nav_list
        acc['net_position'] = net_position_list
        acc['VWAP'] = VWAP_list
        acc['profit'] = profit_list
        acc['total_profit'] = total_profit_list
        acc['num_trades'] = num_trades_list

        logger.debug("%s %s", msg, tabulate(acc, headers="keys"))

        return 0

    def total_sys_profit(self):
        """
        Computes total profit of all traders.
        """

        sum = 0
        for trader in self.traders:
            sum += trader.acc.total_profit
        return sum

    def total_sys_nav(self):
        """
        Computes total NAV of all traders.
        """

        sum = 0
        for trader in self.traders:
            sum += trader.acc.nav
        return sum
