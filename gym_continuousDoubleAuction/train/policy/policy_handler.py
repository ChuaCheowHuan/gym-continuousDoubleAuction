import numpy as np
from ray.rllib.policy.policy import Policy, PolicySpec
from ray.rllib.algorithms.ppo import PPOConfig
  
# Custom Random Policy
class RandomPolicy:
    def __init__(self, observation_space, action_space, config):
        self.action_space = action_space

    def compute_actions(self, obs_batch, state_batches=None, **kwargs):
        actions = [self.action_space.sample() for _ in range(len(obs_batch))]
        return actions, [], {}

    def learn_on_batch(self, samples):
        return {}  # Random policy doesn't learn

    def get_weights(self):
        return {}  # No weights for random policy

    def set_weights(self, weights):
        pass  # No weights to set
    
def create_multi_agent_config(obs_space, act_space, num_agents, num_trained_agents):
    """
    Create multi-agent configuration using Ray 2.4+ API.
    Sets up policies where first num_trained_agents use PPO and rest use RandomPolicy.
    """
    
    # Create policy specifications
    policies = {}
    policies_to_train = []
    
    # Set up trained agents (PPO policies)
    for i in range(num_trained_agents):
        policies[f"policy_{i}"] = PolicySpec(
            policy_class=None,  # Use default PPO policy
            observation_space=obs_space, 
            action_space=act_space, 
            # {
            #     "model": {"custom_model": "model_disc"},
            #     "gamma": 0.99,
            # }
            config={
                "model": {
                    "custom_model": "model_disc"
                    }
                },       
        )
        policies_to_train.append(f"policy_{i}")
    
    # Set up random agents
    for i in range(num_trained_agents, num_agents):
        policies[f"policy_{i}"] = PolicySpec(
            RandomPolicy,  # Use random policy with seed
            observation_space=obs_space, 
            action_space=act_space, 
            # {}
        )
    
    print('policies:', policies)
    print('policies_to_train:', policies_to_train)
    
    return policies, policies_to_train

# Policy mapping function - maps agent IDs to policy IDs
# def policy_mapping_fn(agent_id, episode, worker, **kwargs):
def policy_mapping_fn(agent_id, episode, **kwargs):
    # Extract numeric ID from agent_id (assuming format like "agent_0", "agent_1", etc.)
    if isinstance(agent_id, str) and agent_id.startswith("agent_"):
        agent_num = int(agent_id.split("_")[1])
    else:
        agent_num = int(agent_id)
    return f"policy_{agent_num}"