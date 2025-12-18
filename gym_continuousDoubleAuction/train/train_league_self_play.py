"""
Example training script demonstrating league-based self-play with Ray RLlib.

This script shows how to configure and run league-based self-play training
for the continuous double auction environment.

Usage:
    python train_league_self_play.py --num-agents 5 --stop-iters 100 --metric nav
"""

import argparse
import gym
from ray.rllib.algorithms.ppo import PPOConfig
import ray

# Import league-based self-play components
from gym_continuousDoubleAuction.train.callbk.league_based_self_play import LeagueBasedSelfPlayCallback
from gym_continuousDoubleAuction.train.policy.league_policies import (
    create_league_policies,
    get_league_policy_mapping_fn
)


def parse_args():
    parser = argparse.ArgumentParser(description='League-based self-play training')
    
    parser.add_argument('--num-agents', type=int, default=5,
                       help='Number of trading agents in environment')
    parser.add_argument('--stop-iters', type=int, default=100,
                       help='Number of training iterations')
    parser.add_argument('--win-rate-threshold', type=float, default=0.70,
                       help='Win rate threshold to create policy snapshots')
    parser.add_argument('--min-league-size', type=int, default=10,
                       help='Minimum league size (stop condition)')
    parser.add_argument('--metric', type=str, default='reward', choices=['reward', 'nav'],
                       help='Performance metric: reward or nav')
    parser.add_argument('--checkpoint-freq', type=int, default=10,
                       help='Checkpoint frequency (iterations)')
    parser.add_argument('--num-workers', type=int, default=2,
                       help='Number of rollout workers')
    
    return parser.parse_args()


def main():
    args = parse_args()
    
    print("=" * 80)
    print("League-Based Self-Play Training for Continuous Double Auction")
    print("=" * 80)
    print(f"Configuration:")
    print(f"  Num agents: {args.num_agents}")
    print(f"  Num iterations: {args.stop_iters}")
    print(f"  Win rate threshold: {args.win_rate_threshold}")
    print(f"  Min league size: {args.min_league_size}")
    print(f"  Performance metric: {args.metric}")
    print("=" * 80)
    
    # Initialize Ray
    ray.init(ignore_reinit_error=True)
    
    # Register the environment
    from gym.envs.registration import register
    register(
        id='continuousDoubleAuction-v0',
        entry_point='gym_continuousDoubleAuction.envs:continuousDoubleAuctionEnv',
    )
    
    # Create a dummy env to get spaces
    dummy_env = gym.make('continuousDoubleAuction-v0', 
                        num_of_agents=args.num_agents)
    obs_space = dummy_env.observation_space[f'agent_0']
    act_space = dummy_env.action_space[f'agent_0']
    dummy_env.close()
    
    # Create league policies
    league_policies, policies_to_train = create_league_policies(
        num_agents=args.num_agents,
        obs_space=obs_space,
        act_space=act_space,
        model_name="model_disc"  # Assumes you have a custom model registered
    )
    
    # Create policy mapping function
    league_mapping_fn = get_league_policy_mapping_fn(num_agents=args.num_agents)
    
    # Configure PPO algorithm
    config = (
        PPOConfig()
        .environment(
            env='continuousDoubleAuction-v0',
            env_config={
                "num_of_agents": args.num_agents,
                "max_step": 64,
                "init_cash": 0,
                "tick_size": 1,
                "tape_display_length": 10,
                "is_render": False,  # Disable rendering during training
            }
        )
        .callbacks(
            lambda: LeagueBasedSelfPlayCallback(
                win_rate_threshold=args.win_rate_threshold,
                num_agents=args.num_agents,
                metric=args.metric
            )
        )
        .multi_agent(
            policies=league_policies,
            policy_mapping_fn=league_mapping_fn,
            policies_to_train=policies_to_train,
        )
        .training(
            lr=5e-5,
            num_sgd_iter=30,
            sgd_minibatch_size=128,
            train_batch_size=4000,
        )
        .rollouts(
            num_rollout_workers=args.num_workers,
            rollout_fragment_length=200,
        )
        .debugging(log_level="ERROR")
        .resources(
            num_gpus=0,  # Set to 1 if GPU available
        )
    )
    
    # Build algorithm
    print("\nBuilding algorithm...")
    algo = config.build()
    
    try:
        # Training loop
        print("\nStarting training...")
        print("=" * 80)
        
        for iteration in range(args.stop_iters):
            result = algo.train()
            
            # Print progress
            print(f"\nIteration {iteration + 1}/{args.stop_iters}:")
            print(f"  Episode reward mean: {result.get('episode_reward_mean', 'N/A'):.2f}")
            print(f"  Episode length mean: {result.get('episode_len_mean', 'N/A'):.1f}")
            print(f"  League size: {result.get('custom_metrics', {}).get('league_size', 'N/A')}")
            print(f"  Trainable policies: {result.get('custom_metrics', {}).get('num_trainable_policies', 'N/A')}")
            
            # Checkpoint
            if (iteration + 1) % args.checkpoint_freq == 0:
                checkpoint_path = algo.save()
                print(f"  Checkpoint saved: {checkpoint_path}")
            
            # Check stop condition
            league_size = result.get('custom_metrics', {}).get('league_size', 0)
            if league_size >= args.min_league_size:
                print(f"\nReached minimum league size ({league_size} >= {args.min_league_size})")
                print("Training complete!")
                break
        
        # Final checkpoint
        final_checkpoint = algo.save()
        print(f"\nFinal checkpoint saved: {final_checkpoint}")
        
    finally:
        # Clean up
        algo.stop()
        ray.shutdown()
    
    print("\n" + "=" * 80)
    print("Training finished successfully!")
    print("=" * 80)


if __name__ == "__main__":
    main()
