import numpy as np
import pandas as pd

import gymnasium as gym

import ray
from ray.rllib.env.multi_agent_env import MultiAgentEnv

from .orderbook.orderbook import OrderBook
from .exchg.exchg_helper import Exchg_Helper
from .agent.trader import Trader

from tabulate import tabulate

# The exchange environment
class continuousDoubleAuctionEnv(
    Exchg_Helper, 
    MultiAgentEnv):

    metadata = {'render.modes': ['human']}

    # def __init__(
    #         self, 
    #         num_of_agents=2, 
    #         init_cash=0, 
    #         tick_size=1, 
    #         tape_display_length=10, 
    #         max_step=100, 
    #         is_render=True):
    #     super(continuousDoubleAuctionEnv, self).__init__(
    #         init_cash, 
    #         tick_size, 
    #         tape_display_length)
    def __init__(self, config=None):
        # Handle config parameter for RLlib compatibility
        config = config or {}
        
        # Extract parameters from config with defaults
        self.num_of_agents = config.get("num_of_agents", 2)
        init_cash = config.get("init_cash", 0)
        tick_size = config.get("tick_size", 1)
        tape_display_length = config.get("tape_display_length", 10)
        self.max_step = config.get("max_step", 100)
        is_render = config.get("is_render", True)
        
        # Initialize parent classes
        super(continuousDoubleAuctionEnv, self).__init__(
            init_cash, 
            tick_size, 
            tape_display_length
        )

        self.next_states = {}
        self.rewards = {}
        self.terminateds = {}  # Changed from dones
        self.truncateds = {}   # New in Ray 2.4
        self.done_set = set()
        self.infos = {}

        # step when actions by all traders are executed, not tick time
        # within a step, multiple trades(ticks) could happened
        self.t_step = 0
        # self.max_step = max_step

        self.is_render = is_render

        # list of agents or traders
        self.traders = [Trader(ID, init_cash) for ID in range(0, self.num_of_agents)]

        # Updated agent naming to be consistent with new API
        self._agent_ids = set([f"agent_{i}" for i in range(self.num_of_agents)])
        self.agents = list(self._agent_ids)
        self.possible_agents = list(self._agent_ids)
       
        inf = float('inf')
        neg_inf = float('-inf')
        obs_row = 4
        obs_col = 10       
        self.observation_space = {f"agent_{i}": gym.spaces.Box(low=neg_inf, high=inf, shape=(obs_row * obs_col,), dtype=np.float32) for i in range(self.num_of_agents)}

        act_space = gym.spaces.Tuple((
            gym.spaces.Discrete(3),  # side
            gym.spaces.Discrete(4),  # type
            gym.spaces.Box(low=-1.0, high=1.0, shape=(1,), dtype=np.float32),   # mean
            gym.spaces.Box(low=0.0, high=1.0, shape=(1,), dtype=np.float32),    # sigma
            gym.spaces.Discrete(12),  # price
        ))         
        self.action_space = {f"agent_{i}": act_space for i in range(self.num_of_agents)}
    
    # def get_observation_space(self, agent_id):
    #     """
    #     observation space per agent:
    #         array([[ 1.,  0., -1.,  0.,  0.,  0.,  0.,  0.,  0.,  0.],
    #                 [-1., -4., -4.,  0.,  0.,  0.,  0.,  0.,  0.,  0.],
    #                 [ 0.,  0.,  0.,  0.,  0.,  0.,  0.,  0.,  0.,  0.],
    #                 [ 0.,  0.,  0.,  0.,  0.,  0.,  0.,  0.,  0.,  0.]])
    #     """
    #     inf = float('inf')
    #     neg_inf = float('-inf')
    #     obs_row = 4
    #     obs_col = 10
    
    #     if agent_id.startswith("agent_"):
    #         # return gym.spaces.Box(low=neg_inf, high=inf, shape=(obs_row, obs_col), dtype=np.float32)      
    #         return gym.spaces.Box(low=neg_inf, high=inf, shape=(obs_row * obs_col,), dtype=np.float32)      
    #     else:
    #         raise ValueError(f"bad agent id: {agent_id}!")
    
    # def get_action_space(self, agent_id):
    #     act_space = gym.spaces.Tuple((
    #         gym.spaces.Discrete(3),  # side
    #         gym.spaces.Discrete(4),  # type
    #         gym.spaces.Box(low=-1.0, high=1.0, shape=(1,), dtype=np.float32),   # mean
    #         gym.spaces.Box(low=0.0, high=1.0, shape=(1,), dtype=np.float32),    # sigma
    #         gym.spaces.Discrete(12),  # price
    #     ))        
    #     # Define action spaces for each agent type
    #     if agent_id.startswith("agent_"):
    #         # return act_space
    #         return gym.spaces.Discrete(3)
    #     else:
    #         raise ValueError(f"bad agent id: {agent_id}!")
                
    # Updated reset method to return proper format for new API
    def reset(self, *, seed=None, options=None):
        # Call parent reset if it exists
        if hasattr(super(), 'reset'):
            super().reset(seed=seed)

        self.LOB = OrderBook(1, self.tape_display_length) # new limit order book
        #self.LOB = OrderBook(0.25, self.tape_display_length) # new limit order book
        self.agg_LOB = {}
        self.agg_LOB_aft = {}

        self.next_states = {}
        self.rewards = {}
        self.terminateds = {}  # Changed from dones
        self.truncateds = {}   # New in Ray 2.4
        self.done_set = set()
        self.infos = {}

        self.seq_trades = []
        self.seq_order_in_book = []

        self.model_actions = None
        self.LOB_actions = None
        self.shuffled_actions = None

        self.t_step = 0

        self.reset_traders_acc()

        # Return observations and info dict (new format)
        observations = self.reset_traders_agg_LOB()
        infos = {agent_id: {} for agent_id in self._agent_ids}
        
        return observations, infos

    # # Updated step method to return 5 values: obs, rewards, terminated, truncated, infos
    # def step(self, actions):

    #     self.model_actions = actions
    #     #self.print_table("Model actions:\n", actions)

    #     self.next_states, self.rewards, self.terminateds, self.truncateds, self.infos = {}, {}, {}, {}, {}
    #     self.agg_LOB = self.set_agg_LOB() # LOB state at t before processing LOB

    #     actions = self.set_actions(actions) # format actions from nn output to be acceptable by LOB
    #     self.LOB_actions = actions
    #     #self.print_table("Formatted actions acceptable by LOB:\n", actions)

    #     actions = self.rand_exec_seq(actions, None) # randomized traders execution sequence
    #     self.shuffled_actions = actions
    #     #self.print_table("Shuffled action queueing sequence for LOB executions:\n", actions)

    #     self.seq_trades, self.seq_order_in_book = self.do_actions(actions) # Begin processing LOB
    #     self.mark_to_mkt() # mark to market

    #     # after processing LOB
    #     state_input = self.prep_next_state()
    #     self.next_states, self.rewards, self.terminateds, self.truncateds, self.infos = self.set_step_outputs(state_input)
    #     # self.next_states, self.rewards, self.terminateds, self.truncateds, self.infos = self.set_step_outputs_new_api(state_input)

    #     self.render()
    #     self.t_step += 1

    #     # Return 5 values as required by new API
    #     return self.next_states, self.rewards, self.terminateds, self.truncateds, self.infos

    # Updated step method to return 5 values: obs, rewards, terminated, truncated, infos
    def step(self, actions):

        self.model_actions = actions
        #self.print_table("Model actions:\n", actions)

        self.next_states, self.rewards, self.terminateds, self.truncateds, self.infos = {}, {}, {}, {}, {}
        # self.agg_LOB = self.set_agg_LOB() # LOB state at t before processing LOB

        # actions = self.set_actions(actions) # format actions from nn output to be acceptable by LOB
        # self.LOB_actions = actions
        # #self.print_table("Formatted actions acceptable by LOB:\n", actions)

        # actions = self.rand_exec_seq(actions, None) # randomized traders execution sequence
        # self.shuffled_actions = actions
        # #self.print_table("Shuffled action queueing sequence for LOB executions:\n", actions)

        # self.seq_trades, self.seq_order_in_book = self.do_actions(actions) # Begin processing LOB
        # self.mark_to_mkt() # mark to market

        # after processing LOB
        state_input = self.prep_next_state()
        self.next_states, self.rewards, self.terminateds, self.truncateds, self.infos = self.set_step_outputs(state_input)
        # self.next_states, self.rewards, self.terminateds, self.truncateds, self.infos = self.set_step_outputs_new_api(state_input)

        self.render()
        self.t_step += 1

        # Return 5 values as required by new API
        return self.next_states, self.rewards, self.terminateds, self.truncateds, self.infos

    # render
    def render(self):
        if self.is_render == True:
            #if self.t_step % 300 == 0:
            self._render()

    def _render(self):
        print('\n************************************************** t_step = {} **************************************************\n'.format(self.t_step))

        self.print_table("Model actions:\n", self.model_actions)
        self.print_table("Formatted actions acceptable by LOB:\n", self.LOB_actions)
        self.print_table("Shuffled action queueing sequence for LOB executions:\n", self.shuffled_actions)
        self.model_actions = None
        self.LOB_actions = None
        self.shuffled_actions = None

        #print('\nnext_states:\n', self.next_states)
        print('\nrewards:\n', self.rewards)
        print('\nterminateds:\n', self.terminateds)  # Updated from dones
        print('\ntruncateds:\n', self.truncateds)    # New
        print('\ninfos:\n', self.infos)

        self.print_table("\nagg LOB @ t-1\n", self.agg_LOB)
        self.print_table("\nagg LOB @ t\n", self.agg_LOB_aft)

        print('\nLOB:\n', self.LOB) # print entire LOB with tape

        self.print_trades_all_seq(self.seq_trades)
        self.seq_trades = []
        self.print_order_in_book_all_seq(self.seq_order_in_book)
        self.seq_order_in_book = []

        #print("mark_to_mkt profit@t:")
        #self.mark_to_mkt() # mark to market
        self.print_mark_to_mkt("mark_to_mkt profit@t:")

        self.print_accs("\nAccounts:\n")
        print('\ntotal_sys_profit = {}; total_sys_nav = {}\n'.format(self.total_sys_profit(), self.total_sys_nav()))

    def close(self):
        pass