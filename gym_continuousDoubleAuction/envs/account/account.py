from decimal import Decimal

from .cash_processor import Cash_Processor
from .calculate import Calculate
from ...config_loader import env_default
from ...logging_setup import get_logger

from tabulate import tabulate

logger = get_logger(__name__)

class Account(Calculate, Cash_Processor):
    def __init__(self, ID, cash=env_default("init_cash")):
        self.ID = ID
        self.cash = Decimal(cash)
        # nav is used to calculate P&L & r per t step
        self.cash_on_hold = Decimal(0) # cash deducted for placing order = cash - value of live order in LOB
        self.position_val = Decimal(0) # value of net_position
        # nav is used to calculate P&L & r per t step
        self.init_nav = Decimal(cash) # starting nav @t = 0
        self.nav = Decimal(cash) # nav @t (nav @ end of a single t-step)
        self.prev_nav = Decimal(cash) # nav @t-1
        # assuming only one ticker (1 type of contract)
        self.net_position = 0 # number of contracts currently holding long (positive) or short (negative)
        # The carrying basis of the open position, as the EXACT Decimal sum of
        # the trade values that built it: buys minus sells for a long, sells
        # minus buys for a short (so it is positive on both sides). This is
        # the ledger's primary quantity; `VWAP` is derived from it as a
        # property and is display only.
        #
        # It used to be the other way round - `VWAP` was stored as the
        # quotient `cost / size` and the basis recomputed as `size * VWAP` -
        # and that is why NAV conservation held only to ~1e-22: the quotient
        # rounds at the 28-digit Decimal context whenever it does not
        # terminate, and `mark_to_mkt` then multiplied it back in two
        # independently rounded products. Every trade moves the same exact
        # value between two accounts' cash and basis, so with the basis held
        # as that sum the conservation identity is exact by construction
        # (doc/15 S3-23, doc/16 16.19).
        #
        # Realised P&L is deliberately rolled into it on a partial close:
        # `_size_decrease` subtracts the trade VALUE, not `VWAP x quantity`.
        # That roll is load-bearing - on the short side `position_val` is
        # `2*cost_basis - mkt_val`, so removing it would move NAV - and it is
        # what lets the derived `VWAP` go negative: long 2 @ 100, sell 1 @ 250
        # leaves a basis of -50 on the remaining lot.
        self.cost_basis = Decimal(0)
        # The average price actually paid for the lots still held.
        #
        # `VWAP` is NOT that, for the reason just given.
        #
        # That mattered because `set_private_state` reported
        # `vwap_vs_mid = ... if vwap > 0 else 0.0`, and 0.0 is the encoding for
        # *flat*. So an agent holding an open position was told it held none,
        # on a measured 2.5% of open-position agent-steps. This field is
        # maintained by the three methods that open or reset a position and
        # deliberately untouched by `_size_decrease`, so it stays a price.
        self.entry_vwap = Decimal(0)
        self.profit = Decimal(0) # profit @ each trade(tick) within a single t step
        self.total_profit = Decimal(0) # profit at the end of a single t-step
        self.num_trades = 0
        # float, not int: set_reward assigns a float, and RLlib requires float
        # rewards. Reward is a learning signal, not money - it is the one thing
        # in this account that is deliberately neither Decimal nor int.
        self.reward = 0.0

        # New metrics for improved reward function
        self.max_nav = Decimal(cash) # peak nav seen so far
        self.num_trades_step = 0 # trades in current environment step
        self.num_passive_fills_step = 0 # passive executions in current step
        self.order_step_placed = 0 # 1 if a Market/Limit order was placed this step
        # Orders refused by _order_approved this step. order_step_placed cannot
        # stand in for this: it is 0 both for an agent that never tried and for
        # one whose order was refused, and those are opposite behaviours - the
        # second is an agent repeatedly quoting past its cash (doc/11 2.2).
        self.num_rejected_step = 0
        # `modify` / `cancel` actions this step that named no resting order to
        # act on. The other half of doc/15 S4-14: `num_rejected_step` counts an
        # order the cash check refused, `is_pass_action` a deliberate pass, and
        # until this existed the third silent outcome - an order-management
        # action with nothing to manage - left no trace at all. From the
        # policy's side all three look identical: nothing happened.
        self.num_unmatched_step = 0

        # Written by Reward_Helper.set_reward each step, read by Info_Helper.
        # The reward used to be a single number with its five components
        # discarded the moment it was summed, which is what made the variance
        # split in doc/07 6.4 unmeasurable. See doc/11 2.4.
        # float, not Decimal(0): set_reward stores float(max(0, max_nav - nav)),
        # so initialising this as a Decimal would make the field change type on
        # the first step - the same defect net_position and VWAP already have.
        self.drawdown = 0.0 # max_nav - nav, the level the penalty uses
        self.reward_terms = {} # signed contributions, summing to self.reward

    def reset_acc(self, ID, cash=env_default("init_cash")):
        self.ID = ID
        self.cash = Decimal(cash)
        # nav is used to calculate P&L & r per t step
        self.cash_on_hold = Decimal(0) # cash deducted for placing order = cash - value of live order in LOB
        self.position_val = Decimal(0) # value of net_position
        # nav is used to calculate P&L & r per t step
        self.init_nav = Decimal(cash) # starting nav @t = 0
        self.nav = Decimal(cash) # nav @t (nav @ end of a single t-step)
        self.prev_nav = Decimal(cash) # nav @t-1
        # assuming only one ticker (1 type of contract)
        self.net_position = 0 # number of contracts currently holding long (positive) or short (negative)
        self.cost_basis = Decimal(0) # exact sum of trade values; see __init__
        # The real cost basis; see __init__ for why it is not VWAP.
        self.entry_vwap = Decimal(0)
        self.profit = Decimal(0) # profit @ each trade(tick) within a single t step
        self.total_profit = Decimal(0) # profit at the end of a single t-step
        self.num_trades = 0
        self.reward = 0.0

        # New metrics for improved reward function
        self.max_nav = Decimal(cash)
        self.num_trades_step = 0
        self.num_passive_fills_step = 0
        self.order_step_placed = 0
        self.num_rejected_step = 0
        self.num_unmatched_step = 0

        # See __init__ for what these are and why they exist.
        self.drawdown = 0.0
        self.reward_terms = {}

    @property
    def VWAP(self):
        """The carrying basis per contract, derived: `cost_basis / |net_position|`.

        A Decimal quotient, so it can be inexact - which is fine for a display
        value and is exactly why it is no longer what the ledger stores. Zero
        when flat, as it always was.
        """
        if self.net_position == 0:
            return Decimal(0)
        return self.cost_basis / abs(self.net_position)

    @VWAP.setter
    def VWAP(self, value):
        """Set the basis from a per-contract price, for callers that build a
        position by hand (the tests do). `net_position` must already be set;
        with a flat position there is nothing to carry and the basis is 0.
        """
        self.cost_basis = Decimal(value) * abs(self.net_position)

    def print_acc(self, msg):
        acc = {}
        acc['ID'] = [self.ID]
        acc['cash'] = [self.cash]
        acc['cash_on_hold'] = [self.cash_on_hold]
        acc['position_val'] = [self.position_val]
        acc['prev_nav'] = [self.prev_nav]
        acc['nav'] = [self.nav]
        acc['net_position'] = [self.net_position]
        acc['VWAP'] = [self.VWAP]
        acc['profit'] = [self.profit]
        acc['total_profit'] = [self.total_profit]
        acc['num_trades'] = [self.num_trades]

        logger.debug("%s %s", msg, tabulate(acc, headers="keys"))
        return 0

    def print_both_accs(self, msg, curr_step_trade_ID, counter_party, init_party):
        """
        Print accounts of both counter_party & init_party.
        """

        acc = {}
        acc['seq_Trade_ID'] = [curr_step_trade_ID, curr_step_trade_ID]
        acc['party'] = ["counter", "init"]
        acc['ID'] = [counter_party.acc.ID, init_party.acc.ID]
        acc['cash'] = [counter_party.acc.cash, init_party.acc.cash]
        acc['cash_on_hold'] = [counter_party.acc.cash_on_hold, init_party.acc.cash_on_hold]
        acc['position_val'] = [counter_party.acc.position_val, init_party.acc.position_val]
        acc['prev_nav'] = [counter_party.acc.prev_nav, init_party.acc.prev_nav]
        acc['nav'] = [counter_party.acc.nav, init_party.acc.nav]
        acc['net_position'] = [counter_party.acc.net_position, init_party.acc.net_position]
        acc['VWAP'] = [counter_party.acc.VWAP, init_party.acc.VWAP]
        acc['profit'] = [counter_party.acc.profit, init_party.acc.profit]
        acc['total_profit'] = [counter_party.acc.total_profit, init_party.acc.total_profit]
        acc['num_trades'] = [counter_party.acc.num_trades, init_party.acc.num_trades]

        logger.debug("%s %s", msg, tabulate(acc, headers="keys"))
        return 0

    def _size_increase(self, trade, position, party, trade_val):
        # Sizes add in int; only the value terms below are Decimal.
        total_size = abs(self.net_position) + int(trade.get('quantity'))
        # The basis grows by exactly the trade value. No quotient anywhere on
        # the ledger path - see cost_basis in __init__.
        self.cost_basis += trade_val
        # The real cost basis per contract, rolled from its own previous
        # value, so a prior partial close cannot leak into it. Observation
        # only; its rounding never reaches NAV.
        self.entry_vwap = (
            abs(self.net_position) * self.entry_vwap + trade_val
        ) / total_size
        raw_val = self.cost_basis # value acquired, exactly
        mkt_val = total_size * trade.get('price')
        self.position_val = raw_val + self.cal_profit(position, mkt_val, raw_val)
        self.size_increase_cash_transfer(party, trade_val)
        return 0

    def _covered(self, trade, position):
        """
        Entire position covered, net position = 0
        """

        raw_val = self.cost_basis # value acquired, exactly
        mkt_val = abs(self.net_position) * trade.get('price')
        self.position_val = raw_val + self.cal_profit(position, mkt_val, raw_val)
        self.size_zero_cash_transfer(mkt_val)
        # reset to 0 - as Decimal, not int. position_val and cost_basis are
        # money, so both are Decimal everywhere else; assigning a bare 0 here
        # was what made VWAP read back as an int once a position went flat.
        self.position_val = Decimal(0)
        self.cost_basis = Decimal(0)
        self.entry_vwap = Decimal(0)
        return mkt_val

    def _size_decrease(self, trade, position, party, trade_val):
        size_left = abs(self.net_position) - int(trade.get('quantity'))
        if size_left > 0:
            # The trade VALUE comes off the basis, not VWAP x quantity: the
            # realised P&L stays in the basis of the remaining lots. See
            # cost_basis in __init__ for why that is load-bearing.
            self.cost_basis -= trade_val
            raw_val = self.cost_basis # value acquired, exactly
            mkt_val = size_left * trade.get('price')
            self.position_val = raw_val + self.cal_profit(position, mkt_val, raw_val)
        else: # size_left == 0
            mkt_val = self._covered(trade, position)
        self.size_decrease_cash_transfer(party, trade_val)
        return 0

    def _covered_side_chg(self, trade, position, party):
        mkt_val = self._covered(trade, position)
        self.size_decrease_cash_transfer(party, mkt_val)
        # deal with remaining size that cause position change
        new_size = int(trade.get('quantity')) - abs(self.net_position)
        self.position_val = new_size * trade.get('price') # traded value
        # The flip opened a fresh position at this price, so the basis is it.
        self.cost_basis = self.position_val
        self.entry_vwap = trade.get('price')
        self.size_increase_cash_transfer(party, self.position_val)
        return 0

    def _neutral(self, trade_val, trade, party):
        self.position_val += trade_val
        self.cost_basis = trade_val
        self.entry_vwap = trade.get('price')
        self.size_increase_cash_transfer(party, trade_val)

    def _net_long(self, trade_val, trade, party):
        if trade.get(party).get('side') == 'bid':
            self._size_increase(trade, 'long', party, trade_val)
        else: # ask
            if self.net_position >= trade.get('quantity'): # still long or neutral
                self._size_decrease(trade, 'long', party, trade_val)
            else: # net_position changed to short
                self._covered_side_chg(trade, 'long', party)

    def _net_short(self, trade_val, trade, party):
        if trade.get(party).get('side') == 'ask':
            self._size_increase(trade, 'short', party, trade_val)
        else: # bid
            if abs(self.net_position) >= trade.get('quantity'): # still short or neutral
                self._size_decrease(trade, 'short', party, trade_val)
            else: # net_position changed to long
                self._covered_side_chg(trade, 'short', party)

    def _update_net_position(self, side, trade_quantity):
        # int throughout: a net position is a count of contracts. The Decimal()
        # wrapping this used to carry was working around float sizes coming out
        # of the book - with sizes normalised to int at that boundary
        # (trader._normalise_trade_sizes) the arithmetic is exact in int, and
        # the field no longer changes type on the first fill.
        trade_quantity = int(trade_quantity)
        if self.net_position >= 0: # long or neutral
            if side == 'bid':
                self.net_position += trade_quantity
            else:
                self.net_position -= trade_quantity
        else: # short
            if side == 'ask':
                self.net_position -= trade_quantity
            else:
                self.net_position += trade_quantity
        return 0

    def process_acc(self, trade, party):
        self.num_trades += 1
        self.num_trades_step += 1
        
        # Track passive fills for reward bonus
        if party == 'counter_party':
            self.num_passive_fills_step += 1

        trade_val = Decimal(trade.get('quantity')) * trade.get('price')
        if self.net_position > 0: #long
            self._net_long(trade_val, trade, party)
        elif self.net_position < 0: # short
            self._net_short(trade_val, trade, party)
        else: # neutral
            self._neutral(trade_val, trade, party)
        self._update_net_position(trade.get(party).get('side'), trade.get('quantity'))
        return 0
