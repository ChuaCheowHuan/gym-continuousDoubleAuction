class Done_Helper(object):

    def set_done(self, terminateds, trader):
        """
        When trader is broke (NAV <= 0), he's done ;)
        Add trader ID to set dones_set.

        Arguments:
            terminateds: A dictionary.
            trader: A trader object.

        Returns:
            terminateds: A dictionary.
        """
        if trader.acc.nav <= 0:
            self.done_set.add(f'agent_{trader.ID}') # done_set is a set

        return terminateds

    def set_all_done(self, terminateds):
        """
        Updates the 'terminateds' dictionary by setting the "__all__" key to 1 
        if all agents are done or the maximum episode step has been reached.

        Args:
            terminateds (dict): Dictionary indicating which agents are done.

        Returns:
            dict: Updated 'terminateds' dictionary.
        """
        
        terminateds = {agent: False for agent in self.agents}
        truncateds = {agent: False for agent in self.agents}

        # Check if all traders are done
        all_agents_done = len(self.done_set) == len(self.traders)
        
        # Check if max step has been reached
        episode_timed_out = self.t_step > self.max_step - 1

        # Set "__all__" to 1 if either condition is met
        # terminateds["__all__"] = 1 if all_agents_done or episode_timed_out else 0
        terminateds["__all__"] = 1 if all_agents_done else 0
        truncateds["__all__"] = 1 if episode_timed_out else 0

        return terminateds, truncateds