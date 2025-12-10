"""
Debug script to inspect Ray 2.0+ result structure and policy configuration.

Run this to see what data is available in the training results.
"""

import gym
from ray.rllib.algorithms.ppo import PPOConfig
import ray

# Import league components
from gym_continuousDoubleAuction.train.policy.league_policies import (
    create_league_policies,
    get_league_policy_mapping_fn
)

# Initialize Ray
ray.init(ignore_reinit_error=True)

# Register environment
from gym.envs.registration import register
register(
    id='continuousDoubleAuction-v0',
    entry_point='gym_continuousDoubleAuction.envs:continuousDoubleAuctionEnv',
)

# Create dummy env to get spaces
dummy_env = gym.make('continuousDoubleAuction-v0', num_of_agents=3)
obs_space = dummy_env.observation_space[f'agent_0']
act_space = dummy_env.action_space[f'agent_0']
dummy_env.close()

# Create league policies
print("=" * 80)
print("Creating league policies...")
league_policies, policies_to_train = create_league_policies(
    num_agents=3,
    obs_space=obs_space,
    act_space=act_space,
)

print(f"\nPolicies created: {list(league_policies.keys())}")
print(f"Trainable: {policies_to_train}")
print("=" * 80)

# Create simple config
config = (
    PPOConfig()
    .environment(
        env='continuousDoubleAuction-v0',
        env_config={
            "num_of_agents": 3,
            "max_step": 32,
            "init_cash": 0,
        }
    )
    .multi_agent(
        policies=league_policies,
        policy_mapping_fn=get_league_policy_mapping_fn(num_agents=3),
        policies_to_train=policies_to_train,
    )
    .training(
        train_batch_size=512,
        sgd_minibatch_size=64,
    )
    .env_runners(num_env_runners=0)  # Use only local runner
)

print("\nBuilding algorithm...")
algo = config.build()

print("\n" + "=" * 80)
print("INSPECTING ALGORITHM STRUCTURE")
print("=" * 80)

# Check how to access policies
print(f"\nAlgorithm type: {type(algo)}")
print(f"Has env_runner_group: {hasattr(algo, 'env_runner_group')}")
print(f"Has workers: {hasattr(algo, 'workers')}")

if hasattr(algo, 'env_runner_group'):
    print(f"\nenv_runner_group type: {type(algo.env_runner_group)}")
    runner = algo.env_runner_group.local_env_runner()
    print(f"local_env_runner type: {type(runner)}")
    print(f"Has policy_map: {hasattr(runner, 'policy_map')}")
    print(f"Has module: {hasattr(runner, 'module')}")
    
    if hasattr(runner, 'policy_map'):
        print(f"\nPolicy map keys: {list(runner.policy_map.keys())}")

# Check config structure
print(f"\n\nConfig type: {type(algo.config)}")
print(f"Config has to_dict: {hasattr(algo.config, 'to_dict')}")

if hasattr(algo.config, 'to_dict'):
    config_dict = algo.config.to_dict()
    if 'multiagent' in config_dict:
        ma_config = config_dict['multiagent']
        print(f"\nMultiagent config policies: {list(ma_config.get('policies', {}).keys())}")

# Run one training iteration
print("\n" + "=" * 80)
print("RUNNING ONE TRAINING ITERATION")
print("=" * 80)

result = algo.train()

print(f"\nTop-level result keys:")
for key in sorted(result.keys()):
    print(f"  - {key}")

if 'env_runners' in result:
    print(f"\nenv_runners keys:")
    for key in sorted(result['env_runners'].keys()):
        value = result['env_runners'][key]
        print(f"  - {key}: {type(value).__name__}", end="")
        if isinstance(value, (int, float)):
            print(f" = {value}")
        elif isinstance(value, dict):
            print(f" (dict with keys: {list(value.keys())})")
        else:
            print()

# Check module_episode_returns_mean specifically
if 'env_runners' in result and 'module_episode_returns_mean' in result['env_runners']:
    mer = result['env_runners']['module_episode_returns_mean']
    print(f"\nmodule_episode_returns_mean:")
    print(f"  Type: {type(mer)}")
    print(f"  Value: {mer}")

# Clean up
algo.stop()
ray.shutdown()

print("\n" + "=" * 80)
print("DEBUG COMPLETE")
print("=" * 80)
