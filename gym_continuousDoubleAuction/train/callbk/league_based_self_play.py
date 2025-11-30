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
    when they exceed a performance threshold.
    
    **FIXED**: Properly implements league-based matchmaking so trainable policies
               actually face historical opponents (not just each other).
    """
    
    def __init__(self, return_threshold=None, relative_improvement=0.15, check_every_n_iters=5, 
                 league_opponent_prob=0.7):
        """
        Initialize the minimal league callback with support for relative thresholds.
        
        IMPORTANT: For zero-sum trading environments where returns are typically NEGATIVE,
        use relative_improvement instead of absolute return_threshold.
        
        Args:
            return_threshold: (Optional) Absolute episode return threshold. 
                            Use this ONLY if returns are positive (e.g., >100).
                            Set to None to use relative_improvement instead.
                            
            relative_improvement: Percentage improvement required over baseline to add to league.
                                Example: 0.15 means agent must be 15% better than average.
                                - For negative returns: baseline=-100 → threshold=-85 (15% less negative)
                                - For positive returns: baseline=100 → threshold=115 (15% more positive)
                                Default: 0.15 (15% improvement)
                                
            check_every_n_iters: Check for league updates every N training iterations.
                               Lower = more frequent checks (but more overhead)
                               Higher = less frequent checks (but may miss good snapshots)
                               Default: 5
                               
            league_opponent_prob: Probability that the opponent is a league member (vs another trainable).
                                Higher = more play against historical snapshots
                                Lower = more co-evolution between trainables
                                Default: 0.7 (70% league opponents, 30% other trainables)
        
        Example usage:
            # For negative reward environments (recommended for trading)
            callback = MinimalLeagueCallback(relative_improvement=0.15)
            
            # For positive reward environments
            callback = MinimalLeagueCallback(return_threshold=100.0)
            
            # More aggressive league-based (90% historical opponents)
            callback = MinimalLeagueCallback(league_opponent_prob=0.9)
        """
        super().__init__()
        
        # Determine which threshold mode to use
        if return_threshold is None:
            # Use relative threshold (recommended for zero-sum games)
            self.use_relative_threshold = True
            self.relative_improvement = relative_improvement
            self.return_threshold = None
            print(f"League callback: Using RELATIVE threshold ({relative_improvement*100:.0f}% improvement)")
        else:
            # Use absolute threshold (legacy mode)
            self.use_relative_threshold = False
            self.return_threshold = return_threshold
            self.relative_improvement = None
            print(f"League callback: Using ABSOLUTE threshold ({return_threshold})")
        
        self.check_every_n_iters = check_every_n_iters
        self.league_opponent_prob = league_opponent_prob
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
        """Callback run right after an Episode has been started.

        This method gets called after a SingleAgentEpisode or MultiAgentEpisode instance
        has been reset with a call to `env.reset()` by the EnvRunner.

        1) Single-/MultiAgentEpisode created: `on_episode_created()` is called.
        2) Respective sub-environment (gym.Env) is `reset()`.
        3) Single-/MultiAgentEpisode starts: This callback is called.
        4) Stepping through sub-environment/episode commences.

        Args:
            episode: The just started (after `env.reset()`) SingleAgentEpisode or
                MultiAgentEpisode object.
            env_runner: Reference to the EnvRunner running the env and episode.
            metrics_logger: The MetricsLogger object inside the `env_runner`. Can be
                used to log custom metrics during env/episode stepping.
            env: The gym.Env or gym.vector.Env object running the started episode.
            env_index: The index of the sub-environment that is about to be reset
                (within the vector of sub-environments of the BaseEnv).
            rl_module: The RLModule used to compute actions for stepping the env. In
                single-agent mode, this is a simple RLModule, in multi-agent mode, this
                is a MultiRLModule.
            kwargs: Forward compatibility placeholder.
        """
        # print(f'on_episode_start:{episode}')
        
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
        """Called on each episode step (after the action(s) has/have been logged).

        Note that on the new API stack, this callback is also called after the final
        step of an episode, meaning when terminated/truncated are returned as True
        from the `env.step()` call, but is still provided with the non-numpy'ized
        episode object (meaning the data has NOT been converted to numpy arrays yet).

        The exact time of the call of this callback is after `env.step([action])` and
        also after the results of this step (observation, reward, terminated, truncated,
        infos) have been logged to the given `episode` object.

        Args:
            episode: The just stepped SingleAgentEpisode or MultiAgentEpisode object
                (after `env.step()` and after returned obs, rewards, etc.. have been
                logged to the episode object).
            env_runner: Reference to the EnvRunner running the env and episode.
            metrics_logger: The MetricsLogger object inside the `env_runner`. Can be
                used to log custom metrics during env/episode stepping.
            env: The gym.Env or gym.vector.Env object running the started episode.
            env_index: The index of the sub-environment that has just been stepped.
            rl_module: The RLModule used to compute actions for stepping the env. In
                single-agent mode, this is a simple RLModule, in multi-agent mode, this
                is a MultiRLModule.
            kwargs: Forward compatibility placeholder.
        """
        # print(f'on_episode_step:{episode}')

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

        # print(f'on_episode_end:{episode}')

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

        # # Load later somewhere else when charting is required.
        
    def on_train_result(self, *, algorithm, metrics_logger=None, result, **kwargs):
        """
        Called after each training iteration.
        
        Checks if any trainable policy has exceeded the performance threshold,
        and if so, creates a frozen snapshot and adds it to the league.
        
        For zero-sum trading environments where returns are NEGATIVE, this uses
        relative performance comparison instead of absolute thresholds.
        """
        
        # Only check every N iterations to avoid too frequent league updates
        if algorithm.iteration % self.check_every_n_iters != 0:
            return
        
        # STEP 1: Initialize trainable policies
        if not self._initialize_trainable_policies(algorithm):
            return

        # STEP 2: Extract agent performance metrics
        agent_returns = self._get_agent_returns(result, algorithm)
        if not agent_returns:
            return

        agent_navs = self._get_agent_navs(result, algorithm)
        
        # STEP 3: Calculate performance threshold
        threshold = self._calculate_threshold(agent_returns)
        if threshold is None:
            return

        # STEP 4 & 5: Evaluate each trainable policy and update league
        self._evaluate_and_update_league(algorithm, agent_returns, threshold, agent_navs)
        
        # STEP 6: Add league statistics to results for logging
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
        """Extract agent performance metrics from training results."""
        env_runner_results = result.get(ENV_RUNNER_RESULTS, {})
        agent_returns = env_runner_results.get('agent_episode_returns_mean', {})
        
        if not agent_returns:
            print(f"Iter={algorithm.iteration}: No agent returns found in results")
            return None
        
        # Store returns for tracking
        self.agent_returns = agent_returns
        
        print(f"\n{'='*80}")
        print(f"Iteration {algorithm.iteration} - League Evaluation")
        print(f"{'='*80}")
        print(f"Agent returns: {agent_returns}")
        return agent_returns

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
        # Returns: {'agent_0': 5000000.0, 'agent_1': -2000000.0, ...}

    def _calculate_threshold(self, agent_returns):
        """Calculate performance threshold based on configured mode."""
        if self.use_relative_threshold:
            return self._calculate_relative_threshold(agent_returns)
        else:
            print(f"\n--- Absolute Threshold Mode ---")
            print(f"Fixed threshold: {self.return_threshold:.2f}")
            return self.return_threshold

    def _calculate_relative_threshold(self, agent_returns):
        """Calculate relative threshold based on baseline performance."""
        trainable_returns = [
            ret for agent_id, ret in agent_returns.items()
            if agent_id.replace('agent_', 'policy_') in self.trainable_policies
        ]
        
        if not trainable_returns:
            print("No trainable agent returns found")
            return None
        
        # Use mean as baseline
        baseline = np.mean(trainable_returns)
        
        if baseline < 0:
            # Negative returns: reduce magnitude by improvement percentage
            threshold = baseline * (1 - self.relative_improvement)
        else:
            # Positive returns: increase by improvement percentage
            threshold = baseline * (1 + self.relative_improvement)
        
        print(f"\n--- Relative Threshold Mode ---")
        print(f"Baseline (mean of trainable): {baseline:.2f}")
        print(f"Required improvement: {self.relative_improvement*100:.0f}%")
        print(f"Calculated threshold: {threshold:.2f}")
        
        if baseline < 0:
            improvement_needed = baseline - threshold
            print(f"  → Agents must achieve at least {improvement_needed:.2f} less loss")
            print(f"  → Example: {threshold:.2f} or better (less negative)")
        else:
            improvement_needed = threshold - baseline
            print(f"  → Agents must achieve at least {improvement_needed:.2f} more reward")
            print(f"  → Example: {threshold:.2f} or better")
            
        return threshold

    def _evaluate_and_update_league(self, algorithm, agent_returns, threshold, agent_navs):
        """Evaluate policies and add to league if they qualify."""
        print(f"\n--- Policy Evaluation ---")
        
        for agent_id, mean_return in agent_returns.items():
            policy_id = agent_id.replace('agent_', 'policy_')
            
            if policy_id not in self.trainable_policies:
                continue
            
            qualifies = self._policy_qualifies_for_league(agent_id, mean_return, threshold, agent_navs)

            if qualifies:                
                self._add_policy_to_league(algorithm, policy_id, mean_return)

            self._print_policy_evaluation(policy_id, mean_return, threshold, agent_navs, qualifies)

    def _policy_qualifies_for_league(self, agent_id, mean_return, threshold, agent_navs):
        """Check if a policy meets all criteria for league admission."""
        START_CAP = 1000000
        return (
            mean_return > threshold and 
            agent_navs.get(agent_id, 0) > START_CAP
        )

    def _print_policy_evaluation(self, policy_id, mean_return, threshold, agent_navs, qualifies):
        """Format policy evaluation metrics for display."""
        diff = mean_return - threshold
        diff_pct = (diff / abs(threshold) * 100) if threshold != 0 else 0
        status = "✓ EXCEEDS THRESHOLD AND NAV > START_CAP" if qualifies else "✗ below threshold or NAV < START_CAP"
        
        agent_id = policy_id.replace('policy_', 'agent_')
        nav = agent_navs.get(agent_id, 0)
        
        print(
            f"{policy_id}: {mean_return:>8.2f} | "
            f"threshold: {threshold:>8.2f} | "
            f"diff: {diff:>+8.2f} ({diff_pct:>+6.1f}%) | "
            f"NAV: {nav:>12.2f} | "  # Add NAV to output
            f"{status}"
        )

    def _add_policy_to_league(self, algorithm, policy_id, mean_return):
        """Create a frozen snapshot of the policy and add it to the league."""
        print(f"\n  → {policy_id} qualifies for league!")
        
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
            if (episode_seed + agent_num) % 2 == 0:
                # This agent is a trainable policy
                policy = rng.choice(trainable_list)
                return policy
            else:
                # This agent is an opponent (league or trainable)
                if league_list and rng.random() < league_opponent_prob:
                    # Play against historical league opponent
                    opponent = rng.choice(league_list)
                    matching_stats[("trainable", opponent)] += 1
                    return opponent
                else:
                    # Play against another trainable (co-evolution)
                    opponent = rng.choice(trainable_list)
                    matching_stats[("trainable", "trainable")] += 1
                    return opponent
        
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
