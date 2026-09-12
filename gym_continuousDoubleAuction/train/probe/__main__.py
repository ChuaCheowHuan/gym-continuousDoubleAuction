"""CLI: `python -m gym_continuousDoubleAuction.train.probe`.

Defaults come from `config/cli_defaults.json` -> `cda_probe`; this module holds
no literal default, on the same rule as `CDA_rand`.
"""
from __future__ import annotations

import argparse
import sys
from typing import Dict, List

import numpy as np

from gym_continuousDoubleAuction.config_loader import cli_default, group
from gym_continuousDoubleAuction.logging_setup import configure as configure_logging
from gym_continuousDoubleAuction.logging_setup import get_logger
from gym_continuousDoubleAuction.train.model.encoders import selectable_encoder_types
from gym_continuousDoubleAuction.train.probe import corpus as corpus_module
from gym_continuousDoubleAuction.train.probe import features as features_module
from gym_continuousDoubleAuction.train.probe import rank as rank_module
from gym_continuousDoubleAuction.train.probe import report as report_module
from gym_continuousDoubleAuction.train.probe import targets as targets_module

logger = get_logger("gym_continuousDoubleAuction.train.probe")


def _cli(key):
    return cli_default("cda_probe", key)


def build_features(
    corpus,
    encoders: List[str],
    checkpoint: str = None,
    module_id: str = None,
    pretrained: str = None,
    pretrained_encoder: str = None,
) -> Dict[str, np.ndarray]:
    """The feature matrices to compare: `raw`, each encoder, and a checkpoint.

    The checkpoint contributes one extra set, named for the module it came
    from. Its architecture is whatever the run trained, which need not be any
    of `encoders` - that is the point of restoring rather than rebuilding.
    """
    # Imported here so `--help` and a target listing do not pay for the env.
    from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
        continuousDoubleAuctionEnv,
    )

    env = continuousDoubleAuctionEnv({})
    agent_id = env.agents[0]
    obs_space = env.get_observation_space(agent_id)
    act_space = env.get_action_space(agent_id)

    features = {features_module.RAW_FEATURES: features_module.raw(corpus)}

    for encoder_type in encoders:
        module = features_module.build_module(obs_space, act_space, encoder_type)
        features[encoder_type] = features_module.latents(module, corpus)
        logger.info(
            "%s: untrained latents %s", encoder_type, features[encoder_type].shape
        )

    if checkpoint:
        module = features_module.load_module(checkpoint, module_id)
        name = f"{module_id}@ckpt"
        features[name] = features_module.latents(module, corpus)
        logger.info("%s: trained latents %s", name, features[name].shape)

    if pretrained:
        # Built from the config file's spec block, so the fingerprint written
        # beside the weights is comparable with the one being built here - a
        # mismatch raises rather than loading partially.
        spec = group("train_config.json", "encoder")["encoder_specs"].get(
            pretrained_encoder, {}
        )
        module = features_module.pretrained_module(
            obs_space, act_space, pretrained_encoder, pretrained, spec
        )
        name = f"{pretrained_encoder}@pretrained"
        features[name] = features_module.latents(module, corpus)
        logger.info("%s: pretrained latents %s", name, features[name].shape)

    return features


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Score observation encoders on reward-free microstructure "
                    "targets. See doc/23_probe_harness.md.",
    )
    p.add_argument(
        "--encoders", nargs="*", default=_cli("encoders"),
        help=f"Architectures to score untrained. Available: "
             f"{', '.join(selectable_encoder_types())}.",
    )
    p.add_argument(
        "--targets", nargs="*", default=_cli("targets"),
        help=f"Available: {', '.join(targets_module.selectable_targets())}.",
    )
    p.add_argument(
        "--horizons", nargs="*", type=int, default=_cli("horizons"),
        help="Steps ahead each target looks.",
    )
    p.add_argument("--episodes", type=int, default=_cli("num_episodes"))
    p.add_argument("--steps", type=int, default=_cli("max_step"))
    p.add_argument("--agents", type=int, default=_cli("num_agents"))
    p.add_argument("--seed", type=int, default=_cli("seed"))
    p.add_argument(
        "--parquet", type=str, default=None,
        help="Read the corpus from episode_record output instead of running "
             "rollouts. A file or a directory searched recursively.",
    )
    p.add_argument(
        "--max-rows", type=int, default=None,
        help="Cap on rows read from --parquet.",
    )
    p.add_argument(
        "--per-agent", action="store_true",
        help="Keep every agent's row from --parquet rather than one per step. "
             "The rows at one step share a book and differ only in their "
             "private tail, so this multiplies the corpus by the agent count "
             "while adding only private state - useful when that is the "
             "subject, misleading otherwise.",
    )
    p.add_argument(
        "--checkpoint", type=str, default=None,
        help="An iter_<n> checkpoint directory, scored alongside the "
             "untrained encoders.",
    )
    p.add_argument("--module-id", type=str, default=_cli("module_id"))
    p.add_argument(
        "--pretrained", type=str, default=None,
        help="A directory written by `train.pretrain`, scored alongside the "
             "untrained encoders. Putting the same architecture in the report "
             "twice - once at initialisation, once pretrained - is what "
             "isolates what the self-supervised objective actually taught it.",
    )
    p.add_argument(
        "--pretrained-encoder", type=str, default="jepa",
        help="Which architecture --pretrained holds. Its spec comes from "
             "train_config.json, so the fingerprint check is meaningful.",
    )
    p.add_argument("--out", type=str, default=None, help="Write the report here too.")
    p.add_argument("--log-level", type=str, default=_cli("log_level"))
    args = p.parse_args(argv)

    configure_logging(args.log_level, force=True)

    if args.parquet:
        corpus = corpus_module.from_parquet(
            args.parquet, max_rows=args.max_rows, per_agent=args.per_agent,
        )
    else:
        corpus = corpus_module.from_rollouts(
            num_episodes=args.episodes,
            max_step=args.steps,
            num_agents=args.agents,
            seed=args.seed,
        )

    features = build_features(
        corpus, args.encoders, args.checkpoint, args.module_id,
        args.pretrained, args.pretrained_encoder,
    )
    rows = report_module.run(corpus, features, args.targets, args.horizons)
    ranks = rank_module.rank_table(features)
    text = "\n".join([
        f"Corpus: {corpus.describe()}",
        f"Source: {args.parquet or 'random-agent rollouts'}"
        + (" (per-agent rows)" if args.parquet and args.per_agent else ""),
        "",
        report_module.render(rows, list(features)),
        "",
        rank_module.render(ranks, list(features)),
    ])

    # Through the logger, not `print`: everything under `train/` reports that
    # way (`test_no_module_calls_print`), and it means the report also lands in
    # the run log rather than only in scrollback - which for a comparison
    # anyone will want to cite later is the point.
    logger.info("probe report\n%s", text)
    if args.out:
        with open(args.out, "w") as handle:
            handle.write(text + "\n")
        logger.info("wrote %s", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
