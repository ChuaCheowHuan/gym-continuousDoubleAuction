import json
import matplotlib.pyplot as plt
import os
from collections import defaultdict

def visualize_nav(json_path='latest_episode_data.json'):
    """
    Plots the NAV for each agent from the episode data JSON file.
    """
    if not os.path.exists(json_path):
        # Fallback to local directory if relative path fails
        if os.path.exists('latest_episode_data.json'):
            json_path = 'latest_episode_data.json'
        else:
            print(f"Error: {json_path} not found.")
            return

    print(f"Loading data from {json_path}...")
    with open(json_path, 'r') as f:
        data = json.load(f)

    print(f"Processing {len(data)} steps...")
    
    # Use defaultdict to store NAV history for each agent
    agent_navs = defaultdict(list)
    
    for step in data:
        info = step.get('info', {})
        for agent_id, agent_info in info.items():
            if 'NAV' in agent_info:
                try:
                    # Convert string NAV to float
                    nav_val = float(agent_info['NAV'])
                    agent_navs[agent_id].append(nav_val)
                except ValueError:
                    print(f"Warning: Could not convert NAV '{agent_info['NAV']}' to float for {agent_id}.")

    if not agent_navs:
        print("No NAV data found for any agent.")
        return

    # Plotting
    plt.figure(figsize=(12, 6))
    
    # Sort agent IDs to ensure consistent legend order
    sorted_agents = sorted(agent_navs.keys())
    
    for agent_id in sorted_agents:
        nav_history = agent_navs[agent_id]
        if nav_history:
            plt.plot(nav_history, label=agent_id, linewidth=1.5)

    plt.title('Agent Net Asset Value (NAV) Over Time')
    plt.xlabel('Step')
    plt.ylabel('NAV')
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.tight_layout()

    output_file = 'nav_visualization.png'
    plt.savefig(output_file)
    print(f"Visualization saved to {output_file}")
    plt.show()

if __name__ == "__main__":
    visualize_nav()
