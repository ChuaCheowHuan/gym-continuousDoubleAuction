import matplotlib.pyplot as plt

from gym_continuousDoubleAuction.visualize.episode_data import load_episode


def visualize_nav(run_dir=None, episode_id=None):
    """
    Plots the NAV for each agent over one episode, from the per-step Parquet
    record (`train.episode_record.EpisodeRecorder`).

    run_dir/episode_id default to the most recently recorded run/episode; see
    `episode_data.load_episode`.
    """
    episode = load_episode(run_dir, episode_id, columns=["agent_id", "nav"])
    print(
        f"Episode {episode['episode_id'].iloc[0]}: {len(episode)} rows, "
        f"{episode['agent_id'].nunique()} agents."
    )

    plt.figure(figsize=(20, 10))

    sorted_agents = sorted(episode["agent_id"].unique())

    linestyles = ['-', '--', '-.', ':', (0, (3, 5, 1, 5, 1, 5)), (0, (5, 10)), (0, (1, 10))]

    for i, agent_id in enumerate(sorted_agents):
        nav_history = episode.loc[episode["agent_id"] == agent_id, "nav"].to_numpy()
        style = linestyles[i % len(linestyles)]
        plt.plot(nav_history, label=agent_id, linewidth=2.0, linestyle=style)

    plt.title('Agent Net Asset Value (NAV) Over Time')
    plt.xlabel('Step')
    plt.ylabel('NAV')
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.tight_layout()

    output_file = 'visualize/nav_visualization.png'
    plt.savefig(output_file)
    print(f"Visualization saved to {output_file}")
    plt.show()

if __name__ == "__main__":
    visualize_nav()
