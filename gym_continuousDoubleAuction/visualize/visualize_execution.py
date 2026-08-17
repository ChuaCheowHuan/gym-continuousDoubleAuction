import matplotlib.pyplot as plt
import numpy as np

from gym_continuousDoubleAuction.config_loader import constant
from gym_continuousDoubleAuction.visualize.episode_data import load_episode

#: Fixed per-quantity colors. `REJECTED`/`MAKER` deliberately match the
#: rejection-rate/maker-share colors in the rates panel below - same concept,
#: one a running count and the other a rate, so the same hue across both
#: panels of this figure reads as the same thing rather than two unrelated
#: series that happen to share a color.
#:
#: The three rate colors are public for the same reason `TERM_COLORS` is:
#: `visualize_modules.py` plots these same three fractions aggregated per
#: module, and a rate that changes color between the per-episode view and the
#: per-module one reads as a different quantity.
_PLACED_COLOR = "#008300"    # green - a successful, non-rejected order
REJECTED_COLOR = "#eb6834"   # orange
_TRADES_COLOR = "#4a3aa7"    # violet - the "total fills" line, no rate counterpart
MAKER_COLOR = "#1baf7a"      # aqua
PASS_COLOR = "#2a78d6"       # blue - only appears in the rates panel


def visualize_execution_quality(run_dir=None, episode_id=None, agent_id=None, window=50):
    """
    Plots one agent's order/fill activity over one episode, from the per-step
    Parquet record (`train.episode_record.EpisodeRecorder`): how much it
    traded, how much of that was maker (passive) fills, and how often its
    orders were rejected - the things a return alone cannot distinguish (an
    agent that stopped trading and one that kept trying and kept getting
    refused both show a flat NAV).

    Two panels, one axis each:
      - Cumulative counts: orders placed, orders rejected, trades, and
        passive (maker) fills. All non-negative running totals in the same
        unit (orders/fills), so plain lines - unlike the reward terms, there
        is no sign to misrepresent by NOT stacking them, but they are not a
        part of one whole either (`num_trades_step` already counts both
        sides of a fill, so it is not a peer of the other three, and stacking
        would double-count fills that are also maker fills).
      - Rolling rates: pass / rejection / maker-share, each a ratio of two
        per-step counters (num_rejected_step over agent-steps, etc.) rather
        than a mean of noisy per-step ratios - the same convention
        `league_based_self_play_callback._log_activity` uses for the
        training-level versions of these same fractions, just at episode
        rather than iteration granularity. All three are already on [0, 1],
        so one panel, no second axis.

    agent_id defaults to `visualize_paths.default_agent_id`, matching
    `visualize_orderbook.py` and `visualize_reward_decomposition`: this is a
    single-agent, one-episode view.

    window: rolling window, in steps, for the rates panel. Per-step ratios
        are mostly 0/0 or 1/0 - order/rejection/trade events are sparse
        relative to `max_step` - so a raw per-step rate is unreadable noise;
        summing numerator and denominator over a window before dividing is
        what makes the trend visible.

    run_dir/episode_id default to the most recently recorded run/episode; see
    `episode_data.load_episode`.
    """
    if agent_id is None:
        agent_id = constant("visualize_paths", "default_agent_id")

    columns = [
        "agent_id", "order_step_placed", "num_rejected_step",
        "num_trades_step", "num_passive_fills_step", "is_pass_action",
    ]
    episode = load_episode(run_dir, episode_id, columns=columns)
    episode = episode[episode["agent_id"] == agent_id]
    if episode.empty:
        print(f"No rows for agent {agent_id!r} in this episode.")
        return

    print(f"Episode {episode['episode_id'].iloc[0]}: {len(episode)} steps for {agent_id}.")

    placed = episode["order_step_placed"].fillna(0).to_numpy()
    rejected = episode["num_rejected_step"].fillna(0).to_numpy()
    trades = episode["num_trades_step"].fillna(0).to_numpy()
    passive = episode["num_passive_fills_step"].fillna(0).to_numpy()
    is_pass = episode["is_pass_action"].fillna(False).to_numpy().astype(float)

    fig, (ax_counts, ax_rates) = plt.subplots(2, 1, figsize=(14, 10), sharex=True)

    # --- Panel 1: cumulative counts ---
    ax_counts.plot(np.cumsum(placed), color=_PLACED_COLOR, linewidth=1.5, label="Orders placed")
    ax_counts.plot(np.cumsum(rejected), color=REJECTED_COLOR, linewidth=1.5, label="Orders rejected")
    ax_counts.plot(np.cumsum(trades), color=_TRADES_COLOR, linewidth=1.5, label="Trades (both sides)")
    ax_counts.plot(np.cumsum(passive), color=MAKER_COLOR, linewidth=1.5, label="Passive (maker) fills")
    ax_counts.set_ylabel('Cumulative count')
    ax_counts.set_title(f'Order & Fill Activity ({agent_id})')
    ax_counts.grid(True, linestyle='--', alpha=0.5)
    ax_counts.legend(bbox_to_anchor=(1.01, 1), loc='upper left')

    # --- Panel 2: rolling rates ---
    steps = len(episode)
    w = max(1, min(window, steps))

    def rolling_ratio(numerator, denominator):
        num = np.convolve(numerator, np.ones(w), mode="valid")
        den = np.convolve(denominator, np.ones(w), mode="valid")
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(den > 0, num / den, np.nan)

    ones = np.ones(steps)
    pass_rate = rolling_ratio(is_pass, ones)
    rejection_rate = rolling_ratio(rejected, ones)
    maker_share = rolling_ratio(passive, trades)

    x = np.arange(w - 1, steps)
    ax_rates.plot(x, pass_rate, color=PASS_COLOR, linewidth=1.5, label="Pass rate")
    ax_rates.plot(x, rejection_rate, color=REJECTED_COLOR, linewidth=1.5, label="Rejection rate")
    ax_rates.plot(x, maker_share, color=MAKER_COLOR, linewidth=1.5, label="Maker share")
    ax_rates.set_ylim(0, 1)
    ax_rates.set_ylabel(f'Rate ({w}-step rolling)')
    ax_rates.set_xlabel('Step')
    ax_rates.set_title('Behaviour Rates')
    ax_rates.grid(True, linestyle='--', alpha=0.5)
    ax_rates.legend(bbox_to_anchor=(1.01, 1), loc='upper left')

    plt.tight_layout()

    output_file = 'visualize/execution_quality_visualization.png'
    plt.savefig(output_file)
    print(f"Visualization saved to {output_file}")
    plt.show()

if __name__ == "__main__":
    visualize_execution_quality()
