import numpy as np

class State_Helper(object):

    # reset traders LOB observations/states
    def reset_traders_agg_LOB(self):
        states = {}
        for trader in self.agents:
            states[trader.ID] = self.set_agg_LOB()
        return states

    def prep_next_state(self):
        self.agg_LOB_aft = self.set_agg_LOB() # LOB state at t+1 after processing LOB

        # ********** state_diff should be used in obs preprocessing, not here **********
        #state_diff = self.state_diff(self.agg_LOB, self.agg_LOB_aft)
        state_diff = self.agg_LOB_aft

        return state_diff

    def set_next_state(self, next_states, trader, state_input):
        next_states[trader.ID] = state_input
        return next_states

    # price_map is an OrderTree object (SortedDict object)
    # SortedDict object has key & value
    # key is price, value is an OrderList object
    def set_agg_LOB(self):
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
        return [bid_size_list, bid_price_list, ask_size_list, ask_price_list] # list of np.arrays

    # state_diff should be used in obs preprocessing if needed
    def state_diff(self, agg_LOB, agg_LOB_aft):
        state_diff = []
        #state_diff = np.array()
        for (state_row, next_state_row) in zip(agg_LOB, agg_LOB_aft):
            diff = next_state_row - state_row
            list_diff = list(diff)
            state_diff.append(list_diff)
        state_diff = np.array(state_diff)

        print('state_diff.shape:', state_diff.shape)

        return state_diff
