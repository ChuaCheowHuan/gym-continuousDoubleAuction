import json
import numpy as np
import matplotlib.pyplot as plt
import os

def visualize_episode_data(json_path='latest_episode_data.json', agent_id='agent_0'):
    """
    Visualizes price and size changes for the orderbook from episode data.
    """
    if not os.path.exists(json_path):
        print(f"Error: {json_path} not found.")
        return

    print(f"Loading data from {json_path}...")
    with open(json_path, 'r') as f:
        data = json.load(f)

    steps = len(data)
    print(f"Found {steps} steps in episode.")

    # Data containers
    bid_prices = []
    bid_sizes = []
    ask_prices = []
    ask_sizes = []
    
    # Best Bid/Ask for easier plotting
    best_bids = []
    best_asks = []

    for i, step in enumerate(data):
        obs = step.get('obs', {})
        if agent_id not in obs:
            continue
            
        # Observation structure: 40 elements
        # [0:10] Bid Prices
        # [10:20] Bid Sizes
        # [20:30] Ask Prices (negated)
        # [30:40] Ask Sizes (negated)
        agent_obs = np.array(obs[agent_id])
        
        b_p = agent_obs[0:10]
        b_s = agent_obs[10:20]
        a_p = -agent_obs[20:30] # Negated in env, restore to positive
        a_s = -agent_obs[30:40] # Negated in env, restore to positive
        
        bid_prices.append(b_p)
        bid_sizes.append(b_s)
        ask_prices.append(a_p)
        ask_sizes.append(a_s)
        
        # Best bid is index 0 (as per set_agg_LOB logic: reversed(...) for bids)
        # Best ask is index 0 (as per set_agg_LOB logic: items() for asks)
        best_bids.append(b_p[0] if b_p[0] > 0 else None)
        best_asks.append(a_p[0] if a_p[0] > 0 else None)

    # Convert to numpy arrays for easier manipulation
    bid_prices = np.array(bid_prices)
    bid_sizes = np.array(bid_sizes)
    ask_prices = np.array(ask_prices)
    ask_sizes = np.array(ask_sizes)

    # Plotting
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), sharex=True)

    # 1. Price Plot
    ax1.plot(best_bids, label='Best Bid', color='green', marker='o', markersize=2, linestyle='-')
    ax1.plot(best_asks, label='Best Ask', color='red', marker='o', markersize=2, linestyle='-')
    ax1.set_ylabel('Price')
    ax1.set_title(f'Orderbook Price Changes ({agent_id})')
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # 2. Size Plot (Total Volume)
    total_bid_size = np.sum(bid_sizes, axis=1)
    total_ask_size = np.sum(ask_sizes, axis=1)
    
    ax2.fill_between(range(len(total_bid_size)), total_bid_size, color='green', alpha=0.3, label='Total Bid Size')
    ax2.fill_between(range(len(total_ask_size)), total_ask_size, color='red', alpha=0.3, label='Total Ask Size')
    ax2.set_ylabel('Total Size (Volume)')
    ax2.set_xlabel('Step')
    ax2.set_title('Orderbook Cumulative Size Changes')
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    
    # Save or show
    output_plot = 'orderbook_visualization.png'
    plt.savefig(output_plot)
    print(f"Plot saved to {output_plot}")
    plt.show()

if __name__ == "__main__":
    visualize_episode_data()
