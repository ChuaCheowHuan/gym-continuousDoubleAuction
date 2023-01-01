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
# class continuousDoubleAuctionEnv(Exchg_Helper, gym.Env, MultiAgentEnv):
class continuousDoubleAuctionEnv(Exchg_Helper, MultiAgentEnv):
    metadata = {'render.modes': ['human']}

    def __init__(self, num_of_agents=2, init_cash=0, tick_size=1, tape_display_length=10, max_step=100, is_render=True):
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

        self.is_render = is_render

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
        self.action_space = self.act_space()

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

        self.seq_trades = []
        self.seq_order_in_book = []

        self.model_actions = None
        self.LOB_actions = None
        self.shuffled_actions = None

        self.t_step = 0

        self.reset_traders_acc()

        return self.reset_traders_agg_LOB()

    # actions is a list of actions from all agents (traders) at t step
    # each action is a list of (ID, type, side, size, price)
    def step(self, actions):

        self.model_actions = actions
        #self.print_table("Model actions:\n", actions)

        self.next_states, self.rewards, self.dones, self.infos = {}, {}, {}, {}
        self.agg_LOB = self.set_agg_LOB() # LOB state at t before processing LOB

        actions = self.set_actions(actions) # format actions from nn output to be acceptable by LOB
        self.LOB_actions = actions
        #self.print_table("Formatted actions acceptable by LOB:\n", actions)

        actions = self.rand_exec_seq(actions, None) # randomized traders execution sequence
        self.shuffled_actions = actions
        #self.print_table("Shuffled action queueing sequence for LOB executions:\n", actions)

        self.seq_trades, self.seq_order_in_book = self.do_actions(actions, self.t_step) # Begin processing LOB
        # self.mark_to_mkt() # mark to market

        # after processing LOB
        state_input = self.prep_next_state()
        self.next_states, self.rewards, self.dones, self.infos = self.set_step_outputs(state_input)

        self.render()
        self.t_step += 1

        return self.next_states, self.rewards, self.dones, self.infos

    # render
    def render(self):
        if self.is_render == True:
            #if self.t_step % 300 == 0:
            self._render()

    def _render(self):
        print('\n************************************************** t_step = {} **************************************************\n'.format(self.t_step))

        sum = 0
        step_sum = 0
        for agent in self.agents:
            sum += agent.acc.nav
            step_sum += agent.acc.step_nav
            # agent.acc.print_acc("")
            print(f'ID:{agent.ID}, step_nav:{agent.acc.step_nav}, nav:{agent.acc.nav}, cash:{agent.acc.cash}, order_costs:{agent.acc.order_costs}, qty_long:{agent.acc.qty_long}, qty_short:{agent.acc.qty_short}')
            # print(f'trade_recs:{agent.acc.trade_recs}')
            # print(f'LOB_recs:{agent.acc.LOB_recs}')

        print(f'sum:{sum}')
        print(f'step_sum:{step_sum}')
        if len(self.LOB.tape) > 0:
            last_price = self.LOB.tape[-1].get('price')
            print(f"last_price: {last_price}")

    def close(self):
        pass
