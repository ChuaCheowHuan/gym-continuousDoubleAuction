class Done_Helper(object):

    def set_done(self, terminateds, trader):
        """
        When trader is broke (NAV <= 0), he's done ;)

        Records the agent in `done_set` AND marks it terminated. The two used
        to be separate: this recorded bankruptcy and `set_all_done` then
        rebuilt the whole dictionary as all-`False`, so `terminateds[agent]`
        was `False` for every agent on every step no matter what `done_set`
        held. A bankrupt agent kept emitting transitions, kept accruing reward,
        and kept resting executable orders - and its module return, which is
        what champion promotion reads, was then dominated by a constant
        unrelated to its policy. That is doc/15 S2-4.

        Termination is decided and applied in the same call, which is also what
        settles the `done_set`-is-monotone worry: an agent is terminated at the
        moment its NAV is non-positive, so there is no later step at which a
        recovered agent could be terminated on a stale record. Once out it
        stays out for the episode, which is what RLlib's contract requires -
        an agent that has reported `terminated` must not reappear.

        Arguments:
            terminateds: A dictionary.
            trader: A trader object.

        Returns:
            terminateds: A dictionary.
        """
        agent = f'agent_{trader.ID}'
        if trader.acc.nav <= 0 and agent not in self.done_set:
            self.done_set.add(agent) # done_set is a set
            terminateds[agent] = True
            # Its orders outlive it otherwise - see the docstring.
            trader.cancel_all_orders(self.LOB)

        return terminateds

    def is_live(self, trader):
        """Whether this trader still takes part in the episode.

        `set_step_outputs` asks before building an agent's observation, reward
        and info, so a terminated agent stops being scored rather than merely
        being flagged.
        """
        return f'agent_{trader.ID}' not in self.done_set

    def set_all_done(self, terminateds):
        """
        Complete the per-agent `terminateds` and derive the two `__all__` keys.

        Args:
            terminateds (dict): Per-agent flags, already carrying `True` for
                any agent `set_done` terminated on this step.

        Returns:
            (dict, dict): `terminateds` and `truncateds`.
        """
        # Fill in the agents still live, without disturbing the `True`s
        # `set_done` put here - overwriting them is what made this a no-op.
        # Agents terminated on an *earlier* step are omitted entirely: RLlib
        # expects a terminated agent to stop appearing, and re-reporting it
        # would send a second terminal transition for the same agent.
        for agent in self.agents:
            terminateds.setdefault(agent, False)
        truncateds = {agent: False for agent in terminateds}

        # `self.agents` is the *currently active* set, as distinct from
        # `possible_agents`. RLlib's MultiAgentEnv draws that distinction and
        # this env never used to update either.
        self.agents = [agent for agent in self.agents
                       if agent not in self.done_set]

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

        terminateds["__all__"] = True if all_agents_done else False
        truncateds["__all__"] = True if episode_timed_out else False

        return terminateds, truncateds
