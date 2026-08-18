import logging

import numpy as np
import pandas as pd

import gymnasium as gym

from ray.rllib.env.multi_agent_env import MultiAgentEnv

from .orderbook.orderbook import OrderBook
from .exchg.exchg_helper import Exchg_Helper
from .agent.trader import Trader
from ..config_loader import env_default
from ..logging_setup import get_logger

from tabulate import tabulate

logger = get_logger(__name__)

# The exchange environment
class continuousDoubleAuctionEnv(
    Exchg_Helper, 
    MultiAgentEnv):

    metadata = {'render.modes': ['human']}

    def __init__(self, config=None):      
        # Handle config parameter for RLlib compatibility
        self.config = config or {}

        # Every key below falls back to config/env_defaults.json when the
        # caller omits it. There are no literal defaults here: a training run
        # supplies all of them from train_config.json via TrainConfig.env_config,
        # and a bare env picks up the standalone defaults from the JSON.
        self.num_of_agents = self._cfg("num_of_agents")
        init_cash = self._cfg("init_cash")
        tick_size = self._cfg("tick_size")
        tape_display_length = self._cfg("tape_display_length")
        self.max_step = self._cfg("max_step")
        is_render = self._cfg("is_render")
        self.n_hist = self._cfg("n_hist")

        # Order sizing, consumed by Action_Helper.
        min_size = self._cfg("min_size")
        mkt_max_size = self._cfg("mkt_max_size")
        limit_size_multiple = self._cfg("limit_size_multiple")

        # Reward coefficients, consumed by Reward_Helper.
        order_penalty = self._cfg("order_penalty")
        trade_penalty = self._cfg("trade_penalty")
        drawdown_penalty = self._cfg("drawdown_penalty")
        passive_bonus = self._cfg("passive_bonus")
        loss_multiplier = self._cfg("loss_multiplier")

        # Initialize parent classes
        super().__init__(
            init_cash,
            tick_size,
            tape_display_length,
            n_hist=self.n_hist,
            min_size=min_size,
            mkt_max_size=mkt_max_size,
            limit_size_multiple=limit_size_multiple,
            order_penalty=order_penalty,
            trade_penalty=trade_penalty,
            drawdown_penalty=drawdown_penalty,
            passive_bonus=passive_bonus,
            loss_multiplier=loss_multiplier,
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

        # Agent IDs. `agents` / `possible_agents` are built from a sorted list
        # rather than from the set, because iteration order of a set of strings
        # is not stable across processes (PYTHONHASHSEED). RLlib zips these
        # against per-agent spaces on the EnvRunners, so an unstable order can
        # silently mismatch agents to spaces in a multi-process run.
        agent_ids = [f"agent_{i}" for i in range(self.num_of_agents)]
        self._agent_ids = set(agent_ids)
        self.agents = list(agent_ids)
        self.possible_agents = list(agent_ids)

        # Each snapshot is self.snapshot_dim floats (book_rows * k_rows book
        # features + extra_dim market scalars, all from
        # config/tunable_constants.json -> observation_layout, and set on the
        # instance by State_Helper); n_hist of them are stacked into one flat
        # observation.
        #
        # NOTE: these are the *plural* attributes (`observation_spaces` /
        # `action_spaces`) that RLlib's new API stack reads. The singular
        # `observation_space` / `action_space` on MultiAgentEnv are marked
        # @OldAPIStack in Ray 2.56 and mean something different (the space of a
        # single agent, not a per-agent dict).
        self.observation_spaces = {
            agent_id: gym.spaces.Box(
                low=-np.inf,
                high=np.inf,
                shape=(self.n_hist * self.snapshot_dim,),
                dtype=np.float32
            ) for agent_id in agent_ids
        }

        # Updated action space to use the new Compact Flat structure
        self.action_spaces = self.act_space(self.num_of_agents)

    def _cfg(self, key):
        """One env config value, falling back to `config/env_defaults.json`.

        Written as an explicit membership test rather than `dict.get(key,
        default)` so the fallback is only looked up when it is actually needed,
        and so a missing key raises from the loader - naming the file and the
        keys it does define - instead of resolving to a literal written here.
        """
        return self.config[key] if key in self.config else env_default(key)

    def get_action_space(self, agent_id):
        """Action space for a single agent (not the per-agent dict)."""
        return self.action_spaces[agent_id]

    def get_observation_space(self, agent_id):
        """Observation space for a single agent (not the per-agent dict)."""
        return self.observation_spaces[agent_id]
        
    # Override from RLlib
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
        # Call parent reset if it exists.
        #
        # This is what seeds `self.np_random`, gymnasium's per-env Generator,
        # and it is the only thing the `seed` argument does. It used to do
        # nothing observable, because every random draw in the env went to the
        # global `np.random` instead: the price anchor here, order sizes in
        # `_set_size`, and the queueing order in `rand_exec_seq`. All three now
        # read `self.np_random`, so `reset(seed=...)` means what the Gymnasium
        # API says it means (doc/15 S3-5).
        #
        # `seed=None` deliberately does not re-seed - the contract is that an
        # env which already has a generator keeps its stream across resets, so
        # consecutive episodes differ.
        if hasattr(super(), 'reset'):
            super().reset(seed=seed)

        # Same tick the book was built with in Exchg_Helper, from the tick_size
        # config key. This used to be a literal 1, which disagreed with any
        # other configured tick_size - harmlessly, since OrderBook stores
        # tick_size without ever reading it, but there is no reason to keep a
        # second value here.
        self.LOB = OrderBook(self.tick_size, self.tape_display_length) # new limit order book
        self.agg_LOB = {}
        self.agg_LOB_raw = {}
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

        # Establish initial price anchor, from the seeded generator.
        low = self._cfg("initial_price_min")
        high = self._cfg("initial_price_max")
        self.last_price = float(self.np_random.integers(low, high + 1))

        self.reset_traders_acc()

        # Return observations and info dict (new format)
        observations = self.reset_traders_agg_LOB()
        # print(f'reset (observations): {observations}')

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



        self.agg_LOB = self.set_agg_LOB() # LOB state at t before processing LOB

        # print(actions)
        # {
        # 'agent_3': (np.int32(0), np.int32(3), array([0.7106466], dtype=float32), array([0.21718845], dtype=float32), np.int32(7)), 
        # 'agent_1': (np.int32(2), np.int32(1), array([-0.37776113], dtype=float32), array([0.45237976], dtype=float32), np.int32(11)), 
        # 'agent_0': (np.int32(2), np.int32(3), array([0.26284337], dtype=float32), array([0.6805017], dtype=float32), np.int32(4)), 
        # 'agent_2': (np.int32(0), np.int32(0), array([0.45744383], dtype=float32), array([0.19705606], dtype=float32), np.int32(7))
        # }

        actions = self.set_actions(actions) # format actions from nn output to be acceptable by LOB
        self.LOB_actions = actions
        #self.print_table("Formatted actions acceptable by LOB:\n", actions)

        actions = self.rand_exec_seq(actions, None) # randomized traders execution sequence
        self.shuffled_actions = actions
        #self.print_table("Shuffled action queueing sequence for LOB executions:\n", actions)

        self.seq_trades, self.seq_order_in_book = self.do_actions(actions) # Begin processing LOB
        self.mark_to_mkt() # mark to market



        # after processing LOB
        state_input = self.prep_next_state()
        self.next_states, self.rewards, self.terminateds, self.truncateds, self.infos = self.set_step_outputs(state_input)
        # self.next_states, self.rewards, self.terminateds, self.truncateds, self.infos = self.set_step_outputs_new_api(state_input)

        self.render()
        self.t_step += 1

        # print(f'step: self.terminateds {self.terminateds}')
        # print(f'step: self.truncateds {self.truncateds}')

        # Return 5 values as required by new API
        return self.next_states, self.rewards, self.terminateds, self.truncateds, self.infos

    # render
    def render(self):
        # Two gates, not one. `is_render` is the caller's intent; the DEBUG
        # check is whether the output has anywhere to go. `_render` builds
        # tabulate tables and pandas DataFrames of the whole book, the tape and
        # every account, on every step - none of which is worth constructing
        # for a logger that will drop it.
        if self.is_render == True and logger.isEnabledFor(logging.DEBUG):
            #if self.t_step % 300 == 0:
            self._render()

    def _render(self):
        logger.debug(
            '*'*50 + ' t_step = %s ' + '*'*50, self.t_step,
        )

        self.print_table("Model actions:\n", self.model_actions)
        self.print_table("Formatted actions acceptable by LOB:\n", self.LOB_actions)
        self.print_table("Shuffled action queueing sequence for LOB executions:\n", self.shuffled_actions)
        self.model_actions = None
        self.LOB_actions = None
        self.shuffled_actions = None

        logger.debug(
            'rewards:\n%s\nterminateds:\n%s\ntruncateds:\n%s\ninfos:\n%s',
            self.rewards, self.terminateds, self.truncateds, self.infos,
        )

        self.print_table("\nagg LOB @ t-1\n", self.agg_LOB)
        self.print_table("\nagg LOB @ t\n", self.agg_LOB_aft)

        logger.debug('LOB:\n%s', self.LOB)  # the entire LOB, with tape

        self.print_trades_all_seq(self.seq_trades)
        self.seq_trades = []
        self.print_order_in_book_all_seq(self.seq_order_in_book)
        self.seq_order_in_book = []

        #print("mark_to_mkt profit@t:")
        #self.mark_to_mkt() # mark to market
        self.print_mark_to_mkt("mark_to_mkt profit@t:")

        self.print_accs("\nAccounts:\n")
        logger.debug(
            'total_sys_profit = %s; total_sys_nav = %s',
            self.total_sys_profit(), self.total_sys_nav(),
        )

    def close(self):
        pass