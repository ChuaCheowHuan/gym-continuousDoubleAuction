class Done_Helper(object):

    def set_done(self, dones, trader):
        if trader.acc.nav <= 0: # when trader is broke, he's done ;)
            dones[trader.ID] = 1
            self.done_set.add(trader.ID) # done_set is a set while done is a dictionary
        else:
            dones[trader.ID] = 0
        return dones

    def set_all_done(self, dones):
        dones["__all__"] = len(self.done_set) == len(self.agents) # set to 1 if length are equal
        if self.t_step > self.max_step-1:
            dones["__all__"] = 1 # set to 1 if episode is completed
        return dones
