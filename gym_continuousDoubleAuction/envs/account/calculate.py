from decimal import Decimal

class Calculate(object):

    def cal_nav(self):
        """
        The trader's cash, cash_on_hold & his holding's value (position_val) at
        this current t step.
        """

        self.nav =  self.cash + self.cash_on_hold + self.position_val
        return self.nav

    def cal_total_profit(self):
        """
        The current NAV at t step minus the initial NAV at the start of the trading session.
        """

        self.total_profit = self.nav - self.init_nav
        return self.total_profit

    def cal_profit(self, position, mkt_val, raw_val):
        """
        The profit or loss from current holdings (position_val).
        """

        if position == 'long':
            self.profit = mkt_val - raw_val
        else:
            self.profit = raw_val - mkt_val
        return self.profit

    def mark_to_mkt(self, ID, mkt_price):
        """
        Update acc for a trader with last price in most recent entry of tape.

        note:
            net_position > 0 for long.
            net_position < 0 for short.
        """

        price_diff = (self.VWAP - mkt_price, mkt_price - self.VWAP)[self.net_position >= 0] # (on_false, on_true)[condition]
        self.profit = Decimal(abs(self.net_position)) * price_diff

        print('ID: {}; profit: {}'.format(ID, self.profit))

        raw_val = abs(self.net_position) * self.VWAP
        self.position_val = raw_val + self.profit

        self.prev_nav = self.nav
        self.cal_nav()
        self.cal_total_profit()
        return 0
