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
            self.done_set.add(f'agent_{trader.ID}') # done_set is a set

        return dones

    def set_all_done(self, dones, truncateds):
        """
        Updates the 'dones' dictionary by setting the "__all__" key to 1 
        if all agents are done or the maximum episode step has been reached.

        Args:
            dones (dict): Dictionary indicating which agents are done.

        Returns:
            dict: Updated 'dones' dictionary.
        """
        # Check if all traders are done
        all_agents_done = len(self.done_set) == len(self.traders)
        
        # Check if max step has been reached
        episode_timed_out = self.t_step > self.max_step - 1

        # Set "__all__" to 1 if either condition is met
        # dones["__all__"] = 1 if all_agents_done or episode_timed_out else 0
        dones["__all__"] = 1 if all_agents_done else 0
        truncateds["__all__"] = 1 if episode_timed_out else 0

        return dones, truncateds