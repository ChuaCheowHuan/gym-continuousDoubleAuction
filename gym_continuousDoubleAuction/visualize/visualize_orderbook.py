import os

import numpy as np
import matplotlib.pyplot as plt

from gym_continuousDoubleAuction.config_loader import constant
from gym_continuousDoubleAuction.envs.exchg.state_helper import (
    PRIVATE_DIM,
    SNAPSHOT_DIM,
    obs_row_slice,
)
from gym_continuousDoubleAuction.visualize.episode_data import load_episode

def _newest_snapshot(obs):
    """The most recent book snapshot from a recorded observation.

    An observation is `n_hist` stacked snapshots followed by a per-agent
    private block:

        [ snapshot(t-n_hist+1) | ... | snapshot(t) | private ]

    So the newest snapshot ends at `n_hist * SNAPSHOT_DIM`, NOT at the end of
    the vector. `obs[-SNAPSHOT_DIM:]` returns the private block plus a
    truncated final snapshot, shifted by exactly PRIVATE_DIM - which raises
    nothing and plots private state as ask sizes. That is what this function
    exists to prevent; see 05_observation_space.md section 1.

    `n_hist` is derived from the vector rather than assumed, because a
    recording may have been made with a different window than the config
    currently names.
    """
    flat = np.asarray(obs)
    book_flat_dim = flat.size - PRIVATE_DIM
    n_hist, remainder = divmod(book_flat_dim, SNAPSHOT_DIM)
    if remainder or n_hist < 1:
        raise ValueError(
            f"Recorded observation of {flat.size} floats, less a "
            f"{PRIVATE_DIM}-float private block, leaves {book_flat_dim} - not "
            f"a whole number of {SNAPSHOT_DIM}-float snapshots. Either this "
            "recording did not come from this env, or observation_layout in "
            "tunable_constants.json changed after it was written."
        )
    return flat[(n_hist - 1) * SNAPSHOT_DIM : n_hist * SNAPSHOT_DIM]


def visualize_episode_data(run_dir=None, episode_id=None, agent_id=None):
    """
    Visualizes price and size changes for the orderbook, for one agent, over
    one episode, from the per-step Parquet record
    (`train.episode_record.EpisodeRecorder`).

    `best_bid`/`best_ask` are read straight off their own columns. Sizes have
    no column of their own, so they still come from the raw observation
    snapshot, which `_newest_snapshot` slices out. This reads a recorded
    observation rather than a live env, so it uses the module-level
    SNAPSHOT_DIM / PRIVATE_DIM instead of an instance attribute.

    Rows are addressed by name through `obs_row_slice`, which follows the
    process default `book_mode` (env_defaults.json): the two size rows over
    2 * k_rows + 1 tick offsets in `grid` mode, or the six `levels` rows.

    run_dir/episode_id default to the most recently recorded run/episode; see
    `episode_data.load_episode`.
    """
    if agent_id is None:
        agent_id = constant("visualize_paths", "default_agent_id")

    episode = load_episode(
        run_dir, episode_id, columns=["agent_id", "best_bid", "best_ask", "obs"],
    )
    episode = episode[episode["agent_id"] == agent_id]
    if episode.empty:
        print(f"No rows for agent {agent_id!r} in this episode.")
        return

    print(f"Episode {episode['episode_id'].iloc[0]}: {len(episode)} steps for {agent_id}.")

    best_bids = episode["best_bid"].to_numpy()
    best_asks = episode["best_ask"].to_numpy()

    total_bid_size = []
    total_ask_size = []
    for obs in episode["obs"]:
        snapshot = _newest_snapshot(obs)
        b_s = snapshot[obs_row_slice("bid_size")]
        a_s = snapshot[obs_row_slice("ask_size")]
        total_bid_size.append(b_s.sum())
        total_ask_size.append(a_s.sum())

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
    ax2.plot(range(len(total_bid_size)), total_bid_size, color='green', alpha=0.3, label='Total Bid Size')
    ax2.plot(range(len(total_ask_size)), total_ask_size, color='red', alpha=0.3, label='Total Ask Size')
    ax2.set_ylabel('Total Size (Volume)')
    ax2.set_xlabel('Step')
    ax2.set_title('Orderbook Cumulative Size Changes')
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()

    # Save or show
    output_plot = 'visualize/chart/orderbook_visualization.png'
    os.makedirs(os.path.dirname(output_plot), exist_ok=True)
    plt.savefig(output_plot)
    print(f"Plot saved to {output_plot}")
    plt.show()

if __name__ == "__main__":
    visualize_episode_data()
