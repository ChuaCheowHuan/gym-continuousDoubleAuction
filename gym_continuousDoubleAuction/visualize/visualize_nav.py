import os

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

    output_file = 'visualize/chart/nav_visualization.png'
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    plt.savefig(output_file)
    print(f"Visualization saved to {output_file}")
    plt.show()


def visualize_nav_drawdown(run_dir=None, episode_id=None):
    """
    Plots each agent's NAV against its running peak (`max_nav`) over one
    episode, one small-multiple panel per agent, with the gap between them
    shaded - `drawdown` is exactly `max(0, max_nav - nav)`
    (`reward_helper.Reward_Helper.set_reward`), so the shaded region *is* the
    drawdown, in NAV's own units. That is what keeps this on one axis per
    panel: drawdown needs no second scale because it is not a separate
    quantity, just the distance between two things already measured in NAV.

    Small multiples rather than one shared panel: overlaying N agents' NAV,
    peak, and shading together (as `visualize_nav` does for NAV alone) would
    be unreadable once the fills start crossing.

    run_dir/episode_id default to the most recently recorded run/episode; see
    `episode_data.load_episode`.
    """
    episode = load_episode(run_dir, episode_id, columns=["agent_id", "nav", "max_nav"])
    print(
        f"Episode {episode['episode_id'].iloc[0]}: {len(episode)} rows, "
        f"{episode['agent_id'].nunique()} agents."
    )

    sorted_agents = sorted(episode["agent_id"].unique())
    fig, axes = plt.subplots(
        len(sorted_agents), 1, figsize=(14, 2.5 * len(sorted_agents)), sharex=True,
    )
    if len(sorted_agents) == 1:
        axes = [axes]

    for ax, agent_id in zip(axes, sorted_agents):
        rows = episode[episode["agent_id"] == agent_id]
        nav = rows["nav"].to_numpy()
        peak = rows["max_nav"].to_numpy()
        steps = range(len(rows))

        ax.plot(steps, nav, label="NAV", color="#2a78d6", linewidth=1.5)
        ax.plot(steps, peak, label="Running peak", color="#898781", linestyle="--", linewidth=1.0)
        ax.fill_between(
            steps, nav, peak, where=peak >= nav,
            color="#d03b3b", alpha=0.15, label="Drawdown",
        )
        ax.set_ylabel(agent_id)
        ax.grid(True, linestyle='--', alpha=0.5)

    axes[0].legend(bbox_to_anchor=(1.01, 1), loc='upper left')
    axes[-1].set_xlabel('Step')
    fig.suptitle('Agent NAV vs. Running Peak (drawdown shaded)')
    plt.tight_layout()

    output_file = 'visualize/chart/nav_drawdown_visualization.png'
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    plt.savefig(output_file)
    print(f"Visualization saved to {output_file}")
    plt.show()

if __name__ == "__main__":
    visualize_nav()
    visualize_nav_drawdown()
