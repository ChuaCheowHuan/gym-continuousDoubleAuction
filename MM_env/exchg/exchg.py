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
        self.counter = 0
        self.max_step = max_step
        self.s_next = []
        self.rewards = []
        self.trades = []
        self.order_in_book = []

    # reset
    def reset(self):
        self.counter = 0

        return self.LOB_state()

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
            self.trades, self.order_in_book = self.place_order(type, side, size, price, trader)

        # after processing LOB
        self.LOB_STATE_NEXT = self.LOB_state() # LOB state at t+1 after processing LOB
        state_diff = self.state_diff(self.LOB_STATE, self.LOB_STATE_NEXT)
        self.s_next = state_diff

        # prepare rewards for all agents
        # reward = nav@t+1 - nav@t
        self.rewards = self.reward()

        # set dones for all agents
        self.counter += 1
        dones = 0
        if self.counter > self.max_step-1:
            dones = 1

        # set infos for all agents
        infos = None

        return self.s_next, self.rewards, dones, infos

    # reward per t step
    def reward(self):
        rewards = []
        for trader in self.agents:
            prev_nav = trader.nav
            trader.nav = trader.cal_nav() # new nav
            reward = trader.nav - prev_nav
            rewards.append({'ID': trader.ID, 'reward': reward})

        return rewards

    # render
    def render(self):
        print('\nLOB:\n', self.LOB)
        #print('\ntrades:\n', self.trades)
        #print('\norder_in_book\n:', self.order_in_book)
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

        return (bid_price_list, bid_size_list, ask_price_list, ask_size_list)

    def state_diff(self, LOB_state, LOB_state_next):
        state_diff_list = []
        for (state_row, state_row_next) in zip(LOB_state, LOB_state_next):
            state_diff_list.append(state_row_next - state_row)

        return state_diff_list

    # take or execute action
    def place_order(self, type, side, size, price, trader):
        trades, order_in_book = [],[]

        # begin processing LOB
        if(side == None): # do nothing to LOB
            return trades, order_in_book # do nothing to LOB
        # normal execution
        elif trader.order_approved(trader.cash, size, price):
            order = trader.create_order(type, side, size, price)
            trades, order_in_book = self.LOB.process_order(order, False, False)

            if trades == []:
                trader.update_cash_on_hold(order_in_book) # if there's any unfilled
            else:
                for trade in trades:
                    trade_val = trade.get('price') * trade.get('quantity')
                    # init_party is not counter_party
                    if trade.get('counter_party').get('ID') != trade.get('init_party').get('ID'):
                        for counter_party in self.agents: # search for counter_party
                            if counter_party.ID == trade.get('counter_party').get('ID'):
                                if counter_party.net_position > 0: # long
                                    counter_party.update_val_counter_party(trade, 'counter_party', 'bid')
                                elif counter_party.net_position < 0: # short
                                    counter_party.update_val_counter_party(trade, 'counter_party', 'ask')
                                else: # neutral
                                    counter_party.cash_on_hold -= trade_val # reduce cash_on_hold
                                    counter_party.position_val += trade_val
                                counter_party.update_net_position(trade.get('counter_party').get('side'), trade.get('quantity'))
                                break
                        if trader.net_position > 0: # long
                            trader.update_val_init_party(trade, order_in_book, 'init_party', 'bid')
                        elif trader.net_position < 0: # short
                            trader.update_val_init_party(trade, order_in_book, 'init_party', 'ask')
                        else: # neutral
                            trade_val = trade.get('price') * trade.get('quantity')
                            trader.cash -= trade_val
                            trader.position_val += trade_val
                        trader.update_net_position(trade.get('init_party').get('side'), trade.get('quantity'))
                    else: # init_party is also counter_party
                        trader.cash_on_hold -= trade_val
                        trader.cash += trade_val
                trader.update_cash_on_hold(order_in_book) # if there's any unfilled
            return trades, order_in_book
        else: # not enough cash to place order
            print('Invalid order: order value > cash available.', trader.ID)
            return trades, order_in_book


#if __name__ == "__main__":
