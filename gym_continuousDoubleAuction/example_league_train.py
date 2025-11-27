"""
Example: Minimal League-Based Self-Play Training

Demonstrates how to use MinimalLeagueCallback for league-based self-play
in the multi-agent trading environment.
"""

import ray
from ray.rllib.algorithms.ppo import PPOConfig
import gymnasium as gym

# Import the trading environment
import gym_continuousDoubleAuction
from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import continuousDoubleAuctionEnv

# Import the minimal league callback
from gym_continuousDoubleAuction.train.callbk.minimal_league_callback import MinimalLeagueCallback


def policy_mapping_fn(agent_id, episode, **kwargs):
    """
    Map agents to policies.
    For this example, we use a simple mapping where agent_X -> policy_X
    """
    # Extract agent number from agent_id (e.g., "agent_0" -> 0)
    agent_num = int(agent_id.split('_')[1])
    return f"policy_{agent_num}"


def main():
    """
    Main training function demonstrating league-based self-play.
    """
    
    # Initialize Ray
    ray.init(ignore_reinit_error=True, num_cpus=4)
    
    print("=" * 80)
    print("Minimal League-Based Self-Play Training Example")
    print("=" * 80)
    
    # Environment configuration
    env_config = {
        "num_of_agents": 4,
        "init_cash": 10000,
        "tick_size": 1,
        "tape_display_length": 10,
        "max_step": 50,  # Short episodes for faster iteration
        "is_render": False,  # Disable rendering for faster training
    }
    
    # Create environment to get spaces
    temp_env = continuousDoubleAuctionEnv(config=env_config)
    obs_space = temp_env.observation_space["agent_0"]
    act_space = temp_env.action_space["agent_0"]
    
    print(f"\nEnvironment Configuration:")
    print(f"  Agents: {env_config['num_of_agents']}")
    print(f"  Max steps per episode: {env_config['max_step']}")
    print(f"  Observation space: {obs_space}")
    print(f"  Action space: {act_space}")
    
    # Define policies - 2 trainable, 2 fixed (for diverse initial opponents)
    num_trainable = 2
    policies = {f"policy_{i}": (None, obs_space, act_space, {}) 
                for i in range(env_config['num_of_agents'])}
    
    # Only train first 2 policies
    policies_to_train = [f"policy_{i}" for i in range(num_trainable)]
    
    print(f"\nPolicy Configuration:")
    print(f"  Total policies: {len(policies)}")
    print(f"  Trainable policies: {policies_to_train}")
    print(f"  Fixed policies: {[p for p in policies.keys() if p not in policies_to_train]}")
    
    # Create the minimal league callback
    # Set return threshold low for demonstration (will trigger league expansion)
    league_callback = MinimalLeagueCallback(
        return_threshold=100.0,  # Adjust based on your reward scale
        check_every_n_iters=3,   # Check for league updates every 3 iterations
    )
    
    print(f"\nLeague Configuration:")
    print(f"  Return threshold: {league_callback.return_threshold}")
    print(f"  Check frequency: every {league_callback.check_every_n_iters} iterations")
    
    # Configure PPO algorithm
    config = (
        PPOConfig()
        .environment(
            env=continuousDoubleAuctionEnv,
            env_config=env_config,
        )
        .multi_agent(
            policies=policies,
            policy_mapping_fn=policy_mapping_fn,
            policies_to_train=policies_to_train,
        )
        .env_runners(
            num_env_runners=2,
            num_envs_per_env_runner=1,
        )
        .training(
            train_batch_size=400,
            sgd_minibatch_size=64,
            num_sgd_iter=10,
            lr=5e-4,
        )
        .callbacks(league_callback)
        .framework("torch")
        .resources(
            num_gpus=0,
        )
        .debugging(log_level="WARN")
    )
    
    # Build the algorithm
    print("\n" + "=" * 80)
    print("Building PPO algorithm...")
    print("=" * 80)
    algo = config.build()
    
    # Training loop
    num_iterations = 20
    print(f"\nStarting training for {num_iterations} iterations...\n")
    
    try:
        for i in range(num_iterations):
            print(f"\n{'='*80}")
            print(f"Iteration {i+1}/{num_iterations}")
            print(f"{'='*80}")
            
            # Train
            result = algo.train()
            
            # Extract and display metrics
            env_runner_results = result.get('env_runners', {})
            episode_reward_mean = env_runner_results.get('episode_return_mean', 'N/A')
            agent_returns = env_runner_results.get('agent_episode_returns_mean', {})
            
            print(f"\n  Overall episode return mean: {episode_reward_mean}")
            
            if agent_returns:
                print(f"  Agent returns:")
                for agent_id, ret in sorted(agent_returns.items()):
                    print(f"    {agent_id}: {ret:.2f}")
            
            # Display league stats
            league_stats = league_callback.get_league_stats()
            print(f"\n  League Stats:")
            print(f"    Total league size: {league_stats['league_size']}")
            print(f"    Trainable policies: {league_stats['num_trainable']}")
            print(f"    Frozen opponents: {league_stats['num_frozen']}")
            if league_stats['league_opponents']:
                print(f"    Opponents: {league_stats['league_opponents']}")
            
            # Check if league expanded
            if result.get('league_size', 0) > league_stats['num_trainable']:
                print(f"\n  🎉 League expanded! New opponents added.")
    
    except KeyboardInterrupt:
        print("\n\nTraining interrupted by user.")
    
    except Exception as e:
        print(f"\n\nError during training: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Cleanup
        print("\n" + "=" * 80)
        print("Stopping algorithm and shutting down Ray...")
        print("=" * 80)
        algo.stop()
        ray.shutdown()
        print("\nTraining complete!")


if __name__ == "__main__":
    main()
