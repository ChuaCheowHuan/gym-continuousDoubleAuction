"""
Minimal League-Based Self-Play Callback

A simplified league-based self-play implementation for multi-agent trading environment.
Periodically freezes top-performing policies and adds them to a league of opponents.
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


class MinimalLeagueCallback(RLlibCallback):
    """
    Minimal league-based self-play callback for multi-agent environments.
    
    Tracks performance of trainable policies and freezes snapshots as league opponents
    when they exceed a performance threshold.
    """
    
    def __init__(self, return_threshold=None, relative_improvement=0.15, check_every_n_iters=5):
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
        
        Example usage:
            # For negative reward environments (recommended for trading)
            callback = MinimalLeagueCallback(relative_improvement=0.15)
            
            # For positive reward environments
            callback = MinimalLeagueCallback(return_threshold=100.0)
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
        print(f'on_episode_start:{episode}')
        
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
        print(f'on_episode_step:{episode}')

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

        print(f'on_episode_end:{episode}')

        # last_obs = episode.get_observations(-1)
        # last_act = episode.get_actions(-1)
        # last_reward = episode.get_rewards(-1)
        # last_info = episode.get_infos(-1)
        # print(f'last_obs:{last_obs}')  
        # print(f'last_act:{last_act}')        
        # print(f'last_reward:{last_reward}')        
        # print(f'last_info:{last_info}')     

        # print(self.store)

        os.makedirs('episode_data', exist_ok=True)
        # Save the data
        # with open('episode_data_' + episode.id_ + '.json', 'w') as f:
        #     json.dump(self.store, f, indent=4)
        # Save the data
        with open('episode_data/' + str(episode.id_) + '.pkl', 'wb') as f:
            pickle.dump(self.store, f)

        # # Load later
        # with open('episode_data.pkl', 'rb') as f:
        #     loaded_store = pickle.load(f)

        self.store = None   

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
        
        # ===================================================================
        # STEP 1: Initialize trainable policies from algorithm config
        # ===================================================================
        # This happens once on first call to get which policies are being trained
        if not self.trainable_policies:
            if hasattr(algorithm.config, 'policies_to_train'):
                self.trainable_policies = set(algorithm.config.policies_to_train)
                print(f"Trainable policies initialized: {self.trainable_policies}")
            else:
                print("Warning: Could not get policies_to_train from config")
                return
        
        # ===================================================================
        # STEP 2: Extract agent performance metrics from training results
        # ===================================================================
        # Get the aggregated returns (mean over all episodes this iteration)
        env_runner_results = result.get(ENV_RUNNER_RESULTS, {})
        agent_returns = env_runner_results.get('agent_episode_returns_mean', {})
        
        if not agent_returns:
            print(f"Iter={algorithm.iteration}: No agent returns found in results")
            return
        
        # Store returns for tracking
        self.agent_returns = agent_returns
        
        print(f"\n{'='*80}")
        print(f"Iteration {algorithm.iteration} - League Evaluation")
        print(f"{'='*80}")
        print(f"Agent returns: {agent_returns}")
        
        # ===================================================================
        # STEP 3: Calculate performance threshold
        # ===================================================================
        # Two modes:
        # 1. Absolute threshold: Fixed value (legacy, for positive rewards)
        # 2. Relative threshold: Dynamic based on current performance (recommended)
        
        if self.use_relative_threshold:
            # ---------------------------------------------------------------
            # RELATIVE THRESHOLD CALCULATION
            # ---------------------------------------------------------------
            # Calculate baseline performance from all trainable agents
            # This is the "average" performance we expect
            
            trainable_returns = [
                ret for agent_id, ret in agent_returns.items()
                if agent_id.replace('agent_', 'policy_') in self.trainable_policies
            ]
            
            if not trainable_returns:
                print("No trainable agent returns found")
                return
            
            # Use mean as baseline (could also use median for robustness)
            baseline = np.mean(trainable_returns)
            
            # Calculate relative threshold
            # The key insight: For NEGATIVE numbers, "better" means "less negative"
            # 
            # Example with negative returns (trading environment):
            #   baseline = -100 (average loss)
            #   relative_improvement = 0.15 (require 15% better)
            #   
            #   For negative baseline:
            #     threshold = -100 * (1 - 0.15) = -100 * 0.85 = -85
            #     Agent needs return > -85 (i.e., less negative than -85)
            #     This means -80, -70, -60 all qualify (15% less negative)
            #
            # Example with positive returns (game-playing environment):
            #   baseline = 100 (average score)
            #   relative_improvement = 0.15
            #   
            #   For positive baseline:
            #     threshold = 100 * (1 + 0.15) = 100 * 1.15 = 115
            #     Agent needs return > 115 (i.e., 15% higher score)
            #
            if baseline < 0:
                # Negative returns: reduce magnitude by improvement percentage
                # Example: -100 * (1 - 0.15) = -85 (15% less negative)
                threshold = baseline * (1 - self.relative_improvement)
            else:
                # Positive returns: increase by improvement percentage  
                # Example: 100 * (1 + 0.15) = 115 (15% higher)
                threshold = baseline * (1 + self.relative_improvement)
            
            print(f"\n--- Relative Threshold Mode ---")
            print(f"Baseline (mean of trainable): {baseline:.2f}")
            print(f"Required improvement: {self.relative_improvement*100:.0f}%")
            print(f"Calculated threshold: {threshold:.2f}")
            
            # Interpretation help for user
            if baseline < 0:
                improvement_needed = baseline - threshold  # Will be positive
                print(f"  → Agents must achieve at least {improvement_needed:.2f} less loss")
                print(f"  → Example: {threshold:.2f} or better (less negative)")
            else:
                improvement_needed = threshold - baseline
                print(f"  → Agents must achieve at least {improvement_needed:.2f} more reward")
                print(f"  → Example: {threshold:.2f} or better")
        
        else:
            # ---------------------------------------------------------------
            # ABSOLUTE THRESHOLD (Legacy mode)
            # ---------------------------------------------------------------
            threshold = self.return_threshold
            print(f"\n--- Absolute Threshold Mode ---")
            print(f"Fixed threshold: {threshold:.2f}")
        
        # ===================================================================
        # STEP 4: Evaluate each trainable policy against threshold
        # ===================================================================
        print(f"\n--- Policy Evaluation ---")
        
        for agent_id, mean_return in agent_returns.items():
            # Map agent to policy (agent_0 → policy_0)
            policy_id = agent_id.replace('agent_', 'policy_')
            
            # Skip non-trainable policies (they don't get added to league)
            if policy_id not in self.trainable_policies:
                continue
            
            # Calculate how much better/worse than threshold
            diff = mean_return - threshold
            diff_pct = (diff / abs(threshold) * 100) if threshold != 0 else 0
            
            status = "✓ EXCEEDS" if mean_return > threshold else "✗ below"
            
            print(
                f"{policy_id}: {mean_return:>8.2f} | "
                f"threshold: {threshold:>8.2f} | "
                f"diff: {diff:>+8.2f} ({diff_pct:>+6.1f}%) | "
                f"{status}"
            )
            
            # ===================================================================
            # STEP 5: Add to league if threshold exceeded
            # ===================================================================
            if mean_return > threshold:
                print(f"\n  → {policy_id} qualifies for league!")
                
                # Create unique league opponent ID
                league_id = f"league_{len(self.league_opponents)}"
                
                try:
                    # Get the policy module (neural network)
                    policy_module = algorithm.get_module(policy_id)
                    
                    # Add new frozen module to the algorithm
                    # This creates a copy of the policy but doesn't train it
                    algorithm.add_module(
                        module_id=league_id,
                        module_spec=RLModuleSpec.from_module(policy_module),
                    )
                    
                    # Copy the weights from the successful policy
                    # This ensures the league opponent has the exact same strategy
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
                    
                    # Add to league opponents list (frozen, won't be trained)
                    self.league_opponents.append(league_id)
                    self.league_size = len(self.league_opponents)
                    
                    print(f"  → League opponent '{league_id}' created successfully!")
                    print(f"  → Current league size: {self.league_size}")
                    print(f"  → Snapshot of {policy_id} with return {mean_return:.2f}")
                    
                    # Update policy mapping to include new league opponent
                    self._update_policy_mapping(algorithm)
                    
                except Exception as e:
                    print(f"  → ✗ Error creating league opponent: {e}")
                    import traceback
                    traceback.print_exc()
        
        # ===================================================================
        # STEP 6: Add league statistics to results for logging
        # ===================================================================
        result['league_size'] = self.league_size
        # result['num_league_opponents'] = len(self.league_opponents)
        
        print(f"\n{'='*80}\n")
        
    def _update_policy_mapping(self, algorithm):
        """
        Update the policy mapping function to randomly assign agents to
        either trainable policies or league opponents.
        """
        
        trainable_list = list(self.trainable_policies)
        league_list = self.league_opponents.copy()
        all_policies = trainable_list + league_list
        
        if not all_policies:
            print("Warning: No policies available for mapping")
            return
        
        def policy_mapping_fn(agent_id, episode, **kwargs):
            """
            Randomly map agents to either trainable policies or league opponents.
            This ensures active policies get experience against diverse opponents.
            """
            # For simplicity, randomly select from all available policies
            # More sophisticated strategies could prioritize league opponents
            selected_policy = np.random.choice(all_policies)
            
            # Convert agent_id to policy_id if it's a trainable policy
            agent_policy = agent_id.replace('agent_', 'policy_')
            
            # Use agent's own policy if it's trainable, otherwise random
            if agent_policy in trainable_list:
                return agent_policy
            else:
                # Non-trainable agents get random assignment
                return selected_policy
        
        try:
            # Update policy mapping on all env runners
            algorithm.env_runner_group.foreach_env_runner(
                lambda env_runner: env_runner.config.multi_agent(
                    policy_mapping_fn=policy_mapping_fn,
                    policies_to_train=list(self.trainable_policies),
                ),
                local_env_runner=True,
            )
            
            # Update learner group
            algorithm.learner_group.foreach_learner(
                func=lambda learner: learner.config.multi_agent(
                    policies_to_train=list(self.trainable_policies),
                ),
                timeout_seconds=0.0,
            )
            
            print(f"  -> Policy mapping updated successfully")
            
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
        }
