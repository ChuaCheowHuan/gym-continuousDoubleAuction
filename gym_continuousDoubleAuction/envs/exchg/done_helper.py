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

        # Check if max step has been reached.
        #
        # `t_step` is the 0-based index of the step being completed right now:
        # `step()` increments it *after* this runs, so the number of steps the
        # episode has taken is `t_step + 1`. Written that way rather than as a
        # comparison against `max_step - 1`, which is what made this off by one
        # - `t_step > max_step - 1` first held at `t_step == max_step`, i.e. on
        # the (max_step + 1)-th step, so every episode ran one step long and
        # TrainConfig.train_batch_size (`max_step * num_episodes_per_iter`)
        # understated the batch by one step per episode.
        episode_timed_out = self.t_step + 1 >= self.max_step

        # Set "__all__" to 1 if either condition is met
        # terminateds["__all__"] = 1 if all_agents_done or episode_timed_out else 0
        terminateds["__all__"] = True if all_agents_done else False
        truncateds["__all__"] = True if episode_timed_out else False

        return terminateds, truncateds