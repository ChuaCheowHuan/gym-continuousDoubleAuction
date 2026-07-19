import json
import matplotlib.pyplot as plt
import os
from collections import defaultdict
import numpy as np

def visualize_rewards(json_path='visualize/latest_episode_data.json'):
    """
    Plots the cumulative rewards for each agent from the episode data JSON file.
    """
    if not os.path.exists(json_path):
        print(f"Error: {json_path} not found.")
        return

    print(f"Loading data from {json_path}...")
    with open(json_path, 'r') as f:
        data = json.load(f)

    print(f"Processing {len(data)} steps...")
    
    # Use defaultdict to store individual rewards for each agent
    agent_rewards = defaultdict(list)
    
    for step in data:
        rewards = step.get('reward', {})
        for agent_id, reward_val in rewards.items():
            agent_rewards[agent_id].append(float(reward_val))

    if not agent_rewards:
        print("No reward data found for any agent.")
        return

    # Plotting
    plt.figure(figsize=(20, 10))
    
    # Sort agent IDs to ensure consistent legend order
    sorted_agents = sorted(agent_rewards.keys())
    
    for agent_id in sorted_agents:
        rewards_history = agent_rewards[agent_id]
        if rewards_history:
            # Calculate cumulative rewards
            cumulative_rewards = np.cumsum(rewards_history)
            plt.plot(cumulative_rewards, label=agent_id, linewidth=1.5)

    plt.title('Agent Cumulative Rewards Over Time')
    plt.xlabel('Step')
    plt.ylabel('Cumulative Reward')
    plt.axhline(y=0, color='black', linestyle='-', alpha=0.3)
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.tight_layout()

    output_file = 'visualize/cumulative_rewards_visualization.png'
    plt.savefig(output_file)
    print(f"Visualization saved to {output_file}")
    plt.show()

if __name__ == "__main__":
    visualize_rewards()
