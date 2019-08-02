from decimal import Decimal

class Calculate(object):

    def cal_nav(self):
        self.nav =  self.cash + self.cash_on_hold + self.position_val
        return self.nav

    def cal_total_profit(self):
        self.total_profit = self.nav - self.init_nav
        return self.total_profit

    def cal_profit(self, position, mkt_val, raw_val):
        if position == 'long':
            self.profit = mkt_val - raw_val
        else:
            self.profit = raw_val - mkt_val
        return self.profit

    def mark_to_mkt(self, ID, mkt_price):
        # (on_false, on_true)[condition]
        price_diff = (self.VWAP - mkt_price, mkt_price - self.VWAP)[self.net_position >= 0]
        self.profit = Decimal(abs(self.net_position)) * price_diff

        print('sync_acc profit@t:', ID, self.profit, price_diff)

        raw_val = Decimal(abs(self.net_position)) * self.VWAP
        self.position_val = raw_val + self.profit

        self.prev_nav = self.nav
        self.cal_nav()
        self.cal_total_profit()
        return 0
