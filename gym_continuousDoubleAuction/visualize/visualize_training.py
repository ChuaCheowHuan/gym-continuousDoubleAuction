import glob
import json
import os

import matplotlib.pyplot as plt
import numpy as np
from ray.rllib.utils.metrics import ENV_RUNNER_RESULTS

from gym_continuousDoubleAuction.config_loader import constant
from gym_continuousDoubleAuction.train.episode_record import REWARD_TERMS
from gym_continuousDoubleAuction.visualize.visualize_rewards import TERM_COLORS

PROGRESS_FILE = "progress.jsonl"

#: Status colors, reserved for the two discrete "something happened" events
#: this dashboard marks - never reused for a plain data series (dataviz
#: skill's status-palette rule).
_VIOLATION_COLOR = "#d03b3b"   # critical
_PROMOTION_COLOR = "#0ca30c"   # good


def default_log_root():
    """Where `progress.jsonl` lives, resolved like `episode_data`'s pair:
    the configured path if it exists, else the same name one directory up,
    which is what running from inside `visualize/` needs.
    """
    root = constant("visualize_paths", "training_log_dir")
    if os.path.isdir(root):
        return root
    return constant("visualize_paths", "training_log_fallback")


def latest_run_dir(root):
    """The most recently written run under `root` - the one whose
    `progress.jsonl` has the newest mtime.
    """
    run_dirs = [
        d for d in glob.glob(os.path.join(root, "*"))
        if os.path.isfile(os.path.join(d, PROGRESS_FILE))
    ]
    if not run_dirs:
        return None
    return max(run_dirs, key=lambda d: os.path.getmtime(os.path.join(d, PROGRESS_FILE)))


def load_progress(run_dir=None):
    """This run's `progress.jsonl`, one dict per training iteration, sorted.

    run_dir: a directory holding `progress.jsonl` directly, or its parent
        (the default) - in which case the most recently written run under it
        is used, the same convention `episode_data.load_episode` follows for
        the Parquet record.
    """
    if run_dir is None:
        root = default_log_root()
        run_dir = latest_run_dir(root)
        if run_dir is None:
            raise FileNotFoundError(
                f"no {PROGRESS_FILE} found under {root!r} - run training "
                "first, or pass run_dir explicitly"
            )

    path = run_dir if run_dir.endswith(".jsonl") else os.path.join(run_dir, PROGRESS_FILE)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"{path} does not exist")

    with open(path) as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    if not rows:
        raise ValueError(f"{path} contains no rows")

    rows.sort(key=lambda row: row["training_iteration"])
    return rows


def _env_runner_series(rows, key):
    """`(iterations, values)` for a metric logged through `on_episode_end`'s
    `metrics_logger` - these land under `result[ENV_RUNNER_RESULTS]` regardless
    of which process ran the episode (`train.nav_violations` reads the same
    way, for the same reason).
    """
    iterations, values = [], []
    for row in rows:
        value = (row.get(ENV_RUNNER_RESULTS) or {}).get(key)
        if value is None:
            continue
        iterations.append(row["training_iteration"])
        values.append(float(value))
    return np.array(iterations), np.array(values)


def _league_series(rows, key):
    """`(iterations, values)` for a league number, read from `result["league"]`.

    Not from the same-named `metrics_logger` values `on_train_result` also
    logs: RLlib compiles `result` before that hook runs, so a value logged
    there is one iteration late by the time it is reduced into a row.
    `result["league"]` is written directly into the result for the iteration
    it describes instead, precisely so `progress.jsonl` would have a
    same-iteration source (league_based_self_play_callback.py:883-905).
    """
    iterations, values = [], []
    for row in rows:
        value = (row.get("league") or {}).get(key)
        if value is None:
            continue
        iterations.append(row["training_iteration"])
        values.append(float(value))
    return np.array(iterations), np.array(values)


def _event_iterations(iterations, values, threshold=0.0):
    return [it for it, v in zip(iterations, values) if v > threshold]


def _mark_events(ax, iterations, color, label):
    """A dashed vertical line per iteration, labelled once so the legend
    picks up a single entry rather than one per occurrence.
    """
    for i, iteration in enumerate(iterations):
        ax.axvline(
            iteration, color=color, linestyle="--", linewidth=1.0, alpha=0.7,
            label=label if i == 0 else None,
        )


def _plot_nav_conservation(ax, rows):
    """`abs(total NAV - total initial cash)`, log-scaled - it should sit near
    float noise, so a scale that shows orders of magnitude is what makes a
    real break visible against that floor. Violations (the check actually
    failing, `nav_tolerance` exceeded) are marked as events rather than
    plotted as a value, since the metric that matters there is *whether*, not
    *how much*.
    """
    iterations, error = _env_runner_series(rows, "nav_conservation_error")
    if len(iterations):
        ax.plot(iterations, error, color="#2a78d6", linewidth=1.5, label="Conservation error")
        ax.set_yscale("log")

    viol_iterations, violations = _env_runner_series(rows, "nav_conservation_violations")
    _mark_events(ax, _event_iterations(viol_iterations, violations), _VIOLATION_COLOR, "Violation")

    ax.set_ylabel('|error| (log)')
    ax.set_title('NAV Conservation')
    ax.grid(True, linestyle='--', alpha=0.5)
    ax.legend(bbox_to_anchor=(1.01, 1), loc='upper left')


def _plot_league_return(ax, rows):
    """League mean return with a +/- 1 std band - one axis, since the band is
    the same quantity as the line, not a second measure. Champion promotions
    are marked as events on top: a training-return chart with no context for
    *why* a jump happened is a harder-to-read one than the same chart with
    that context.
    """
    iterations, mean = _league_series(rows, "mean_return")
    _, std = _league_series(rows, "std_return")
    if len(iterations):
        ax.plot(iterations, mean, color="#2a78d6", linewidth=1.5, label="Mean return")
        ax.fill_between(iterations, mean - std, mean + std, color="#2a78d6", alpha=0.15, label="+/- 1 std")

    promo_iterations, promoted = _league_series(rows, "promoted")
    _mark_events(ax, _event_iterations(promo_iterations, promoted), _PROMOTION_COLOR, "Champion promoted")

    ax.set_ylabel('Return')
    ax.set_title('League Return')
    ax.grid(True, linestyle='--', alpha=0.5)
    ax.legend(bbox_to_anchor=(1.01, 1), loc='upper left')


def _plot_reward_term_means(ax, rows):
    """The signed mean of each reward term, per iteration - a line chart, not
    stacked, for the same reason `visualize_reward_decomposition` isn't: the
    terms are mixed-sign, and stacking assumes they aren't.
    """
    for term, color in zip(REWARD_TERMS, TERM_COLORS):
        iterations, values = _env_runner_series(rows, f"reward_term_mean_{term}")
        if len(iterations):
            ax.plot(iterations, values, color=color, linewidth=1.5, label=term)

    ax.axhline(y=0, color='black', linestyle='-', alpha=0.3)
    ax.set_ylabel('Mean value')
    ax.set_title('Reward Term Means')
    ax.grid(True, linestyle='--', alpha=0.5)
    ax.legend(bbox_to_anchor=(1.01, 1), loc='upper left')


def _plot_reward_term_shares(ax, rows):
    """Each term's share of the reward's variance, stacked. Unlike the means
    above, a stack is honest here: `_log_reward_terms` normalises the five
    variances to sum to 1, so this genuinely is a part-to-whole quantity, not
    a signed decomposition forced into looking like one.

    Only iterations where all five terms reported a share are plotted - they
    are logged together in one call (`_log_reward_terms`), so this should
    never drop a real iteration, but a stack over mismatched x-values would
    silently misalign the terms if it ever did.
    """
    per_term = {
        term: dict(zip(*_env_runner_series(rows, f"reward_term_var_share_{term}")))
        for term in REWARD_TERMS
    }
    common_iterations = sorted(set.intersection(*(set(d) for d in per_term.values())))

    if common_iterations:
        values = [[per_term[term][it] for it in common_iterations] for term in REWARD_TERMS]
        ax.stackplot(common_iterations, values, colors=TERM_COLORS, labels=REWARD_TERMS, alpha=0.85)

    ax.set_ylim(0, 1)
    ax.set_ylabel('Variance share')
    ax.set_title('Reward Term Variance Share')
    ax.grid(True, linestyle='--', alpha=0.5)
    ax.legend(bbox_to_anchor=(1.01, 1), loc='upper left')


def _plot_behavior_fractions(ax, rows):
    """Three unrelated fractions that happen to share units and range: how
    often agents pass, how often their orders are refused, and the most
    maker-like agent's share of its own fills. One panel, since all three are
    already on the same [0, 1] scale.
    """
    fractions = (
        ("pass_action_fraction", "#2a78d6"),
        ("order_rejection_fraction", "#eb6834"),
        ("maker_fill_ratio_max", "#1baf7a"),
    )
    for key, color in fractions:
        iterations, values = _env_runner_series(rows, key)
        if len(iterations):
            ax.plot(iterations, values, color=color, linewidth=1.5, label=key)

    ax.set_ylim(0, 1)
    ax.set_ylabel('Fraction')
    ax.set_title('Behaviour Fractions')
    ax.grid(True, linestyle='--', alpha=0.5)
    ax.legend(bbox_to_anchor=(1.01, 1), loc='upper left')


def visualize_training(run_dir=None):
    """
    Plots training-health metrics across iterations, from `progress.jsonl`
    (`train._append_progress` writes the whole RLlib result dict, one line per
    iteration) - the one source with all 27 of doc/11's custom metrics, and
    the one thing in `visualize/` that reads training progress rather than a
    single recorded episode.

    Five panels, sharing an iteration axis: NAV conservation (with violation
    iterations marked), league return (with promotion iterations marked),
    reward term means, reward term variance share, and the pass/rejection/
    maker-fill behaviour fractions.

    run_dir defaults to the most recently written run under
    `config/tunable_constants.json` -> `visualize_paths.training_log_dir`.
    """
    rows = load_progress(run_dir)
    print(
        f"{len(rows)} iterations, {rows[0]['training_iteration']} to "
        f"{rows[-1]['training_iteration']}."
    )

    fig, (ax_nav, ax_league, ax_means, ax_shares, ax_fractions) = plt.subplots(
        5, 1, figsize=(14, 20), sharex=True,
    )

    _plot_nav_conservation(ax_nav, rows)
    _plot_league_return(ax_league, rows)
    _plot_reward_term_means(ax_means, rows)
    _plot_reward_term_shares(ax_shares, rows)
    _plot_behavior_fractions(ax_fractions, rows)

    ax_fractions.set_xlabel('Training Iteration')
    fig.suptitle('Training Health')
    plt.tight_layout(rect=[0, 0, 1, 0.98])

    output_file = 'visualize/chart/training_visualization.png'
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    plt.savefig(output_file)
    print(f"Visualization saved to {output_file}")
    plt.show()

if __name__ == "__main__":
    visualize_training()
