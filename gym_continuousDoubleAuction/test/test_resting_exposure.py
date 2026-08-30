"""The cash check nets an order against the position *and* against this
trader's own resting orders.

doc/15 S1-5. `_order_approved` used to compute the "opening" portion of an
order against `abs(net_position)` alone, so every resting order on the closing
side netted against the same lots. N individually-"closing" orders were each
waved through against one position, and because the approval is what bounds
risk, the cash check could be bypassed entirely by layering them across price
levels - a trader long 10 with no cash reached a 90-lot short without a single
refusal.

These tests pin the netting. The escrow's own behaviour - it charges full
notional even for an order that only closes, so `cash` can dip negative while
`cash_on_hold` rises by the same amount - is a separate, NAV-neutral
convention and is asserted here rather than fixed, so a change to it is a
deliberate one.
"""
import sys
from decimal import Decimal

if "../" not in sys.path:
    sys.path.append("../")

from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook
from gym_continuousDoubleAuction.envs.agent.trader import Trader


class TestRestingExposureNetsAgainstThePosition:
    def setup_method(self):
        self.book = OrderBook()
        self.a = Trader(ID=1, cash=1000)
        self.maker = Trader(ID=2, cash=10_000_000)
        self.agents = [self.a, self.maker]

    def _make_a_long_10(self):
        """Leave trader `a` long 10 @ 100 with every spare unit of cash gone."""
        self.maker.place_order('limit', 'ask', 10, 100, self.book, self.agents)
        self.a.place_order('limit', 'bid', 10, 100, self.book, self.agents)
        assert self.a.acc.net_position == 10
        self.a.acc.cash = Decimal(0)
        self.a.acc.cash_on_hold = Decimal(0)
        self.a.acc.cal_nav()

    def test_the_first_closing_order_is_approved(self):
        """The rule this is all in service of: closing always succeeds."""
        self._make_a_long_10()

        self.a.place_order('limit', 'ask', 10, 200, self.book, self.agents)

        assert self.a.acc.num_rejected_step == 0
        assert self.a.acc.num_rejected_step == 0
        assert len(self.book.asks) == 1

    def test_a_second_closing_order_at_another_price_is_refused(self):
        """The position is already claimed by the order resting at 200."""
        self._make_a_long_10()
        self.a.place_order('limit', 'ask', 10, 200, self.book, self.agents)
        rejected = self.a.acc.num_rejected_step

        self.a.place_order('limit', 'ask', 10, 201, self.book, self.agents)

        assert self.a.acc.num_rejected_step == rejected + 1
        assert len(self.book.asks) == 1, "the refused order must not reach the book"

    def test_layering_cannot_build_a_position_the_cash_cannot_cover(self):
        """The measured exploit, end to end.

        Before the fix this filled into a 90-lot short from a 10-lot long.
        """
        self._make_a_long_10()
        for offset in range(10):
            self.a.place_order('limit', 'ask', 10, 201 + offset, self.book, self.agents)

        assert self.a.acc.num_rejected_step == 9, "only one ask may rest against 10 lots"

        # Lift everything that did rest.
        self.maker.place_order('market', 'bid', 100, -1, self.book, self.agents)

        assert self.a.acc.net_position == 0, "a closing order may close, never flip"

    def test_a_partial_close_frees_exactly_what_it_closed(self):
        self._make_a_long_10()
        self.a.place_order('limit', 'ask', 4, 200, self.book, self.agents)
        rejected = self.a.acc.num_rejected_step

        # 6 lots are still unclaimed, so 6 more is fine and 7 is not.
        self.a.place_order('limit', 'ask', 6, 201, self.book, self.agents)
        assert self.a.acc.num_rejected_step == rejected

        self.a.place_order('limit', 'ask', 1, 202, self.book, self.agents)
        assert self.a.acc.num_rejected_step == rejected + 1

    def test_replacing_an_order_at_the_same_price_is_not_double_counted(self):
        """A limit at a price this trader already rests at is an upsert.

        The old order's quantity is released by the very call that would
        otherwise be charged for it, so counting it would refuse a replacement
        that frees more exposure than it takes.
        """
        self._make_a_long_10()
        self.a.place_order('limit', 'ask', 10, 200, self.book, self.agents)
        rejected = self.a.acc.num_rejected_step

        self.a.place_order('limit', 'ask', 10, 200, self.book, self.agents)

        assert self.a.acc.num_rejected_step == rejected
        assert len(self.book.asks) == 1

    def test_a_modify_is_not_double_counted_either(self):
        self._make_a_long_10()
        self.a.place_order('limit', 'ask', 10, 200, self.book, self.agents)
        rejected = self.a.acc.num_rejected_step

        self.a.place_order('modify', 'ask', 10, 205, self.book, self.agents)

        assert self.a.acc.num_rejected_step == rejected
        assert len(self.book.asks) == 1

    def test_the_opening_side_is_still_checked_against_cash_alone(self):
        """Resting bids do not net against anything; the escrow already
        charged them, so the opening side needs no second term."""
        self.a.place_order('limit', 'bid', 5, 100, self.book, self.agents)
        assert self.a.acc.cash == Decimal(500)

        self.a.place_order('limit', 'bid', 5, 101, self.book, self.agents)
        assert self.a.acc.num_rejected_step == 1, "505 > 500 of remaining cash"
        assert self.a.acc.cash == Decimal(500), "a refused order moves no cash"


class TestEscrowConventionOnClosingOrders:
    """The half of S1-5 that is documented rather than fixed.

    A resting order is escrowed at full notional whether it opens or closes, so
    a cash-poor trader closing a position drives `cash` negative. That is a
    reclassification between `cash` and `cash_on_hold`, not a loss: NAV is
    untouched. Changing it would mean tracking escrow per order, because the
    partial-fill paths in `Cash_Processor` all assume escrow == full notional.
    """

    def setup_method(self):
        self.book = OrderBook()
        self.a = Trader(ID=1, cash=1000)
        self.maker = Trader(ID=2, cash=10_000_000)
        self.agents = [self.a, self.maker]

    def test_a_closing_order_escrows_full_notional_and_nav_is_unmoved(self):
        self.maker.place_order('limit', 'ask', 10, 100, self.book, self.agents)
        self.a.place_order('limit', 'bid', 10, 100, self.book, self.agents)
        self.a.acc.cash = Decimal(0)
        self.a.acc.cash_on_hold = Decimal(0)
        nav_before = self.a.acc.cal_nav()

        self.a.place_order('limit', 'ask', 10, 200, self.book, self.agents)

        assert self.a.acc.cash == Decimal(-2000)
        assert self.a.acc.cash_on_hold == Decimal(2000)
        assert self.a.acc.cash + self.a.acc.cash_on_hold == Decimal(0)
        assert self.a.acc.cal_nav() == nav_before, "escrow is NAV-neutral"
