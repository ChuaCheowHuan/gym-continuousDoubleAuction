"""
Minimal League-Based Self-Play Callback (FIXED VERSION)

A simplified league-based self-play implementation for multi-agent trading environment.
Periodically freezes top-performing policies and adds them to a league of opponents.

FIXED: Now properly implements league-based matchmaking where trainable policies
       actually play against historical snapshots (the original version was broken).
"""

import json
import pprint
import pickle
import os
import numpy as np

from collections import defaultdict

from ray.rllib.callbacks.callbacks import RLlibCallback
from ray.rllib.core.rl_module.rl_module import RLModuleSpec
from ray.rllib.utils.metrics import ENV_RUNNER_RESULTS


class LeagueBasedSelfPlayCallback(RLlibCallback):
    """
    Minimal league-based self-play callback for multi-agent environments.
    
    Tracks performance of trainable policies and freezes snapshots as league opponents
    when they achieve the maximum episode mean return among trainable policies.
    
    **FIXED**: Properly implements league-based matchmaking so trainable policies
               actually face historical opponents (not just each other).
    """
    
    def __init__(self, check_every_n_iters=5, league_opponent_prob=0.7):
        """
        Initialize the minimal league callback.
        
        League membership condition:
        - Policy must be trainable
        - Policy must have the maximum episode mean return among ALL trainable policies
        
        Args:
            check_every_n_iters: Check for league updates every N training iterations.
                               Lower = more frequent checks (but more overhead)
                               Higher = less frequent checks (but may miss good snapshots)
                               Default: 5
                               
            league_opponent_prob: Probability that the opponent is a league member (vs another trainable).
                                Higher = more play against historical snapshots
                                Lower = more co-evolution between trainables
                                Default: 0.7 (70% league opponents, 30% other trainables)
        
        Example usage:
            # Standard configuration
            callback = LeagueBasedSelfPlayCallback(check_every_n_iters=5)
            
            # More aggressive league-based (90% historical opponents)
            callback = LeagueBasedSelfPlayCallback(league_opponent_prob=0.9)
        """
        super().__init__()
        
        self.check_every_n_iters = check_every_n_iters
        self.league_opponent_prob = league_opponent_prob
        print(f"League callback: Adding policy with MAX return among trainables")
        print(f"League opponent probability: {league_opponent_prob*100:.0f}%")
        
        # Track which policies are actively training vs frozen in league
        self.trainable_policies = set()  # Will be populated from config
        self.league_opponents = []  # List of frozen policy snapshot names
        
        # Track performance stats
        self.agent_returns = {}  # Current iteration's returns
        self.league_size = 0     # Total number of league opponents
        
        # Matchup statistics (for debugging/analysis)
        self._matching_stats = defaultdict(int)

    def on_episode_start(
        self,
        *,
        episode,
        env_runner,
        metrics_logger,
        env,
        env_index,
        rl_module,
        **kwargs,
    ) -> None:
        """Callback run right after an Episode has been started."""
        self.ID = episode.id_
        self.store = []

    def on_episode_step(
        self,
        *,
        episode,
        env_runner,
        metrics_logger,
        env,
        env_index,
        rl_module,
        **kwargs,
    ) -> None:
        """Called on each episode step (after the action(s) has/have been logged)."""
        self.ID = episode.id_
        last_obs = episode.get_observations(-1)
        last_act = episode.get_actions(-1)
        last_reward = episode.get_rewards(-1)
        last_info = episode.get_infos(-1)
        step_data = {
            'episode_id': self.ID,
            'obs': last_obs,
            'act': last_act,
            'reward': last_reward,
            'info': last_info, 
        }
        self.store.append(step_data)

    def on_episode_end(
        self,
        *,
        episode,
        env_runner,
        metrics_logger,
        env,
        env_index,
        rl_module,
        **kwargs,
    ) -> None:
        """Called when an episode ends."""
        # Extract final NAV from last step's infos
        last_infos = episode.get_infos(-1)
    
        # Log NAV for each agent as custom metrics
        for agent_id, info in last_infos.items():
            if 'NAV' in info:
                nav_value = float(info['NAV'])  # Convert from string
                # Log to metrics_logger for aggregation
                metrics_logger.log_value(
                    f"{agent_id}_final_nav", 
                    nav_value,
                    reduce="mean"  # Will average across episodes
                )

        os.makedirs('episode_data', exist_ok=True)
        # Save the data
        with open('episode_data/' + str(episode.id_) + '.pkl', 'wb') as f:
            pickle.dump(self.store, f)
        
    def on_train_result(self, *, algorithm, metrics_logger=None, result, **kwargs):
        """
        Called after each training iteration.
        
        Checks if any trainable policy has the maximum episode mean return,
        and if so, creates a frozen snapshot and adds it to the league.
        """
        
        # Only check every N iterations to avoid too frequent league updates
        if algorithm.iteration % self.check_every_n_iters != 0:
            return
        
        # STEP 1: Initialize trainable policies
        if not self._initialize_trainable_policies(algorithm):
            return

        # STEP 2: Extract agent performance metrics and aggregate by policy
        policy_returns = self._get_agent_returns(result, algorithm)
        if not policy_returns:
            return

        agent_navs = self._get_agent_navs(result, algorithm)
        
        # STEP 3: Find the trainable policy with maximum return
        max_trainable_return, max_trainable_policy = self._find_max_trainable_policy(policy_returns)
        if max_trainable_policy is None:
            return

        # STEP 4: Add the max policy to league and print evaluation
        self._evaluate_and_update_league(algorithm, policy_returns, agent_navs, 
                                        max_trainable_return, max_trainable_policy)
        
        # STEP 5: Add league statistics to results for logging
        result['league_size'] = self.league_size
        
        print(f"\n{'='*80}\n")

    def _initialize_trainable_policies(self, algorithm):
        """Initialize trainable policies from algorithm config if not already done."""
        if not self.trainable_policies:
            if hasattr(algorithm.config, 'policies_to_train'):
                self.trainable_policies = set(algorithm.config.policies_to_train)
                print(f"Trainable policies initialized: {self.trainable_policies}")
            else:
                print("Warning: Could not get policies_to_train from config")
                return False
        return True

    def _get_agent_returns(self, result, algorithm):
        """Extract agent performance metrics and aggregate by policy."""
        env_runner_results = result.get(ENV_RUNNER_RESULTS, {})
        agent_returns = env_runner_results.get('agent_episode_returns_mean', {})
        
        if not agent_returns:
            print(f"Iter={algorithm.iteration}: No agent returns found in results")
            return None
        
        # Store raw agent returns for reference
        self.agent_returns = agent_returns
        
        # Aggregate returns by policy
        policy_returns = self._aggregate_returns_by_policy(result, algorithm)
        
        print(f"\n{'='*80}")
        print(f"Iteration {algorithm.iteration} - League Evaluation")
        print(f"{'='*80}")
        print(f"Agent returns: {agent_returns}")
        print(f"Policy returns (aggregated): {policy_returns}")
        
        return policy_returns

    def _get_agent_navs(self, result, algorithm):
        """Extract final NAV metrics from training results."""
        env_runner_results = result.get(ENV_RUNNER_RESULTS, {})
        
        agent_navs = {}
        for agent_id in self.trainable_policies:
            # Map policy_0 -> agent_0
            agent_key = agent_id.replace('policy_', 'agent_')
            nav_key = f"{agent_key}_final_nav"
            
            if nav_key in env_runner_results:
                agent_navs[agent_key] = env_runner_results[nav_key]
        
        return agent_navs

    def _aggregate_returns_by_policy(self, result, algorithm):
        """
        Aggregate agent returns by their assigned policy.
        
        Multiple agents can use the same policy, so we need to aggregate their returns
        to get the true policy performance.
        
        Since agent-to-policy mapping is dynamic (determined by policy_mapping_fn),
        we need to track actual mappings from episodes.
        
        Args:
            result: Training result dictionary
            algorithm: The RLlib algorithm instance
            
        Returns:
            Dict mapping policy_id to mean return across all agents using that policy
        """
        # RLlib tracks policy returns directly in the metrics
        # Look for 'module_episode_returns_mean' which groups by policy/module
        env_runner_results = result.get(ENV_RUNNER_RESULTS, {})
        
        # Try to get policy-level returns directly
        policy_returns = env_runner_results.get('module_episode_returns_mean', {})
        
        if policy_returns:
            print(f"Using direct policy returns from module_episode_returns_mean")
            return policy_returns
        
        # Fallback: If direct policy returns aren't available, we need to track
        # the mapping ourselves. This requires the policy_mapping_fn to be deterministic
        # or we need to log the actual mapping during episodes.
        print("Warning: module_episode_returns_mean not found in results")
        print("Available keys in env_runner_results:", list(env_runner_results.keys()))
        
        # As a last resort, return agent returns with a warning
        # The calling code should handle this case
        return {}

    def _find_max_trainable_policy(self, policy_returns):
        """
        Find the trainable policy with maximum episode mean return.
        
        Args:
            policy_returns: Dict mapping policy_id to aggregated mean return
        
        Returns:
            tuple: (max_return, max_policy_id) or (None, None) if no trainable policies found
        """
        # Filter to only trainable policies
        trainable_returns = {
            policy_id: return_val 
            for policy_id, return_val in policy_returns.items()
            if policy_id in self.trainable_policies
        }
        
        if not trainable_returns:
            print("No trainable policy returns found")
            return None, None
        
        # Find the policy with maximum return
        max_policy_id = max(trainable_returns, key=trainable_returns.get)
        max_return = trainable_returns[max_policy_id]
        
        print(f"\n--- Max Trainable Policy ---")
        print(f"Policy: {max_policy_id}")
        print(f"Return: {max_return:.2f}")
        
        return max_return, max_policy_id

    def _evaluate_and_update_league(self, algorithm, policy_returns, agent_navs, 
                                   max_trainable_return, max_trainable_policy):
        """Evaluate policies and add the max trainable policy to league."""
        print(f"\n--- Policy Evaluation ---")
        
        # Add the max policy to league
        self._add_policy_to_league(algorithm, max_trainable_policy, max_trainable_return)
        
        # Print evaluation for all trainable policies
        for policy_id, mean_return in policy_returns.items():
            if policy_id not in self.trainable_policies:
                continue
            
            # Only the max trainable policy qualifies
            qualifies = (policy_id == max_trainable_policy)
            self._print_policy_evaluation(policy_id, mean_return, agent_navs, 
                                         qualifies, max_trainable_return)

    def _print_policy_evaluation(self, policy_id, mean_return, agent_navs, 
                                qualifies, max_return):
        """Format policy evaluation metrics for display."""
        diff = mean_return - max_return
        
        is_max = abs(diff) < 1e-5
        max_str = " (MAX)" if is_max else ""
        
        status = "✓ ADDED TO LEAGUE" if qualifies else "✗ not max"
        
        agent_id = policy_id.replace('policy_', 'agent_')
        nav = agent_navs.get(agent_id, 0)
        
        print(
            f"{policy_id}: {mean_return:>8.2f}{max_str} | "
            f"diff from max: {diff:>+8.2f} | "
            f"NAV: {nav:>12.2f} | "
            f"{status}"
        )

    def _add_policy_to_league(self, algorithm, policy_id, mean_return):
        """Create a frozen snapshot of the policy and add it to the league."""
        print(f"\n  → {policy_id} qualifies for league (MAX return among trainables)!")
        
        league_id = f"league_{len(self.league_opponents)}"
        
        try:
            policy_module = algorithm.get_module(policy_id)
            
            algorithm.add_module(
                module_id=league_id,
                module_spec=RLModuleSpec.from_module(policy_module),
            )
            
            algorithm.set_state(
                {
                    "learner_group": {
                        "learner": {
                            "rl_module": {
                                league_id: policy_module.get_state(),
                            }
                        }
                    }
                }
            )
            
            self.league_opponents.append(league_id)
            self.league_size = len(self.league_opponents)
            
            print(f"  → League opponent '{league_id}' created successfully!")
            print(f"  → Current league size: {self.league_size}")
            print(f"  → Snapshot of {policy_id} with return {mean_return:.2f}")
            
            self._update_policy_mapping(algorithm)
            
        except Exception as e:
            print(f"  → ✗ Error creating league opponent: {e}")
            import traceback
            traceback.print_exc()

    def _update_policy_mapping(self, algorithm):
        """
        Update the policy mapping function to properly implement league-based self-play.
        
        PROPER LEAGUE-BASED IMPLEMENTATION (FIXED):
        - Ensures at least one trainable policy per match (no wasted compute)
        - Trainable policies actually face historical opponents (true league-based learning)
        - Configurable probability of facing league opponents vs other trainables
        
        This is the KEY FIX that makes this callback truly league-based!
        """
        
        trainable_list = list(self.trainable_policies)
        league_list = self.league_opponents.copy()
        
        if not trainable_list:
            print("Warning: No trainable policies available for mapping")
            return
        
        # Capture config values for closure
        league_opponent_prob = self.league_opponent_prob if league_list else 0.0
        matching_stats = self._matching_stats
        
        def policy_mapping_fn(agent_id, episode, **kwargs):
            """
            Proper league-based matchmaking for n agents, k trainable.
            
            Strategy:
            - Each agent has a probability to be trainable or opponent
            - Ensures at least some agents are trainable per episode
            - Opponents are sampled from league (historical) or trainable (co-evolution)
            """
            
            # Extract agent number from agent_id string (e.g., "agent_0" -> 0)
            agent_num = int(agent_id.split('_')[-1])
            
            # Use episode hash to ensure diverse matchmaking across episodes
            episode_seed = abs(hash(episode.id_))
            
            # Deterministic pseudo-random based on episode + agent
            # This ensures consistent matchmaking within an episode
            rng_seed = (episode_seed + agent_num) % (2**32)
            rng = np.random.RandomState(rng_seed)
            
            # Decide if this agent should be a trainable or opponent
            # Use agent_num to ensure different agents get different roles
            selected_policy = None
            
            if (episode_seed + agent_num) % 2 == 0:
                # This agent is a trainable policy
                selected_policy = rng.choice(trainable_list)
            else:
                # This agent is an opponent (league or trainable)
                if league_list and rng.random() < league_opponent_prob:
                    # Play against historical league opponent
                    selected_policy = rng.choice(league_list)
                    matching_stats[("trainable", selected_policy)] += 1
                else:
                    # Play against another trainable (co-evolution)
                    selected_policy = rng.choice(trainable_list)
                    matching_stats[("trainable", "trainable")] += 1
            
            # Log the mapping so we can see who is playing against whom
            print(f"Policy Map: {agent_id} -> {selected_policy} (Ep: {episode.id_})")
            
            return selected_policy
        
        try:
            # Update policy mapping on all env runners
            algorithm.env_runner_group.foreach_env_runner(
                lambda env_runner: env_runner.config.multi_agent(
                    policy_mapping_fn=policy_mapping_fn,
                    policies_to_train=trainable_list,
                ),
                local_env_runner=True,
            )
            
            # Update learner group
            algorithm.learner_group.foreach_learner(
                func=lambda learner: learner.config.multi_agent(
                    policies_to_train=trainable_list,
                ),
                timeout_seconds=0.0,
            )
            
            print(f"  -> Policy mapping updated successfully")
            print(f"  -> League opponent probability: {league_opponent_prob*100:.0f}%")
            if league_list:
                print(f"  -> Trainables will now play against: {league_list}")
            
        except Exception as e:
            print(f"  -> Warning: Could not update policy mapping: {e}")
    
    def get_league_stats(self):
        """
        Get current league statistics.
        
        Returns:
            dict with league size and opponent names
        """
        return {
            'league_size': self.league_size,
            'num_trainable': len(self.trainable_policies),
            'num_frozen': len(self.league_opponents),
            'trainable_policies': list(self.trainable_policies),
            'league_opponents': self.league_opponents.copy(),
            'matching_stats': dict(self._matching_stats),
        }