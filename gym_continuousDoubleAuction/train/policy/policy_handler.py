# from ray.rllib.policy.policy import Policy

# def make_RandomPolicy(_seed):

#     class RandomPolicy(Policy):
#         """
#         A hand-coded policy that returns random actions in the env (doesn't learn).
#         """

#         def __init__(self, observation_space, action_space, config):
#             self.observation_space = observation_space
#             self.action_space = action_space
#             self.action_space.seed(_seed)

#         def compute_actions(self,
#                             obs_batch,
#                             state_batches,
#                             prev_action_batch=None,
#                             prev_reward_batch=None,
#                             info_batch=None,
#                             episodes=None,
#                             **kwargs):
#             """Compute actions on a batch of observations."""
#             return [self.action_space.sample() for _ in obs_batch], [], {}

#         def learn_on_batch(self, samples):
#             """No learning."""
#             #return {}
#             pass

#         def get_weights(self):
#             pass

#         def set_weights(self, weights):
#             pass

#     return RandomPolicy

# def gen_policy(i, obs_space, act_space):
#     """
#     Each policy can have a different configuration (including custom model)
#     """

#     config = {"model": {"custom_model": "model_disc"},
#               "gamma": 0.99,}
#     return (None, obs_space, act_space, config)

# def set_agents_policies(policies, obs_space, act_space, num_agents, num_trained_agent):
#     """
#     Set 1st policy as PPO & override all other policies as RandomPolicy with
#     different seed.
#     """

#     # set all agents to use random policy
#     for i in range(num_agents):
#         policies["policy_{}".format(i)] = (make_RandomPolicy(i), obs_space, act_space, {})

#     # set trained agents to use None (PPOTFPolicy)
#     for i in range(num_trained_agent):
#         #policies["policy_{}".format(i)] = (PPOTFPolicy, obs_space, act_space, {})
#         policies["policy_{}".format(i)] = (None, obs_space, act_space, {})

#     print('policies:', policies)
#     return 0

# def create_train_policy_list(num_trained_agent, prefix):
#     """
#     Storage for train_policy_list for declaring train poilicies in trainer config.
#     """
    
#     storage = []
#     for i in range(0, num_trained_agent):
#         storage.append(prefix + str(i))

#     print("train_policy_list = ", storage)
#     return storage



from ray.rllib.policy.policy import Policy
from ray.rllib.algorithms.ppo import PPOConfig
# from ray.rllib.core.rl_module.rl_module import SingleAgentRLModuleSpec
# from ray.rllib.core.rl_module.marl_module import MultiAgentRLModuleSpec
# from ray.rllib.utils.typing import PolicyID
import numpy as np


def make_RandomPolicy(seed):
    """Factory function to create a RandomPolicy class with a given seed."""
    
    class RandomPolicy(Policy):
        """
        A hand-coded policy that returns random actions in the env (doesn't learn).
        Compatible with Ray 2.4+ RLlib API.
        """
        
        def __init__(self, observation_space, action_space, config):
            # Call parent constructor with required parameters
            super().__init__(observation_space, action_space, config)
            self.observation_space = observation_space
            self.action_space = action_space
            # Set seed for reproducible random actions
            if hasattr(self.action_space, 'seed'):
                self.action_space.seed(seed)
            else:
                # Fallback for action spaces that don't support seeding
                np.random.seed(seed)
        
        def compute_actions(self,
                          obs_batch,
                          state_batches=None,
                          prev_action_batch=None,
                          prev_reward_batch=None,
                          info_batch=None,
                          episodes=None,
                          **kwargs):
            """Compute actions on a batch of observations."""
            # Sample random actions for each observation in the batch
            actions = [self.action_space.sample() for _ in obs_batch]
            return actions, [], {}
        
        def learn_on_batch(self, samples):
            """No learning for random policy."""
            # Return empty stats dict (required in newer versions)
            return {}
        
        def get_weights(self):
            """Return empty weights (no parameters to return)."""
            return {}
        
        def set_weights(self, weights):
            """No weights to set for random policy."""
            pass
            
        def compute_single_action(self, obs, state=None, prev_action=None, 
                                prev_reward=None, info=None, **kwargs):
            """Compute a single action (required method in newer API)."""
            return self.action_space.sample(), [], {}

    return RandomPolicy


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
        policy_id = f"policy_{i}"
        policies[policy_id] = (
            None,  # Use default PPO policy
            obs_space, 
            act_space, 
            {
                "model": {"custom_model": "model_disc"},
                "gamma": 0.99,
            }
        )
        policies_to_train.append(policy_id)
    
    # Set up random agents
    for i in range(num_trained_agents, num_agents):
        policy_id = f"policy_{i}"
        policies[policy_id] = (
            make_RandomPolicy(i),  # Use random policy with seed
            obs_space,
            act_space,
            {}
        )
    
    print('policies:', policies)
    print('policies_to_train:', policies_to_train)
    
    return policies, policies_to_train

# Policy mapping function - maps agent IDs to policy IDs
def policy_mapping_fn(agent_id, episode, worker, **kwargs):
    # Extract numeric ID from agent_id (assuming format like "agent_0", "agent_1", etc.)
    if isinstance(agent_id, str) and agent_id.startswith("agent_"):
        agent_num = int(agent_id.split("_")[1])
    else:
        agent_num = int(agent_id)
    return f"policy_{agent_num}"
    
def create_algorithm_config(env_name, obs_space, act_space, num_agents, num_trained_agents):
    """
    Create PPO algorithm configuration for multi-agent setup using Ray 2.4+ API.
    """
    
    # Get policies and training list
    policies, policies_to_train = create_multi_agent_config(
        obs_space, act_space, num_agents, num_trained_agents
    )
    
    # Create PPO configuration
    config = (
        PPOConfig()
        .environment(env=env_name)
        .multi_agent(
            policies=policies,
            policy_mapping_fn=policy_mapping_fn,
            policies_to_train=policies_to_train,
        )
        .framework("torch")  # or "tf2" depending on your preference
        .training(
            lr=5e-5,
            num_sgd_iter=10,
            sgd_minibatch_size=128,
            train_batch_size=4000,
        )
        .rollouts(
            num_rollout_workers=2,
            rollout_fragment_length=200,
        )
        .debugging(log_level="WARN")
    )
    
    return config


def create_and_train_algorithm(config, num_iterations=100):
    """
    Create and train the algorithm using the new Ray 2.4+ API.
    """
    
    # Build the algorithm
    algo = config.build()
    
    try:
        # Training loop
        for i in range(num_iterations):
            result = algo.train()
            
            # Print progress every 10 iterations
            if i % 10 == 0:
                print(f"Iteration {i}: "
                      f"Episode reward mean: {result.get('episode_reward_mean', 'N/A')}")
                
        print("Training completed!")
        
    finally:
        # Clean up
        algo.stop()
    
    return algo


# Example usage function
def example_usage():
    """
    Example of how to use the updated multi-agent setup.
    """
    
    # Example parameters (adjust according to your environment)
    env_name = "your_multi_agent_env"  # Replace with your actual environment
    # obs_space and act_space would come from your environment
    # obs_space = your_env.observation_space
    # act_space = your_env.action_space
    
    num_agents = 4
    num_trained_agents = 2
    
    # Uncomment and modify the following lines when you have your environment set up:
    
    # # Create configuration
    # config = create_algorithm_config(
    #     env_name, obs_space, act_space, num_agents, num_trained_agents
    # )
    
    # # Train the algorithm
    # trained_algo = create_and_train_algorithm(config, num_iterations=50)
    
    print("Example setup complete. Uncomment the lines above to run with your environment.")


if __name__ == "__main__":
    example_usage()