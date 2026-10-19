"""A price-time-priority limit order book.

Adapted from https://github.com/dyn4mik3/OrderBook. Prices and sizes are
`Decimal` inside the book; `process_order` converts an incoming limit price
with `Decimal(str(price))`, which is the conversion every caller that later
looks a price up must apply too (see `Trader._get_order_ID`).

Malformed input raises `ValueError`. It used to exit the interpreter, which
under RLlib ends an env-runner process rather than the order - and the
traceback, swallowed by Ray's fault tolerance, restarted the worker instead
of naming the caller that produced a zero-size order. Every raise below names
the method and the value it refused.

The book enforces no tick grid and never did: it keys its price map on
whatever `Decimal` it is handed. The grid is the action layer's
(`Action_Helper._set_price`, which snaps to `tick_size`). The constructor
used to accept a `tick_size` it stored and never read; that parameter is
gone, so the code no longer suggests a guarantee the book does not provide.
"""

from io import StringIO
from itertools import chain
from collections import deque  # a faster insert/pop queue
from decimal import Decimal
from typing import Any, Callable, NamedTuple

import pandas as pd

from .ordertree import OrderTree
from ...logging_setup import get_logger

logger = get_logger(__name__)


class _Clearing(NamedTuple):
    """What one batch auction settled: the price, the volume, and who took part."""

    p_star: Any  # the clearing price; None when nothing crosses
    volume: Any  # the executable volume
    live: list  # queued orders that did not sit out
    buys: list  # ... the bids among them
    sells: list  # ... and the asks
    dropped: set  # ids of queued orders that could not pay
    sit_out: set  # ids of resting orders that could not pay

    @property
    def disturbed(self) -> bool:
        """Whether anyone sat out, which changes how leftovers may rest."""
        return bool(self.dropped or self.sit_out)


class _QuantityOnly:
    """A queued order seen as `allocate` reads it: something with a `.quantity`."""

    def __init__(self, q):
        self.q = q
        self.quantity = Decimal(q['quantity'])


class _Side(NamedTuple):
    """One side of the book from the point of view of an order resting or arriving on it."""

    own: Any  # the tree the order rests in
    opposite: Any  # the tree it trades against
    opposite_name: str  # that tree's side name, as `process_order_list` takes it
    crosses: Callable[[Any], bool]  # whether a limit price reaches the opposite touch

    def best_opposite_list(self):
        """The orders at the opposite touch (lowest ask for a bid, highest bid for an ask)."""
        return (
            self.opposite.min_price_list()
            if self.opposite_name == 'ask'
            else self.opposite.max_price_list()
        )


class OrderBook(object):
    #: How the quantity that reaches one price level is split among the orders
    #: resting there (docs/06 section 8). `fifo` is price-time priority: the
    #: oldest order fills first, the default and what every continuous double
    #: auction this simulates runs. `pro_rata` splits it in proportion to
    #: resting size, largest-remainder rounded to whole contracts, with the
    #: rounding residue going in time order - the rule some futures markets
    #: use, which rewards size over speed.
    MATCHING_RULES = ("fifo", "pro_rata")

    def __init__(self, tape_display_length=10, *, matching_rule="fifo"):
        self.tape = deque(maxlen=None)  # appended, so tape[-1] is the most recent trade
        self.bids = OrderTree()
        self.asks = OrderTree()
        self.last_tick = None
        self.last_timestamp = 0
        self.time = 0
        self.next_order_id = 0
        # Orders that sat out the last batch because their owner could not pay at
        # the clearing price. Set here as well as in `clear_batch`, so a read on
        # a book that has not cleared yet is an empty list, not an AttributeError.
        self.batch_unaffordable = []
        # Direction of the last batch price move (+1 up, -1 down, None before any), for the
        # tick rule that signs a trade with no aggressor (`_auction_initiator`).
        self.last_batch_sign = None
        self.tape_display_length = tape_display_length
        if matching_rule not in self.MATCHING_RULES:
            raise ValueError(
                f"matching_rule must be one of {self.MATCHING_RULES}; got {matching_rule!r}"
            )
        self.matching_rule = matching_rule
        # Batch clearing (docs/06 section 8): while `batching`, a new market or
        # limit order is queued instead of matched, and `clear_batch` clears
        # the queue against the book at one uniform price.
        self.batching = False
        self.pending = []

    def update_time(self):
        self.time += 1

    def process_order(self, quote, from_data, verbose):
        order_type = quote['type']
        order_in_book = None
        if from_data:
            self.time = quote['timestamp']
        else:
            self.update_time()
            quote['timestamp'] = self.time
        if quote['quantity'] <= 0:
            raise ValueError(
                f"process_order(): order quantity must be > 0, got "
                f"{quote['quantity']!r} (trade_id {quote.get('trade_id')!r})"
            )
        if not from_data:
            self.next_order_id += 1
        if order_type == 'limit':
            quote['price'] = Decimal(str(quote['price']))
        if order_type in ('market', 'limit') and self.batching:
            # Deferred to `clear_batch`. The order id is assigned now, so a
            # leftover that rests keeps the id the caller can address.
            if not from_data:
                quote['order_id'] = self.next_order_id
            self.pending.append(dict(quote))
            return [], None
        if order_type == 'market':
            trades = self.process_market_order(quote, verbose)
        elif order_type == 'limit':
            trades, order_in_book = self.process_limit_order(quote, from_data, verbose)
        else:
            raise ValueError(
                f"process_order(): order type must be 'market' or 'limit', got {order_type!r}"
            )
        return trades, order_in_book

    def allocate(self, orders, quantity):
        """Split `quantity` among `orders` (time order) under `matching_rule`.

        Returns `[(order, fill)]` in time order with every fill > 0, summing to
        `min(quantity, sum of the orders' quantities)`. `fifo` fills the oldest
        order first; `pro_rata` gives each order `floor(quantity * its size /
        level size)` and hands the rounding residue out one contract at a time
        in time order to orders with room left, so a small order behind a large
        one gets a share it would never see under fifo, and the total is exact.
        """
        orders = list(orders)
        quantity = Decimal(quantity)
        total = sum((Decimal(o.quantity) for o in orders), Decimal(0))
        if quantity >= total:
            return [(o, Decimal(o.quantity)) for o in orders]
        if self.matching_rule == "fifo":
            out, left = [], quantity
            for o in orders:
                if left <= 0:
                    break
                fill = min(Decimal(o.quantity), left)
                out.append((o, fill))
                left -= fill
            return out
        # pro_rata: floors, then the residue in time order.
        fills = [
            (Decimal(o.quantity) * quantity / total).to_integral_value(rounding="ROUND_FLOOR")
            for o in orders
        ]
        residue = quantity - sum(fills, Decimal(0))
        i = 0
        while residue > 0:
            if fills[i] < Decimal(orders[i].quantity):
                fills[i] += 1
                residue -= 1
            i = (i + 1) % len(orders)
        return [(o, f) for o, f in zip(orders, fills) if f > 0]

    def _fill_resting(self, side, order, fill):
        """Take `fill` from resting `order` on `side`; return its new book quantity (None if gone)."""
        tree = self.bids if side == 'bid' else self.asks
        fill = Decimal(fill)
        if fill < order.quantity:
            new_book_quantity = order.quantity - fill
            order.update_quantity(new_book_quantity, order.timestamp)
            tree.volume -= fill
            return new_book_quantity
        tree.remove_order_by_id(order.order_id)
        return None

    def process_order_list(self, side, order_list, quantity_still_to_trade, quote, verbose):
        '''
        Takes an OrderList (stack of orders at one price) and an incoming order and matches
        appropriate trades given the order's quantity.

        Who at the level fills, and how much, is `allocate`'s decision
        (`matching_rule`); this method only executes the allocation and writes
        the records.
        '''
        trades = []  # local only
        quantity_to_trade = Decimal(quantity_still_to_trade)
        if len(order_list) == 0 or quantity_to_trade <= 0:
            return quantity_to_trade, trades
        # Snapshot the level's orders first: filling removes them from the list.
        for head_order, traded_quantity in self.allocate(list(order_list), quantity_to_trade):
            traded_price = head_order.price
            counter_party = head_order.trade_id
            new_book_quantity = self._fill_resting(side, head_order, traded_quantity)
            quantity_to_trade -= traded_quantity
            if verbose:
                logger.debug(
                    "TRADE: Time - %s, Price - %s, Quantity - %s, TradeID - %s, "
                    "Matching TradeID - %s",
                    self.time,
                    traded_price,
                    traded_quantity,
                    counter_party,
                    quote['trade_id'],
                )

            transaction_record = {
                'timestamp': self.time,
                'price': traded_price,
                'quantity': traded_quantity,
                'time': self.time,
            }
            if side == 'bid':  # counter_party's side
                transaction_record['counter_party'] = {
                    'ID': counter_party,
                    'side': 'bid',
                    'order_id': head_order.order_id,
                    'new_book_quantity': new_book_quantity,
                }
                transaction_record['init_party'] = {
                    'ID': quote['trade_id'],
                    'side': 'ask',
                    'order_id': None,
                    'new_book_quantity': None,
                }
            else:
                transaction_record['counter_party'] = {
                    'ID': counter_party,
                    'side': 'ask',
                    'order_id': head_order.order_id,
                    'new_book_quantity': new_book_quantity,
                }
                transaction_record['init_party'] = {
                    'ID': quote['trade_id'],
                    'side': 'bid',
                    'order_id': None,
                    'new_book_quantity': None,
                }

            self.tape.append(transaction_record)
            trades.append(transaction_record)  # appending indicates a trade done, order filled
        return quantity_to_trade, trades

    # ------------------------------------------------------------------
    # Batch clearing (docs/06 section 8)
    # ------------------------------------------------------------------

    def begin_batch(self):
        """Queue every new market and limit order until `clear_batch`."""
        self.batching = True
        self.pending = []

    @staticmethod
    def _record(price, quantity, init, counter):
        """A tape record in the sequential engine's format.

        The records `clear_batch` builds put a `resting` key in the counter party
        dict they pass in, saying whether that order was on the book (escrowed) or
        arrived in the same batch; this function only assembles the record and sets
        no flag. The sequential engine's records carry none because their counter
        party always rested.
        """
        return {'price': price, 'quantity': quantity, 'init_party': init, 'counter_party': counter}

    def _auction(self, buys, sells, limit_of, sit_out, reference_price):
        """The clearing price: `(key, price, executable volume)`, or None.

        Maximises executable volume, then minimises the leftover imbalance,
        then lies closest to `reference_price`. Candidate prices are every
        limit on the book and in the batch, and the reference price, so that
        when a whole interval of prices clears the same volume (a bid at 102
        against an ask at 98) the auction settles at the reference inside it
        rather than at one of its ends. Resting orders in `sit_out` take no
        part (their owner could not pay at an earlier price).
        """
        candidates = set(self.bids.prices) | set(self.asks.prices)
        candidates |= {limit_of(q) for q in buys + sells if q['type'] == 'limit'}
        candidates.discard(None)
        if reference_price is not None:
            candidates.add(Decimal(str(reference_price)))
        if not candidates:
            return None

        def demand(p):
            total = sum(
                (
                    Decimal(o.quantity)
                    for price, ol in self.bids.price_map.items()
                    if price >= p
                    for o in ol
                    if o.order_id not in sit_out
                ),
                Decimal(0),
            )
            total += sum(
                (Decimal(q['quantity']) for q in buys if limit_of(q) is None or limit_of(q) >= p),
                Decimal(0),
            )
            return total

        def supply(p):
            total = sum(
                (
                    Decimal(o.quantity)
                    for price, ol in self.asks.price_map.items()
                    if price <= p
                    for o in ol
                    if o.order_id not in sit_out
                ),
                Decimal(0),
            )
            total += sum(
                (Decimal(q['quantity']) for q in sells if limit_of(q) is None or limit_of(q) <= p),
                Decimal(0),
            )
            return total

        ref = Decimal(str(reference_price)) if reference_price is not None else None
        best = None
        for p in sorted(candidates):
            d, s = demand(p), supply(p)
            executable = min(d, s)
            key = (-executable, abs(d - s), abs(p - ref) if ref is not None else Decimal(0), p)
            if best is None or key < best[0]:
                best = (key, p, executable)
        return best

    def _unaffordable(self, buys, sells, limit_of, sit_out, p_star, affordable):
        """The orders that would trade at `p_star` whose owners cannot pay for it.

        Returns `(queued orders, resting order ids)`. Asked of the full
        quantity: a marginal order may fill less, so this can turn away an
        order that would have fit, never admit one that does not.
        """
        out_new = []
        for q in buys:
            lim = limit_of(q)
            if (lim is None or lim >= p_star) and not affordable(
                q['trade_id'], 'bid', Decimal(q['quantity']), p_star, None, None
            ):
                out_new.append(q)
        for q in sells:
            lim = limit_of(q)
            if (lim is None or lim <= p_star) and not affordable(
                q['trade_id'], 'ask', Decimal(q['quantity']), p_star, None, None
            ):
                out_new.append(q)
        out_resting = set()
        for (
            price,
            ol,
        ) in self.asks.price_map.items():  # a resting bid never pays more than its limit
            if price > p_star:
                break
            for o in ol:
                if o.order_id not in sit_out and not affordable(
                    o.trade_id, 'ask', o.quantity, p_star, o.price, o.order_id
                ):
                    out_resting.add(o.order_id)
        return out_new, out_resting

    def clear_batch(self, reference_price=None, verbose=False, affordable=None):
        """Clear the queued orders against the book at one uniform price.

        A call auction over the step's arrivals plus the resting book: the
        clearing price maximises executable volume (then minimises the
        leftover imbalance, then lies closest to `reference_price`), every
        buy with a limit above it and every sell with a limit below it fills in
        full, and the marginal price level is rationed - resting orders first,
        in time order, then the batch's, under `matching_rule`. Leftover limit
        orders rest at their own limit; leftover market orders lapse, as in
        the sequential engine. No order is advantaged by where the step's
        shuffle put it unless it is marginal.

        Returns one `(trade_id, trades, order_in_book)` per queued order, in
        queue order, with each trade attached to the order that is its
        `init_party`: the batch order when the other side rested; when both
        arrived in the batch nobody is the aggressor, so a tick rule decides -
        the buyer if the clearing price is above `reference_price`, the seller
        if below, and the direction of the last move if equal (the buyer before
        there has been one). Then `counter_party['resting']` is False, and the
        caller settles that party without an escrow release. Every record is
        on the tape.

        `affordable(trade_id, side, quantity, price, resting_limit, order_id)`
        is asked, once a clearing price is chosen, of every order that would
        trade at it: can its owner pay for the fill at that price? The checks
        made when an order was queued cannot know the price, and a market
        order, a limit sell opening a short and a resting ask filled above its
        limit can all cost more at it. An order that answers no sits out and the
        auction runs again without it, until everyone left can pay. A queued
        order that sits out lapses, market or limit: resting a limit at its own
        price would put it beside the orders it could not afford to trade with
        (a bid above a resting ask), and a crossed book is not one the next
        batch can clear. A resting order simply stays where it is. The queued
        orders that lapsed this way are left in `self.batch_unaffordable` for
        the caller to count as rejected.

        Once anything has sat out, a leftover limit order that would cross what
        is now resting - the counterparty it was to meet sat out - lapses too,
        uncounted: nothing is wrong with that order.
        """
        self.batching = False
        self.batch_unaffordable = []
        pending, self.pending = self.pending, []
        results = {id(q): (q['trade_id'], [], None) for q in pending}
        order = [id(q) for q in pending]
        if not pending:
            return []

        clearing = self._clear_round(pending, reference_price, affordable)
        if clearing.volume <= 0:
            return self._rest_all(clearing.live, results, order, sat_out=clearing.disturbed)

        buy_fills = self._allocate_side(True, clearing)
        sell_fills = self._allocate_side(False, clearing)
        bought, sold = sum(f for *_, f in buy_fills), sum(f for *_, f in sell_fills)
        if not bought == sold == clearing.volume:
            # An exception, not an assert: `python -O` removes asserts, and a
            # mismatch here would go on to pair the two lists into a one-sided trade.
            raise RuntimeError(
                f"batch auction filled {bought} on the buy side and {sold} on the sell "
                f"side against an executable volume of {clearing.volume}; the sides must match"
            )

        filled_qty = self._pair_fills(
            buy_fills, sell_fills, clearing.p_star, results, reference_price
        )
        self._rest_leftovers(clearing, filled_qty, results)
        return [results[k] for k in order]

    @staticmethod
    def _limit_of(q):
        """A queued order's limit as a Decimal; None for a market order."""
        return None if q['type'] == 'market' else Decimal(str(q['price']))

    def _clear_round(self, pending, reference_price, affordable):
        """Run the auction, dropping whoever cannot pay at its price, until everyone left can.

        Returns the `_Clearing` that settled: the price and volume, the queued orders
        still live, and who sat out. A `volume` of 0 means nothing crosses.
        """
        dropped, sit_out = set(), set()  # queued ids / resting order ids that sit out
        while True:
            live = [q for q in pending if id(q) not in dropped]
            buys = [q for q in live if q['side'] == 'bid']
            sells = [q for q in live if q['side'] == 'ask']
            best = self._auction(buys, sells, self._limit_of, sit_out, reference_price)
            if best is None or best[2] <= 0:
                return _Clearing(None, Decimal(0), live, buys, sells, dropped, sit_out)
            _, p_star, volume = best
            if affordable is None:
                break
            out_new, out_resting = self._unaffordable(
                buys, sells, self._limit_of, sit_out, p_star, affordable
            )
            if not out_new and not out_resting:
                break
            for q in out_new:
                dropped.add(id(q))
                self.batch_unaffordable.append(q)
            sit_out |= out_resting
        return _Clearing(p_star, volume, live, buys, sells, dropped, sit_out)

    def _allocate_side(self, is_buy, clearing):
        """The fills of one side at the clearing price, `(order, resting, quantity)` in priority.

        Strictly better limits and market orders first (most aggressive price first,
        then time), then the marginal level, resting before batch, under `matching_rule`.
        """
        p_star, volume, sit_out = clearing.p_star, clearing.volume, clearing.sit_out
        tree = self.bids if is_buy else self.asks
        batch = clearing.buys if is_buy else clearing.sells
        strict, marginal = [], []
        for price, ol in tree.price_map.items():
            better = price > p_star if is_buy else price < p_star
            bucket = strict if better else marginal if price == p_star else None
            if bucket is not None:
                for o in ol:
                    if o.order_id not in sit_out:
                        bucket.append((o, True))
        for q in batch:
            lim = self._limit_of(q)
            if lim is None or (lim > p_star if is_buy else lim < p_star):
                strict.append((q, False))
            elif lim == p_star:
                marginal.append((q, False))

        def aggressiveness(item):
            o, resting = item
            lim = o.price if resting else self._limit_of(o)
            if lim is None:
                lim = Decimal("Infinity") if is_buy else Decimal("-Infinity")
            # Most aggressive first; earlier timestamp first within a price.
            return ((-lim) if is_buy else lim, o.timestamp if resting else o['timestamp'])

        strict.sort(key=aggressiveness)
        fills, left = [], volume
        for o, resting in strict:
            qty = Decimal(o.quantity) if resting else Decimal(o['quantity'])
            fill = min(qty, left)
            if fill > 0:
                fills.append((o, resting, fill))
                left -= fill
            if left <= 0:
                break
        if left > 0 and marginal:
            # Resting orders at the marginal level keep time priority over
            # the batch; within each group the matching rule applies.
            resting_orders = [o for o, r in marginal if r]
            batch_orders = [o for o, r in marginal if not r]
            for o, fill in self.allocate(resting_orders, left):
                fills.append((o, True, fill))
                left -= fill
            if left > 0 and batch_orders:
                wrapped = [_QuantityOnly(q) for q in batch_orders]
                for w, fill in self.allocate(wrapped, left):
                    fills.append((w.q, False, fill))
                    left -= fill
        return fills

    def _auction_initiator(self, p_star, reference_price):
        """Which side initiates a trade whose two sides both arrived in the batch.

        A call auction has no aggressor, and the order flow the observation carries
        (`signed_volume`, `trade_direction`) needs a sign. Always naming the buyer made 53% of
        batch trades buyer-initiated by construction (docs/29 R-1, #171). A tick rule instead:
        a clearing price above the reference (the pre-batch mid) was pushed there by buyers, one
        below it by sellers, and an unchanged price repeats the last direction - the buyer
        until there has been one, which keeps the old answer where nothing is known.
        """
        sign = 0
        if reference_price is not None:
            diff = Decimal(str(p_star)) - Decimal(str(reference_price))
            sign = (diff > 0) - (diff < 0)
        if sign != 0:
            self.last_batch_sign = sign
        elif self.last_batch_sign is not None:
            sign = self.last_batch_sign
        return "ask" if sign < 0 else "bid"

    def _pair_fills(self, buy_fills, sell_fills, p_star, results, reference_price=None):
        """Pair the two fill lists into trade records at `p_star`, on the tape and in `results`.

        Returns how much of each queued order filled, by `id(order)`.
        """
        self.update_time()
        # Decided once per clearing, not per pair: one auction, one price, one direction.
        auction_initiator = self._auction_initiator(p_star, reference_price)
        filled_qty = {}  # id(pending quote) -> filled
        i = j = 0
        bq = [list(x) for x in buy_fills]
        sq = [list(x) for x in sell_fills]
        while i < len(bq) and j < len(sq):
            b, b_rest, b_left = bq[i]
            s, s_rest, s_left = sq[j]
            q = min(b_left, s_left)
            b_id = b.trade_id if b_rest else b['trade_id']
            s_id = s.trade_id if s_rest else s['trade_id']
            # `limit_price` on a resting party: its escrow was posted at that
            # price, and a batch can fill it at a better one, so the settler
            # needs both (Trader.settle_batch).
            b_party = {
                'ID': b_id,
                'side': 'bid',
                'order_id': b.order_id if b_rest else b.get('order_id'),
                'new_book_quantity': None,
                'resting': b_rest,
                'limit_price': b.price if b_rest else None,
            }
            s_party = {
                'ID': s_id,
                'side': 'ask',
                'order_id': s.order_id if s_rest else s.get('order_id'),
                'new_book_quantity': None,
                'resting': s_rest,
                'limit_price': s.price if s_rest else None,
            }
            if b_rest:
                b_party['new_book_quantity'] = self._fill_resting('bid', b, q)
            else:
                filled_qty[id(b)] = filled_qty.get(id(b), Decimal(0)) + q
            if s_rest:
                s_party['new_book_quantity'] = self._fill_resting('ask', s, q)
            else:
                filled_qty[id(s)] = filled_qty.get(id(s), Decimal(0)) + q
            # The batch order is the init party when the other side rested; when both
            # arrived in the batch the tick rule decides. A resting order is never the
            # init party.
            if s_rest and not b_rest:
                init, counter, owner = b_party, s_party, b
            elif b_rest and not s_rest:
                init, counter, owner = s_party, b_party, s
            elif auction_initiator == "ask":
                init, counter, owner = s_party, b_party, s
            else:
                init, counter, owner = b_party, s_party, b
            record = self._record(p_star, q, init, counter)
            record['timestamp'] = self.time
            record['time'] = self.time
            self.tape.append(record)
            tid, trades, oib = results[id(owner)]
            trades.append(record)
            results[id(owner)] = (tid, trades, oib)
            bq[i][2] -= q
            sq[j][2] -= q
            if bq[i][2] <= 0:
                i += 1
            if sq[j][2] <= 0:
                j += 1
        return filled_qty

    def _rest_leftovers(self, clearing, filled_qty, results):
        """Limit orders rest at their own limit, market orders lapse."""
        for q in clearing.live:
            left = Decimal(q['quantity']) - filled_qty.get(id(q), Decimal(0))
            if left > 0 and q['type'] == 'limit':
                if clearing.disturbed and self._would_cross(q):
                    continue
                q['quantity'] = left
                tree = self.bids if q['side'] == 'bid' else self.asks
                tree.insert_order(q)
                tid, trades, _ = results[id(q)]
                results[id(q)] = (tid, trades, q)

    def _would_cross(self, q):
        """Whether resting `q` at its limit would cross an order already resting."""
        price = Decimal(str(q['price']))
        if q['side'] == 'bid':
            return bool(self.asks) and price >= self.asks.min_price()
        return bool(self.bids) and price <= self.bids.max_price()

    def _rest_all(self, pending, results, order, sat_out=False):
        """No cross: every limit order rests, every market order lapses.

        With `sat_out`, an order that would now cross what rests (its
        counterparty sat out) lapses instead.
        """
        for q in pending:
            if q['type'] == 'limit':
                if sat_out and self._would_cross(q):
                    continue
                tree = self.bids if q['side'] == 'bid' else self.asks
                tree.insert_order(q)
                tid, trades, _ = results[id(q)]
                results[id(q)] = (tid, trades, q)
        return [results[k] for k in order]

    def _side(self, side, caller):
        """The two trees an order on `side` works with, as a `_Side`.

        Every operation below is the same for a bid and an ask except which tree is
        the order's own, which is the one it meets, and the direction of one price
        comparison. Writing each twice meant a fix to one side could miss the other
        (issue #256); this is the one place the two are told apart.
        """
        if side == 'bid':
            return _Side(self.bids, self.asks, 'ask', lambda price: price >= self.asks.min_price())
        if side == 'ask':
            return _Side(self.asks, self.bids, 'bid', lambda price: price <= self.bids.max_price())
        raise ValueError(f"{caller}(): side must be 'bid' or 'ask', got {side!r}")

    def process_market_order(self, quote, verbose):
        trades = []
        quantity_to_trade = quote['quantity']
        side = self._side(quote['side'], 'process_market_order')
        while quantity_to_trade > 0 and side.opposite:
            quantity_to_trade, new_trades = self.process_order_list(
                side.opposite_name, side.best_opposite_list(), quantity_to_trade, quote, verbose
            )
            trades += new_trades
        return trades

    def process_limit_order(self, quote, from_data, verbose):
        order_in_book = None
        trades = []
        quantity_to_trade = quote['quantity']
        side = self._side(quote['side'], 'process_limit_order')
        price = quote['price']
        while side.opposite and side.crosses(price) and quantity_to_trade > 0:
            quantity_to_trade, new_trades = self.process_order_list(
                side.opposite_name, side.best_opposite_list(), quantity_to_trade, quote, verbose
            )
            trades += new_trades
        # If volume remains, need to update the book with new quantity
        if quantity_to_trade > 0:
            if not from_data:
                quote['order_id'] = self.next_order_id
            quote['quantity'] = quantity_to_trade
            side.own.insert_order(quote)
            order_in_book = quote
        return trades, order_in_book

    def cancel_order(self, side, order_id, time=None):
        if time is not None:  # a supplied 0 is a time, not "unset"
            self.time = time
        else:
            self.update_time()
        own = self._side(side, 'cancel_order').own
        if own.order_exists(order_id):
            own.remove_order_by_id(order_id)

    def modify_order(self, order_id, order_update, time=None):

        if time is not None:  # a supplied 0 is a time, not "unset"
            self.time = time
        else:
            self.update_time()

        side = order_update['side']
        order_update['order_id'] = order_id
        order_update['timestamp'] = self.time

        # Find the existing order to compare parameters
        tree = self._side(side, 'modify_order').own
        if not tree.order_exists(order_id):
            return [], None
        original_order = tree.get_order(order_id)

        original_price = original_order.price
        original_quantity = original_order.quantity

        # Ensure price and quantity are Decimals for type-safety in underlying logic
        order_update['price'] = Decimal(str(order_update['price']))
        order_update['quantity'] = Decimal(str(order_update['quantity']))

        new_price = order_update['price']
        new_quantity = order_update['quantity']
        if new_quantity <= 0:
            raise ValueError(
                f"modify_order(): order quantity must be > 0, got {new_quantity!r} "
                f"(order_id {order_id!r})"
            )

        # Scenario 4: Quantity decrease at same price -> Keep priority
        if new_price == original_price and new_quantity <= original_quantity:
            tree.update_order(order_update)
            return [], order_update

        # All other scenarios: Remove and re-process to ensure matching and correct priority
        trade_id = original_order.trade_id
        tree.remove_order_by_id(order_id)

        # Prepare quote for re-processing
        quote = {
            'type': 'limit',
            'side': side,
            'quantity': new_quantity,
            'price': new_price,
            'trade_id': trade_id,
            'timestamp': self.time,
            'order_id': order_id,
        }

        if self.batching:
            # Deferred to `clear_batch` like a new order; keeps its id.
            self.pending.append(dict(quote))
            return [], None
        # process_limit_order handles matching and returns trades, order_in_book
        return self.process_limit_order(quote, from_data=True, verbose=False)

    def get_best_bid(self):
        return self.bids.max_price()

    def get_worst_bid(self):
        return self.bids.min_price()

    def get_best_ask(self):
        return self.asks.min_price()

    def get_worst_ask(self):
        return self.asks.max_price()

    def tape_dump(self, filename, filemode, tapemode):
        dumpfile = open(filename, filemode)
        for tapeitem in self.tape:
            dumpfile.write(
                'Time: %s, Price: %s, Quantity: %s\n'
                % (tapeitem['time'], tapeitem['price'], tapeitem['quantity'])
            )
        dumpfile.close()
        if tapemode == 'wipe':
            self.tape.clear()

    def __str__(self):
        tempfile = StringIO()

        tempfile.write("***Bids***\n")
        if self.bids != None and len(self.bids) > 0:
            # price_map is sorted dict, key is price, value is orderlist
            all_bids = []
            for key, value in reversed(self.bids.price_map.items()):
                all_bids.append(value.to_list())

            flat_bids = list(self._flatten(all_bids))  # flat list of dicts
            df_bid = pd.DataFrame(flat_bids)
            tempfile.write(df_bid.to_string())

        tempfile.write("\n***Asks***\n")
        if self.asks != None and len(self.asks) > 0:
            all_asks = []
            for key, value in self.asks.price_map.items():
                all_asks.append(value.to_list())

            flat_ask = list(self._flatten(all_asks))  # flat list of dicts
            df_ask = pd.DataFrame(flat_ask)
            tempfile.write(df_ask.to_string())

        tempfile.write("\n***tape***\n")
        if self.tape != None and len(self.tape) > 0:
            num = 0
            all_TS = []
            for entry in reversed(self.tape):
                if num < self.tape_display_length:  # get last num of entries
                    TS = {}
                    TS["size"] = entry['quantity']
                    TS["price"] = entry['price']
                    TS["timestamp"] = entry['timestamp']
                    TS["counter_party_ID"] = entry['counter_party']['ID']
                    TS["init_party_ID"] = entry['init_party']['ID']
                    TS["init_party_side"] = entry['init_party']['side']
                    # tempfile.write(str(TS) + "\n")
                    all_TS.append(TS)

                    num += 1
                else:
                    break

            all_TS_df = pd.DataFrame(all_TS)
            tempfile.write(all_TS_df.to_string())

        tempfile.write("\n")

        return tempfile.getvalue()

    def _flatten(self, list_of_lists):
        "Flatten one level of nesting"
        return chain.from_iterable(list_of_lists)
