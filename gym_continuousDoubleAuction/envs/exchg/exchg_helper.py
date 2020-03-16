import pandas as pd

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

        self.seq_trades = [] # list of trade lists
        self.seq_order_in_book = [] # list of new order_in_book dicts

        self.init_cash = init_cash
        self.tape_display_length = tape_display_length

        self.model_actions = None
        self.LOB_actions = None
        self.shuffled_actions = None

    def reset_traders_acc(self):
        """
        Reset traders accounts.
        """

        for trader in self.agents:
            trader.acc.reset_acc(trader.ID, self.init_cash)

    def mark_to_mkt(self):
        """
        Update acc for all traders with last price in most recent entry of tape.
        """

        if len(self.LOB.tape) > 0:
            mkt_price = self.LOB.tape[-1].get('price')
            for trader in self.agents:
                trader.acc.mark_to_mkt(trader.ID, mkt_price)
        return 0

    def set_step_outputs(self, state_input):
        """
        Set outputs for each step.

        Arguments:
            state_input: The aggregated LOB after actions executions.

        Return:
            next_states, rewards, dones, infos
        """

        next_states, rewards, dones, infos = {},{},{},{}
        for trader in self.agents:
            next_states = self.set_next_state(next_states, trader, state_input) # dict of tuple of tuples
            rewards = self.set_reward(rewards, trader)
            dones = self.set_done(dones, trader)
            infos = self.set_info(infos, trader)

        dones = self.set_all_done(dones)

        return next_states, rewards, dones, infos

    def print_table(self, msg, data):
        """
        Tabulate data for display.
        """

        print(msg, tabulate(data))
        return 0

    def print_order_in_book_all_seq(self, all_order_in_book):
        for act_seq_num, order_in_book in enumerate(all_order_in_book):
            #print(order_in_book)
            if order_in_book is not None and order_in_book != []:
                print("order_in_book (act_seq_num): {}\n".format(act_seq_num) + tabulate([order_in_book], headers="keys"))
        print("\n")

    def print_trades_all_seq(self, all_trades):
        for act_seq_num, trades in enumerate(all_trades):
            self._print_trades(act_seq_num, trades)
        print("\n")

    def _print_trades(self, act_seq_num, trades):
        """
        Prints trades executed by the action in this sequence in this current t-step.

        Arguments:
            act_seq_num: The order in which the action is executed in this
                         shuffled sequence in this current t-step.

        Returns:
            str: The output string.
        """

        trade_list = []
        for i, trade in enumerate(trades):
            trade_dict = self._pack_trade_dict(i, trade)
            trade_list.append(trade_dict)

        df_trade_list = pd.DataFrame(trade_list)

        if df_trade_list.empty == True:
            str = ""
        else:
            str = "TRADES (act_seq_num): {}\n".format(act_seq_num) + df_trade_list.to_string()
            print(str)

        return str

    def _pack_trade_dict(self, i, trade):
        """
        Repack trade into 1 dim dict.

        Arguments:
            i: The sequence of all actions by all traders(agents) in current t-step
            trade: A dictionary with nested dicts.

        Returns:
            trade_dict: A dictionary.
        """

        trade_dict = {}

        trade_dict['seq_Trade_ID'] = i # seq means all actions by all traders(agents) in current t-step

        trade_dict['timestamp'] = trade['timestamp']
        trade_dict['price'] = trade['price']
        trade_dict['size'] = trade['quantity']
        trade_dict['time'] = trade['time']

        counter_party_dict = trade['counter_party']
        trade_dict['counter_ID'] = counter_party_dict['ID']
        trade_dict['counter_side'] = counter_party_dict['side']
        trade_dict['counter_order_ID'] = counter_party_dict['order_id']
        trade_dict['counter_new_book_size'] = counter_party_dict['new_book_quantity']

        init_party_dict = trade['init_party']
        trade_dict['init_ID'] = init_party_dict['ID']
        trade_dict['init_side'] = init_party_dict['side']
        trade_dict['init_order_ID'] = init_party_dict['order_id']
        trade_dict['init_new_LOB_size'] = init_party_dict['new_book_quantity']

        return trade_dict

    def print_accs(self, msg):
        """
        Print account info for all traders(agents).
        """

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
        """
        Computes total profit of all traders.
        """

        sum = 0
        for trader in self.agents:
            sum += trader.acc.total_profit
        return sum

    def total_sys_nav(self):
        """
        Computes total NAV of all traders.
        """

        sum = 0
        for trader in self.agents:
            sum += trader.acc.nav
        return sum
