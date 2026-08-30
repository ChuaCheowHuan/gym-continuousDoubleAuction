"""CLI: `python -m gym_continuousDoubleAuction.train.pretrain`.

Defaults come from `config/cli_defaults.json` -> `cda_pretrain`; this module
holds no literal default, on the same rule as `CDA_rand` and the probe.
"""
from __future__ import annotations

import argparse
import sys

from gym_continuousDoubleAuction.config_loader import cli_default, group
from gym_continuousDoubleAuction.logging_setup import configure as configure_logging
from gym_continuousDoubleAuction.logging_setup import get_logger
# Named imports, not `import pretrain as pretrain_module`: the package
# re-exports a *function* called `pretrain`, so that spelling binds the
# function and every attribute lookup on it fails.
from gym_continuousDoubleAuction.train.pretrain import (
    PRETRAINABLE,
    pretrain,
    save,
)

logger = get_logger("gym_continuousDoubleAuction.train.pretrain")


def _cli(key):
    return cli_default("cda_pretrain", key)


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Pretrain a JEPA encoder on observations alone. "
                    "See doc/24_pretraining.md.",
    )
    p.add_argument("--out", type=str, default=_cli("out_dir"),
                   help="Directory to write the encoder and its fingerprint to.")
    p.add_argument("--encoder", type=str, default=_cli("encoder_type"),
                   help=f"Available: {', '.join(PRETRAINABLE)}.")
    p.add_argument("--steps", type=int, default=_cli("steps"))
    p.add_argument("--batch-size", type=int, default=_cli("batch_size"))
    p.add_argument("--lr", type=float, default=_cli("lr"))
    p.add_argument("--seed", type=int, default=_cli("seed"))
    p.add_argument("--log-every", type=int, default=_cli("log_every"))
    p.add_argument("--episodes", type=int, default=_cli("num_episodes"),
                   help="Random-agent rollout episodes, when --parquet is unset.")
    p.add_argument("--env-steps", type=int, default=_cli("max_step"),
                   help="Steps per rollout episode.")
    p.add_argument("--agents", type=int, default=_cli("num_agents"))
    p.add_argument(
        "--parquet", type=str, default=None,
        help="Read the corpus from episode_record output instead of running "
             "rollouts. A trained league's books look nothing like a random "
             "agent's, so prefer this once a run exists.",
    )
    p.add_argument("--max-rows", type=int, default=None)
    p.add_argument("--log-level", type=str, default=_cli("log_level"))
    args = p.parse_args(argv)

    configure_logging(args.log_level, force=True)

    # Imported here so `--help` does not pay for the env or for torch.
    from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
        continuousDoubleAuctionEnv,
    )
    from gym_continuousDoubleAuction.train.probe import corpus as corpus_module

    if args.parquet:
        corpus = corpus_module.from_parquet(args.parquet, max_rows=args.max_rows)
    else:
        corpus = corpus_module.from_rollouts(
            num_episodes=args.episodes,
            max_step=args.env_steps,
            num_agents=args.agents,
            seed=args.seed,
        )

    env = continuousDoubleAuctionEnv({})
    agent_id = env.agents[0]
    encoder_spec = group("train_config.json", "encoder")["encoder_specs"].get(
        args.encoder, {}
    )

    module, report = pretrain(
        corpus,
        env.get_observation_space(agent_id),
        env.get_action_space(agent_id),
        encoder_type=args.encoder,
        encoder_spec=encoder_spec,
        steps=args.steps,
        batch_size=args.batch_size,
        lr=args.lr,
        seed=args.seed,
        log_every=args.log_every,
    )

    save(module, args.out, args.encoder, encoder_spec)
    logger.info("pretraining report\n%s\n%s", corpus.describe(), report.summary())

    # A collapsed encoder is not a usable one, and its loss looks excellent
    # precisely because of the collapse. Fail the command rather than leaving a
    # good-looking number in the log beside weights nobody should load.
    return 1 if report.collapsed else 0


if __name__ == "__main__":
    sys.exit(main())
