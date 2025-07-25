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
    
# def create_algorithm_config(env_name, obs_space, act_space, num_agents, num_trained_agents):
#     """
#     Create PPO algorithm configuration for multi-agent setup using Ray 2.4+ API.
#     """
    
#     # Get policies and training list
#     policies, policies_to_train = create_multi_agent_config(
#         obs_space, act_space, num_agents, num_trained_agents
#     )
    
#     # Create PPO configuration
#     config = (
#         PPOConfig()
#         .environment(env=env_name)
#         .multi_agent(
#             policies=policies,
#             policy_mapping_fn=policy_mapping_fn,
#             policies_to_train=policies_to_train,
#         )
#         .framework("torch")  # or "tf2" depending on your preference
#         .training(
#             lr=5e-5,
#             num_sgd_iter=10,
#             sgd_minibatch_size=128,
#             train_batch_size=4000,
#         )
#         .rollouts(
#             num_rollout_workers=2,
#             rollout_fragment_length=200,
#         )
#         .debugging(log_level="WARN")
#     )
    
#     return config


# def create_and_train_algorithm(config, num_iterations=100):
#     """
#     Create and train the algorithm using the new Ray 2.4+ API.
#     """
    
#     # Build the algorithm
#     algo = config.build()
    
#     try:
#         # Training loop
#         for i in range(num_iterations):
#             result = algo.train()
            
#             # Print progress every 10 iterations
#             if i % 10 == 0:
#                 print(f"Iteration {i}: "
#                       f"Episode reward mean: {result.get('episode_reward_mean', 'N/A')}")
                
#         print("Training completed!")
        
#     finally:
#         # Clean up
#         algo.stop()
    
#     return algo


# # Example usage function
# def example_usage():
#     """
#     Example of how to use the updated multi-agent setup.
#     """
    
#     # Example parameters (adjust according to your environment)
#     env_name = "your_multi_agent_env"  # Replace with your actual environment
#     # obs_space and act_space would come from your environment
#     # obs_space = your_env.observation_space
#     # act_space = your_env.action_space
    
#     num_agents = 4
#     num_trained_agents = 2
    
#     # Uncomment and modify the following lines when you have your environment set up:
    
#     # # Create configuration
#     # config = create_algorithm_config(
#     #     env_name, obs_space, act_space, num_agents, num_trained_agents
#     # )
    
#     # # Train the algorithm
#     # trained_algo = create_and_train_algorithm(config, num_iterations=50)
    
#     print("Example setup complete. Uncomment the lines above to run with your environment.")


# if __name__ == "__main__":
#     example_usage()