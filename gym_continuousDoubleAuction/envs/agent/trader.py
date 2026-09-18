from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..account.account import Account
from ...config_loader import env_default


def _normalise_trade_sizes(trades):
    """Coerce the sizes in the book's trade records back to int, in place.

    Sizes enter the book as int, but `Order.__init__` stores them as `Decimal`,
    so a fill reports whichever the branch that produced it happened to hold:
    `quantity_to_trade` (int) on a partial or exact fill, `head_order.quantity`
    (Decimal) when the incoming order is the larger one. Measured over a 120
    step run that is 84 int against 10 Decimal on the same tape.

    The orderbook is deliberately left untouched (see doc/11 1.8), so the mixing
    is absorbed here instead - at the one point every trade passes through,
    before any account arithmetic sees it. This is the *only* place env code
    should have to think about it.

    Lossless by construction, not by luck: ints go in, and the book only ever
    subtracts one whole size from another, so every quantity out is integral.
    The assertion says so out loud rather than letting a fractional size become
    a silent truncation.
    """
    for trade in trades:
        quantity = trade.get('quantity')
        if quantity is None:
            continue
        as_int = int(quantity)
        if as_int != quantity:
            raise ValueError(
                f"non-integral trade size {quantity!r} out of the order book: "
                f"sizes are counts of contracts and must stay whole"
            )
        trade['quantity'] = as_int


class Trader:
    def __init__(self, ID: int, cash=env_default("init_cash")) -> None:
        self.ID = ID # trader unique ID
        self.acc = Account(ID, cash)

    def place_order(self, type: str, side: Optional[str], size: int, price: float,
                    LOB, agents: Sequence["Trader"], slot: int = 0) -> Tuple[List[dict], Any]:
        """
        Execute an action.

        Arguments:
            slot: Which of this trader's own resting orders a `modify` or
                `cancel` targets, counted from the touch (1 = nearest the
                market; best price first, oldest first within a level), and
                clamped to the deepest one when the trader has fewer. 0 is
                "every own order on that side" for a cancel and "the oldest
                order" for a modify - the pre-slot rule, so callers that pass
                nothing get the old behaviour. Ignored by market and limit.
                A miss - counted in `num_unmatched_step` - is now only
                "nothing resting on that side". See doc/15 S3-24.

        Return:
            trades: list
            order_in_book: list

        Notes:
            If side is None, do nothing. Otherwise, if the order is approved,
            create the order & execute it. If trades took placed in this order,
            process the trades. Update the (init_party) trader's account if
            there's any unfilled.
        """

        trades, order_in_book = [],[]

        if(side == None): # do nothing to LOB
            #print('side == None')
            return trades, order_in_book

        # normal execution
        if self._order_approved(side, size, price, LOB, type, slot=slot):
            # Before the order can reach the matcher. Every regulated venue
            # runs self-match prevention, and this one needs it more than
            # most: `Exchg_Helper.mark_to_mkt` marks *every* account off a
            # single market price, so one self-traded contract at a chosen
            # price used to re-price the whole market including the
            # self-trader's own reward (doc/15 S2-5).
            self._prevent_self_match(LOB, type, side, price)

            order = self._create_order(type, side, size, price, slot=slot)

            # Option B: Flag only Market and Limit orders for entry penalty
            if order.get('type') in ['market', 'limit']:
                self.acc.order_step_placed = 1

            if order['type'] == 'market':
                trades, order_in_book = LOB.process_order(order, False, False)
            elif order['type'] == 'limit':
                trades, order_in_book = self._place_limit_order(LOB, order)
            elif order['type'] == 'modify':
                trades, order_in_book = self._modify_limit_order(LOB, order)
            elif order['type'] == 'cancel':
                trades, order_in_book = self._cancel_limit_order(LOB, order)
            else: # order == {} do nothing to LOB
                return trades, order_in_book

            if trades != []: # if trades took placed in this order
                _normalise_trade_sizes(trades)
                self._process_trades(trades, agents)

            self.acc.order_in_book_passive_party(order_in_book) # if there's any unfilled
            return trades, order_in_book

        else: # not enough cash to place order
            #print('Invalid order: order value > cash available.', self.ID)

            # print("\nOrder NOT approved: -ve NAV for trader_ID {}.\n".format(self.ID))

            # A refusal used to leave no trace at all: the agent asked to trade
            # and the book never heard about it. Counted so the rejection rate
            # is measurable - a policy quoting past its cash every step looks
            # identical to a passive one from returns alone (doc/11 2.2).
            self.acc.num_rejected_step += 1
            return trades, order_in_book

    def _prevent_self_match(self, LOB, type: str, side: Optional[str], price: float) -> int:
        """Cancel this trader's own resting orders the incoming order would cross.

        The "cancel resting order" self-match-prevention mode: the older order
        gives way and the aggressor proceeds. Done here rather than in
        `OrderBook.process_order_list`, where a `head_order.trade_id !=
        quote['trade_id']` skip would be the natural place for it, because
        `envs/orderbook/` is off-limits to changes (doc/15 S3-4). The effect on
        what can reach the tape is the same; what differs is that the resting
        order is withdrawn rather than stepped over, which is also the more
        common venue behaviour.

        Why it matters beyond tidiness: a self-trade printed to the tape, and
        `mark_to_mkt` marks every account off a single market price, so one
        self-matched contract re-marked the entire market. Measured before
        this: a 1-lot self-print moved 1,000 NAV between two traders. It was
        also free - `_process_trades` sends a self-trade down a path that never
        calls `process_acc`, so neither `num_trades` nor `num_trades_step` ever
        incremented and `trade_penalty` never charged for it. Any "refuse to
        promote a champion that does not trade" guard would have been evadable
        the same way.

        A `cancel` crosses nothing. A `modify` re-processes as a limit and can,
        so it is included.

        Returns:
            The number of own orders withdrawn.
        """
        if type not in ('market', 'limit', 'modify'):
            return 0

        if side == 'bid':
            contra = 'ask'
        elif side == 'ask':
            contra = 'bid'
        else:
            return 0

        order_map = self._find_orderTree(LOB, {'side': contra})
        if order_map is None:
            return 0

        # A market order names no price and sweeps the whole contra side, so
        # every one of this trader's resting orders there is in its path.
        is_market = (type == 'market') or (price is None) or (price == -1.0)
        # Decimal, matching how the book stores a resting price, so the
        # comparison below is exact rather than going through a float.
        limit = None if is_market else Decimal(str(price))

        def crosses(resting_price):
            if is_market:
                return True
            return resting_price <= limit if side == 'bid' else resting_price >= limit

        doomed = [
            (order_ID, order)
            for order_ID, order in order_map.items()
            if order.trade_id == self.ID and crosses(order.price)
        ]
        for order_ID, order in doomed:
            LOB.cancel_order(contra, order_ID)
            self.acc.cancel_cash_transfer(order)

        return len(doomed)

    def _resting_exposure(self, LOB, side: str, exclude_order_id: Optional[int] = None) -> int:
        """This trader's own live resting quantity on `side`.

        Walks the tree's `order_map` for this trader's `trade_id`, the way
        `_get_order_ID` does, and reuses `_find_orderTree` so there is one
        definition of which tree a side names.

        `exclude_order_id` drops the order an incoming quote is about to
        replace. A `limit` at a price this trader already rests at is an upsert
        (`_place_limit_order`) and a `modify` is a cancel-and-reprocess, so in
        both cases the old order's quantity is released by the same call that
        would otherwise be charged for it. Counting it would refuse orders that
        free more exposure than they take.
        """
        order_map = self._find_orderTree(LOB, {'side': side})
        if order_map is None:
            return 0

        total = 0
        for order_ID, order in order_map.items():
            if order.trade_id != self.ID:
                continue
            if exclude_order_id is not None and order_ID == exclude_order_id:
                continue
            total += int(order.quantity)

        return total

    def _closing_escrow(self, LOB, exclude_order_id: Optional[int] = None) -> Decimal:
        """Escrow held against this trader's resting orders that would only
        flatten its position.

        The ledger escrows `price x quantity` for every resting order, whichever
        side it is on and whatever it would do to the position. For an ask
        resting against a long (or a bid against a short) that cash backs a
        fill that can only *reduce* risk - it is margin against nothing - yet
        the cash check treated it as spent, so an opening order elsewhere was
        refused while the trader held inventory the resting order would merely
        close. That is the tail of doc/15 S1-5, measured in doc/16 §16.18:
        under random play at init_cash 100,000, 84% of refusals happened while
        such escrow existed and 67% of all refusals would have passed had it
        counted.

        Only the portion that actually closes counts: resting quantity beyond
        `|net_position|` would open the opposite position, and its escrow is
        real margin. Orders are walked oldest first, matching the priority in
        which they would fill. The order a modify or upsert is about to replace
        is excluded, because `_order_approved` already counts its release.
        """
        pos = self.acc.net_position
        if pos == 0:
            return Decimal(0)
        side = 'ask' if pos > 0 else 'bid'
        order_map = self._find_orderTree(LOB, {'side': side})
        if order_map is None:
            return Decimal(0)

        remaining = abs(pos)
        total = Decimal(0)
        mine = sorted(
            (
                (order_ID, order) for order_ID, order in order_map.items()
                if order.trade_id == self.ID and order_ID != exclude_order_id
            ),
            key=lambda item: item[1].timestamp,
        )
        for _order_ID, order in mine:
            if remaining <= 0:
                break
            covered = min(int(order.quantity), remaining)
            total += order.price * covered
            remaining -= covered
        return total

    def _replaced_order(self, LOB, type, side, price, slot=0):
        """The resting order this quote would replace, as `(order_id, order)`,
        or `(None, None)`.

        Only `limit`, `modify` and `cancel` can replace an order, and each
        resolves its target through `_get_order_ID` - so this asks that same
        function rather than re-deriving the rule. A market order never
        replaces anything and never reaches the lookup.

        Both halves are returned because `_order_approved` needs both: the id
        to leave the order out of `_resting_exposure`, and the order itself to
        know how much escrow its replacement releases.
        """
        if type not in ('limit', 'modify', 'cancel'):
            return None, None

        order_ID, order = self._get_order_ID(
            LOB, {'trade_id': self.ID, 'side': side,
                  'price': price, 'type': type, 'slot': slot},
        )
        if order_ID == -1:
            return None, None
        return order_ID, order

    def _replaced_order_id(self, LOB, type, side, price, slot=0):
        """The order id this quote would replace, or None. See `_replaced_order`."""
        return self._replaced_order(LOB, type, side, price, slot)[0]

    def _order_approved(self, side: str, size: int, price: float, LOB,
                        type: Optional[str] = None, slot: int = 0) -> bool:
        """
        Conditions for order approval. Handles:
        1. NAV positivity.
        2. Position flips (Long -> Short, Short -> Long). Only the "opening"
           portion of an order requires a cash check.
        3. Orders already resting on the closing side, which have claimed part
           of the position and so cannot close it a second time.
        4. Market order price estimation.
        5. Decimal precision.

        Return: boolean.
        """
        if self.acc.nav <= 0:
            return False

        # A cancel places nothing. It withdraws a resting order and returns its
        # escrow to cash, so there is no notional to check it against - and
        # checking it anyway is what used to happen: `opening_size` was the
        # cancel's (meaningless) size and `est_price` its price, so a trader
        # whose cash was fully escrowed in resting orders was *refused the
        # cancel that would have freed it*. Measured: cash 0, 1,000 on hold in
        # one bid, `cancel` -> `num_rejected_step` 1 and the order still
        # resting. The same trap caught a size-reducing `modify`. That is the
        # one action an over-committed agent needs, and it was the one it could
        # not take. See doc/15 S2-13.
        if type == 'cancel':
            return True

        # The order this quote replaces, if any. A `limit` at a price this
        # trader already rests at is an upsert and a `modify` is a
        # cancel-and-reprocess, so in both cases `cancel_cash_transfer` hands
        # the old order's escrow back to cash *before* the new quote is
        # processed. It is therefore excluded from the resting exposure below
        # and counted as available cash in the check at the bottom.
        replaced_id, replaced = self._replaced_order(LOB, type, side, price, slot)
        released = (
            replaced.price * replaced.quantity if replaced is not None
            else Decimal(0)
        )

        # Determine how much of the order is "opening" a new/larger position
        net_pos = float(self.acc.net_position)
        
        # Scenario 1: Order is on the same side as current position (Increasing)
        if (side == 'bid' and net_pos >= 0) or (side == 'ask' and net_pos <= 0):
            opening_size = size
        # Scenario 2: Order is on the opposite side (Decreasing or Flipping)
        #
        # `closable` is the position NOT already claimed by this trader's own
        # resting orders on this side, and it is the whole point of this
        # branch. Netting against `abs(net_pos)` alone let every resting order
        # net against the *same* lots, so N individually-"closing" orders were
        # each waved through against one position and the cash check could be
        # bypassed entirely by layering them across price levels. Measured
        # before this: a trader long 10 with `cash == 0` rested ten 10-lot asks
        # - all approved - and filled into a 90-lot short having never been
        # refused. That is doc/15 S1-5.
        else:
            resting = self._resting_exposure(LOB, side,
                                             exclude_order_id=replaced_id)
            closable = max(0, int(abs(net_pos)) - resting)
            opening_size = max(0, size - closable)

        # If we are only closing/decreasing a position, no cash check is needed
        if opening_size <= 0:
            return True

        # Opening/Increasing portion requires cash check
        # For market orders, use best available price as estimate
        if price == -1.0:
            if side == 'bid':
                est_price = LOB.get_best_ask() or (LOB.tape[-1]['price'] if LOB.tape else 1)
            else:
                est_price = LOB.get_best_bid() or (LOB.tape[-1]['price'] if LOB.tape else 1)
        else:
            est_price = price

        order_val = Decimal(str(opening_size)) * Decimal(str(est_price))

        # `released` is the escrow the replaced order gives back on the same
        # call, so it is as spendable as cash for this quote. Without it a
        # trader with everything escrowed could neither re-price nor shrink
        # an order.
        #
        # `closing` is the escrow held against resting orders that would only
        # flatten the position - margin against a fill that reduces risk. It
        # is spendable too: if that order fills, its escrow and the position's
        # value both come back to cash; if it is cancelled, the escrow comes
        # back directly. Either way the cash exists. Spending it can take
        # `cash` transiently below zero by at most this amount, while
        # `cash + cash_on_hold` never does, and NAV - which sums both - is
        # untouched. See `_closing_escrow`.
        closing = self._closing_escrow(LOB, exclude_order_id=replaced_id)
        if self.acc.cash + released + closing >= order_val:
            return True

        return False

    def _create_order(self, type: str, side: str, size: int, price: float, slot: int = 0) -> Dict[str, Any]:
        """
        Create the order dictionary.

        Return:
            order: A dictionary.
        """

        if type == 'market':
            order = {'type': type,
                     'side': side,
                     'quantity': size,
                     'trade_id': self.ID}
        elif type == 'limit':
            order = {'type': type,
                     'side': side,
                     'quantity': size,
                     'price': price,
                     'trade_id': self.ID}
        elif type == 'modify':
            order = {'type': type,
                     'side': side,
                     'quantity': size,
                     'price': price,
                     'trade_id': self.ID,
                     'slot': slot}
        elif type == 'cancel':
            order = {'type': type,
                     'side': side,
                     'quantity': size,
                     'price': price,
                     'trade_id': self.ID,
                     'slot': slot}
        else:
            order = {}

        return order

    def _place_limit_order(self, orderBook, qoute):
        """
        Note:
            process_order if no such order exists in order tree.
            Otherwise, modify the existing limit order.
        """

        trades, order_in_book = [],[]
        order_id, order = self._get_order_ID(orderBook, qoute)
        if order_id == -1:  # no such order exist
            trades, order_in_book = orderBook.process_order(qoute, False, False)
        else:
            trades, order_in_book = self.__modify_limit_order(orderBook, order_id, order, qoute)

        return trades, order_in_book

    def _modify_limit_order(self, orderBook, qoute):
        """
        Note:
            __modify_limit_order if order exists in order tree.
        """

        order_id, order = self._get_order_ID(orderBook, qoute)
        if order_id == -1:  # not found
            # Counted, so a policy that keeps modifying orders it does not
            # have is distinguishable from one that manages real ones.
            self.acc.num_unmatched_step += 1
            trades, order_in_book = [],[]
        else:
            trades, order_in_book = self.__modify_limit_order(orderBook, order_id, order, qoute)

        return trades, order_in_book

    def __modify_limit_order(self, orderBook, order_id, order, qoute):
        """
        Note:
            Handle cash transfer accordingly before modifying order then,
            modify_order in LOB.
        """

        qoute['type'] = 'limit'
        # qoute['quantity'] = Decimal(qoute['quantity']) # already handled in caller or orderbook

        # "Undo" the old order's accounting to prepare for the modified order.
        self.acc.cancel_cash_transfer(order)

        # modify_order now returns trades and the updated order residue.
        trades, order_in_book = orderBook.modify_order(order_id, qoute)

        return trades, order_in_book

    def _cancel_limit_order(self, orderBook, qoute):
        """Cancel by slot: 0 is every own order on the side, k the k-th from the touch.

        A cancel used to match by exact price, which needed the agent to name
        the one code in thirty that its order sat at, and landed 7% of the
        time under random play (doc/15 S3-24). Both slot forms release each
        cancelled order's escrow through `cancel_cash_transfer`, the same call
        `cancel_all_orders` uses.
        """
        trades, order_in_book = [], []
        slot = int(qoute.get('slot', 0) or 0)

        if slot == 0:
            mine = self._own_orders_from_touch(orderBook, qoute['side'])
            if not mine:
                # Nothing to cancel: the third silent outcome doc/15 S4-14 lists.
                self.acc.num_unmatched_step += 1
                return trades, order_in_book
            for order_id, order in mine:
                orderBook.cancel_order(qoute['side'], order_id)
                self.acc.cancel_cash_transfer(order)
            return trades, order_in_book

        order_id, order = self._get_order_ID(orderBook, qoute)
        if order_id == -1:  # nothing resting on this side
            self.acc.num_unmatched_step += 1
        else:
            orderBook.cancel_order(qoute['side'], order_id)
            self.acc.cancel_cash_transfer(order)

        return trades, order_in_book

    def _own_orders_from_touch(self, orderBook, side: str) -> List[tuple]:
        """This trader's resting orders on `side`, nearest the market first.

        Best price first - highest bid, lowest ask - and oldest first within a
        level, which is fill priority. Slot k of a modify or cancel is element
        k-1 of this list, and it is also the order the own-book observation
        block lists them in, so what the agent sees and what it can aim at
        agree.
        """
        order_map = self._find_orderTree(orderBook, {'side': side})
        if order_map is None:
            return []
        mine = [(order_ID, order) for order_ID, order in order_map.items()
                if order.trade_id == self.ID]
        if side == 'bid':
            mine.sort(key=lambda item: (-item[1].price, item[1].timestamp))
        else:
            mine.sort(key=lambda item: (item[1].price, item[1].timestamp))
        return mine

    def cancel_all_orders(self, LOB) -> int:
        """Pull every order this trader has resting, on both sides.

        Used when a trader is terminated: a bankrupt agent stops acting, but
        its resting orders stay live and executable unless something takes
        them down, so the rest of the market would keep trading against a
        participant that no longer exists (doc/15 S2-4).

        Cancels through the same two calls `_cancel_limit_order` uses -
        `OrderBook.cancel_order` and `cancel_cash_transfer` - so the escrow is
        released by the same path in both cases. The order ids are collected
        before anything is cancelled, because `remove_order_by_id` mutates the
        map being walked.

        Returns:
            The number of orders cancelled.
        """
        cancelled = 0
        for side in ('bid', 'ask'):
            order_map = self._find_orderTree(LOB, {'side': side})
            if order_map is None:
                continue
            mine = [(order_ID, order) for order_ID, order in order_map.items()
                    if order.trade_id == self.ID]
            for order_ID, order in mine:
                LOB.cancel_order(side, order_ID)
                self.acc.cancel_cash_transfer(order)
                cancelled += 1

        return cancelled

    def _get_order_ID(self, orderBook, qoute: Dict[str, Any]) -> tuple:
        """
        Find the order in the order tree.

        Note:
            If order already exist, return
                order_ID, order.
            If no such order in order tree, return
                -1, None.
        """

        order_map = self._find_orderTree(orderBook, qoute)
        if order_map is None:
            return -1, None

        matching_orders = []
        for order_ID, order in order_map.items():
            if order.trade_id == qoute['trade_id']:
                matching_orders.append((order_ID, order))

        if not matching_orders:
            return -1, None

        if qoute.get('type') in ('modify', 'cancel'):
            slot = int(qoute.get('slot', 0) or 0)
            if slot > 0:
                # Slot k is the k-th own order from the touch (doc/15 S3-24,
                # phase 2), clamped to the deepest one when the agent has
                # fewer than k. Clamped rather than missed: a slot past the
                # count would be a dead action, and measured under random
                # play (doc/16 16.20) a head with dead slots made modify
                # WORSE than the FIFO rule it replaced (48% -> 23% hits) while
                # a learned policy gains nothing from them - it can read its
                # own-order counts and aim exactly. With the clamp the only
                # miss left is the genuine one: nothing resting on that side.
                ranked = self._own_orders_from_touch(orderBook, qoute['side'])
                if not ranked:
                    return -1, None
                return ranked[min(slot, len(ranked)) - 1]
            if qoute.get('type') == 'cancel':
                # Slot 0 of a cancel is "all"; `_cancel_limit_order` handles
                # it before reaching here. Asked anyway, answer the touch.
                ranked = self._own_orders_from_touch(orderBook, qoute['side'])
                return ranked[0] if ranked else (-1, None)
            # modify, slot 0: FIFO - the oldest existing order (smallest
            # timestamp), which is what a modify always did before slots.
            return min(matching_orders, key=lambda x: x[1].timestamp)
        
        # For 'cancel' or 'limit', we match the specific price.
        #
        # Compared as Decimal, the type the book stores prices in. The action
        # layer hands over a float, and `Decimal('100.1') == 100.1` is False
        # (the float is 100.09999...), so on any non-integer tick a cancel
        # never found its order and a limit at a price already rested at was
        # placed as a second order instead of an upsert. `Decimal(str(x))` is
        # exactly the conversion `OrderBook.process_order` applies on the way
        # in, so the two sides of the comparison are built the same way.
        target_price = qoute.get('price')
        if target_price is None:
            return -1, None
        if not isinstance(target_price, Decimal):
            target_price = Decimal(str(target_price))
        for order_ID, order in matching_orders:
            if order.price == target_price:
                return order_ID, order

        return -1, None # no matching order found for this price

    def _find_orderTree(self, orderBook, qoute):
        """
        Get 1 of the 2 LOB trees.

        returns: Either the bid or ask tree or None.
        """

        if qoute['side'] == 'bid':
            return orderBook.bids.order_map
        elif qoute['side'] == 'ask':
            return orderBook.asks.order_map
        else:
            return None

    def _process_trades(self, trades: List[dict], agents: Sequence["Trader"]) -> int:
        """
        Process trades for the init_party & counter_party.

        Notes:
            It's possible that the init_party is also the counter_party.
        """

        for i, trade in enumerate(trades):
            trade_val = Decimal(trade.get('quantity')) * trade.get('price')

            # init_party is not counter_party
            if trade.get('counter_party').get('ID') != trade.get('init_party').get('ID'):
                self._process_counter_party(agents, trade)
                self.acc.process_acc(trade, 'init_party')

                #self.acc.print_both_accs("\nAffected accounts_0:\n", i, counter_party, init_party=self)

            else: # init_party is also counter_party, balance out limit order in LOB with mkt order.
                self.acc.init_is_counter_cash_transfer(trade_val)

                #self.acc.print_both_accs("\nAffected accounts (init_party = counter_party)_0:\n", i, counter_party=self, init_party=self)

            #print('trades:', trades)

        return 0

    def _process_counter_party(self, agents, trade):
        """
        Find & return the counter_party.

        return:
            agent: A trader object.
        """

        wanted = trade.get('counter_party').get('ID')
        # In the env the roster is indexed by trader ID (agent_i is
        # traders[i]), so the counter-party is one lookup. The scan is kept as
        # the fallback for callers that pass an arbitrary list - the tests do -
        # and for a roster whose IDs are not its indices (doc/15 S4-11).
        agent = None
        if isinstance(wanted, int) and 0 <= wanted < len(agents) and agents[wanted].ID == wanted:
            agent = agents[wanted]
        else:
            for counter_party in agents: # search for counter_party
                if counter_party.ID == wanted:
                    agent = counter_party
                    break
        if agent is not None:
            agent.acc.process_acc(trade, 'counter_party')

        return agent
