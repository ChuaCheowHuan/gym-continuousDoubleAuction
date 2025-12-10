"""
League-Based Self-Play Helper Functions

Additional utilities for creating and managing league policies.
"""

import random
from ray.rllib.policy.policy import PolicySpec


def create_league_policies(num_agents, obs_space, act_space, model_name="model_disc"):
    """
    Create initial league policies for league-based self-play.
   
    Ensures minimum league size with mix of trainable and frozen policies.
    
    Args:
        num_agents: Number of agents in environment
        obs_space: Observation space for policies
        act_space: Action space for policies
        model_name: Name of the custom model to use
        
    Returns:
        tuple: (policies_dict, policies_to_train_list)
    """
    from gym_continuousDoubleAuction.train.policy.policy_handler import RandomPolicy
    
    policies = {}
    policies_to_train = []
    
    # 1. Main policy (trainable)
    policies['main'] = PolicySpec(
        policy_class=None,  # Use default PPO policy
        observation_space=obs_space,
        action_space=act_space,
        config={
            'model': {'custom_model': model_name},
            'explore': True,
        }
    )
    policies_to_train.append('main')
    
    # 2. Main exploiters: one random (frozen), one trainable
    policies['main_exploiter_0'] = PolicySpec(
        RandomPolicy,  # Frozen random policy
        observation_space=obs_space,
        action_space=act_space,
    )
    
    policies['main_exploiter_1'] = PolicySpec(
        policy_class=None,  # Trainable PPO
        observation_space=obs_space,
        action_space=act_space,
        config={
            'model': {'custom_model': model_name},
            'explore': True,
        }
    )
    policies_to_train.append('main_exploiter_1')
    
    # 3. League exploiters: one random (frozen), one trainable
    policies['league_exploiter_0'] = PolicySpec(
        RandomPolicy,  # Frozen random policy
        observation_space=obs_space,
        action_space=act_space,
    )
    
    policies['league_exploiter_1'] = PolicySpec(
        policy_class=None,  # Trainable PPO
        observation_space=obs_space,
        action_space=act_space,
        config={
            'model': {'custom_model': model_name},
            'explore': True,
        }
    )
    policies_to_train.append('league_exploiter_1')
    
    print(f'[PolicyHandler] Created league policies:')
    print(f'  Total policies: {len(policies)}')
    print(f'  Trainable: {policies_to_train}')
    print(f'  Frozen: {[p for p in policies.keys() if p not in policies_to_train]}')
    print(f'  Num agents: {num_agents}')
    
    return policies, policies_to_train


def get_league_policy_mapping_fn(num_agents):
    """
    Create a policy mapping function for league-based self-play.
    
    CRITICAL CONSTRAINTS:
    - Each trainable policy can only be used by ONE agent per episode
    - Frozen policies CAN be reused by multiple agents
    
    Args:
        num_agents: Number of agents in the environment
        
    Returns:
        Callable policy mapping function
    """
    
    def policy_mapping_fn(agent_id, episode, **kwargs):
        """
        Map agents to policies ensuring trainable policy uniqueness.
        """
        # Extract agent index
        if isinstance(agent_id, str) and '_' in agent_id:
            agent_idx = int(agent_id.split('_')[1])
        else:
            agent_idx = int(agent_id)
        
        # Static assignment for initial league
        trainable_policies = ['main', 'main_exploiter_1', 'league_exploiter_1']
        frozen_policies = ['main_exploiter_0', 'league_exploiter_0']
        
        # Use episode ID for deterministic shuffling
        episode_id = episode.episode_id if hasattr(episode, 'episode_id') else 0
        rng = random.Random(episode_id)
        
        # Shuffle trainable and frozen separately
        shuffled_trainable = trainable_policies.copy()
        shuffled_frozen = frozen_policies.copy()
        rng.shuffle(shuffled_trainable)
        rng.shuffle(shuffled_frozen)
        
        # Assign trainable policies first (one per agent)
        if agent_idx < len(shuffled_trainable):
            return shuffled_trainable[agent_idx]
        else:
            # Fill remaining with frozen policies (can repeat)
            frozen_idx = (agent_idx - len(shuffled_trainable)) % len(shuffled_frozen)
            return shuffled_frozen[frozen_idx]
    
    return policy_mapping_fn
