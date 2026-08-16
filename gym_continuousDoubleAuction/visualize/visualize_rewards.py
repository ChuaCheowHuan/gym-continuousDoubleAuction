import matplotlib.pyplot as plt
import numpy as np

from gym_continuousDoubleAuction.visualize.episode_data import load_episode


def visualize_rewards(run_dir=None, episode_id=None):
    """
    Plots the cumulative reward for each agent over one episode, from the
    per-step Parquet record (`train.episode_record.EpisodeRecorder`).

    run_dir/episode_id default to the most recently recorded run/episode; see
    `episode_data.load_episode`.
    """
    episode = load_episode(run_dir, episode_id, columns=["agent_id", "reward"])
    print(
        f"Episode {episode['episode_id'].iloc[0]}: {len(episode)} rows, "
        f"{episode['agent_id'].nunique()} agents."
    )

    plt.figure(figsize=(20, 10))

    sorted_agents = sorted(episode["agent_id"].unique())

    for agent_id in sorted_agents:
        rewards_history = episode.loc[episode["agent_id"] == agent_id, "reward"].fillna(0.0).to_numpy()
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
