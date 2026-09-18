"""The encoder comparison protocol of doc/18 §5.5, as one command.

    python -m gym_continuousDoubleAuction.train.compare \\
        --encoders mlp transformer --seeds 0 1 2 --iters 16 --out compare_out

For every (encoder, seed) it runs a **separate** training run - its own
`log_base_dir`, so checkpoints never mix, and its own `run_id` - with the seed
pinned, then scores the final checkpoint's trainable module on the reward-free
probe harness ([23](../../doc/23_probe_harness.md)) against one corpus shared by
every run. It writes a JSON file with every per-run number and a Markdown table
of per-encoder means and standard deviations across seeds.

Why this exists. [10](../../doc/10_testing.md) §8 has called "no encoder is
tested for whether it learns" the suite's largest gap for three review passes,
and [18](../../doc/18_configuration.md) §5.5 wrote the protocol down - pinned
seeds, several seeds per architecture, separate runs, parameter counts - without
anything that executes it. Run by hand, the protocol is a dozen shell
invocations and a spreadsheet, and the spreadsheet is where the seed pinning
and the "separate runs" rule get lost. This is the protocol as code.

What it does NOT do. It does not decide. A difference between two encoders is
reported as *separated* only when the gap between their means exceeds the sum
of their standard deviations across seeds; at fewer than three seeds that
column always reads "not separated", and it is right to. The numbers from a
short run at scaled-down settings - the shape the tests run it at - say nothing
about the architectures and everything about the settings, exactly as
[25](../../doc/25_continual_backprop.md) §3.6 warns for continual backprop.

Metrics collected per run, all from the final iteration's result dict and the
final checkpoint:

* `return`: `module_episode_returns_mean` averaged over the trainable modules.
* `vf_explained_var`: the same average, of the critic's explained variance.
* `pass_action_fraction`, `order_rejection_fraction`, `unmatched_action_fraction`:
  the three ways an action can change nothing, so a "winning" encoder whose
  policy has collapsed to doing nothing is visible as such.
* `maker_fill_ratio_max`: the most maker-like agent's share of its own fills.
* `obs_clip_fraction`: agent-steps whose observation hit a declared bound
  (S4-15); a number other than 0 means a bound is wrong for the market.
* `parameters`: trainable parameter count of one trainable module.
* `probe:<target>@<horizon>`: the probe score of the checkpoint's `policy_0`
  latents on that target, against the shared corpus.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import os
import statistics
import sys
import time
from typing import Any, Dict, List, Optional, Sequence

from gym_continuousDoubleAuction.config_loader import cli_default
from gym_continuousDoubleAuction.logging_setup import configure as configure_logging
from gym_continuousDoubleAuction.logging_setup import get_logger, merge_runtime_env

logger = get_logger("gym_continuousDoubleAuction.train.compare")

#: The JSON and Markdown files written under `--out`.
RESULTS_FILE = "compare_results.json"
TABLE_FILE = "compare_table.md"

#: Below this many seeds per encoder a standard deviation is two numbers'
#: distance, and "separated" would be a statement about the seeds drawn rather
#: than the architectures. `separated` reports False for any side with fewer.
MIN_SEEDS_TO_SEPARATE = 3

#: Metrics reported in the table, in this order, with their display precision.
TABLE_METRICS = (
    ("return", ".3g"),
    ("vf_explained_var", ".3g"),
    ("pass_action_fraction", ".3g"),
    ("order_rejection_fraction", ".3g"),
    ("unmatched_action_fraction", ".3g"),
    ("maker_fill_ratio_max", ".3g"),
    ("obs_clip_fraction", ".3g"),
)


def _cli(key):
    return cli_default("cda_compare", key)


# --- one run --------------------------------------------------------------------

def run_one(base_cfg, encoder: str, seed: int, out_dir: str, iters: int) -> Dict[str, Any]:
    """Train one (encoder, seed) and return its per-run metrics.

    Imports the training stack lazily so `--help` and the aggregation helpers
    below (which the tests exercise) do not pay for ray and torch.
    """
    from ray.rllib.utils.metrics import ENV_RUNNER_RESULTS

    from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import (
        MODULE_EPISODE_RETURNS_MEAN,
    )
    from gym_continuousDoubleAuction.train.policy.policy_handler import trainable_policy_ids
    from gym_continuousDoubleAuction.train.train import (
        list_checkpoints,
        train,
        vf_explained_var,
    )

    run_root = os.path.join(out_dir, encoder, f"seed{seed}")
    cfg = dataclasses.replace(
        base_cfg,
        encoder_type=encoder,
        seed=seed,
        num_iters=iters,
        num_iters_is_delta=False,
        is_restore=False,
        restore_path=None,
        log_base_dir=run_root,
        run_id=f"{encoder}_seed{seed}",
        # The per-step record is the one output that does not feed this
        # comparison, and it is ~34 MB per episode.
        episode_data_dir=None,
    )
    started = time.time()
    algo, result = train(cfg)
    try:
        env_runners = result.get(ENV_RUNNER_RESULTS) or {}
        returns = env_runners.get(MODULE_EPISODE_RETURNS_MEAN) or {}
        trainable = trainable_policy_ids(cfg.num_trained_agents)
        vf = vf_explained_var(result, cfg)
        row: Dict[str, Any] = {
            "encoder": encoder,
            "seed": seed,
            "iterations": int(result.get("training_iteration", 0) or 0),
            "wall_time_s": time.time() - started,
            "return": _mean([returns.get(pid) for pid in trainable]),
            "vf_explained_var": _mean([vf.get(pid) for pid in trainable]),
            "pass_action_fraction": _as_float(env_runners.get("pass_action_fraction")),
            # The two other no-op fractions and the maker ratio, because the
            # claim an order-management change makes is about *activity*, not
            # returns: "agents that can aim cancels quote more and hold fewer
            # stale orders" shows up here first (doc/15 S3-24, phase 4).
            "order_rejection_fraction": _as_float(env_runners.get("order_rejection_fraction")),
            "unmatched_action_fraction": _as_float(env_runners.get("unmatched_action_fraction")),
            "maker_fill_ratio_max": _as_float(env_runners.get("maker_fill_ratio_max")),
            # Agent-steps whose observation was clipped to the declared Box
            # bounds (doc/15 S4-15); should be 0 unless the bounds are wrong.
            "obs_clip_fraction": _as_float(env_runners.get("obs_clip_fraction")),
            "parameters": _parameter_count(algo, trainable[0]),
        }
        checkpoints = list_checkpoints(cfg.checkpoint_dir)
        row["checkpoint"] = checkpoints[-1][1] if checkpoints else None
    finally:
        algo.stop()
    return row


def _parameter_count(algo, module_id: str) -> Optional[int]:
    modules = getattr(getattr(algo, "env_runner", None), "module", None)
    module = modules.get(module_id) if modules is not None and hasattr(modules, "get") else None
    if module is None:
        return None
    return int(sum(p.numel() for p in module.parameters() if p.requires_grad))


def probe_checkpoint(row: Dict[str, Any], corpus, module_id: str,
                     targets: Sequence[str], horizons: Sequence[int]) -> None:
    """Add `probe:<target>@<horizon>` scores for the run's final checkpoint.

    Every run is scored against the *same* corpus object, so the scores are
    comparable across runs for the reason `probe.report` gives: identical
    rows, identical split, identical ridge grid.
    """
    from gym_continuousDoubleAuction.train.probe import features as features_module
    from gym_continuousDoubleAuction.train.probe import report as report_module

    if not row.get("checkpoint"):
        return
    module = features_module.load_module(row["checkpoint"], module_id)
    features = {"ckpt": features_module.latents(module, corpus)}
    for r in report_module.run(corpus, features, targets, horizons):
        result = r.results.get("ckpt")
        row[f"probe:{r.target}@{r.horizon}"] = (
            None if result is None else float(result.score)
        )


# --- aggregation (pure; tested without ray) -------------------------------------

def _as_float(value) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _mean(values: Sequence[Any]) -> Optional[float]:
    clean = [v for v in (_as_float(x) for x in values) if v is not None]
    return sum(clean) / len(clean) if clean else None


def metric_names(rows: Sequence[Dict[str, Any]]) -> List[str]:
    """Every numeric metric present in any row, table metrics first."""
    fixed = [name for name, _ in TABLE_METRICS]
    probes = sorted({k for row in rows for k in row if k.startswith("probe:")})
    return fixed + ["parameters"] + probes


def aggregate(rows: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """`{encoder: {metric: {"mean", "std", "n"}}}` across seeds.

    `std` is the sample standard deviation and is None below two values; a
    single seed has no spread to report, and reporting 0.0 would read as
    "perfectly reproducible" rather than "measured once".
    """
    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for encoder in sorted({row["encoder"] for row in rows}):
        mine = [row for row in rows if row["encoder"] == encoder]
        out[encoder] = {}
        for metric in metric_names(rows):
            values = [v for v in (_as_float(row.get(metric)) for row in mine) if v is not None]
            out[encoder][metric] = {
                "mean": sum(values) / len(values) if values else None,
                "std": statistics.stdev(values) if len(values) >= 2 else None,
                "n": len(values),
            }
    return out


def separated(summary: Dict[str, Dict[str, Dict[str, Any]]], metric: str) -> Dict[str, bool]:
    """Per encoder: does its mean sit clear of every other encoder's spread?

    "Clear" is `|mean_a - mean_b| > std_a + std_b` against every other encoder,
    which is deliberately crude and deliberately conservative: with two or
    more seeds per side it says a gap is larger than the seed-to-seed noise on
    both sides put together, and with fewer it says nothing at all. It is not
    a significance test, and the table says so.
    """
    result = {}
    for a, stats_a in summary.items():
        ma, sa = stats_a[metric]["mean"], stats_a[metric]["std"]
        if ma is None or sa is None or stats_a[metric]["n"] < MIN_SEEDS_TO_SEPARATE:
            result[a] = False
            continue
        clear = True
        for b, stats_b in summary.items():
            if b == a:
                continue
            mb, sb, nb = stats_b[metric]["mean"], stats_b[metric]["std"], stats_b[metric]["n"]
            if mb is None or sb is None or nb < MIN_SEEDS_TO_SEPARATE or abs(ma - mb) <= sa + sb:
                clear = False
                break
        result[a] = clear and len(summary) > 1
    return result


def _fmt(stats: Dict[str, Any], spec: str) -> str:
    if stats["mean"] is None:
        return "-"
    text = format(stats["mean"], spec)
    if stats["std"] is not None:
        text += f" ± {format(stats['std'], spec)}"
    return text


def render(rows: Sequence[Dict[str, Any]], summary=None) -> str:
    """The Markdown table: one row per encoder, means ± std across seeds."""
    summary = summary or aggregate(rows)
    probes = [m for m in metric_names(rows) if m.startswith("probe:")]
    headers = ["encoder", "seeds", "params"] + [m for m, _ in TABLE_METRICS] + probes + ["separated on"]
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    sep = {m: separated(summary, m) for m, _ in TABLE_METRICS}
    for encoder, stats in summary.items():
        cells = [
            encoder,
            str(stats["return"]["n"]),
            "-" if stats["parameters"]["mean"] is None else f"{int(stats['parameters']['mean']):,}",
        ]
        cells += [_fmt(stats[m], spec) for m, spec in TABLE_METRICS]
        cells += [_fmt(stats[m], ".3g") for m in probes]
        clear = [m for m, _ in TABLE_METRICS if sep[m].get(encoder)]
        cells.append(", ".join(clear) if clear else "nothing")
        lines.append("| " + " | ".join(cells) + " |")
    n_seeds = sorted({stats["return"]["n"] for stats in summary.values()})
    note = (
        "\n\"separated on\" lists the metrics where this encoder's mean sits "
        "further from every other encoder's than the two standard deviations "
        "combined. It is not a significance test."
    )
    if any(n < 3 for n in n_seeds):
        note += (
            " Fewer than three seeds per encoder: treat every row as a "
            "smoke test of the protocol, not a result."
        )
    return "\n".join(lines) + note


# --- CLI ------------------------------------------------------------------------

def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Train each encoder at several seeds, in separate runs, and "
                    "tabulate returns, critic quality, passivity and probe scores. "
                    "See doc/18 §5.5.",
    )
    p.add_argument("--encoders", nargs="+", default=_cli("encoders"))
    p.add_argument("--seeds", nargs="+", type=int, default=_cli("seeds"))
    p.add_argument("--iters", type=int, default=_cli("num_iters"))
    p.add_argument("--out", type=str, default=_cli("out_dir"))
    p.add_argument(
        "--config", type=str, default=None,
        help="Alternative train_config.json every run starts from. The encoder, "
             "seed, iteration count and output paths are overridden per run.",
    )
    p.add_argument("--agents", type=int, dest="num_agents", default=argparse.SUPPRESS)
    p.add_argument("--trained-agents", type=int, dest="num_trained_agents", default=argparse.SUPPRESS)
    p.add_argument("--max-step", type=int, default=argparse.SUPPRESS)
    p.add_argument("--episodes-per-iter", type=int, dest="num_episodes_per_iter", default=argparse.SUPPRESS)
    p.add_argument("--probe-episodes", type=int, default=_cli("probe_episodes"))
    p.add_argument("--probe-steps", type=int, default=_cli("probe_steps"))
    p.add_argument("--probe-seed", type=int, default=_cli("probe_seed"))
    p.add_argument("--targets", nargs="*", default=_cli("targets"))
    p.add_argument("--horizons", nargs="*", type=int, default=_cli("horizons"))
    p.add_argument("--module-id", type=str, default=_cli("module_id"))
    p.add_argument("--no-probe", action="store_true")
    p.add_argument("--log-level", type=str, default=_cli("log_level"))
    args = p.parse_args(argv)

    configure_logging(args.log_level, force=True)

    # Imported here for the same reason `run_one` imports lazily.
    import ray

    from gym_continuousDoubleAuction.train.runtime import apply_env_vars
    from gym_continuousDoubleAuction.train.train import TrainConfig

    apply_env_vars()

    base = TrainConfig.from_json(args.config) if args.config else TrainConfig()
    overrides = {
        k: v for k, v in vars(args).items()
        if k in {"num_agents", "num_trained_agents", "max_step", "num_episodes_per_iter"}
    }
    base = dataclasses.replace(base, **overrides)

    os.makedirs(args.out, exist_ok=True)
    ray.init(ignore_reinit_error=True, include_dashboard=False,
             runtime_env=merge_runtime_env())
    rows: List[Dict[str, Any]] = []
    try:
        corpus = None
        if not args.no_probe:
            from gym_continuousDoubleAuction.train.probe import corpus as corpus_module

            corpus = corpus_module.from_rollouts(
                num_episodes=args.probe_episodes, max_step=args.probe_steps,
                num_agents=base.num_agents, seed=args.probe_seed,
            )
            logger.info("probe corpus: %s", corpus.describe())

        for encoder in args.encoders:
            for seed in args.seeds:
                logger.info("=== %s seed %s: %s iterations ===", encoder, seed, args.iters)
                row = run_one(base, encoder, seed, args.out, args.iters)
                if corpus is not None:
                    probe_checkpoint(row, corpus, args.module_id, args.targets, args.horizons)
                rows.append(row)
                # Written after every run, so an interrupted sweep keeps what
                # it finished - the same reason progress.jsonl is appended.
                _write(args.out, rows)
    finally:
        ray.shutdown()

    logger.info("encoder comparison\n%s", render(rows))
    return 0


def _write(out_dir: str, rows: Sequence[Dict[str, Any]]) -> None:
    summary = aggregate(rows)
    with open(os.path.join(out_dir, RESULTS_FILE), "w") as fh:
        json.dump({"runs": list(rows), "summary": summary}, fh, indent=2)
    with open(os.path.join(out_dir, TABLE_FILE), "w") as fh:
        fh.write(render(rows, summary) + "\n")


if __name__ == "__main__":
    sys.exit(main())
