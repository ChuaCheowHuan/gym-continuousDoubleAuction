"""
Example usage of league-based self-play with champion snapshotting.

This script demonstrates how to configure and run training with the updated
SelfPlayCallback that creates frozen champion snapshots instead of copying weights.
"""

from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import SelfPlayCallback
from gym_continuousDoubleAuction.train.policy.policy_handler import (
    create_multi_agent_config, 
    RandomPolicy
)
from ray.rllib.algorithms.ppo import PPOConfig
from ray.rllib.policy.policy import PolicySpec
import ray

# Initialize Ray
ray.init(ignore_reinit_error=True)

# Environment configuration
env_config = {
    'num_of_agents': 4,
    'init_cash': 1000000,
    'tick_size': 1,
    'tape_display_length': 10,
    'max_step': 1024,
    'is_render': False
}

# Create callback instance with champion configuration
callback = SelfPlayCallback(
    std_dev_multiplier=2.0,      # Snapshot when return > mean + 2*std
    max_champions=5,             # Keep last 5 champions (rolling window)
)

# Set up policies (2 trainable + 2 random)
policies = {
    "policy_0": PolicySpec(
        policy_class=None,  # Use default PPO
        observation_space=None,  # Will be inferred from env
        action_space=None,       # Will be inferred from env
        config={"model": {"custom_model": "model_disc"}}
    ),
    "policy_1": PolicySpec(
        policy_class=None,
        observation_space=None,
        action_space=None,
        config={"model": {"custom_model": "model_disc"}}
    ),
    "policy_2": PolicySpec(
        policy_class=RandomPolicy,
        observation_space=None,
        action_space=None,
    ),
    "policy_3": PolicySpec(
        policy_class=RandomPolicy,
        observation_space=None,
        action_space=None,
    ),
}

# Configure PPO algorithm with league-based self-play
config = (
    PPOConfig()
    .environment("continuousDoubleAuction-v0", env_config=env_config)
    .framework("torch")
    .training(
        lr=5e-5,
        num_epochs=4,
        minibatch_size=128,
        train_batch_size=4096,
    )
    .env_runners(
        num_env_runners=0,  # Use local runner only for testing
        num_envs_per_env_runner=1,
    )
    .multi_agent(
        policies=policies,
        policy_mapping_fn=SelfPlayCallback.get_mapping_fn(callback),
        policies_to_train=["policy_0", "policy_1"],  # Only these are trainable
    )
    .callbacks(lambda: callback)
    .debugging(log_level="INFO")
)

# Build algorithm
algo = config.build()

print("\n" + "="*80)
print("LEAGUE-BASED SELF-PLAY TRAINING")
print("="*80)
print(f"Std Dev Multiplier: {callback.std_dev_multiplier}")
print(f"Max champions: {callback.max_champions}")
print(f"Trainable policies: policy_0, policy_1")
print(f"Fixed policies: policy_2 (random), policy_3 (random)")
print("="*80 + "\n")

# Training loop
num_iterations = 100

for i in range(num_iterations):
    result = algo.train()
    
    # Print progress
    league_size = 2 + callback.champion_count
    agent_returns = result['env_runners']['agent_episode_returns_mean']
    
    print(f"\n{'='*80}")
    print(f"Iteration {i+1}/{num_iterations}")
    print(f"League size: {league_size} (2 trainable + {callback.champion_count} champions)")
    print(f"Agent returns: {agent_returns}")
    print(f"Champions: {[c['id'] for c in callback.champion_history]}")
    print(f"{'='*80}")
    
    # Save checkpoint every 20 iterations
    if (i + 1) % 20 == 0:
        checkpoint_path = algo.save()
        print(f"\n💾 Checkpoint saved: {checkpoint_path}\n")

# Final results
print("\n" + "="*80)
print("TRAINING COMPLETE")
print("="*80)
print(f"Final league size: {2 + callback.champion_count}")
print(f"Total champions created: {len(callback.champion_history)}")
print("\nChampion history:")
for champ in callback.champion_history:
    print(f"  - {champ['id']}: {champ['source_policy']} @ iter {champ['iteration']} "
          f"(return={champ['return']:.2f})")
print("="*80 + "\n")

# Cleanup
algo.stop()
ray.shutdown()
