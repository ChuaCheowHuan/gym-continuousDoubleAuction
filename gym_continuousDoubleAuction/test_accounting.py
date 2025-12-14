from decimal import Decimal
import sys

# Mocking the classes based on file content
class Cash_Processor(object):
    def order_in_book_init_party(self, order_in_book):
        if order_in_book != None and order_in_book != []:
            order_in_book_val = order_in_book.get('price') * Decimal(order_in_book.get('quantity'))
            self.cash -= order_in_book_val
            self.cash_on_hold += order_in_book_val
        return 0

    def size_increase_cash_transfer(self, party, trade_val):
        if party == 'init_party':
            self.cash -= trade_val
        else:
            self.cash_on_hold -= trade_val
        return 0

    def size_decrease_cash_transfer(self, party, trade_val):
        if party == 'init_party':
            self.cash += trade_val
        else:
            self.cash += trade_val
            self.cash_on_hold -= trade_val
            self.cash += trade_val
        return 0

    def size_zero_cash_transfer(self, trade_val):
        self.cash += self.position_val - trade_val
        return 0

    def init_is_counter_cash_transfer(self, trade_val):
        self.cash_on_hold -= trade_val
        self.cash += trade_val
        return 0

    def modify_cash_transfer(self, qoute, order):
        # omitted for this test
        return 0

    def cancel_cash_transfer(self, order):
        # omitted for this test
        return 0

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
        price_diff = (self.VWAP - mkt_price, mkt_price - self.VWAP)[self.net_position >= 0]
        self.profit = Decimal(abs(self.net_position)) * price_diff
        raw_val = abs(self.net_position) * self.VWAP
        self.position_val = raw_val + self.profit
        self.prev_nav = self.nav
        self.cal_nav()
        self.cal_total_profit()
        return 0

class Account(Calculate, Cash_Processor):
    def __init__(self, ID, cash=0):
        self.ID = ID
        self.cash = Decimal(cash)
        self.cash_on_hold = Decimal(0)
        self.position_val = Decimal(0)
        self.init_nav = Decimal(cash)
        self.nav = Decimal(cash)
        self.prev_nav = Decimal(cash)
        self.net_position = 0
        self.VWAP = Decimal(0)
        self.profit = Decimal(0)
        self.total_profit = Decimal(0)
        self.num_trades = 0

    def _size_increase(self, trade, position, party, trade_val):
        total_size = abs(self.net_position) + Decimal(trade.get('quantity'))
        self.VWAP = (abs(self.net_position) * self.VWAP + trade_val) / total_size
        raw_val = total_size * self.VWAP
        mkt_val = total_size * trade.get('price')
        self.position_val = raw_val + self.cal_profit(position, mkt_val, raw_val)
        self.size_increase_cash_transfer(party, trade_val)
        return 0

    def _covered(self, trade, position):
        raw_val = abs(self.net_position) * self.VWAP
        mkt_val = abs(self.net_position) * trade.get('price')
        self.position_val = raw_val + self.cal_profit(position, mkt_val, raw_val)
        self.size_zero_cash_transfer(mkt_val)
        self.position_val = 0
        self.VWAP = 0
        return mkt_val

    def _size_decrease(self, trade, position, party, trade_val):
        size_left = abs(self.net_position) - Decimal(trade.get('quantity'))
        if size_left > 0:
            self.VWAP = (abs(self.net_position) * self.VWAP - trade_val) / size_left
            raw_val = size_left * self.VWAP
            mkt_val = size_left * trade.get('price')
            self.position_val = raw_val + self.cal_profit(position, mkt_val, raw_val)
        else:
            mkt_val = self._covered(trade, position)
        self.size_decrease_cash_transfer(party, trade_val)
        return 0

    def _covered_side_chg(self, trade, position, party):
        mkt_val = self._covered(trade, position)
        self.size_decrease_cash_transfer(party, mkt_val)
        new_size = Decimal(trade.get('quantity')) - abs(self.net_position)
        self.position_val = new_size * trade.get('price')
        self.VWAP = trade.get('price')
        self.size_increase_cash_transfer(party, self.position_val)
        return 0

    def _neutral(self, trade_val, trade, party):
        self.position_val += trade_val
        self.VWAP = trade.get('price')
        self.size_increase_cash_transfer(party, trade_val)

    def _net_long(self, trade_val, trade, party):
        if trade.get(party).get('side') == 'bid':
            self._size_increase(trade, 'long', party, trade_val)
        else:
            if self.net_position >= trade.get('quantity'):
                self._size_decrease(trade, 'long', party, trade_val)
            else:
                self._covered_side_chg(trade, 'long', party)

    def _net_short(self, trade_val, trade, party):
        if trade.get(party).get('side') == 'ask':
            self._size_increase(trade, 'short', party, trade_val)
        else:
            if abs(self.net_position) >= trade.get('quantity'):
                self._size_decrease(trade, 'short', party, trade_val)
            else:
                self._covered_side_chg(trade, 'short', party)

    def _update_net_position(self, side, trade_quantity):
        if self.net_position >= 0:
            if side == 'bid':
                self.net_position = Decimal(self.net_position) + Decimal(trade_quantity)
            else:
                self.net_position = Decimal(self.net_position) - Decimal(trade_quantity)
        else:
            if side == 'ask':
                self.net_position = Decimal(self.net_position) - Decimal(trade_quantity)
            else:
                self.net_position = Decimal(self.net_position) + Decimal(trade_quantity)
        return 0

    def process_acc(self, trade, party):
        self.num_trades += 1
        trade_val = Decimal(trade.get('quantity')) * trade.get('price')
        if self.net_position > 0:
            self._net_long(trade_val, trade, party)
        elif self.net_position < 0:
            self._net_short(trade_val, trade, party)
        else:
            self._neutral(trade_val, trade, party)
        self._update_net_position(trade.get(party).get('side'), trade.get('quantity'))
        self.cal_nav()
        return 0

# Test Script
acc = Account("TestTrader", 1000)
print(f"Initial: Cash {acc.cash}, NAV {acc.nav}")

# 1. Open Short 2 @ 100
trade1 = {
    'price': Decimal(100),
    'quantity': Decimal(2),
    'init_party': {'side': 'ask', 'ID':'TestTrader'}, # Selling
    'counter_party': {'ID': 'Other'}
}
print("\n--- Short 2 @ 100 ---")
acc.process_acc(trade1, 'init_party')
print(f"Cash {acc.cash}, PosVal {acc.position_val}, NAV {acc.nav}, VWAP {acc.VWAP}")
# Exp: Cash 800 (1000 - 200), PosVal 200 (Cost), NAV 1000

# 2. Mark to Market Price drop to 50
print("\n--- Mark to Market @ 50 ---")
acc.mark_to_mkt("TestTrader", Decimal(50))
print(f"Cash {acc.cash}, PosVal {acc.position_val}, NAV {acc.nav}, VWAP {acc.VWAP}")
# Exp: Cash 800, PosVal 300 (200 Cost + 100 Profit), NAV 1100

# 3. Partial Cover 1 @ 50
trade2 = {
    'price': Decimal(50),
    'quantity': Decimal(1),
    'init_party': {'side': 'bid', 'ID':'TestTrader'}, # Buying to cover
    'counter_party': {'ID': 'Other'}
}
print("\n--- Cover 1 @ 50 ---")
acc.process_acc(trade2, 'init_party')
print(f"Cash {acc.cash}, PosVal {acc.position_val}, NAV {acc.nav}, VWAP {acc.VWAP}")
# Exp (Based on analysis): Cash 850 (+50 trade val), PosVal 250 (Trapped Profit), NAV 1100

# 4. Final Cover 1 @ 50
trade3 = {
    'price': Decimal(50),
    'quantity': Decimal(1),
    'init_party': {'side': 'bid', 'ID':'TestTrader'}, 
    'counter_party': {'ID': 'Other'}
}
print("\n--- Cover 1 @ 50 (Final) ---")
acc.process_acc(trade3, 'init_party')
print(f"Cash {acc.cash}, PosVal {acc.position_val}, NAV {acc.nav}, VWAP {acc.VWAP}")
# Exp: Cash 1100, PosVal 0, NAV 1100
