from collections import defaultdict

import numpy as np
import json
import pprint
import pickle
import os

from ray.rllib.callbacks.callbacks import RLlibCallback
from ray.rllib.core.rl_module.rl_module import RLModuleSpec
from ray.rllib.utils.metrics import ENV_RUNNER_RESULTS


class SelfPlayCallback(RLlibCallback):
    def __init__(
        self, 
        num_trainable_policies=2, 
        num_random_policies=2, 
        std_dev_multiplier=2.0, 
        max_champions=2, 
        min_iterations_between_champions=2,
    ):
        """
        Initialize league-based self-play callback with generalized agent configuration.
        
        Args:
            num_trainable_policies (k): Number of policies that learn (Agents 0 to k-1)
            num_random_policies (m): Number of initial fixed/random policies (Agents k to n-1)
            std_dev_multiplier: Number of standard deviations above mean to trigger snapshot
            max_champions: Maximum number of champions to maintain (rolling window)
            
        Total Agents n = k + m
        """
        super().__init__()
        
        self.num_trainable = num_trainable_policies
        self.num_random = num_random_policies
        
        # Champion snapshotting configuration
        self.std_dev_multiplier = std_dev_multiplier
        self.max_champions = max_champions
        self.min_iterations_between_champions = min_iterations_between_champions
        
        # Champion tracking state
        self.champion_count = 0
        self.champion_id_counter = 0  # Monotonic counter for unique IDs
        self.champion_history = []  # List of dicts with champion metadata
        
        # Initialize available modules: [policy_0...policy_k-1] + [policy_k...policy_n-1]
        self.available_modules = [f"policy_{i}" for i in range(self.num_trainable + self.num_random)]
        
        # Episode data storage (unchanged)
        self.ID = None
        self.store = None


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
        print(f"\n{'='*40}")
        print(f"Episode {episode.id_} Started - Policy Map:")
        
        # replicate mapping logic to display what will happen
        # Available modules contains: [0..k-1 (Trainable), k..n-1 (Random), Champions...]
        # Opponent pool starts after the trainable policies
        candidates = self.available_modules[self.num_trainable:]
        total_agents = self.num_trainable + self.num_random
        
        for i in range(total_agents):
            agent_id = f"agent_{i}"
            if i < self.num_trainable:
                # Trainable agents always map to their own policy
                policy = f"policy_{i}"
            else:
                # Random/League agents map to pool
                if not candidates:
                    policy = f"policy_{i}"
                else:
                    # Logic must match get_mapping_fn exactly
                    # Note: currently assigns same opponent to all fixed agents
                    idx = (hash(episode.id_) + i) % len(candidates)
                    policy = candidates[idx]
            
            print(f"  {agent_id} -> {policy}")
            
        print(f"{'='*40}\n")
            
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
        # print('on_episode_step')

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
        # # Compute the win rate for this episode and log it with a window of 100.
        # main_agent = 0 if episode.module_for(0) == "main" else 1
        # rewards = episode.get_rewards()
        # if main_agent in rewards:
        #     main_won = rewards[main_agent][-1] == 1.0
        #     metrics_logger.log_value(
        #         "win_rate",
        #         main_won,
        #         reduce="mean",
        #         window=100,
        #     )

        # last_obs = episode.get_observations(-1)
        # last_act = episode.get_actions(-1)
        # last_reward = episode.get_rewards(-1)
        # last_info = episode.get_infos(-1)

        print(f'on_episode_end:{episode}')

        # print(f'last_obs:{last_obs}')  
        # print(f'last_act:{last_act}')        
        # print(f'last_reward:{last_reward}')        
        # print(f'last_info:{last_info}')     

        # print(self.store)

        # Save the data
        # with open('episode_data_' + episode.id_ + '.json', 'w') as f:
        #     json.dump(self.store, f, indent=4)


        os.makedirs('episode_data', exist_ok=True)
        # Save the data
        with open('episode_data/' + str(episode.id_) + '.pkl', 'wb') as f:
            pickle.dump(self.store, f)

        # # Load later
        # with open('episode_data.pkl', 'rb') as f:
        #     loaded_store = pickle.load(f)

        self.store = None   

    def on_train_result(self, *, algorithm, metrics_logger=None, result, **kwargs):
        """
        Callback after each training iteration.
        
        Uses relative ranking based on POLICY returns to identify champions.
        snapshots created when return > mean + std_dev_multiplier * std.
        """
        # Get POLICY returns (not agent returns)
        # Check standard locations for policy rewards
        if 'policy_reward_mean' in result['env_runners']:
            policy_returns = result['env_runners']['policy_reward_mean']
        elif 'custom_metrics' in result['env_runners']: # Fallback
            policy_returns = {k: v for k,v in result['env_runners']['custom_metrics'].items() if 'policy' in k}
        else:
             # Fallback to aggregation from agent returns if simple mapping
            # This is less accurate if multiple agents share policy, but works for 1:1
            print("Warning: policy_reward_mean not found, falling back to agent returns")
            policy_returns = {}
            agent_returns = result['env_runners']['agent_episode_returns_mean']
            for agent_id, ret in agent_returns.items():
                # Map agent_X -> policy_X
                policy_id = f"policy_{agent_id.split('_')[1]}"
                policy_returns[policy_id] = ret

        iteration = result['training_iteration']
        
        # Filter mostly interesting policies (exclude extremely sparse ones if any)
        # and calculate league statistics
        valid_returns = [v for v in policy_returns.values() if v is not None]
        
        if not valid_returns:
            print("No valid policy returns found this iteration.")
            return

        league_mean = np.mean(valid_returns)
        league_std = np.std(valid_returns)
        
        # Determine dynamic threshold
        # If std is 0 (all same), effectively requires > mean
        threshold = league_mean + (self.std_dev_multiplier * league_std)
        
        print(f"\n{'='*80}")
        print(f"Iteration {iteration} League Stats:")
        print(f"Mean: {league_mean:.2f} | Std: {league_std:.2f} | Threshold: {threshold:.2f}")
        print(f"Policy Returns: {policy_returns}")
        
        # Check trainable policies for champion status
        trainable_policies = [f"policy_{i}" for i in range(self.num_trainable)]
        
        best_candidate = None
        best_return = -float('inf')
        
        for pid in trainable_policies:
            if pid in policy_returns:
                p_ret = policy_returns[pid]
                if p_ret > best_return:
                    best_return = p_ret
                    best_candidate = pid
        
        print(f"Best Trainable: {best_candidate} ({best_return:.2f})")
        print(f"{'='*80}\n")
        
        # Check relative performance trigger
        if best_candidate and best_return > threshold:
            # Also check if it's better than previous champion (optional but good for progress)
            # best_historical = max([c['return'] for c in self.champion_history]) if self.champion_history else -float('inf')
            
            if self._should_create_champion(best_return, iteration):
                 # Pass policy ID directly
                self._create_champion_snapshot_from_policy(algorithm, best_candidate, best_return, iteration)
        
        # Log metrics
        if metrics_logger:
            metrics_logger.log_value("league_size", 2 + self.champion_count, window=1)
            metrics_logger.log_value("league_mean_return", league_mean, window=10)
            metrics_logger.log_value("league_std_return", league_std, window=10)
    
    def _should_create_champion(self, return_value, iteration):
        """
        Decide if we should create a champion snapshot.
        
        Args:
            return_value: The return value of the best policy
            iteration: Current training iteration
            
        Returns:
            True if champion should be created, False otherwise
        """
        # Don't snapshot too frequently
        if self.champion_history:
            last_champion_iter = self.champion_history[-1]['iteration']
            if iteration - last_champion_iter < self.min_iterations_between_champions:
                print(f"Skipping champion creation: only {iteration - last_champion_iter} iterations "
                      f"since last champion (min: {self.min_iterations_between_champions})")
                return False
        
        # Check if we need to remove old champion first (rolling window)
        if self.champion_count >= self.max_champions:
            print(f"Max champions ({self.max_champions}) reached, will remove oldest")
            self._remove_oldest_champion()
        
        return True
    
    def _create_champion_snapshot_from_policy(self, algorithm, policy_id, return_value, iteration):
        """
        Create a frozen champion snapshot of the best policy.
        
        Args:
            algorithm: The training algorithm instance
            policy_id: ID of the policy to snapshot
            return_value: Performance metric that triggered snapshotting
            iteration: Current training iteration
        """
        # Create unique champion name using monotonic counter
        self.champion_id_counter += 1
        champion_id = f"champion_{self.champion_id_counter}"
        
        print(f"\n{'*'*80}")
        print(f"🏆 CREATING CHAMPION SNAPSHOT 🏆")
        print(f"Champion ID: {champion_id}")
        print(f"Source Policy: {policy_id}")
        print(f"Return: {return_value:.2f}")
        print(f"Iteration: {iteration}")
        print(f"{'*'*80}\n")
        
        try:
            # Get the source module
            source_module = algorithm.get_module(policy_id)
            
            # Create module spec for the champion (frozen, no exploration)
            from ray.rllib.core.rl_module.rl_module import RLModuleSpec
            champion_spec = RLModuleSpec.from_module(source_module)
            
            # Add the champion module to the algorithm
            algorithm.add_module(
                module_id=champion_id,
                module_spec=champion_spec,
            )
            
            # Copy weights from source to champion
            algorithm.set_state({
                "learner_group": {
                    "learner": {
                        "rl_module": {
                            champion_id: source_module.get_state(),
                        }
                    }
                }
            })
            
            # Record champion metadata
            champion_info = {
                'id': champion_id,
                'source_policy': policy_id,
                'iteration': iteration,
                'return': return_value,
            }
            self.champion_history.append(champion_info)
            self.champion_count += 1
            
            # Update available modules for matchmaking
            self.available_modules.append(champion_id)
            
            print(f"✓ Champion {champion_id} created successfully!")
            print(f"✓ League size now: {2 + self.champion_count} "
                  f"(2 trainable + {self.champion_count} champions)")
            print(f"✓ Active champions: {[c['id'] for c in self.champion_history]}\n")
            
        except Exception as e:
            print(f"✗ Error creating champion {champion_id}: {e}")
            import traceback
            traceback.print_exc()
    
    def _remove_oldest_champion(self):
        """
        Remove the oldest champion to maintain rolling window.
        
        Note: RLlib 2.4+ doesn't provide a clean way to remove modules,
        so we remove from tracking but module remains in memory.
        """
        if not self.champion_history:
            return
        
        # Get oldest champion
        oldest = self.champion_history.pop(0)
        champion_id = oldest['id']
        
        print(f"\n⚠️  Removing oldest champion: {champion_id} "
              f"(from iteration {oldest['iteration']}, return={oldest['return']:.2f})")
        
        # Remove from available modules (won't be assigned to agents anymore)
        if champion_id in self.available_modules:
            self.available_modules.remove(champion_id)
        
        self.champion_count -= 1
        
        print(f"✓ Champion removed. Active champions: {[c['id'] for c in self.champion_history]}\n")
    
    @classmethod
    def get_mapping_fn(cls, callback_instance):
        """
        Create an agent-to-module mapping function that includes champions.
        
        Args:
            callback_instance: Instance of SelfPlayCallback with champion tracking
            
        Returns:
            Mapping function for use in multi_agent config
        """
        def agent_to_module_mapping_fn(agent_id, episode, **kwargs):
            """Assign agents to modules including dynamic champions."""
            agent_num = int(agent_id.split("_")[1])
            
            # Trainable policies always assigned to their respective agents
            if agent_num < callback_instance.num_trainable:
                return f"policy_{agent_num}"
            
            # For random/league agents, assign from pool (champions + original randoms)
            # The pool starts AFTER the trainable policies
            # Pool = available_modules[k:] 
            candidates = callback_instance.available_modules[callback_instance.num_trainable:]
            print(f"\nCandidates: {candidates}")

            if not candidates:
                # Fallback if no champions yet
                return f"policy_{agent_num}"
            
            # Use episode hash AND agent_num for deterministic but varied assignment
            # This ensures opponent agents can get different opponents
            idx = (hash(episode.id_) + agent_num) % len(candidates)
            return candidates[idx]
        
        return agent_to_module_mapping_fn