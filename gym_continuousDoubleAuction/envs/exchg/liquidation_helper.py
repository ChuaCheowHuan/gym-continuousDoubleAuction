"""Maintenance margin and liquidation (doc/04 section 8).

A trader whose equity falls to `maintenance_margin` of its position's value is
closed out at the end of the step, in the order a real venue would do it:

1. **Margin call.** Its resting orders are cancelled, which returns their
   escrow to cash.
2. **Liquidation in the book (A).** An immediate-or-cancel order for the whole
   position goes to the book on the closing side. Its limit is the trader's
   *bankruptcy price* - the worst price at which its NAV is still >= 0 - so
   the book stage can never take the account below zero. The fills are
   ordinary trades against orders other agents chose to rest, and they print.
3. **Auto-deleveraging (B).** What the book could not absorb inside that band
   is transferred at the mark to the live traders holding the opposite
   position, pro rata to their size. Positions sum to zero, so the opposite
   side always holds enough, and a transfer at the mark moves no NAV - it only
   shortens positions. This is the backstop, not the mechanism: it runs only
   for the remainder.

`gradual_adl` spreads steps 2 and 3 over up to `liquidation_horizon` steps, as
a real liquidation engine works a large position: the account is frozen, each
step closes `ceil(remaining / steps_left)` in the book inside a band
recomputed from that step's NAV, whatever the book did not take rolls forward
so it can refill in between, and ADL closes what is left on the last step. If
NAV reaches zero meanwhile there is nothing left to protect and the remainder
is closed at once. A horizon of 1 is `market_adl`.

Afterwards the trader is flat. With NAV > 0 it keeps trading on what is left,
as a margin-called account does; with NAV <= 0 `Done_Helper.set_done`
terminates it as before - but now flat, so its NAV is frozen and exact rather
than drifting with a position it can no longer manage (the trapped short that
reached -1.9M in CDA_train.ipynb).

Why this exists: bankruptcy used to be checked only at NAV <= 0 and did not
close the position, so a bankrupt short stayed open and marked to market for
the rest of the episode. Its later losses were the survivors' gains, paid by a
counterparty that could not act and whose policy was never charged for them.
"""
from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Dict, List

from ..agent.trader import _normalise_trade_sizes
from ...config_loader import env_default
from ...logging_setup import get_logger

logger = get_logger(__name__)


class Liquidation_Helper(object):
    #: `market_adl`: maintenance margin, then the book, then ADL, all in the
    #: step the breach is seen. `gradual_adl`: the same, spread over up to
    #: `liquidation_horizon` steps so the book can refill between slices, ADL
    #: for what is left at the end. `off`: the previous behaviour - no margin,
    #: a bankrupt trader keeps its position. Not "none": `train.compare --set`
    #: reads none/null as None.
    LIQUIDATION_MODES = ("market_adl", "gradual_adl", "off")

    def __init__(self, liquidation=env_default("liquidation"),
                 maintenance_margin=env_default("maintenance_margin"),
                 liquidation_horizon=env_default("liquidation_horizon"), **kwargs):
        """
        Arguments:
            liquidation: One of `LIQUIDATION_MODES`.
            maintenance_margin: The equity a position must keep, as a fraction
                of its value at the mark. A trader is liquidated when
                `NAV <= maintenance_margin * |net_position| * mark`. 0 means
                "at bankruptcy", i.e. NAV <= 0.
            liquidation_horizon: `gradual_adl` only - the most steps a
                liquidation may take before ADL closes the remainder. 1 is
                `market_adl`.
        """
        super().__init__(**kwargs)
        if liquidation not in self.LIQUIDATION_MODES:
            raise ValueError(
                f"liquidation must be one of {self.LIQUIDATION_MODES}; got {liquidation!r}."
            )
        margin = Decimal(str(maintenance_margin))
        if not Decimal(0) <= margin < Decimal(1):
            raise ValueError(
                f"maintenance_margin must be in [0, 1); got {maintenance_margin!r}."
            )
        if int(liquidation_horizon) != liquidation_horizon or liquidation_horizon < 1:
            raise ValueError(
                f"liquidation_horizon must be a whole number of steps >= 1; got "
                f"{liquidation_horizon!r}."
            )
        self.liquidation = liquidation
        self.maintenance_margin = margin
        self.liquidation_horizon = int(liquidation_horizon)

    # ------------------------------------------------------------------ trigger

    def margin_ratio(self, trader, mark) -> Decimal:
        """Equity over position value at `mark`; None when flat."""
        pos = trader.acc.net_position
        if pos == 0 or mark is None or mark <= 0:
            return None
        return trader.acc.nav / (abs(pos) * mark)

    def _in_breach(self, trader, mark) -> bool:
        pos = trader.acc.net_position
        if pos == 0 or mark is None or mark <= 0:
            return False
        return trader.acc.nav <= self.maintenance_margin * abs(pos) * mark

    @staticmethod
    def _liquidating(trader) -> bool:
        return trader.acc.liquidation_steps_left > 0

    def liquidate(self) -> List[Dict]:
        """Run this step's liquidations; returns one record per action taken.

        Runs after the step's `mark_to_mkt` and before the observation is
        built, so the reward, the observation and the info of this step all
        see the accounts after it.

        1. `gradual_adl` only: every liquidation already under way closes its
           next slice, most distressed first.
        2. Then, repeatedly until nothing is left to do: a live trader newly
           in breach is liquidated - closed out in full (`market_adl`), or
           frozen with its first slice closed now (`gradual_adl`) - and a
           trader in liquidation whose NAV has reached zero is closed out in
           full, since there is no equity left for a slower close to protect.
           Each can move the mark and put someone else in breach, which is the
           cascade a squeeze produces. Every action either starts a
           liquidation (once per trader) or leaves a trader flat, so the loop
           ends within `2 * len(traders)` rounds.

        The invariant it leaves behind: no live trader with NAV <= 0 holds a
        position, so `set_done` only ever terminates a flat account.
        """
        if self.liquidation == "off":
            return []

        events = []
        if self.liquidation == "gradual_adl":
            mark = self.mark_price()
            under_way = [t for t in self.traders if self.is_live(t) and self._liquidating(t)]
            for trader in sorted(under_way, key=lambda t: (self.margin_ratio(t, mark) or 0, t.ID)):
                if trader.acc.net_position == 0:
                    # Flattened meanwhile - by another liquidation's ADL.
                    trader.acc.liquidation_steps_left = 0
                    continue
                if trader.acc.nav <= 0:
                    continue  # no equity left: closed in full below
                events.append(self._close_slice(trader, self.mark_price()))
                self._remark_keeping_prev_nav()

        for _ in range(2 * len(self.traders)):
            mark = self.mark_price()
            due = [t for t in self.traders if self.is_live(t) and (
                (self._liquidating(t) and t.acc.net_position != 0 and t.acc.nav <= 0)
                or (not self._liquidating(t) and self._in_breach(t, mark)))]
            if not due:
                break
            trader = min(due, key=lambda t: (self.margin_ratio(t, mark), t.ID))
            if self.liquidation == "gradual_adl" and trader.acc.nav > 0:
                events.append(self._start_gradual(trader, mark))
            else:
                events.append(self._liquidate_one(trader, mark))
            self._remark_keeping_prev_nav()
        return events

    # -------------------------------------------------------------- close-out

    def _margin_call(self, trader):
        """Pull every resting order; their escrow returns to cash, and no forced
        order can then meet one of the trader's own."""
        if trader.cancel_all_orders(self.LOB):
            self._snapshot_stale = True

    def _liquidate_one(self, trader, mark) -> Dict:
        """Close the whole position now: the book inside the band, ADL the rest."""
        acc = trader.acc
        nav_before = acc.nav
        position = acc.net_position
        # Counted as a liquidation only if it is not the end of one already
        # counted when it started (a gradual close-out whose NAV ran out).
        if not self._liquidating(trader):
            acc.num_liquidations_step += 1
        self._margin_call(trader)

        side = 'bid' if position < 0 else 'ask'
        band = self._bankruptcy_price(trader, mark)
        book_qty = self._close_in_book(trader, side, abs(position), band)

        # ADL for the remainder, at the TRIGGER mark - the one the breach was
        # measured at and the band built from - not the mark after the book
        # stage. The book fills may have moved the mid against the trader;
        # transferring at that newer price could take it below zero, which the
        # band exists to prevent. At the trigger mark its final NAV is
        # `nav_before` less the book stage's slippage, >= 0 whenever
        # `nav_before` was.
        remainder = abs(acc.net_position)
        adl_qty = self._deleverage(trader, remainder, mark) if remainder else 0

        acc.liquidated_book_qty_step += book_qty
        acc.liquidated_adl_qty_step += adl_qty
        acc.liquidation_steps_left = 0
        return self._record(trader, "close", position, mark, band, book_qty, adl_qty, nav_before)

    def _start_gradual(self, trader, mark) -> Dict:
        """Freeze the account and close its first slice in this same step.

        The freeze is `liquidation_steps_left > 0`: `Trader._order_approved`
        refuses every order while it is set, so the action mask marks every
        category but pass impossible and the policy can see it is being
        liquidated. Irreversible once started, as on a real venue - a price
        that swings back does not hand a half-closed position back.
        """
        trader.acc.num_liquidations_step += 1
        self._margin_call(trader)
        trader.acc.liquidation_steps_left = self.liquidation_horizon
        return self._close_slice(trader, mark)

    def _close_slice(self, trader, mark) -> Dict:
        """One TWAP slice: `ceil(remaining / steps_left)` in the book, inside
        the band recomputed from this step's NAV and mark. What the book does
        not take rolls into the later slices; on the last step ADL closes it.
        """
        acc = trader.acc
        nav_before = acc.nav
        position = acc.net_position
        remaining = abs(position)
        steps_left = acc.liquidation_steps_left
        target = -(-remaining // steps_left)  # ceil

        side = 'bid' if position < 0 else 'ask'
        band = self._bankruptcy_price(trader, mark)
        book_qty = self._close_in_book(trader, side, target, band)
        acc.liquidated_book_qty_step += book_qty

        acc.liquidation_steps_left = steps_left - 1
        adl_qty = 0
        left = abs(acc.net_position)
        if left and acc.liquidation_steps_left == 0:
            adl_qty = self._deleverage(trader, left, mark)
            acc.liquidated_adl_qty_step += adl_qty
        if acc.net_position == 0:
            acc.liquidation_steps_left = 0
        return self._record(trader, "slice", position, mark, band, book_qty, adl_qty, nav_before)

    def _record(self, trader, kind, position, mark, band, book_qty, adl_qty, nav_before) -> Dict:
        event = {
            "ID": trader.ID,
            "kind": kind,
            "position": position,
            "mark": mark,
            "band": band,
            "book_qty": book_qty,
            "adl_qty": adl_qty,
            "nav_before": nav_before,
            "steps_left": trader.acc.liquidation_steps_left,
        }
        logger.info(
            "liquidation (%s) of agent_%s at t_step %s: position %s, NAV %s, mark %s; "
            "%s closed in the book (band %s), %s by ADL, %s steps left",
            kind, trader.ID, getattr(self, "t_step", "?"), position, nav_before,
            mark, book_qty, band, adl_qty, trader.acc.liquidation_steps_left,
        )
        return event

    def _bankruptcy_price(self, trader, mark) -> Decimal:
        """The worst closing price at which the trader's NAV stays >= 0.

        Closing `|pos|` contracts at price p changes NAV by
        `net_position * (p - mark)`, so NAV reaches 0 at
        `mark - NAV / net_position`. With NAV already <= 0 there is no equity
        to protect, and the band is the mark itself: the book may only improve
        on it. Snapped to the tick grid on the conservative side - down for a
        buy, up for a sell - and never below one tick.
        """
        acc = trader.acc
        tick = Decimal(str(self.min_tick))
        cushion = max(acc.nav, Decimal(0)) / abs(acc.net_position)
        if acc.net_position < 0:  # closing a short: buy, at most this
            price = ((mark + cushion) / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
        else:  # closing a long: sell, at least this
            price = ((mark - cushion) / tick).to_integral_value(rounding=ROUND_CEILING) * tick
        return max(price, tick)

    def _close_in_book(self, trader, side, quantity, band) -> int:
        """An immediate-or-cancel order: fill inside `band`, rest nothing.

        Goes to the book directly rather than through `Trader.place_order`:
        a liquidation is not the trader's action, so the cash check that
        refuses every order at NAV <= 0 must not apply to it, and no escrow is
        posted because nothing is left resting. The fills are settled by the
        same `_process_trades` every trade goes through, so the counterparties'
        resting orders release their escrow as usual.

        The forced fills are not counted in the trader's `num_trades_step`:
        that counter is what `trade_penalty` charges and what the activity
        metrics read, and neither is about an order the agent did not place.
        `num_trades`, the cumulative count, does include them.
        """
        if quantity <= 0:
            return 0
        own_step_trades = trader.acc.num_trades_step
        before = abs(trader.acc.net_position)
        quote = {'type': 'limit', 'side': side, 'quantity': int(quantity),
                 'price': band, 'trade_id': trader.ID}
        trades, order_in_book = self.LOB.process_order(quote, False, False)
        if order_in_book:
            self.LOB.cancel_order(side, order_in_book['order_id'])
        if trades:
            _normalise_trade_sizes(trades)
            trader._process_trades(trades, self.traders)
        trader.acc.num_trades_step = own_step_trades
        return before - abs(trader.acc.net_position)

    def _deleverage(self, trader, quantity, mark) -> int:
        """Transfer `quantity` of the trader's position to the opposite side.

        Pro rata to the size of each live opposite position, whole contracts,
        largest remainder first and then lowest ID, so the split is exact and
        deterministic. Each leg is booked for both parties through
        `Account.process_acc` as a cash-settled trade at the mark - the path
        `Trader.settle_batch` uses for a counter party with no resting order -
        so the ledger arithmetic is the one every fill uses. At the mark the
        breach was measured at, it leaves every counterparty's NAV where that
        mark put it.

        Not printed to the tape, as real venues do not print ADL: it is a
        transfer, not a trade anyone chose, and printing it would move
        `last_price`.
        """
        buying = trader.acc.net_position < 0
        opposite = [t for t in self.traders
                    if t is not trader and self.is_live(t)
                    and (t.acc.net_position > 0 if buying else t.acc.net_position < 0)]
        available = sum(abs(t.acc.net_position) for t in opposite)
        if available < quantity:
            # Positions sum to zero and a terminated trader is always flat
            # under this mode, so this means the ledger is broken.
            raise RuntimeError(
                f"ADL for agent_{trader.ID} needs {quantity} contracts but the "
                f"opposite side holds {available}; positions no longer sum to zero."
            )

        shares = self._pro_rata(opposite, quantity, available)
        mark = Decimal(mark)
        own_side, other_side = ('bid', 'ask') if buying else ('ask', 'bid')
        for other, qty in shares:
            if qty <= 0:
                continue
            for party, side in ((trader, own_side), (other, other_side)):
                steps = party.acc.num_trades_step
                party.acc.process_acc(
                    {'price': mark, 'quantity': qty,
                     'init_party': {'ID': party.ID, 'side': side}},
                    'init_party',
                )
                party.acc.num_trades_step = steps
            other.acc.adl_qty_step += qty
        return quantity

    @staticmethod
    def _pro_rata(traders, quantity, available):
        """Largest-remainder split of `quantity` in proportion to |position|."""
        raw = [(t, Decimal(abs(t.acc.net_position)) * quantity / available) for t in traders]
        shares = {t.ID: int(r.to_integral_value(rounding=ROUND_FLOOR)) for t, r in raw}
        residue = quantity - sum(shares.values())
        by_remainder = sorted(raw, key=lambda item: (-(item[1] - shares[item[0].ID]), item[0].ID))
        for t, _ in by_remainder[:residue]:
            shares[t.ID] += 1
        return [(t, shares[t.ID]) for t in traders]

    def _remark_keeping_prev_nav(self):
        """Re-mark every account at the post-liquidation price.

        `Calculate.mark_to_mkt` moves `nav` into `prev_nav`, and the reward is
        `nav - prev_nav`. The step's own mark has already done that once, so a
        second call would leave the reward holding only the liquidation's
        slice of the step. `prev_nav` is put back so the reward still spans
        the whole step, including the close-out.
        """
        prev = [t.acc.prev_nav for t in self.traders]
        self.mark_to_mkt()
        for t, p in zip(self.traders, prev):
            t.acc.prev_nav = p
