"""Take a trained policy's weights out of a checkpoint, as a plain torch file.

    python -m gym_continuousDoubleAuction.train.export \\
        --checkpoint results/chkpt/iter_00016 --out champion.pt

doc/14 section 5.9 lists "no inference/serving path" as a production gap.
`evaluate.py` closed half of it - a checkpoint can be *run* - and this closes
the other half: a checkpoint's weights can be taken out of it. Until now the
only way to read a trained network was to restore the whole `Algorithm`, or to
know that `RLModule.from_checkpoint` accepts the right subdirectory, which is
not written down anywhere a user looks.

Which module is the winner
--------------------------
The league promotes a trainable policy to a frozen `champion_N` when it beats
the league mean by `std_dev_multiplier` standard deviations
([08](../../doc/08_self_play_league.md) section 5). `train.save_checkpoint`
writes the bookkeeping - which champion came from which policy, at which
iteration, on what return - to `league_state.json` beside every checkpoint, so
the winner can be named without unpickling anything. With no `--module-id`
this exports the champion with the best recorded return.

That default is a starting guess and the log says so. A champion's `return` is
its score *relative to the league at the iteration it was promoted*, so two
champions' returns are not comparable: the league they were measured against is
not the same league. Settling which policy is actually best is what
`train.evaluate --seed` is for, and its per-module table names a module id to
pass back here.

What the file holds
-------------------
`torch.save` of a dict: the `state_dict`, plus what a reader needs to know
whether these weights mean anything - the module id and class, the checkpoint
and iteration they came from, the promotion record, and the observation/action
layout stamp. Weights without that stamp are a tensor of the right shape and
the wrong meaning as soon as the layout moves ([47.5](../../doc/17_changelog.md)).

Deliberately not TorchScript or ONNX. Reloading this file still needs
`ray[rllib]` and this package importable, because the architecture is rebuilt
from the checkpoint's own spec rather than hard-coded here - the same reasoning
`probe.features.load_module` gives. A frozen graph would be a second definition
of the network to keep in step with the first.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

from gym_continuousDoubleAuction.config_loader import cli_default
from gym_continuousDoubleAuction.envs.layout_version import LAYOUT_KEY, layout_stamp
from gym_continuousDoubleAuction.logging_setup import configure as configure_logging
from gym_continuousDoubleAuction.logging_setup import get_logger
from gym_continuousDoubleAuction.train.probe import features as features_module
from gym_continuousDoubleAuction.train.train import LEAGUE_STATE_FILE

logger = get_logger("gym_continuousDoubleAuction.train.export")


def _cli(key):
    return cli_default("cda_export", key)


def read_league_state(checkpoint: str) -> Dict[str, Any]:
    """The sidecar beside `checkpoint`, or `{}` if it has none.

    Deliberately not `train._read_league_state`: that one warns and returns
    None on an unreadable file, which is right for a restore that can carry on
    without it. Here the sidecar is the only thing that names a winner, so an
    unreadable one is reported as what it is and the caller falls back to
    `--module-id`.
    """
    path = os.path.join(checkpoint, LEAGUE_STATE_FILE)
    if not os.path.isfile(path):
        logger.warning(
            "%s has no %s. Champions cannot be named without it - pass "
            "--module-id, or --list to see what the checkpoint holds.",
            checkpoint, LEAGUE_STATE_FILE,
        )
        return {}
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        logger.warning("could not read %s: %s", path, exc)
        return {}


def best_champion(state: Dict[str, Any]) -> Optional[dict]:
    """The champion with the highest recorded return, or None if there are none.

    `max` over a metric that is only comparable within one iteration; see this
    module's docstring for why that is a guess rather than an answer. Ties go to
    the earliest promotion, which `max` gives for free and which is the more
    conservative of the two - a later champion at the same return is a later
    snapshot of a league that had already moved.
    """
    history = state.get("champion_history") or []
    return max(history, key=lambda c: c["return"]) if history else None


def resolve_module(state: Dict[str, Any],
                   module_id: Optional[str]) -> Tuple[str, Optional[dict]]:
    """Which module to export, and its promotion record if it has one.

    Raises:
        ValueError: if no module was named and the run promoted no champion.
    """
    if module_id:
        record = next(
            (c for c in state.get("champion_history") or [] if c["id"] == module_id),
            None,
        )
        return module_id, record

    champion = best_champion(state)
    if champion is None:
        raise ValueError(
            "this checkpoint's league promoted no champion, so there is no "
            "winning module to export. The trainable modules are policy_0 .. "
            "policy_<num_trained_agents-1>; name one with --module-id, or pass "
            "--list to see what the checkpoint holds. A run that never promotes "
            "is usually a std_dev_multiplier that is too high - see doc/08 "
            "section 4."
        )
    return champion["id"], champion


def build_record(module, module_id: str, checkpoint: str,
                 state: Dict[str, Any], record: Optional[dict]) -> Dict[str, Any]:
    """What gets written: the weights, and enough to know what they mean."""
    import torch

    weights = {
        key: value.detach().cpu() if torch.is_tensor(value) else value
        for key, value in module.state_dict().items()
    }
    return {
        "module_id": module_id,
        "module_class": f"{type(module).__module__}.{type(module).__name__}",
        "checkpoint": os.path.abspath(checkpoint),
        "training_iteration": state.get("training_iteration"),
        "promotion": record,
        # Without this a reader cannot tell whether these weights read an
        # observation the way the env writes one. doc/17 section 47.5.
        LAYOUT_KEY: state.get(LAYOUT_KEY),
        "state_dict": weights,
    }


def warn_about_layout(state: Dict[str, Any]) -> Optional[str]:
    """Report, without refusing, that the weights predate the current layout.

    `evaluate` refuses a foreign layout because it drives the env with it. This
    does not: taking the weights out of an old checkpoint to look at them is a
    reasonable thing to want, and the stamp travels in the file either way. So
    the mismatch is said once and the export proceeds. Returns the message, for
    a test to assert on.
    """
    stamped = state.get(LAYOUT_KEY)
    if not stamped:
        return None
    current = layout_stamp(stamped.get("book_mode"))
    differs = [
        key for key in ("observation_version", "action_version")
        if stamped.get(key) != current.get(key)
    ]
    if not differs:
        return None
    message = (
        "these weights were trained against "
        + ", ".join(f"{key.split('_')[0]} layout v{stamped.get(key)}" for key in differs)
        + ", and this checkout is at "
        + ", ".join(f"v{current.get(key)}" for key in differs)
        + ". They are exported as they are - the stamp travels in the file - "
        "but they do not read this env's observations."
    )
    logger.warning(message)
    return message


def render(state: Dict[str, Any], modules: List[str]) -> str:
    """What this checkpoint holds, as the `--list` output."""
    lines = [f"modules: {', '.join(modules) if modules else '(none found)'}"]
    history = state.get("champion_history") or []
    if not history:
        lines.append("champions: none promoted")
        return "\n".join(lines)

    best = best_champion(state)
    lines.append("")
    lines.append("| champion | from | iteration | return | best |")
    lines.append("|---|---|---|---|---|")
    for champion in history:
        lines.append(
            f"| {champion['id']} | {champion['source_policy']} | "
            f"{champion['iteration']} | {champion['return']:.6g} | "
            f"{'yes' if champion is best else ''} |"
        )
    lines.append("")
    lines.append(
        "A return ranks a champion against the league of its own iteration "
        "only. Use train.evaluate --seed to compare two of them."
    )
    return "\n".join(lines)


def export(checkpoint: str, module_id: Optional[str] = None,
           out: Optional[str] = None) -> Dict[str, Any]:
    """Load one module out of `checkpoint` and write its weights to `out`.

    Returns the record that was written, with `out` added as `path`.
    """
    import torch

    state = read_league_state(checkpoint)
    module_id, record = resolve_module(state, module_id)
    if record is not None:
        logger.info(
            "%s was promoted from %s at iteration %s, return %.6g",
            module_id, record["source_policy"], record["iteration"], record["return"],
        )
    warn_about_layout(state)

    module = features_module.load_module(checkpoint, module_id)
    written = build_record(module, module_id, checkpoint, state, record)

    out = out or f"{module_id}.pt"
    parent = os.path.dirname(os.path.abspath(out))
    os.makedirs(parent, exist_ok=True)
    torch.save(written, out)

    weights = written["state_dict"]
    logger.info(
        "wrote %s: %s, %s tensor(s), %s parameter(s)\n%s",
        out, written["module_class"], len(weights),
        f"{sum(v.numel() for v in weights.values()):,}",
        "\n".join(f"    {k}  {tuple(v.shape)}" for k, v in weights.items()),
    )
    return {**written, "path": os.path.abspath(out)}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Export one module's weights from a training checkpoint. "
                    "See doc/26 section 26.9.2.",
    )
    p.add_argument("--checkpoint", required=True, help="One iter_<n> directory.")
    p.add_argument("--module-id", type=str, default=_cli("module_id"),
                   help="Export this module. Default: the champion with the best "
                        "recorded return.")
    p.add_argument("--out", type=str, default=_cli("out"),
                   help="Where to write the .pt. Default: <module_id>.pt here.")
    p.add_argument("--list", action="store_true",
                   help="Print the checkpoint's modules and champions, export nothing.")
    p.add_argument("--log-level", type=str, default=_cli("log_level"))
    args = p.parse_args(argv)

    configure_logging(args.log_level, force=True)

    if args.list:
        state = read_league_state(args.checkpoint)
        logger.info("%s\n%s", os.path.abspath(args.checkpoint),
                    render(state, features_module.available_modules(args.checkpoint)))
        return 0

    try:
        export(args.checkpoint, args.module_id, args.out)
    except (ValueError, FileNotFoundError) as exc:
        logger.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
