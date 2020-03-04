#import tensorflow as tf
import numpy as np
import pandas as pd

import gym
from gym import error, spaces, utils
from gym.utils import seeding

import ray
from ray.rllib.env.multi_agent_env import MultiAgentEnv

from .orderbook.orderbook import OrderBook
from .exchg.exchg_helper import Exchg_Helper
from .agent.trader import Trader

from tabulate import tabulate

# The exchange environment
class continuousDoubleAuctionEnv(Exchg_Helper, gym.Env, MultiAgentEnv):

    metadata = {'render.modes': ['human']}

    def __init__(self, num_of_agents=2, init_cash=0, tick_size=1, tape_display_length=10, max_step=100):
        super(continuousDoubleAuctionEnv, self).__init__(init_cash, tick_size, tape_display_length)

        self.next_states = {}
        self.rewards = {}
        self.dones = {}
        self.done_set = set()
        self.infos = {}

        # step when actions by all traders are executed, not tick time
        # within a step, multiple trades(ticks) could happened
        self.t_step = 0
        self.max_step = max_step

        # list of agents or traders
        self.agents = [Trader(ID, init_cash) for ID in range(0, num_of_agents)]

        # observation space per agent:
        # array([[ 1.,  0., -1.,  0.,  0.,  0.,  0.,  0.,  0.,  0.],
        #        [-1., -4., -4.,  0.,  0.,  0.,  0.,  0.,  0.,  0.],
        #        [ 0.,  0.,  0.,  0.,  0.,  0.,  0.,  0.,  0.,  0.],
        #        [ 0.,  0.,  0.,  0.,  0.,  0.,  0.,  0.,  0.,  0.]])
        inf = float('inf')
        neg_inf = float('-inf')
        obs_row = 4
        obs_col = 10
        self.observation_space = spaces.Box(low=neg_inf, high=inf, shape=(obs_row,obs_col))

        # order per agent: {'ID': 0, 'type': 'market', 'side': 'bid', 'size': 1, 'price': 8}
        # action space per agent: {'type_side': 0-4, 'size': 1-inf, 'price': tick_size-inf}
        self.action_space = self.disc_act()

        self.model_actions = None
        self.LOB_actions = None
        self.shuffled_actions = None

    # reset
    def reset(self):

        self.LOB = OrderBook(1, self.tape_display_length) # new limit order book
        #self.LOB = OrderBook(0.25, self.tape_display_length) # new limit order book
        self.agg_LOB = {}
        self.agg_LOB_aft = {}

        self.next_states = {}
        self.rewards = {}
        self.dones = {}
        self.done_set = set()
        self.infos = {}

        self.trades = None # a trade between init_party & counter_party
        self.order_in_book = None # unfilled orders goes to LOB

        self.t_step = 0

        self.reset_traders_acc()

        return self.reset_traders_agg_LOB()

    # actions is a list of actions from all agents (traders) at t step
    # each action is a list of (ID, type, side, size, price)
    def step(self, actions):

        self.model_actions = actions
        #print('step actions:', actions)

        self.next_states, self.rewards, self.dones, self.infos = {}, {}, {}, {}
        self.agg_LOB = self.set_agg_LOB() # LOB state at t before processing LOB

        actions = self.set_actions(actions) # format actions from nn output to be acceptable by LOB
        self.LOB_actions = actions

        actions = self.rand_exec_seq(actions, None) # randomized traders execution sequence
        self.shuffled_actions = actions

        self.trades, self.order_in_book = self.do_actions(actions) # Begin processing LOB
        #self.mark_to_mkt() # mark to market

        # after processing LOB
        state_input = self.prep_next_state()
        self.next_states, self.rewards, self.dones, self.infos = self.set_step_outputs(state_input)

        self.render()
        self.t_step += 1

        return self.next_states, self.rewards, self.dones, self.infos

    # render
    def render(self):
        #if self.t_step % 10 == 0:
        self._render()
        #return 0

    def _render(self):
        print('\n************************************************** t_step = {} **************************************************\n'.format(self.t_step))

        self._table("Model actions:\n", self.model_actions)
        self._table("Formatted actions acceptable by LOB:\n", self.LOB_actions)
        self._table("Shuffled action queueing sequence for LOB executions:\n", self.shuffled_actions)

        #print('\nnext_states:\n', self.next_states)
        print('\nrewards:\n', self.rewards)
        print('\ndones:\n', self.dones)
        print('\ninfos:\n', self.infos)

        #print('\nagg_LOB:\n', self.agg_LOB)
        self._table("\nagg LOB @ t-1\n", self.agg_LOB)
        #print('\nagg_LOB_aft:\n', self.agg_LOB_aft)
        self._table("\nagg LOB @ t\n", self.agg_LOB_aft)

        print('\nLOB:\n', self.LOB) # print entire LOB with tape


        if self.trades is not None:
            self.print_trades_all_seq(self.trades)
            self.trades = None
        else:
            print("\nNo trades in this t-step.\n")

        if self.order_in_book is not None:
            self.print_order_in_book_all_seq(self.order_in_book)
            self.order_in_book = None
        else:
            print("\nNo new limit orders in this t-step.\n")

        print("mark_to_mkt profit@t:")
        self.mark_to_mkt() # mark to market
        self.print_accs("\nAccounts:\n")
        print('\ntotal_sys_profit = {}; total_sys_nav = {}\n'.format(self.total_sys_profit(), self.total_sys_nav()))

    def _table(self, msg, data):
        print(msg, tabulate(data))
        #print(tabulate(data, headers=["bid size","bid price", "ask size","ask price"]))
        return 0

    def close(self):
        pass

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
        trade_dict = {}

        trade_dict['seq_Trade_ID'] = i

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
