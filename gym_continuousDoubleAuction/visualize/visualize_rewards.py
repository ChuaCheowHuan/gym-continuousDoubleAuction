import matplotlib.pyplot as plt
import numpy as np

from gym_continuousDoubleAuction.config_loader import constant
from gym_continuousDoubleAuction.train.episode_record import REWARD_TERMS
from gym_continuousDoubleAuction.visualize.episode_data import load_episode

#: The categorical palette's first five slots, in a fixed order that never
#: changes with the data - each reward term keeps the same color across every
#: episode and every run, which is what makes the legend readable at a glance.
#: Public (not `_`-prefixed) so `visualize_training.py` can plot the same
#: terms, aggregated over training, in matching colors.
TERM_COLORS = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4")


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


def visualize_reward_decomposition(run_dir=None, episode_id=None, agent_id=None):
    """
    Plots one agent's cumulative reward, split into its five signed terms, over
    one episode. The terms (`reward_helper.Reward_Helper.set_reward`) sum to
    the reward by construction, so this is a decomposition, not an estimate.

    A stacked-area chart would misrepresent this: `nav_term` can be either
    sign, `order_penalty`/`trade_penalty`/`drawdown_penalty` are always <= 0,
    `passive_bonus` is always >= 0, and stacking assumes same-signed parts of
    a whole. Cumulative lines per term, against the actual total as a
    reference, stay honest about sign and are a direct visual check that the
    terms really do add up to the reward recorded for this agent.

    agent_id defaults to `visualize_paths.default_agent_id`, matching
    `visualize_orderbook.py`: decomposing every agent's five terms in one
    panel would be unreadable, so this is a single-agent, one-episode view.

    run_dir/episode_id default to the most recently recorded run/episode; see
    `episode_data.load_episode`.
    """
    if agent_id is None:
        agent_id = constant("visualize_paths", "default_agent_id")

    term_columns = [f"reward_term_{term}" for term in REWARD_TERMS]
    episode = load_episode(run_dir, episode_id, columns=["agent_id", "reward"] + term_columns)
    episode = episode[episode["agent_id"] == agent_id]
    if episode.empty:
        print(f"No rows for agent {agent_id!r} in this episode.")
        return

    print(f"Episode {episode['episode_id'].iloc[0]}: {len(episode)} steps for {agent_id}.")

    plt.figure(figsize=(20, 10))

    for term, color in zip(REWARD_TERMS, TERM_COLORS):
        values = episode[f"reward_term_{term}"].fillna(0.0).to_numpy()
        plt.plot(np.cumsum(values), label=term, color=color, linewidth=2.0)

    total = episode["reward"].fillna(0.0).to_numpy()
    plt.plot(
        np.cumsum(total), label="reward (total)",
        color="black", linestyle="--", linewidth=1.5, alpha=0.7,
    )

    plt.title(f'Cumulative Reward Decomposition ({agent_id})')
    plt.xlabel('Step')
    plt.ylabel('Cumulative Value')
    plt.axhline(y=0, color='black', linestyle='-', alpha=0.3)
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.tight_layout()

    output_file = 'visualize/reward_decomposition_visualization.png'
    plt.savefig(output_file)
    print(f"Visualization saved to {output_file}")
    plt.show()

if __name__ == "__main__":
    visualize_rewards()
    visualize_reward_decomposition()
