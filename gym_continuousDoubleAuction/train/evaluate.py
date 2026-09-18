"""Use a trained checkpoint: roll episodes with its policies, no learning.

    python -m gym_continuousDoubleAuction.train.evaluate \\
        --checkpoint results/chkpt/iter_00016 --episodes 4 --out eval.json

doc/15 S4-12: the repository could train a policy and could not *use* one.
Every consumer of a checkpoint was another training run (`--restore`) or the
probe harness, which reads latents. This rolls episodes the way the training
sampler does - the checkpoint's own `policy_mapping_fn` assigns modules to
agents, so the league's random baselines and champions play their parts - and
reports, per module, the return, the NAV change and the three activity
fractions, as the mean over episodes.

Two things it deliberately is not. It is not `Algorithm.evaluate()`: that spins
up RLlib's evaluation env runners with their own connectors and config, which
is the right tool for a metric inside a training loop and the wrong one for
"what does this policy do", where a plain env loop that the reader can step
through matters more. And it is not a benchmark: one checkpoint's numbers mean
something only against another checkpoint's on the same seeds, which is what
`--seed` pins.

Actions come from `forward_inference`: a module that emits `Columns.ACTIONS`
directly (the random baselines) is taken as is; one that emits distribution
inputs is sampled, or made deterministic with `--deterministic`, through the
module's own inference distribution class - the same path the env runner takes.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

import numpy as np

from gym_continuousDoubleAuction.config_loader import cli_default
from gym_continuousDoubleAuction.logging_setup import configure as configure_logging
from gym_continuousDoubleAuction.logging_setup import get_logger, merge_runtime_env

logger = get_logger("gym_continuousDoubleAuction.train.evaluate")

#: The per-agent activity counters summed over an episode.
ACTIVITY_FIELDS = ("is_pass_action", "num_rejected_step", "num_unmatched_step",
                   "num_trades_step", "num_passive_fills_step")


def _cli(key):
    return cli_default("cda_evaluate", key)


def _unbatch(value):
    """First (only) row of a batched action, as plain Python / numpy."""
    if isinstance(value, dict):
        return {k: _unbatch(v) for k, v in value.items()}
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    value = np.asarray(value)
    row = value[0] if value.ndim > 0 else value
    # Discrete components come back as 0-d ints; Box components keep their shape.
    return int(row) if row.ndim == 0 and np.issubdtype(row.dtype, np.integer) else row


def act(module, obs: np.ndarray, deterministic: bool, normalize: bool, clip: bool):
    """One agent's action from one module, the env-runner way.

    A PPO module's Box heads are Gaussians over a *normalised* range when the
    config's `normalize_actions` is on (RLlib's default), and the env runner's
    module-to-env connector unsquashes them into the space's bounds before
    `env.step`. Skipping that step hands the env a `size_sigma` below zero on
    roughly half the samples, which `np.random.normal` refuses - so the same
    unsquash (or clip, under `clip_actions`) is applied here. A module that
    emits `Columns.ACTIONS` directly, the random baselines, already samples
    inside the space.
    """
    import torch
    from ray.rllib.core.columns import Columns
    from ray.rllib.utils.spaces.space_utils import (
        clip_action,
        get_base_struct_from_space,
        unsquash_action,
    )

    batch = {Columns.OBS: torch.as_tensor(obs[None, :], dtype=torch.float32)}
    with torch.no_grad():
        out = module.forward_inference(batch)
    if Columns.ACTIONS in out:
        return _unbatch(out[Columns.ACTIONS])
    dist_cls = module.get_inference_action_dist_cls()
    dist = dist_cls.from_logits(out[Columns.ACTION_DIST_INPUTS])
    if deterministic:
        dist = dist.to_deterministic()
    action = _unbatch(dist.sample())
    struct = get_base_struct_from_space(module.action_space)
    if normalize:
        action = unsquash_action(action, struct)
    elif clip:
        action = clip_action(action, struct)
    return action


def roll_episode(algo, env, mapping_fn, episode_index: int, seed: Optional[int],
                 deterministic: bool) -> Dict[str, Any]:
    """Play one episode to termination or truncation; return its per-agent record."""
    obs, _ = env.reset(seed=None if seed is None else seed + episode_index)
    normalize = bool(getattr(algo.config, "normalize_actions", True))
    clip = bool(getattr(algo.config, "clip_actions", False))

    class _Episode:
        """What the mapping fn reads: an id. The league fn seeds its draw from it."""
        id_ = f"eval-{seed}-{episode_index}"

    assignment = {agent: str(mapping_fn(agent, _Episode())) for agent in env.possible_agents}
    modules = {mid: algo.get_module(mid) for mid in set(assignment.values())}

    totals: Dict[str, Dict[str, float]] = {
        agent: {"return": 0.0, **{f: 0 for f in ACTIVITY_FIELDS}} for agent in env.possible_agents
    }
    last_info: Dict[str, dict] = {}
    steps = 0
    while True:
        actions = {
            agent: act(modules[assignment[agent]], obs[agent], deterministic,
                       normalize, clip)
            for agent in env.agents
        }
        obs, rewards, terminateds, truncateds, infos = env.step(actions)
        steps += 1
        for agent, reward in rewards.items():
            totals[agent]["return"] += float(reward)
        for agent, info in infos.items():
            last_info[agent] = info
            for field in ACTIVITY_FIELDS:
                totals[agent][field] += int(bool(info.get(field, 0))) if field == "is_pass_action" \
                    else int(info.get(field, 0) or 0)
        if terminateds.get("__all__") or truncateds.get("__all__"):
            break

    agents = []
    for agent in env.possible_agents:
        info = last_info.get(agent, {})
        nav = float(info["NAV"]) if "NAV" in info else None
        agents.append({
            "agent": agent,
            "module": assignment[agent],
            "return": totals[agent]["return"],
            "final_nav": nav,
            "nav_change_frac": (None if nav is None else (nav - float(env.init_cash)) / float(env.init_cash)),
            "num_trades": int(info.get("num_trades", 0) or 0),
            "pass_fraction": totals[agent]["is_pass_action"] / steps,
            "rejection_fraction": totals[agent]["num_rejected_step"] / steps,
            "unmatched_fraction": totals[agent]["num_unmatched_step"] / steps,
            "passive_fill_share": (totals[agent]["num_passive_fills_step"] / totals[agent]["num_trades_step"]
                                   if totals[agent]["num_trades_step"] else None),
            "terminated": bool(terminateds.get(agent, False)),
        })
    return {"episode": episode_index, "steps": steps, "agents": agents}


def summarise(episodes: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Per module: mean over every (episode, agent) it played, plus the count."""
    by_module: Dict[str, List[dict]] = defaultdict(list)
    for ep in episodes:
        for row in ep["agents"]:
            by_module[row["module"]].append(row)
    out = {}
    for module, rows in sorted(by_module.items()):
        out[module] = {"agent_episodes": len(rows)}
        for key in ("return", "nav_change_frac", "num_trades", "pass_fraction",
                    "rejection_fraction", "unmatched_fraction", "passive_fill_share"):
            values = [r[key] for r in rows if r[key] is not None]
            out[module][key] = float(np.mean(values)) if values else None
        out[module]["terminated"] = sum(1 for r in rows if r["terminated"])
    return out


def render(summary: Dict[str, Dict[str, Any]]) -> str:
    headers = ["module", "agent-eps", "return", "nav change", "trades", "pass", "rejected",
               "unmatched", "passive share", "bankrupt"]
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]

    def f(v, spec=".3g"):
        return "-" if v is None else format(v, spec)

    for module, s in summary.items():
        lines.append("| " + " | ".join([
            module, str(s["agent_episodes"]), f(s["return"]), f(s["nav_change_frac"], ".2%"),
            f(s["num_trades"], ".1f"), f(s["pass_fraction"]), f(s["rejection_fraction"]),
            f(s["unmatched_fraction"]), f(s["passive_fill_share"]), str(s["terminated"]),
        ]) + " |")
    return "\n".join(lines)


def evaluate(checkpoint: str, episodes: int, seed: Optional[int], deterministic: bool,
             env_overrides: Optional[dict] = None) -> Dict[str, Any]:
    """Restore `checkpoint`, roll `episodes`, return the full record."""
    from ray.rllib.algorithms.algorithm import Algorithm

    from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
        continuousDoubleAuctionEnv,
    )
    from gym_continuousDoubleAuction.envs.layout_version import check_layout_stamp
    from gym_continuousDoubleAuction.train.train import _read_league_state, register_env

    # A checkpoint from another layout cannot drive this env; say so by name.
    check_layout_stamp(_read_league_state(checkpoint), checkpoint)
    register_env(None)
    algo = Algorithm.from_checkpoint(checkpoint)
    try:
        env_config = dict(algo.config.env_config)
        env_config.update(env_overrides or {})
        env_config["is_render"] = False
        env = continuousDoubleAuctionEnv(env_config)
        mapping_fn = algo.config.policy_mapping_fn
        started = time.time()
        records = [
            roll_episode(algo, env, mapping_fn, i, seed, deterministic) for i in range(episodes)
        ]
        summary = summarise(records)
        return {
            "checkpoint": os.path.abspath(checkpoint),
            "iteration": int(getattr(algo, "iteration", 0) or 0),
            "episodes": records,
            "summary": summary,
            "seed": seed,
            "deterministic": deterministic,
            "wall_time_s": time.time() - started,
        }
    finally:
        algo.stop()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Roll episodes with a trained checkpoint's policies and report what "
                    "they do. See doc/26 section 26.10.",
    )
    p.add_argument("--checkpoint", required=True, help="One iter_<n> directory.")
    p.add_argument("--episodes", type=int, default=_cli("episodes"))
    p.add_argument("--seed", type=int, default=_cli("seed"),
                   help="Episode i is reset with seed + i, so two checkpoints evaluated with the "
                        "same seed see the same price anchors and opponent draws.")
    p.add_argument("--deterministic", action="store_true",
                   help="Take each distribution's mode instead of sampling it.")
    p.add_argument("--max-step", type=int, default=None, help="Override the checkpoint's max_step.")
    p.add_argument("--out", type=str, default=_cli("out"), help="Write the full record here as JSON.")
    p.add_argument("--log-level", type=str, default=_cli("log_level"))
    args = p.parse_args(argv)

    configure_logging(args.log_level, force=True)

    import ray

    from gym_continuousDoubleAuction.train.runtime import apply_env_vars

    apply_env_vars()
    ray.init(ignore_reinit_error=True, include_dashboard=False, runtime_env=merge_runtime_env())
    try:
        record = evaluate(
            args.checkpoint, args.episodes, args.seed, args.deterministic,
            env_overrides={"max_step": args.max_step} if args.max_step else None,
        )
    finally:
        ray.shutdown()

    logger.info("evaluation of %s (iteration %s), %s episode(s)\n%s",
                record["checkpoint"], record["iteration"], args.episodes, render(record["summary"]))
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(record, fh, indent=2, default=str)
        logger.info("wrote %s", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
