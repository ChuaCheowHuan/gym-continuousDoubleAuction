from .state_helper import State_Helper
from .action_helper import Action_Helper
from .reward_helper import Reward_Helper
from .done_helper import Done_Helper
from .info_helper import Info_Helper

from ..orderbook.orderbook import OrderBook
from ..agent.trader import Trader

from tabulate import tabulate

class Exchg_Helper(State_Helper, Action_Helper, Reward_Helper, Done_Helper, Info_Helper):
    def __init__(self, init_cash=0, tick_size=1, tape_display_length=10):
        super(Exchg_Helper, self).__init__()

        self.LOB = OrderBook(tick_size, tape_display_length) # limit order book
        self.agg_LOB = {} # aggregated or consolidated LOB
        self.agg_LOB_aft = {} # aggregated or consolidated LOB after processing orders

        self.trades = {} # a trade between init_party & counter_party
        self.order_in_book = {} # unfilled orders goes to LOB

        self.init_cash = init_cash
        self.tape_display_length = tape_display_length

    # reset traders accounts
    def reset_traders_acc(self):
        for trader in self.agents:
            trader.acc.reset_acc(trader.ID, self.init_cash)

    # update acc for all traders with last price in most recent entry of tape
    def mark_to_mkt(self):
        if len(self.LOB.tape) > 0:
            mkt_price = self.LOB.tape[-1].get('price')
            for trader in self.agents:
                trader.acc.mark_to_mkt(trader.ID, mkt_price)
        return 0

    def set_step_outputs(self, state_input):
        next_states, rewards, dones, infos = {},{},{},{}
        for trader in self.agents:
            next_states = self.set_next_state(next_states, trader, state_input) # dict of tuple of tuples
            rewards = self.set_reward(rewards, trader)
            dones = self.set_done(dones, trader)
            infos = self.set_info(infos, trader)

        dones = self.set_all_done(dones)
        return next_states, rewards, dones, infos

    def print_accs(self, msg):
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

        for trader in self.agents:
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

        print(msg, tabulate(acc, headers="keys"))

        return 0

    def total_sys_profit(self):
        sum = 0
        for trader in self.agents:
            sum += trader.acc.total_profit
        return sum

    def total_sys_nav(self):
        sum = 0
        for trader in self.agents:
            sum += trader.acc.nav
        return sum
