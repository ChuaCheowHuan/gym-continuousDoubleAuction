from decimal import Decimal

from .account_state import AccountState


class Calculate(AccountState):
    def cal_nav(self) -> Decimal:
        """
        The trader's cash, cash_on_hold & his holding's value (position_val) at
        this current t step.
        """

        self.nav = self.cash + self.cash_on_hold + self.position_val
        return self.nav

    def update_peak(self) -> Decimal:
        """Raise the running peak (`max_nav`) to the NAV the step ended on.

        Called once per step, after the last re-mark, and not from `cal_nav`: a
        liquidation cascade re-marks every account several times in one step, and a NAV
        that existed between two of those re-marks is one no observation or reward ever
        saw. Letting it set the peak charged drawdown against a level nobody could have
        held at a step boundary (doc/15 R-4, #174). A fund's high-water mark is set the
        same way, at valuation points.
        """
        if self.nav > self.max_nav:
            self.max_nav = self.nav
        return self.max_nav

    def cal_total_profit(self) -> Decimal:
        """
        The current NAV at t step minus the initial NAV at the start of the trading session.
        """

        self.total_profit = self.nav - self.init_nav
        return self.total_profit

    def cal_profit(self, position: str, mkt_val: Decimal, raw_val: Decimal) -> Decimal:
        """
        The profit or loss from current holdings (position_val).
        """

        if position == 'long':
            self.profit = mkt_val - raw_val
        else:
            self.profit = raw_val - mkt_val
        return self.profit

    def mark_to_mkt(self, ID: int, mkt_price: Decimal) -> int:
        """
        Update acc for a trader with last price in most recent entry of tape.

        note:
            net_position > 0 for long.
            net_position < 0 for short.
        """

        # Built from the exact basis and one product, `|pos| x mark`. It used
        # to be `|pos| x VWAP + |pos| x (mark - VWAP)`: two products of a
        # rounded quotient, rounded independently, which is where NAV
        # conservation lost its last digit (doc/15 S3-23). For a long this is
        # `mkt_val` exactly; for a short `2 x cost_basis - mkt_val`.
        raw_val = self.cost_basis
        mkt_val = abs(self.net_position) * mkt_price
        self.cal_profit('long' if self.net_position >= 0 else 'short', mkt_val, raw_val)
        self.position_val = raw_val + self.profit

        self.prev_nav = self.nav
        self.cal_nav()
        self.cal_total_profit()
        return 0
