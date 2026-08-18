import os

import matplotlib.pyplot as plt
import numpy as np

from gym_continuousDoubleAuction.config_loader import flat
from gym_continuousDoubleAuction.train.policy.policy_handler import (
    CHAMPION_PREFIX,
    POLICY_PREFIX,
)
from gym_continuousDoubleAuction.visualize.episode_data import load_run
from gym_continuousDoubleAuction.visualize.visualize_execution import (
    MAKER_COLOR,
    PASS_COLOR,
    REJECTED_COLOR,
)

#: The three module families, in the order they are laid out on the x axis,
#: with the color each is drawn in. Three categorical slots, not one per
#: module: the number of modules grows with every champion promoted, and a
#: palette that runs out is the thing the dataviz series cap exists to
#: prevent. The family is also the comparison that is actually being made -
#: "did the champion beat the random baseline" is a question about families.
FAMILIES = ("trainable", "baseline", "champion")
_FAMILY_COLORS = {
    "trainable": "#2a78d6",   # blue
    "baseline": "#898781",    # muted gray - the do-nothing reference
    "champion": "#eb6834",    # orange
}


def module_family(module_id, num_trained_agents):
    """Which family a ModuleID belongs to, from its name alone.

    `policy_handler`'s layout: `policy_0..policy_(k-1)` are the trainable PPO
    modules, `policy_k..policy_(n-1)` are frozen RandomRLModule baselines, and
    `champion_*` are frozen PPO snapshots. Only the champion/policy split is
    visible in the name; the trainable/baseline boundary is `k`, which is a
    property of the *run* and is not recorded in the Parquet file - hence the
    argument.
    """
    module_id = str(module_id)
    if module_id.startswith(CHAMPION_PREFIX):
        return "champion"
    if module_id.startswith(POLICY_PREFIX):
        suffix = module_id[len(POLICY_PREFIX):]
        if suffix.isdigit() and int(suffix) < num_trained_agents:
            return "trainable"
        return "baseline"
    return "baseline"


def per_agent_episode(frame):
    """One row per (episode, agent): the unit a module is compared on.

    An episode is one sample of one matchup - the league redraws opponents
    every episode (`SelfPlayCallback.get_mapping_fn`), so a module's record is
    the set of agent-episodes it played, not any single one of them.

    The rates are summed-then-divided, not averaged over per-step ratios, for
    the reason `visualize_execution` gives: the per-step numerator is mostly
    zero, so a mean of ratios is dominated by the steps where nothing
    happened. `maker_share` is NaN where the agent never traded, which is a
    different statement from 0.0 ("it traded and always crossed the spread")
    and must not be averaged in as one.
    """
    grouped = frame.groupby(["episode_id", "agent_id"], sort=False)
    rows = grouped.agg(
        module_id=("module_id", "first"),
        episode_return=("reward", "sum"),
        final_nav=("nav", "last"),
        steps=("step", "size"),
        passes=("is_pass_action", "sum"),
        rejections=("num_rejected_step", "sum"),
        trades=("num_trades_step", "sum"),
        passive=("num_passive_fills_step", "sum"),
    ).reset_index()

    rows["pass_rate"] = rows["passes"] / rows["steps"]
    rows["rejection_rate"] = rows["rejections"] / rows["steps"]
    rows["maker_share"] = np.where(
        rows["trades"] > 0, rows["passive"] / rows["trades"], np.nan,
    )
    return rows


def _ordered_modules(rows):
    """Modules grouped by family, so the families read as blocks on the axis
    rather than being interleaved by whatever order pandas saw them in.
    """
    by_family = {family: [] for family in FAMILIES}
    for module_id, family in (
        rows[["module_id", "family"]].drop_duplicates().itertuples(index=False)
    ):
        by_family[family].append(module_id)
    ordered = []
    for family in FAMILIES:
        ordered.extend(sorted(by_family[family]))
    return ordered


def _plot_return_distribution(ax, rows, modules):
    """Per-agent-episode return, as a box per module.

    A box rather than a bar of means: the question a league asks is whether a
    module is *reliably* ahead, and two modules with the same mean and
    different spread are the case that matters. The count is annotated on
    each box because the opponent draw is random - a champion with three
    agent-episodes and one with forty are not equally strong evidence, and a
    box plot alone does not say which one you are looking at.
    """
    data = [rows.loc[rows["module_id"] == m, "episode_return"].to_numpy() for m in modules]
    positions = np.arange(len(modules))

    boxes = ax.boxplot(
        data, positions=positions, widths=0.6, patch_artist=True,
        medianprops={"color": "#0b0b0b", "linewidth": 1.5},
        flierprops={"marker": "o", "markersize": 3, "alpha": 0.5},
    )
    for patch, module_id in zip(boxes["boxes"], modules):
        family = rows.loc[rows["module_id"] == module_id, "family"].iloc[0]
        patch.set_facecolor(_FAMILY_COLORS[family])
        patch.set_alpha(0.65)

    # Headroom first, then the counts inside it: annotating at the current
    # top puts the text where the panel title already is.
    bottom, top = ax.get_ylim()
    ax.set_ylim(bottom, top + 0.12 * (top - bottom))
    for position, values in zip(positions, data):
        ax.text(
            position, top, f"n={len(values)}", ha="center", va="bottom",
            fontsize=8, color="#52514e",
        )

    ax.axhline(y=0, color='black', linestyle='-', alpha=0.3)
    ax.set_ylabel('Episode return')
    ax.set_title('Return by Module (one box = one module, one point = one agent-episode)')
    ax.grid(True, linestyle='--', alpha=0.5, axis='y')


def _plot_behaviour_rates(ax, rows, modules):
    """Mean pass / rejection / maker rate per module, as grouped bars.

    Grouped rather than stacked: the three are unrelated fractions of
    different denominators, not parts of one whole.

    `maker_share` is averaged over only the agent-episodes that traded at all
    (`per_agent_episode` leaves the rest NaN). Note that the maker share
    summed over *every* agent is exactly 0.5 by construction in a closed
    double auction - both sides of a fill increment `num_trades_step` and only
    the passive side increments `num_passive_fills_step` - so what carries
    information here is the spread *between* modules, not the level.
    """
    series = (
        ("pass_rate", "Pass rate", PASS_COLOR),
        ("rejection_rate", "Rejection rate", REJECTED_COLOR),
        ("maker_share", "Maker share", MAKER_COLOR),
    )
    positions = np.arange(len(modules))
    width = 0.26

    for i, (column, label, color) in enumerate(series):
        means = [
            np.nanmean(rows.loc[rows["module_id"] == m, column].to_numpy())
            if rows.loc[rows["module_id"] == m, column].notna().any() else np.nan
            for m in modules
        ]
        ax.bar(
            positions + (i - 1) * width, means, width=width * 0.92,
            color=color, label=label,
        )

    ax.set_ylim(0, 1)
    ax.set_ylabel('Mean rate')
    ax.set_title('Behaviour by Module')
    ax.grid(True, linestyle='--', alpha=0.5, axis='y')
    ax.legend(bbox_to_anchor=(1.01, 1), loc='upper left')


def visualize_modules(run_dir=None, num_trained_agents=None):
    """
    Compares the league's modules against each other over a whole run, from
    the per-step Parquet record (`train.episode_record.EpisodeRecorder`).

    This is the one view that needs `module_id`, and the reason that column
    exists: agents k..n-1 are drawn from the opponent pool afresh every
    episode, so `agent_3`'s rows are not one policy's rows - without
    `module_id` they cannot be attributed to a module at all, and a
    per-agent-slot comparison silently averages several modules together.

    Only completed episodes are counted (`episode_data.load_run`): a run's
    final, truncated episode would otherwise contribute a short fragment as
    though it were a whole episode, biasing exactly the per-episode
    aggregates this view is made of.

    num_trained_agents: how many `policy_*` modules were trainable in the run
        that produced this data. Defaults to `train_config.json`, which is
        right whenever the config has not changed since the run - it is a
        property of the run and is not recorded in the file, so the value
        used is printed rather than assumed silently. It only affects
        labelling (trainable vs baseline), never the numbers.

    run_dir defaults to the most recently written run; see
    `episode_data.load_run`.
    """
    if num_trained_agents is None:
        # `flat`, the same way TrainConfig reads its own defaults, so the group
        # this key lives in is not hardcoded in a second place.
        num_trained_agents = flat("train_config.json")["num_trained_agents"]

    columns = [
        "agent_id", "module_id", "reward", "nav", "is_pass_action",
        "num_rejected_step", "num_trades_step", "num_passive_fills_step",
    ]
    frame = load_run(run_dir, columns=columns)

    if frame["module_id"].isna().all():
        print(
            "Every module_id is null - the episode record could not name the "
            "module that played each agent (episode_record._module_for is "
            "best-effort against RLlib's episode API). Nothing to compare."
        )
        return

    frame = frame[frame["module_id"].notna()]
    rows = per_agent_episode(frame)
    rows["family"] = [module_family(m, num_trained_agents) for m in rows["module_id"]]

    modules = _ordered_modules(rows)
    print(
        f"{rows['episode_id'].nunique()} completed episode(s), "
        f"{len(rows)} agent-episodes, {len(modules)} module(s). "
        f"Trainable/baseline split assumes num_trained_agents="
        f"{num_trained_agents}."
    )

    fig, (ax_return, ax_rates) = plt.subplots(2, 1, figsize=(14, 11), sharex=True)

    _plot_return_distribution(ax_return, rows, modules)
    _plot_behaviour_rates(ax_rates, rows, modules)

    ax_rates.set_xticks(np.arange(len(modules)))
    ax_rates.set_xticklabels(modules, rotation=30, ha='right')
    ax_rates.set_xlabel('Module')

    # The family legend belongs to the box plot, whose fill colors carry it;
    # the rates panel has its own legend for its three series.
    handles = [
        plt.Rectangle((0, 0), 1, 1, facecolor=_FAMILY_COLORS[family], alpha=0.65)
        for family in FAMILIES
    ]
    ax_return.legend(handles, FAMILIES, bbox_to_anchor=(1.01, 1), loc='upper left')

    fig.suptitle('League Module Comparison')
    plt.tight_layout(rect=[0, 0, 1, 0.98])

    output_file = 'visualize/chart/modules_visualization.png'
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    plt.savefig(output_file)
    print(f"Visualization saved to {output_file}")
    plt.show()

if __name__ == "__main__":
    visualize_modules()
