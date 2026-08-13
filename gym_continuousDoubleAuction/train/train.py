"""
Training entry point for the CDA environment with league-based self-play.

This was extracted from CDA_NSP.ipynb so the training path is importable and
testable. The notebook now imports from here rather than defining the config
inline; see `gym_continuousDoubleAuction/test/integration/` for the tests that
exercise it.

Run:
    python -m gym_continuousDoubleAuction.train.train --iters 4 --agents 4
    python -m gym_continuousDoubleAuction.train.train --help

From a notebook:
    from gym_continuousDoubleAuction.train.train import TrainConfig, build_algo, train
    cfg = TrainConfig(num_agents=8, num_trained_agents=2, num_iters=16)
    algo = train(cfg)
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
from dataclasses import dataclass, field
from typing import List, Optional

import ray
import torch
from ray import tune
from ray.rllib.algorithms.algorithm import Algorithm
from ray.rllib.algorithms.ppo import PPOConfig

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import (
    SelfPlayCallback,
)
from gym_continuousDoubleAuction.train.policy.policy_handler import (
    create_multi_agent_config,
)

ENV_NAME = "continuousDoubleAuction-v0"


@dataclass
class TrainConfig:
    """All training knobs in one place (was scattered across notebook cells)."""

    # --- Environment ---------------------------------------------------------
    num_agents: int = 8
    num_trained_agents: int = 2
    init_cash: int = 1_000_000
    tick_size: int = 1
    tape_display_length: int = 10
    max_step: int = 1024 * 4
    is_render: bool = False
    n_hist: int = 4

    # Bounds of the per-episode price anchor, drawn as randint(min, max) in
    # reset(). These were readable by the env but had no TrainConfig field, so
    # training runs could not narrow the range - the relative tick therefore
    # varied 10x across episodes with no way to control it. See doc/15 S3-4.
    initial_price_min: int = 10
    initial_price_max: int = 100

    # Order sizing. limit orders may be limit_size_multiple x larger than
    # market orders.
    min_size: int = 1
    mkt_max_size: int = 100
    limit_size_multiple: int = 10

    # Reward coefficients. Previously hardcoded in Reward_Helper.set_reward,
    # which made them the least reachable knobs in the project despite being
    # the ones most worth sweeping.
    order_penalty: float = 0.1
    trade_penalty: float = 0.05
    drawdown_penalty: float = 0.2
    passive_bonus: float = 0.1
    loss_multiplier: float = 1.5

    # --- Rollouts ------------------------------------------------------------
    # 0 keeps sampling in the driver process, which is the right default for a
    # CPU dev box and for tests. Raise it for real training runs.
    num_env_runners: int = 0
    num_envs_per_env_runner: int = 1
    num_cpus_per_env_runner: float = 1.0

    # --- Learner -------------------------------------------------------------
    num_learners: int = 0
    # Fraction of a GPU per learner. Ignored (forced to 0) when CUDA is not
    # available - the notebook used to hardcode 0.75, which hard-fails on any
    # CPU-only machine.
    num_gpus_per_learner: float = 0.75

    # --- PPO -----------------------------------------------------------------
    num_episodes_per_iter: int = 4
    num_epochs: int = 4
    lr: float = 5e-5
    fcnet_hiddens: List[int] = field(default_factory=lambda: [256, 256])
    fcnet_activation: str = "tanh"
    # False keeps policy and value on separate trunks, which matters against
    # the non-stationary league opponents - see model_handler.
    vf_share_layers: bool = False
    # PPO requires minibatch_size <= train_batch_size_per_learner. RLlib's
    # default is 128, which is larger than the batch of a short-episode test
    # run, so this is exposed rather than left implicit.
    minibatch_size: Optional[int] = None

    # --- League self-play ----------------------------------------------------
    std_dev_multiplier: float = 0.1
    max_champions: int = 8
    min_iterations_between_champions: int = 2
    original_opponent_weight: float = 1.0
    champion_weight: float = 3.0
    # None disables the per-episode step pickles (a lot of I/O at max_step=4096).
    episode_data_dir: Optional[str] = "episode_data"

    # --- Run / checkpointing -------------------------------------------------
    num_iters: int = 16
    chkpt_freq: int = 2
    log_base_dir: str = "results"
    is_restore: bool = False
    log_level: str = "WARN"
    seed: Optional[int] = None

    @classmethod
    def from_json(cls, path: str) -> "TrainConfig":
        """Build a TrainConfig from a JSON file such as `config/train_config.json`.

        The file is grouped (`environment`, `rollouts`, `ppo`, ...) while this
        dataclass is flat, so groups are flattened one level. Keys beginning
        with `_` are documentation (`_source`, `_description`, `_note`) and are
        skipped at every level.

        Unknown keys raise rather than being ignored. Silently dropping a
        renamed or misspelled key is the failure mode this loader exists to
        remove - the file used to be purely descriptive, so a typo in it had no
        symptom at all.

        Note the one name change across the boundary: the field here is
        `num_agents`, and `env_config` forwards it to the env as
        `num_of_agents`.
        """
        with open(path) as fh:
            raw = json.load(fh)

        flat: dict = {}
        for key, value in raw.items():
            if key.startswith("_"):
                continue
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    if not sub_key.startswith("_"):
                        flat[sub_key] = sub_value
            else:
                flat[key] = value

        known = {f.name for f in dataclasses.fields(cls)}
        unknown = sorted(set(flat) - known)
        if unknown:
            raise ValueError(
                f"{path}: unknown config keys {unknown}. "
                f"Valid keys: {sorted(known)}"
            )
        return cls(**flat)

    @property
    def train_batch_size(self) -> int:
        return self.max_step * self.num_episodes_per_iter

    @property
    def checkpoint_dir(self) -> str:
        return os.path.abspath(os.path.join(self.log_base_dir, "chkpt"))

    @property
    def env_config(self) -> dict:
        return {
            "num_of_agents": self.num_agents,
            "init_cash": self.init_cash,
            "tick_size": self.tick_size,
            "tape_display_length": self.tape_display_length,
            "max_step": self.max_step,
            "is_render": self.is_render,
            "n_hist": self.n_hist,
            "initial_price_min": self.initial_price_min,
            "initial_price_max": self.initial_price_max,
            "min_size": self.min_size,
            "mkt_max_size": self.mkt_max_size,
            "limit_size_multiple": self.limit_size_multiple,
            "order_penalty": self.order_penalty,
            "trade_penalty": self.trade_penalty,
            "drawdown_penalty": self.drawdown_penalty,
            "passive_bonus": self.passive_bonus,
            "loss_multiplier": self.loss_multiplier,
        }

    def resolved_gpus_per_learner(self) -> float:
        """num_gpus_per_learner, forced to 0 when no CUDA device is present."""
        if self.num_gpus_per_learner and not torch.cuda.is_available():
            print(
                f"[train] num_gpus_per_learner={self.num_gpus_per_learner} requested "
                f"but torch.cuda.is_available() is False - falling back to CPU."
            )
            return 0.0
        return self.num_gpus_per_learner


def register_env(cfg: TrainConfig) -> None:
    """Register the CDA env with Tune under ENV_NAME."""
    tune.register_env(ENV_NAME, lambda env_config: continuousDoubleAuctionEnv(env_config))


def make_spaces(cfg: TrainConfig):
    """Instantiate a throwaway env just to read its per-agent spaces."""
    env = continuousDoubleAuctionEnv(cfg.env_config)
    agent_id = env.agents[0]
    return env.get_observation_space(agent_id), env.get_action_space(agent_id)


def build_config(cfg: TrainConfig):
    """Build the PPOConfig, the callback instance, and the module spec.

    Returns:
        (ppo_config, callback_instance)

    The callback instance is returned because the caller needs the *same*
    object that the policy mapping function closes over - it owns the live
    champion pool.
    """
    register_env(cfg)
    obs_space, act_space = make_spaces(cfg)

    policies, policies_to_train, rl_module_spec = create_multi_agent_config(
        obs_space,
        act_space,
        num_agents=cfg.num_agents,
        num_trained_agents=cfg.num_trained_agents,
        fcnet_hiddens=cfg.fcnet_hiddens,
        fcnet_activation=cfg.fcnet_activation,
        vf_share_layers=cfg.vf_share_layers,
    )

    callback_instance = SelfPlayCallback(
        num_trainable_policies=cfg.num_trained_agents,
        num_random_policies=cfg.num_agents - cfg.num_trained_agents,
        std_dev_multiplier=cfg.std_dev_multiplier,
        max_champions=cfg.max_champions,
        min_iterations_between_champions=cfg.min_iterations_between_champions,
        original_opponent_weight=cfg.original_opponent_weight,
        champion_weight=cfg.champion_weight,
        episode_data_dir=cfg.episode_data_dir,
    )

    ppo = (
        PPOConfig()
        .environment(ENV_NAME, env_config=cfg.env_config)
        .framework("torch")
        .multi_agent(
            policies=policies,
            # The league mapping fn, not the static 1:1 one: agents beyond the
            # trainable ones are drawn from the opponent pool each episode.
            policy_mapping_fn=SelfPlayCallback.get_mapping_fn(callback_instance),
            policies_to_train=policies_to_train,
            count_steps_by="env_steps",
        )
        # Declaring module classes here is what actually binds RandomRLModule to
        # the baseline opponents. Passing them via PolicySpec (as this used to)
        # is silently ignored on the new API stack.
        .rl_module(rl_module_spec=rl_module_spec)
        .env_runners(
            num_env_runners=cfg.num_env_runners,
            num_envs_per_env_runner=cfg.num_envs_per_env_runner,
            num_cpus_per_env_runner=cfg.num_cpus_per_env_runner,
        )
        .learners(
            num_learners=cfg.num_learners,
            num_gpus_per_learner=cfg.resolved_gpus_per_learner(),
        )
        .training(
            train_batch_size_per_learner=cfg.train_batch_size,
            num_epochs=cfg.num_epochs,
            lr=cfg.lr,
            **({"minibatch_size": cfg.minibatch_size}
               if cfg.minibatch_size is not None else {}),
        )
        # Returns the same instance every call, so the driver-side champion pool
        # is the one the mapping fn reads.
        .callbacks(lambda: callback_instance)
        .debugging(log_level=cfg.log_level, seed=cfg.seed)
    )

    return ppo, callback_instance


def build_algo(cfg: TrainConfig):
    """Build (or restore) the Algorithm."""
    ppo, callback_instance = build_config(cfg)

    if cfg.is_restore and os.path.exists(cfg.checkpoint_dir):
        print(f"[train] restoring from checkpoint: {cfg.checkpoint_dir}")
        algo = Algorithm.from_checkpoint(cfg.checkpoint_dir)
        _fix_checkpoint_optimizer_betas(algo)
    else:
        print("[train] starting from scratch")
        algo = ppo.build_algo()

    return algo, callback_instance


def _fix_checkpoint_optimizer_betas(algo) -> None:
    """Work around Adam `betas` deserialising as tensors from a checkpoint."""

    def fix_betas(learner):
        for optimizer in learner._optimizer_parameters.keys():
            for param_group in optimizer.param_groups:
                if "betas" in param_group:
                    param_group["betas"] = tuple(
                        b.item() if torch.is_tensor(b) else b
                        for b in param_group["betas"]
                    )

    algo.learner_group.foreach_learner(fix_betas)


def train(cfg: TrainConfig):
    """Run the full training loop. Returns the trained Algorithm."""
    algo, _callback = build_algo(cfg)

    os.makedirs(cfg.checkpoint_dir, exist_ok=True)

    for i in range(cfg.num_iters):
        result = algo.train()
        _print_iteration(i + 1, cfg.num_iters, result)

        if cfg.chkpt_freq and (i + 1) % cfg.chkpt_freq == 0:
            path = algo.save(cfg.checkpoint_dir)
            print(f"[train] checkpoint at iter {i + 1}: {path}")

    final = algo.save(cfg.checkpoint_dir)
    print(f"[train] final checkpoint: {final}")
    return algo


def _print_iteration(i: int, total: int, result: dict) -> None:
    from ray.rllib.utils.metrics import ENV_RUNNER_RESULTS

    env_runners = result.get(ENV_RUNNER_RESULTS, {})
    returns = env_runners.get("module_episode_returns_mean", {})
    steps = env_runners.get("num_env_steps_sampled", "n/a")
    print(
        f"[train] iter {i}/{total} | env steps sampled: {steps} | "
        f"module returns: { {k: round(float(v), 1) for k, v in returns.items()} }"
    )


def _parse_args(argv=None) -> TrainConfig:
    """Resolve a TrainConfig from the command line.

    Precedence is dataclass defaults -> `--config` file -> explicit flags.

    Every flag below defaults to `argparse.SUPPRESS`, so an unset flag is
    absent from the namespace entirely. That distinction is what makes the
    precedence work: with ordinary argparse defaults, `--config` could set
    `num_agents=4` and an unpassed `--agents` would immediately overwrite it
    with 8. The suppressed defaults are identical to the dataclass defaults, so
    behaviour without `--config` is unchanged.
    """
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument(
        "--config",
        type=str,
        default=None,
        help="JSON config file, e.g. config/train_config.json. Flags override it.",
    )
    p.add_argument("--agents", type=int, dest="num_agents", default=argparse.SUPPRESS)
    p.add_argument("--trained-agents", type=int, dest="num_trained_agents", default=argparse.SUPPRESS)
    p.add_argument("--iters", type=int, dest="num_iters", default=argparse.SUPPRESS)
    p.add_argument("--max-step", type=int, default=argparse.SUPPRESS)
    p.add_argument("--env-runners", type=int, dest="num_env_runners", default=argparse.SUPPRESS)
    p.add_argument("--envs-per-runner", type=int, dest="num_envs_per_env_runner", default=argparse.SUPPRESS)
    p.add_argument("--gpus-per-learner", type=float, dest="num_gpus_per_learner", default=argparse.SUPPRESS)
    p.add_argument("--restore", action="store_true", dest="is_restore", default=argparse.SUPPRESS)
    p.add_argument("--log-base-dir", type=str, default=argparse.SUPPRESS)
    p.add_argument("--log-level", type=str, default=argparse.SUPPRESS)
    p.add_argument("--seed", type=int, default=argparse.SUPPRESS)
    p.add_argument(
        "--no-episode-data",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Disable per-episode step pickles (large I/O at long episodes).",
    )
    args = p.parse_args(argv)

    overrides = {
        k: v for k, v in vars(args).items()
        if k not in ("config", "no_episode_data")
    }
    if getattr(args, "no_episode_data", False):
        overrides["episode_data_dir"] = None

    base = TrainConfig.from_json(args.config) if args.config else TrainConfig()
    return dataclasses.replace(base, **overrides)


def main(argv=None) -> None:
    cfg = _parse_args(argv)

    os.environ.setdefault("RAY_DEBUG_DISABLE_MEMORY_MONITOR", "True")
    ray.init(ignore_reinit_error=True, include_dashboard=False)
    try:
        train(cfg)
    finally:
        ray.shutdown()


if __name__ == "__main__":
    main()
