"""
League-based self-play callback for multi-agent reinforcement learning.

Implements a three-tier league system based on DeepMind's AlphaStar approach:
- Main policies: Current best policy and historical snapshots
- Main exploiters: Policies trained specifically against main policies
- League exploiters: Policies trained against the entire league

This callback manages policy snapshots, league composition, and matchmaking
to enable robust competitive self-play training in zero-sum environments.
"""

import random
from typing import Dict, List, Optional, Set, Callable
import numpy as np

from ray.rllib.algorithms.callbacks import DefaultCallbacks
from ray.rllib.env import BaseEnv
# from ray.rllib.evaluation import Episode, RolloutWorker
from ray.rllib.policy import Policy
from ray.rllib.utils.typing import PolicyID


class LeagueBasedSelfPlayCallback(DefaultCallbacks):
    """
    Callback for managing league-based self-play training.
    
    Monitors policy performance and creates frozen snapshots when performance
    thresholds are met. Maintains a diverse league of policies for robust training.
    
    Args:
        win_rate_threshold (float): Performance threshold to trigger snapshot creation (0.0-1.0)
        num_agents (int): Number of agents in the environment (for validation)
        metric (str): Performance metric to use - 'reward' or 'nav'
    """
    
    def __init__(self, 
                 win_rate_threshold: float = 0.70,
                 num_agents: int = 4,
                 metric: str = 'reward'):
        super().__init__()
        
        self.win_rate_threshold = win_rate_threshold
        self.num_agents = num_agents
        self.metric = metric
        
        # League composition tracking
        self.league = {
            'main': [],  # Current main + historical snapshots
            'main_exploiters': [],  # Policies trained vs main
            'league_exploiters': []  # Policies trained vs entire league
        }
        
        # Policy status tracking
        self.trainable_policies: Set[PolicyID] = set()
        self.frozen_policies: Set[PolicyID] = set()
        
        # Performance tracking
        self.policy_performance_history: Dict[PolicyID, List[float]] = {}
        
        # Snapshot counter for naming
        self.snapshot_counter = 0
        
        print(f"[LeagueCallback] Initialized with:")
        print(f"  - Win rate threshold: {self.win_rate_threshold}")
        print(f"  - Num agents: {self.num_agents}")
        print(f"  - Performance metric: {self.metric}")
    
    def on_algorithm_init(self, *, algorithm, **kwargs) -> None:
        """
        Initialize league structures from the algorithm's policy map.
        
        Called once when the algorithm is first created.
        """
        # Get initial policies from algorithm
        # Ray 2.0+ uses env_runner_group instead of workers
        try:
            # Try new API first (Ray 2.0+)
            if hasattr(algorithm, 'env_runner_group'):
                # New API: env_runner_group.local_env_runner()
                local_runner = algorithm.env_runner_group.local_env_runner()
                policy_map = local_runner.module.keys() if hasattr(local_runner, 'module') else {}
            elif hasattr(algorithm, 'workers'):
                # Try workers() as method
                workers_obj = algorithm.workers() if callable(algorithm.workers) else algorithm.workers
                if hasattr(workers_obj, 'local_env_runner'):
                    local_runner = workers_obj.local_env_runner()
                    policy_map = local_runner.module.keys() if hasattr(local_runner, 'module') else {}
                else:
                    # Old API
                    local_runner = workers_obj.local_worker()
                    policy_map = local_runner.policy_map
            else:
                raise AttributeError("Cannot find workers or env_runner_group")
            
            # For new API, policy_map might be from config
            if not policy_map and hasattr(algorithm, 'config'):
                policy_map = algorithm.config.get('policies', {}).keys()
                
        except Exception as e:
            print(f"[LeagueCallback] ERROR accessing policy map: {e}")
            print(f"[LeagueCallback] Trying to get policies from algorithm config...")
            # Fallback: get from config
            try:
                if hasattr(algorithm, 'config'):
                    # In Ray 2.0+, config is an AlgorithmConfig object, not a dict
                    config = algorithm.config
                    
                    # Try to convert to dict first
                    try:
                        config_dict = config.to_dict() if hasattr(config, 'to_dict') else config
                        multiagent_config = config_dict.get('multiagent', {})
                        policy_map = multiagent_config.get('policies', {}).keys()
                    except:
                        # Try accessing multiagent attribute directly
                        if hasattr(config, 'policies'):
                            policy_map = config.policies.keys()
                        else:
                            print(f"[LeagueCallback] Cannot extract policies from config")
                            print(f"[LeagueCallback] Config type: {type(config)}")
                            print(f"[LeagueCallback] Config attributes: {dir(config)[:10]}...")  # First 10
                            return
                else:
                    print(f"[LeagueCallback] Cannot access policies, aborting initialization")
                    return
            except Exception as e2:
                print(f"[LeagueCallback] Failed to get policies from config: {e2}")
                import traceback
                traceback.print_exc()
                return
        
        if not policy_map:
            print(f"[LeagueCallback] WARNING: No policies found in policy_map!")
            return
        
        # Categorize initial policies
        for policy_id in policy_map:
            if 'main' in policy_id and policy_id == 'main':
                self.league['main'].append(policy_id)
                self.trainable_policies.add(policy_id)
            elif 'main_exploiter' in policy_id:
                self.league['main_exploiters'].append(policy_id)
                # exploiter_0 is random (frozen), exploiter_1 is trainable
                if policy_id.endswith('_0'):
                    self.frozen_policies.add(policy_id)
                else:
                    self.trainable_policies.add(policy_id)
            elif 'league_exploiter' in policy_id:
                self.league['league_exploiters'].append(policy_id)
                # exploiter_0 is random (frozen), exploiter_1 is trainable
                if policy_id.endswith('_0'):
                    self.frozen_policies.add(policy_id)
                else:
                    self.trainable_policies.add(policy_id)
        
        total_league_size = sum(len(v) for v in self.league.values())
        print(f"[LeagueCallback] League initialized:")
        print(f"  - Main policies: {self.league['main']}")
        print(f"  - Main exploiters: {self.league['main_exploiters']}")
        print(f"  - League exploiters: {self.league['league_exploiters']}")
        print(f"  - Total league size: {total_league_size}")
        print(f"  - Trainable policies: {self.trainable_policies}")
        print(f"  - Frozen policies: {self.frozen_policies}")
        
        # Validate minimum league requirements
        if len(self.trainable_policies) < 1:
            print("[LeagueCallback] WARNING: No trainable policies found!")
    
    def on_train_result(self, *, algorithm, result: dict, **kwargs) -> None:
        """
        Called after each training iteration to check performance and manage league.
        
        Calculates policy-based performance metrics and creates snapshots if
        performance thresholds are met.
        """
        # Calculate policy-based performance
        policy_performance = self._calculate_policy_performance(result)
        
        # Update performance history
        for policy_id, perf in policy_performance.items():
            if policy_id not in self.policy_performance_history:
                self.policy_performance_history[policy_id] = []
            self.policy_performance_history[policy_id].append(perf)
        
        # Calculate win rates for trainable policies
        win_rates = self._calculate_win_rates(policy_performance)
        
        # Log league metrics (initialize custom_metrics if needed)
        if 'custom_metrics' not in result:
            result['custom_metrics'] = {}
        
        result['custom_metrics']['league_size'] = sum(len(v) for v in self.league.values())
        result['custom_metrics']['num_trainable_policies'] = len(self.trainable_policies)
        result['custom_metrics']['num_frozen_policies'] = len(self.frozen_policies)
        
        for policy_id, win_rate in win_rates.items():
            result['custom_metrics'][f'win_rate_{policy_id}'] = win_rate
            
        print(f"\n[LeagueCallback] Iteration {result.get('training_iteration', 'N/A')}:")
        print(f"  Policy performance ({self.metric}):")
        for policy_id, perf in policy_performance.items():
            trainable_str = "(trainable)" if policy_id in self.trainable_policies else "(frozen)"
            print(f"    {policy_id:30s} {trainable_str:12s}: {perf:.4f}")
        
        # Check if any trainable policy should be snapshotted
        for policy_id in self.trainable_policies:
            if policy_id in win_rates and win_rates[policy_id] >= self.win_rate_threshold:
                print(f"\n[LeagueCallback] Policy '{policy_id}' reached win rate threshold!")
                print(f"  Win rate: {win_rates[policy_id]:.3f} >= {self.win_rate_threshold:.3f}")
                
                # Create snapshot for main policy only
                if policy_id == 'main':
                    self._create_main_snapshot(algorithm, policy_id)
    
    def _calculate_policy_performance(self, result: dict) -> Dict[PolicyID, float]:
        """
        Calculate performance metrics aggregated by policy_id.
        
        Extracts either rewards or NAV from episode data and groups by policy.
        Multiple agents using the same policy contribute to that policy's metric.
        
        Returns:
            Dictionary mapping policy_id to mean performance
        """
        policy_metrics: Dict[PolicyID, List[float]] = {}
        
        # Ray 2.0+ uses different result structure
        # Try multiple ways to get policy performance
        
        # Method 1: Use policy_reward_mean if available (most reliable)
        if 'env_runners' in result:
            # New API structure
            env_runners = result['env_runners']
            
            # Check for module episode returns (new API)
            if 'module_episode_returns_mean' in env_runners:
                module_returns = env_runners['module_episode_returns_mean']
                
                # Debug: show what we got
                if not hasattr(self, '_logged_module_structure'):
                    print(f"[LeagueCallback] DEBUG: module_episode_returns_mean type: {type(module_returns)}")
                    print(f"[LeagueCallback] DEBUG: module_episode_returns_mean content: {module_returns}")
                    self._logged_module_structure = True
                
                # module_episode_returns_mean might be a dict or a single value
                if isinstance(module_returns, dict):
                    for policy_id, reward in module_returns.items():
                        all_policies = self.league['main'] + self.league['main_exploiters'] + self.league['league_exploiters']
                        if policy_id in all_policies:
                            if policy_id not in policy_metrics:
                                policy_metrics[policy_id] = []
                            policy_metrics[policy_id].append(reward)
                else:
                    # Single value - might need to map to all policies
                    print(f"[LeagueCallback] WARNING: module_episode_returns_mean is not a dict")
            
            # Also check old-style policy_reward_mean
            elif 'policy_reward_mean' in env_runners:
                policy_reward_mean = env_runners['policy_reward_mean']
                for policy_id, reward in policy_reward_mean.items():
                    all_policies = self.league['main'] + self.league['main_exploiters'] + self.league['league_exploiters']
                    if policy_id in all_policies:
                        if policy_id not in policy_metrics:
                            policy_metrics[policy_id] = []
                        policy_metrics[policy_id].append(reward)
        
        # Method 2: Direct policy_reward_mean at top level (older Ray 2.0)
        elif 'policy_reward_mean' in result:
            policy_reward_mean = result['policy_reward_mean']
            for policy_id, reward in policy_reward_mean.items():
                all_policies = self.league['main'] + self.league['main_exploiters'] + self.league['league_exploiters']
                if policy_id in all_policies:
                    if policy_id not in policy_metrics:
                        policy_metrics[policy_id] = []
                    policy_metrics[policy_id].append(reward)
        
        # Method 3: sampler_results (old API)
        elif 'sampler_results' in result:
            # Old API structure
            episodes = result.get('sampler_results', {}).get('episodes', [])
            # This would require episode-level processing
            pass
        
        # If no metrics found, log warning
        if not policy_metrics:
            # Don't spam warnings, just note it once
            if not hasattr(self, '_warned_no_metrics'):
                print(f"[LeagueCallback] WARNING: Could not find policy performance metrics in result")
                print(f"[LeagueCallback] Available keys: {list(result.keys())}")
                if 'env_runners' in result:
                    print(f"[LeagueCallback] env_runners keys: {list(result['env_runners'].keys())}")
                self._warned_no_metrics = True
            return {}
        
        # Compute mean performance per policy
        performance = {}
        for policy_id, metrics in policy_metrics.items():
            if metrics:
                performance[policy_id] = np.mean(metrics)
        
        return performance
    
    def _calculate_win_rates(self, policy_performance: Dict[PolicyID, float]) -> Dict[PolicyID, float]:
        """
        Calculate win rates for trainable policies.
        
        In a zero-sum game, the policy with the highest performance "wins" that iteration.
        Win rate is calculated as the proportion of times a policy has the best performance.
        
        Args:
            policy_performance: Current iteration's performance per policy
            
        Returns:
            Dictionary mapping policy_id to win rate (0.0-1.0)
        """
        win_rates = {}
        
        # Only calculate for trainable policies
        trainable_performance = {
            pid: perf for pid, perf in policy_performance.items()
            if pid in self.trainable_policies
        }
        
        if not trainable_performance:
            return {}
        
        # Find the winner of this iteration
        best_policy = max(trainable_performance, key=trainable_performance.get)
        
        # Calculate win rate based on history
        for policy_id in self.trainable_policies:
            if policy_id not in self.policy_performance_history:
                win_rates[policy_id] = 0.0
                continue
            
            # Count wins in history
            history = self.policy_performance_history[policy_id]
            if len(history) == 0:
                win_rates[policy_id] = 0.0
                continue
            
            # Simple win rate: percentage of iterations where this policy had best performance
            # For now, use a moving average of recent performance vs threshold
            recent_performance = history[-min(10, len(history)):]  # Last 10 iterations
            avg_performance = np.mean(recent_performance)
            
            # Normalize to 0-1 range (simplified)
            # In practice, you'd compare against other policies
            win_rates[policy_id] = avg_performance / (abs(avg_performance) + 1e-6)
            win_rates[policy_id] = max(0.0, min(1.0, win_rates[policy_id]))
        
        return win_rates
    
    def _create_main_snapshot(self, algorithm, policy_id: PolicyID) -> None:
        """
        Create a frozen snapshot of the main policy and add it to the league.
        
        Args:
            algorithm: The training algorithm instance
            policy_id: ID of the policy to snapshot (should be 'main')
        """
        self.snapshot_counter += 1
        snapshot_name = f"main_{self.snapshot_counter}"
        
        print(f"[LeagueCallback] Creating snapshot: {snapshot_name}")
        
        try:
            # Get the policy weights from local runner
            # Ray 2.0+ API: use env_runner_group.local_env_runner()
            try:
                if hasattr(algorithm, 'env_runner_group'):
                    local_runner = algorithm.env_runner_group.local_env_runner()
                    # In new API, might need to access differently
                    if hasattr(local_runner, 'module'):
                        # New RLModule API - more complex
                        print(f"[LeagueCallback] WARNING: RLModule API detected, snapshot not yet supported")
                        return
                    else:
                        # Has policy_map
                        policy = local_runner.policy_map[policy_id]
                elif hasattr(algorithm, 'workers'):
                    workers_obj = algorithm.workers() if callable(algorithm.workers) else algorithm.workers
                    if hasattr(workers_obj, 'local_env_runner'):
                        local_runner = workers_obj.local_env_runner()
                        policy = local_runner.policy_map[policy_id]
                    else:
                        local_runner = workers_obj.local_worker()
                        policy = local_runner.policy_map[policy_id]
                else:
                    print(f"[LeagueCallback] ERROR: Cannot access runners/workers")
                    return
            except Exception as e:
                print(f"[LeagueCallback] ERROR accessing local runner: {e}")
                return
            
            weights = policy.get_weights()
            
            # Get policy spec from the original policy
            obs_space = policy.observation_space
            act_space = policy.action_space
            config = policy.config.copy()
            
            # Disable exploration for frozen snapshot
            config['explore'] = False
            
            # Add the frozen policy to workers
            local_worker.add_policy(
                policy_id=snapshot_name,
                policy_cls=type(policy),
                observation_space=obs_space,
                action_space=act_space,
                config=config,
            )
            
            # Set the weights
            local_worker.set_weights({snapshot_name: weights})
            
            # Add to remote workers if they exist
            try:
                if hasattr(algorithm, 'env_runner_group'):
                    # New API
                    num_workers = algorithm.env_runner_group.num_healthy_remote_workers()
                else:
                    num_workers = algorithm.workers.num_healthy_remote_workers()
                
                if num_workers > 0:
                    # Sync weights to remote workers
                    if hasattr(algorithm, 'env_runner_group'):
                        algorithm.env_runner_group.sync_weights(policies=[snapshot_name])
                    else:
                        algorithm.workers.sync_weights(policies=[snapshot_name])
            except Exception as e:
                print(f"[LeagueCallback] Warning: Could not sync to remote workers: {e}")
            
            # Update league tracking
            self.league['main'].append(snapshot_name)
            self.frozen_policies.add(snapshot_name)
            
            print(f"[LeagueCallback] Successfully added frozen snapshot: {snapshot_name}")
            print(f"[LeagueCallback] League now has {len(self.league['main'])} main policies")
            
        except Exception as e:
            print(f"[LeagueCallback] ERROR creating snapshot: {e}")
            import traceback
            traceback.print_exc()
