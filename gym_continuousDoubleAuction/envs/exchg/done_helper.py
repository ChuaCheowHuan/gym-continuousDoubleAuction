class Done_Helper(object):

    def set_done(self, dones, trader):
        """
        When trader is broke (NAV <= 0), he's done ;)
        Add trader ID to set dones_set.

        Arguments:
            dones: A dictionary.
            trader: A trader object.

        Returns:
            dones: A dictionary.
        """

        if trader.acc.nav <= 0:
            self.done_set.add(trader.ID) # done_set is a set

        return dones

    def set_all_done(self, dones):
        """
        Set dones["__all__"] to 1 if episode is completed

        Arguments:
            dones: A dictionary.

        Returns:
            dones: A dictionary.
        """

        dones["__all__"] = len(self.done_set) == len(self.traders) # set dones["__all__"] to 1 if length are equal
        if self.t_step > self.max_step-1:
            dones["__all__"] = 1

        return dones
