import numpy as np

from .orderbook import OrderBook
from .trader import Trader

# The exchange environment
class Exchg(object):
    def __init__(self, num_of_agents=2, init_cash=100, tape_display_length=10, max_step=100):
        self.LOB = OrderBook(0.25, tape_display_length) # limit order book
        self.LOB_STATE = {}
        self.LOB_STATE_NEXT = {}
        # list of agents or traders
        self.agents = [Trader(ID, init_cash) for ID in range(0, num_of_agents)]
        # step when actions by all traders are executed, not tick time
        # within a step, multiple trades(ticks) could happened
        self.t_step = 0
        self.max_step = max_step
        self.s_next = []
        self.rewards = []
        self.trades = [] # a trade between init_party & counter_party
        self.order_in_book = [] # unfilled orders goes to LOB

    # reset
    def reset(self, tape_display_length):
        self.LOB = OrderBook(0.25, tape_display_length) # new limit order book
        self.LOB_STATE = {}
        self.LOB_STATE_NEXT = {}
        self.t_step = 0
        self.s_next = []
        self.rewards = []
        self.trades = [] # a trade between init_party & counter_party
        self.order_in_book = [] # unfilled orders goes to LOB
        return self.LOB_state()

    # update acc for all traders with last price in most recent entry of tape
    def mark_to_mkt(self):
        if len(self.LOB.tape) > 0:
            mkt_price = self.LOB.tape[-1].get('price')
            for trader in self.agents:
                trader.acc.mark_to_mkt(trader.ID, mkt_price)
        return 0

    # actions is a list of actions from all agents (traders) at t step
    # each action is a list of (type, side, size, price)
    def step(self, actions):
        self.LOB_STATE = self.LOB_state() # LOB state at t before processing LOB
        # Begin processing LOB
        # process actions for all agents
        for i, action in enumerate(actions):
            # use dict
            type = action.get("type")
            side = action.get("side")
            size = action.get("size")
            price = action.get("price")
            trader = self.agents[i]
            self.trades, self.order_in_book = trader.place_order(type, side, size, price, self.LOB, self.agents)
        self.mark_to_mkt() # mark to market
        # after processing LOB
        self.LOB_STATE_NEXT = self.LOB_state() # LOB state at t+1 after processing LOB
        state_diff = self.state_diff(self.LOB_STATE, self.LOB_STATE_NEXT)
        self.s_next = state_diff
        # prepare rewards for all agents
        self.rewards = self.reward()
        # set dones for all agents
        self.t_step += 1
        dones = 0
        if self.t_step > self.max_step-1:
            dones = 1
        # set infos for all agents
        infos = None
        return self.s_next, self.rewards, dones, infos

    # reward per t step
    # reward = nav@t+1 - nav@t
    def reward(self):
        rewards = []
        for trader in self.agents:
            reward = trader.acc.nav - trader.acc.prev_nav
            rewards.append({'ID': trader.ID, 'reward': reward})
        return rewards

    # render
    def render(self):
        print('\nLOB:\n', self.LOB)
        print('\nLOB_STATE:\n', self.LOB_STATE)
        print('\nLOB_STATE_NEXT:\n', self.LOB_STATE_NEXT)
        print('\nstate_diff:\n', self.s_next)
        print('\nrewards:\n', self.rewards)
        return 0

    # price_map is an OrderTree object (SortedDict object)
    # SortedDict object has key & value
    # key is price, value is an OrderList object
    def LOB_state(self):
        k_rows = 10
        bid_price_list = np.zeros(k_rows)
        bid_size_list = np.zeros(k_rows)
        ask_price_list = np.zeros(k_rows)
        ask_size_list = np.zeros(k_rows)

        # LOB
        if self.LOB.bids != None and len(self.LOB.bids) > 0:
            for k, set in enumerate(reversed(self.LOB.bids.price_map.items())):
                if k < k_rows:
                    bid_price_list[k] = set[0] # set[0] is price (key)
                    bid_size_list[k] = set[1].volume # set[1] is an OrderList object (value)
                else:
                    break

        if self.LOB.asks != None and len(self.LOB.asks) > 0:
            for k, set in enumerate(self.LOB.asks.price_map.items()):
                if k < k_rows:
                    ask_price_list[k] = -set[0]
                    ask_size_list[k] = -set[1].volume
                else:
                    break
        # tape
        if self.LOB.tape != None and len(self.LOB.tape) > 0:
            num = 0
            for entry in reversed(self.LOB.tape):
                if num < self.LOB.tape_display_length: # get last n entries
                    #tempfile.write(str(entry['quantity']) + " @ " + str(entry['price']) + " (" + str(entry['timestamp']) + ") " + str(entry['party1'][0]) + "/" + str(entry['party2'][0]) + "\n")
                    num += 1
                else:
                    break
        return (bid_size_list, bid_price_list, ask_size_list, ask_price_list)

    def state_diff(self, LOB_state, LOB_state_next):
        state_diff_list = []
        for (state_row, state_row_next) in zip(LOB_state, LOB_state_next):
            state_diff_list.append(state_row_next - state_row)
        return state_diff_list
