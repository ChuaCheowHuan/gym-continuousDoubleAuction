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
    algo, result = train(cfg)
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import ray
import torch
from ray import tune
from ray.rllib.algorithms.algorithm import Algorithm
from ray.rllib.algorithms.ppo import PPOConfig

from gym_continuousDoubleAuction.config_loader import (
    flat as flat_config,
    flatten,
)
from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.logging_setup import configure as configure_logging
from gym_continuousDoubleAuction.logging_setup import get_logger
from gym_continuousDoubleAuction.logging_setup import (
    log_file_path,
    merge_runtime_env,
    set_iteration,
)
from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import (
    SelfPlayCallback,
)
from gym_continuousDoubleAuction.train.policy.policy_handler import (
    CHAMPION_PREFIX,
    create_multi_agent_config,
    trainable_policy_ids,
)

logger = get_logger("gym_continuousDoubleAuction.train.train")

ENV_NAME = "continuousDoubleAuction-v0"

#: The file every TrainConfig default is read from.
TRAIN_CONFIG_FILE = "train_config.json"

#: Per-iteration result dicts, one JSON object per line, under `run_dir`.
#: `algo.train()` returns a full metrics dict every iteration and the loop used
#: to read two keys out of it for a log line and drop the rest, so a finished
#: run left behind checkpoints and no record of how it got there. This is the
#: record. See doc/11 1.6.
PROGRESS_FILE = "progress.jsonl"

#: How long the driver waits for the runners to accept a new iteration tag.
#: Short and non-fatal: this is a log field, and a runner that is slow to answer
#: must delay sampling by as little as possible. Missing it costs `iter=-` on
#: that runner's lines for one iteration, nothing more.
_BROADCAST_TIMEOUT_S = 10.0


def generate_run_id() -> str:
    """A directory name unique to this run: local date, time, four hex digits.

    The timestamp is what makes a listing readable and orderable; the random
    suffix is what makes it *unique*, because two runs launched by the same
    script in the same second would otherwise collide on the second - which is
    exactly the shared-directory case `run_dir` exists to prevent.

    Local time rather than UTC, to match the log timestamps a reader is
    correlating this against.
    """
    return f"run_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"

#: `result["learners"][<module_id>]["vf_explained_var"]`: the fraction of return
#: variance the critic accounts for. Defined by RLlib as
#: `ppo.LEARNER_RESULTS_VF_EXPLAINED_VAR_KEY` and written by PPOTorchLearner;
#: spelled out here rather than imported so a rename in Ray degrades to a
#: missing metric instead of an ImportError that stops training. A critic stuck
#: near 0.0 is the failure this exists to make visible while a run is going,
#: which no amount of reading `module_episode_returns_mean` will show.
VF_EXPLAINED_VAR_KEY = "vf_explained_var"


def _default(key: str, *, compare: bool = True):
    """A dataclass default read from `config/train_config.json`.

    The value is fetched when a TrainConfig is instantiated, not when this
    module is imported, so a config tree swapped in via `$CDA_CONFIG_DIR` takes
    effect without re-importing. A key missing from the file raises: the
    dataclass declares the schema, the file supplies every value in it, and a
    literal written here would be a second source that can disagree.

    `compare=False` keeps a field out of `__eq__`, for the one field whose value
    identifies the run rather than configuring it - see `run_id`.
    """

    def factory():
        values = flat_config(TRAIN_CONFIG_FILE)
        if key not in values:
            raise KeyError(
                f"{TRAIN_CONFIG_FILE} is missing the key {key!r}, which "
                f"TrainConfig has no default for. Keys found: {sorted(values)}."
            )
        return values[key]

    return field(default_factory=factory, compare=compare)


@dataclass
class TrainConfig:
    """All training knobs in one place.

    This dataclass is the *schema*: it names every knob, its type, and what it
    does. It holds no values - each field's default is read from
    `config/train_config.json` by `_default`, so editing that file changes what
    a run does, with no second copy in Python to keep in step.
    """

    # --- Environment ---------------------------------------------------------
    num_agents: int = _default("num_agents")
    num_trained_agents: int = _default("num_trained_agents")
    init_cash: int = _default("init_cash")
    tick_size: int = _default("tick_size")
    tape_display_length: int = _default("tape_display_length")
    max_step: int = _default("max_step")
    is_render: bool = _default("is_render")
    n_hist: int = _default("n_hist")

    # Bounds of the per-episode price anchor, drawn as randint(min, max) in
    # reset(). These were readable by the env but had no TrainConfig field, so
    # training runs could not narrow the range - the relative tick therefore
    # varied 10x across episodes with no way to control it. See doc/15 S3-4.
    initial_price_min: int = _default("initial_price_min")
    initial_price_max: int = _default("initial_price_max")

    # Order sizing. limit orders may be limit_size_multiple x larger than
    # market orders.
    min_size: int = _default("min_size")
    mkt_max_size: int = _default("mkt_max_size")
    limit_size_multiple: int = _default("limit_size_multiple")

    # Reward coefficients. Previously hardcoded in Reward_Helper.set_reward,
    # which made them the least reachable knobs in the project despite being
    # the ones most worth sweeping.
    order_penalty: float = _default("order_penalty")
    trade_penalty: float = _default("trade_penalty")
    drawdown_penalty: float = _default("drawdown_penalty")
    passive_bonus: float = _default("passive_bonus")
    loss_multiplier: float = _default("loss_multiplier")

    # --- Rollouts ------------------------------------------------------------
    # 0 keeps sampling in the driver process, which is the right setting for a
    # CPU dev box and for tests. Raise it for real training runs.
    num_env_runners: int = _default("num_env_runners")
    num_envs_per_env_runner: int = _default("num_envs_per_env_runner")
    num_cpus_per_env_runner: float = _default("num_cpus_per_env_runner")
    # How long the driver waits for a remote runner's share of the batch.
    # RLlib's default is 60s, which this env cannot meet at the configured
    # batch size: a timed-out iteration discards its partial rollouts, so the
    # learner gets nothing and the iteration trains on no data at all while
    # still counting itself and checkpointing. See the note in
    # train_config.json. Ignored when num_env_runners is 0.
    sample_timeout_s: float = _default("sample_timeout_s")

    # --- Learner -------------------------------------------------------------
    num_learners: int = _default("num_learners")
    # Fraction of a GPU per learner. Ignored (forced to 0) when CUDA is not
    # available, so a non-zero value here does not hard-fail a CPU-only machine.
    num_gpus_per_learner: float = _default("num_gpus_per_learner")

    # --- PPO -----------------------------------------------------------------
    num_episodes_per_iter: int = _default("num_episodes_per_iter")
    num_epochs: int = _default("num_epochs")
    lr: float = _default("lr")
    fcnet_hiddens: List[int] = _default("fcnet_hiddens")
    fcnet_activation: str = _default("fcnet_activation")
    # False keeps policy and value on separate trunks, which matters against
    # the non-stationary league opponents - see model_handler.
    vf_share_layers: bool = _default("vf_share_layers")
    # PPO requires minibatch_size <= train_batch_size_per_learner. RLlib's
    # default is 128, which is larger than the batch of a short-episode test
    # run, so this is exposed rather than left implicit.
    minibatch_size: Optional[int] = _default("minibatch_size")

    # --- League self-play ----------------------------------------------------
    std_dev_multiplier: float = _default("std_dev_multiplier")
    max_champions: int = _default("max_champions")
    min_iterations_between_champions: int = _default("min_iterations_between_champions")
    original_opponent_weight: float = _default("original_opponent_weight")
    champion_weight: float = _default("champion_weight")
    # null disables the per-episode step pickles (a lot of I/O at long episodes).
    episode_data_dir: Optional[str] = _default("episode_data_dir")
    # Episode-end NAV conservation check. The ledger is Decimal throughout, so
    # the sum of every agent's NAV equals the cash the system started with, to
    # the cent; the tolerance only absorbs the float() round trip through the
    # info dict. strict raises on a violation rather than logging one, because
    # a broken conservation invariant means the ledger is corrupt and whatever
    # trains after it is meaningless.
    nav_tolerance: float = _default("nav_tolerance")
    strict_nav_check: bool = _default("strict_nav_check")

    # --- Run / checkpointing -------------------------------------------------
    # num_iters is a *target* iteration, not an amount: a restored run trains up
    # to it, so resuming a 16-iteration run at 9 does 7 more. That keeps the
    # total length of a run independent of how many times it was interrupted.
    # num_iters_is_delta restores the old reading - run num_iters more from
    # wherever the restore landed - for anyone who wants to extend a finished run.
    num_iters: int = _default("num_iters")
    num_iters_is_delta: bool = _default("num_iters_is_delta")
    chkpt_freq: int = _default("chkpt_freq")
    # How many `iter_*` checkpoints to retain. Every save used to overwrite one
    # directory, so a run had exactly one recoverable state and no way back from
    # a league that collapsed. <= 0 keeps all of them.
    chkpt_keep: int = _default("chkpt_keep")
    log_base_dir: str = _default("log_base_dir")
    # Names the per-run directory under log_base_dir holding progress.jsonl and
    # the run logs. null generates one, so two runs cannot land on the same
    # files: sharing run.log is the cross-process RotatingFileHandler race the
    # per-worker files already avoid for env runners, and sharing
    # progress.jsonl lets two drivers interleave writes inside one JSON line
    # (`json.dump` writes incrementally, and a result dict above the ~8KiB
    # stream buffer is several write syscalls). Pin it to resume into an
    # existing run directory. `__post_init__` resolves null to a real value, so
    # this is a str by the time anything reads it.
    #
    # Out of __eq__: it names the run, it does not configure it, and since
    # __post_init__ generates a fresh one per instance, comparing it would make
    # no two TrainConfigs equal - including the checked-in file against its own
    # defaults, and a restored checkpoint's config against the current one,
    # which `config_divergence` reports on.
    run_id: Optional[str] = _default("run_id", compare=False)
    is_restore: bool = _default("is_restore")
    # Which checkpoint to resume from. null takes the newest readable one under
    # checkpoint_dir, which is what a disconnect wants; a path pins one, which
    # is how a run is rolled back past a collapsed league. Requires is_restore.
    restore_path: Optional[str] = _default("restore_path")
    # Ray's log level, handed to PPOConfig.debugging.
    log_level: str = _default("log_level")
    # This package's own log level, applied by logging_setup and exported so
    # remote env runners - separate processes that never run main() - come up
    # at the same level. Kept apart from Ray's: Ray at INFO is noise, while
    # this package at INFO is the per-episode NAV table and the per-iteration
    # league statistics.
    cda_log_level: str = _default("cda_log_level")
    seed: Optional[int] = _default("seed")

    def __post_init__(self) -> None:
        """Resolve `run_id` once, here, rather than on each property read.

        A property that generated a name per call would hand a different
        directory to every caller, and `dataclasses.replace` - which the
        runtime profiles and the tests both use - would silently re-roll it.
        Resolving in the constructor makes the name a property of the config
        object, so a replace()d copy keeps writing where the original did.
        """
        if not self.run_id:
            self.run_id = generate_run_id()

    @classmethod
    def from_json(cls, path: str) -> "TrainConfig":
        """Build a TrainConfig from an arbitrary JSON file.

        `config/train_config.json` is already the source of every default, so
        this is for running against a *different* file - a sweep variant, or a
        config saved alongside a past run. Keys the other file omits fall back
        to the checked-in one.

        The file is grouped (`environment`, `rollouts`, `ppo`, ...) while this
        dataclass is flat, so groups are flattened one level. Keys beginning
        with `_` are documentation (`_source`, `_description`, `_note`) and are
        skipped at every level.

        Unknown keys raise rather than being ignored. Silently dropping a
        renamed or misspelled key is the failure mode this loader exists to
        remove.

        Note the one name change across the boundary: the field here is
        `num_agents`, and `env_config` forwards it to the env as
        `num_of_agents`.
        """
        with open(path) as fh:
            raw = json.load(fh)

        values = flatten(raw, path)

        known = {f.name for f in dataclasses.fields(cls)}
        unknown = sorted(set(values) - known)
        if unknown:
            raise ValueError(
                f"{path}: unknown config keys {unknown}. "
                f"Valid keys: {sorted(known)}"
            )
        return cls(**values)

    @property
    def train_batch_size(self) -> int:
        return self.max_step * self.num_episodes_per_iter

    @property
    def checkpoint_dir(self) -> str:
        """Root of the checkpoint tree. Individual saves are `iter_*` beneath it.

        Under `log_base_dir` and *not* under `run_dir`, which is the one place
        the per-run split is deliberately not applied. Restoring from a
        disconnect means finding the newest `iter_*` written by an *earlier*
        run; a per-run checkpoint tree would hide it, and every resumed run
        would start from scratch. Checkpoints are therefore shared across runs
        and the files that cannot tolerate sharing are not.

        `warn_about_stale_checkpoints` covers the cost of that sharing: a fresh
        run into a directory that already holds checkpoints says so.
        """
        return os.path.abspath(os.path.join(self.log_base_dir, "chkpt"))

    @property
    def run_dir(self) -> str:
        """This run's own directory, holding progress.jsonl and the run logs.

        Scoped per run rather than shared, because both files are written
        without any cross-process interlock: two drivers sharing one
        `log_base_dir` would rotate the same `run.log` underneath each other,
        and interleave partial writes into the same `progress.jsonl` line.
        Giving each run its own directory removes the sharing rather than
        trying to make the writes atomic.

        The checkpoint tree deliberately stays *outside* it - see
        `checkpoint_dir`.
        """
        return os.path.abspath(os.path.join(self.log_base_dir, self.run_id))

    @property
    def progress_path(self) -> str:
        """The per-iteration JSONL log, in this run's own directory.

        Under `log_base_dir` rather than `episode_data_dir` deliberately: this
        is one short line per iteration, so it belongs with the checkpoints that
        must survive a disconnect, not with the per-episode pickles that
        runtime_profiles.json keeps off the Drive FUSE layer.

        Appending still matters within a run directory: the file is opened per
        iteration, so a killed run keeps what it had finished, and a restore
        that pins the same `run_id` extends that history rather than starting a
        second file.
        """
        return os.path.abspath(os.path.join(self.run_dir, PROGRESS_FILE))

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
            logger.warning(
                "num_gpus_per_learner=%s requested but torch.cuda.is_available() "
                "is False - falling back to CPU.", self.num_gpus_per_learner,
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
        nav_tolerance=cfg.nav_tolerance,
        strict_nav_check=cfg.strict_nav_check,
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
            sample_timeout_s=cfg.sample_timeout_s,
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


# --- Checkpoint layout -------------------------------------------------------
#
# Each save goes into its own `iter_<n>` directory under `checkpoint_dir`, and
# the newest `chkpt_keep` of them are kept. Every save used to be written to
# `chkpt/` itself, which gave a run exactly one recoverable state: a league that
# collapsed at iteration 12 could not be rolled back to 8, and a save
# interrupted partway - the thing checkpointing exists to survive - destroyed
# the only copy.
#
# A save is staged in `<dir>.tmp` and renamed into place, so an interrupted one
# leaves a `.tmp` directory the scanner skips rather than a half-written
# checkpoint that looks complete.

CHECKPOINT_PREFIX = "iter_"
CHECKPOINT_TMP_SUFFIX = ".tmp"

#: Champion bookkeeping, written beside each checkpoint. See `_write_league_state`.
LEAGUE_STATE_FILE = "league_state.json"

#: Checkpoint roots already reported as holding an old-layout checkpoint, so the
#: note is printed once per run rather than once per save.
_NOTED_OLD_LAYOUT = set()


def _is_checkpoint(path: str) -> bool:
    return os.path.isfile(os.path.join(path, "rllib_checkpoint.json"))


def list_checkpoints(root: str) -> List[Tuple[int, str]]:
    """Every readable checkpoint under `root`, oldest first, as (iteration, path).

    A checkpoint written by the old single-directory layout sits in `root`
    itself. It is reported with iteration -1 so it sorts oldest: still usable on
    a box that has one, never preferred over a save whose iteration is known.
    """
    found: List[Tuple[int, str]] = []
    if not os.path.isdir(root):
        return found

    if _is_checkpoint(root):
        found.append((-1, root))

    for name in sorted(os.listdir(root)):
        if not name.startswith(CHECKPOINT_PREFIX) or name.endswith(CHECKPOINT_TMP_SUFFIX):
            continue
        path = os.path.join(root, name)
        try:
            iteration = int(name[len(CHECKPOINT_PREFIX):])
        except ValueError:
            continue
        if _is_checkpoint(path):
            found.append((iteration, path))

    return sorted(found)


def save_checkpoint(algo, cfg: TrainConfig, iteration: int) -> str:
    """Save `algo` as `iter_<iteration>`, then prune to `cfg.chkpt_keep`."""
    root = cfg.checkpoint_dir
    os.makedirs(root, exist_ok=True)

    final = os.path.join(root, f"{CHECKPOINT_PREFIX}{iteration:05d}")
    staging = final + CHECKPOINT_TMP_SUFFIX

    for stale in (staging, final):
        # `final` exists when a restored run reaches an iteration it already
        # saved; `staging` when a previous save was interrupted.
        if os.path.exists(stale):
            shutil.rmtree(stale, ignore_errors=True)

    algo.save(staging)
    _write_league_state(staging, algo, iteration)
    os.rename(staging, final)

    _prune_checkpoints(root, cfg.chkpt_keep)
    return final


def _prune_checkpoints(root: str, keep: int) -> None:
    """Delete all but the `keep` most recently written saves. <= 0 keeps everything.

    Recency is the directory's mtime, not its iteration number. Ranking by
    iteration number deletes the save that was just written whenever the
    directory also holds higher-numbered ones from an earlier run: a fresh run
    reaching `iter_00002` in a directory that still has `iter_00012/14/16` sees
    its own checkpoint pruned microseconds after the rename that made it real,
    and keeps the stale ones instead. Both GPU runs of 2026-08-15 did exactly
    that for iterations 2 through 10 - the whole first half of each run left
    unrecoverable while the previous run's checkpoints survived. mtime says
    what the iteration number cannot: which of these did *this* run write.

    Only `iter_*` directories are pruned. A checkpoint left in `root` by the old
    layout is another tool's data as far as this function is concerned, so it is
    reported once and left alone.
    """
    if not keep or keep <= 0:
        return

    checkpoints = list_checkpoints(root)
    if any(iteration < 0 for iteration, _ in checkpoints) and root not in _NOTED_OLD_LAYOUT:
        _NOTED_OLD_LAYOUT.add(root)
        logger.info(
            "note: %s also holds a checkpoint in the old single-directory "
            "layout. It is kept as a last-resort restore candidate and is never "
            "pruned; delete it by hand once the iter_* saves are trusted.", root,
        )

    prunable = [path for iteration, path in checkpoints if iteration >= 0]
    # Oldest first, so the tail of the list is what `keep` retains. The
    # iteration number breaks mtime ties, which is what a filesystem with
    # coarse timestamps produces when two saves land in the same second.
    prunable.sort(key=lambda path: (_mtime(path), _iteration_of(path)))

    for path in prunable[:max(0, len(prunable) - keep)]:
        shutil.rmtree(path, ignore_errors=True)
        logger.info("pruned old checkpoint: %s", path)


def _mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _iteration_of(path: str) -> int:
    """The iteration in an `iter_<n>` basename, or -1 if it has none."""
    name = os.path.basename(path)
    try:
        return int(name[len(CHECKPOINT_PREFIX):])
    except ValueError:
        return -1


def warn_about_foreign_checkpoints(cfg: TrainConfig) -> List[str]:
    """Report checkpoints a fresh run is about to write alongside.

    A run that is not restoring shares its directory with whatever the last run
    left there, and the two are told apart only by iteration number. Until this
    run passes that number, `list_checkpoints` reports the *stale* save as the
    newest, so an interrupted run restored with `--restore` silently resumes
    someone else's weights - which is how a run that trained on nothing could
    have been picked up as if it were this one. Nothing is deleted here; the
    directory belongs to the operator, not to this function.

    Returns the stale paths, newest first, for the caller to log or test.
    """
    if cfg.is_restore:
        return []

    stale = [path for _iteration, path in reversed(list_checkpoints(cfg.checkpoint_dir))]
    if stale:
        logger.warning(
            "%s already holds %s checkpoint(s) from an earlier run, newest "
            "first: %s. This run is not restoring, so they are left alone - but "
            "until it passes their iteration numbers, a --restore would pick "
            "one of them over anything written here. Move or delete them, or "
            "point log_base_dir somewhere new.",
            cfg.checkpoint_dir, len(stale), ", ".join(os.path.basename(p) for p in stale),
        )
    return stale


def algo_callback(algo) -> Optional[SelfPlayCallback]:
    """The SelfPlayCallback instance the Algorithm is actually running.

    `.callbacks(lambda: callback_instance)` means the algorithm holds the same
    object the mapping fn closes over - but after a restore that object is
    RLlib's unpickled copy, not the one `build_config` just made. Anything that
    wants the live champion pool has to ask the algorithm for it.
    """
    callbacks = getattr(algo, "callbacks", None)
    if not isinstance(callbacks, (list, tuple)):
        callbacks = [callbacks]
    for callback in callbacks:
        if isinstance(callback, SelfPlayCallback):
            return callback
    return None


def _write_league_state(path: str, algo, iteration: int) -> None:
    """Write champion bookkeeping beside a checkpoint, as plain JSON.

    The champion *modules* are in the checkpoint proper. Their metadata -
    history, the monotonic ID counter, the matchmaking pool - lives only inside
    the cloudpickled callback, so it survives exactly as long as
    `SelfPlayCallback` stays unpickle-compatible. Rename the class, change its
    `__init__`, or resume across a Ray upgrade, and the modules come back while
    the league that indexes them does not: the counter restarts and mints a
    second `champion_1`. This sidecar is the readable copy that
    `_reconcile_league_state` repairs from.
    """
    callback = algo_callback(algo)
    if callback is None:
        return

    state = callback.league_state()
    state["training_iteration"] = iteration
    with open(os.path.join(path, LEAGUE_STATE_FILE), "w") as fh:
        json.dump(state, fh, indent=2)


def _read_league_state(path: str) -> Optional[dict]:
    state_file = os.path.join(path, LEAGUE_STATE_FILE)
    if not os.path.isfile(state_file):
        return None
    try:
        with open(state_file) as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        logger.warning("could not read %s: %s", state_file, exc)
        return None


def _present_module_ids(algo) -> Optional[set]:
    """ModuleIDs actually present on an EnvRunner, or None if unobtainable."""
    try:
        if algo.env_runner is not None:
            return set(algo.env_runner.module.keys())
    except Exception:
        pass
    try:
        per_runner = algo.env_runner_group.foreach_env_runner(
            lambda env_runner: list(env_runner.module.keys())
        )
        if per_runner:
            return set(per_runner[0])
    except Exception:
        pass
    return None


def _reconcile_league_state(algo, path: str) -> None:
    """Repair the restored callback's league bookkeeping against the sidecar."""
    callback = algo_callback(algo)
    if callback is None:
        logger.error(
            "restored algorithm has no SelfPlayCallback - league state cannot "
            "be checked. Champion matchmaking will not work."
        )
        return

    state = _read_league_state(path)
    if state is None:
        # Pre-sidecar checkpoints, and the old layout, have nothing to check
        # against. The pickled callback is all there is.
        return

    repairs = callback.restore_league_state(state, _present_module_ids(algo))
    if not repairs:
        logger.info(
            "league state verified: %s champion(s)", callback.champion_count,
        )
        return

    logger.warning(
        "league state repaired against league_state.json:\n%s\n"
        "  Repairs apply to the driver's matchmaking pool. With "
        "num_env_runners > 0 the remote runners hold their own pickled mapping "
        "fn, so prefer restoring from a checkpoint that verifies clean.",
        "\n".join(f"  - {repair}" for repair in repairs),
    )


# --- Config vs. checkpoint ---------------------------------------------------
#
# `Algorithm.from_checkpoint` rebuilds everything from the config stored in the
# checkpoint and discards the PPOConfig just built from `config/train_config.json`.
# Since resuming is documented as "edit train_config.json, set is_restore true",
# that is the same file holding lr, the reward coefficients and num_agents - so
# edits made in the same pass as the restore flag were silently ignored. These
# make the divergence loud, and fatal where it would invalidate the weights.

#: Keys whose value the restored weights depend on. A change here is a hard error.
STRUCTURAL_CONFIG_KEYS = (
    "policies",
    "policies_to_train",
    "env_config.num_of_agents",
    "env_config.n_hist",
)


def _config_fingerprint(config) -> dict:
    """The comparable subset of an AlgorithmConfig, flattened to scalars."""
    missing = object()
    fingerprint = {}

    for key in (
        "lr",
        "num_epochs",
        "minibatch_size",
        "train_batch_size_per_learner",
        "num_env_runners",
        "num_envs_per_env_runner",
        "sample_timeout_s",
        "num_learners",
        "num_gpus_per_learner",
    ):
        value = getattr(config, key, missing)
        if value is not missing:
            fingerprint[key] = value

    for key in ("policies", "policies_to_train"):
        value = getattr(config, key, missing)
        # Only the ids matter, and only the ones the config asks for: champions
        # are added to `policies` during a run, so a restored config legitimately
        # holds more of them than a freshly built one. `policies_to_train` can be
        # a callable, which has nothing comparable about it.
        if value is not missing and isinstance(value, (list, tuple, set, dict)):
            fingerprint[key] = sorted(
                m for m in value if not str(m).startswith(CHAMPION_PREFIX)
            )

    for key, value in (getattr(config, "env_config", None) or {}).items():
        fingerprint[f"env_config.{key}"] = value

    return fingerprint


def _check_restored_config(restored, desired) -> None:
    """Report config keys the restore is about to ignore; raise on structural ones.

    Raises:
        ValueError: a structural key differs, so the checkpoint's weights do not
            fit the requested configuration.
    """
    old = _config_fingerprint(restored)
    new = _config_fingerprint(desired)

    diverged = {
        key: (old[key], new[key])
        for key in set(old) & set(new)
        if old[key] != new[key]
    }
    if not diverged:
        return

    structural = {k: v for k, v in diverged.items() if k in STRUCTURAL_CONFIG_KEYS}
    if structural:
        detail = "\n".join(
            f"  {key}: checkpoint has {was!r}, config asks for {wants!r}"
            for key, (was, wants) in sorted(structural.items())
        )
        raise ValueError(
            "Cannot restore: the configuration changes the shape of the problem "
            f"the checkpoint was trained on.\n{detail}\n"
            "The restored weights do not fit. Either revert these keys, or start "
            "a fresh run (is_restore false, or a new log_base_dir)."
        )

    detail = "\n".join(
        f"  {key}: {was!r} (checkpoint, in effect) != {wants!r} (config, ignored)"
        for key, (was, wants) in sorted(diverged.items())
    )
    logger.warning(
        "restoring keeps the checkpoint's own config. These config values will "
        "NOT take effect:\n%s\n"
        "  Restore rebuilds the algorithm from the checkpoint, so only the "
        "driver-side knobs (num_iters, chkpt_freq, chkpt_keep) still apply. To "
        "train with these values, start a fresh run.", detail,
    )


def restore_candidates(cfg: TrainConfig) -> List[Tuple[int, str]]:
    """The checkpoints a restore may use, oldest first.

    Without `restore_path` that is every checkpoint under `checkpoint_dir`, so
    an unreadable newest one can fall back to the one before it. With
    `restore_path` it is exactly the one checkpoint named, because falling back
    from a pinned checkpoint would train from something other than what was
    asked for.

    Raises:
        ValueError: `restore_path` is set without `is_restore`, or does not name
            a checkpoint directory.
    """
    if cfg.restore_path and not cfg.is_restore:
        raise ValueError(
            f"restore_path is set to {cfg.restore_path!r} but is_restore is false, "
            f"so the run would start from scratch and ignore it. Set is_restore "
            f"true to resume from that checkpoint, or restore_path to null to "
            f"start fresh."
        )

    if not cfg.is_restore:
        return []

    if not cfg.restore_path:
        return list_checkpoints(cfg.checkpoint_dir)

    path = os.path.abspath(cfg.restore_path)
    if not _is_checkpoint(path):
        available = [p for _i, p in reversed(list_checkpoints(cfg.checkpoint_dir))]
        listing = (
            "\n".join(f"  {p}" for p in available) if available
            else f"  (none under {cfg.checkpoint_dir})"
        )
        raise ValueError(
            f"restore_path {path} is not a checkpoint directory - it has no "
            f"rllib_checkpoint.json. Name one save, not the directory holding "
            f"them. Available, newest first:\n{listing}"
        )

    return [(_checkpoint_iteration(path), path)]


def _checkpoint_iteration(path: str) -> int:
    """The iteration a checkpoint directory's name encodes, or -1 if it does not."""
    name = os.path.basename(os.path.normpath(path))
    if name.startswith(CHECKPOINT_PREFIX):
        try:
            return int(name[len(CHECKPOINT_PREFIX):])
        except ValueError:
            pass
    return -1


def build_algo(cfg: TrainConfig):
    """Build (or restore) the Algorithm.

    Returns:
        (algorithm, callback). On a restore the callback is the algorithm's own
        unpickled instance - the one holding the restored champion pool. It is
        None only if the restored algorithm has no SelfPlayCallback at all. This
        used to return the freshly built instance instead, which trained fine
        (the algorithm uses its own) but reported an empty champion history to
        anything that inspected it.
    """
    # Resolved before build_config, so a bad restore_path fails immediately
    # rather than after an env build and a module spec.
    candidates = restore_candidates(cfg)
    pinned = bool(cfg.restore_path)

    ppo, callback_instance = build_config(cfg)

    for _iteration, path in reversed(candidates):
        logger.info(
            "restoring from %scheckpoint: %s", "pinned " if pinned else "", path,
        )
        try:
            algo = Algorithm.from_checkpoint(path)
        except Exception as exc:
            # A save killed partway through, or one written by an incompatible
            # version. Fall back to the one before it rather than losing the run -
            # unless this checkpoint was named, in which case quietly training
            # from a different one is the last thing the caller wants.
            if pinned:
                raise
            logger.warning(
                "checkpoint unreadable (%s: %s); falling back to the previous one",
                type(exc).__name__, exc,
            )
            continue

        _fix_checkpoint_optimizer_betas(algo)
        _check_restored_config(algo.config, ppo)
        _reconcile_league_state(algo, path)

        restored_callback = algo_callback(algo)
        if restored_callback is None:
            logger.warning("restored algorithm exposes no SelfPlayCallback")
        return algo, restored_callback

    if cfg.is_restore:
        logger.warning(
            "no readable checkpoint under %s - starting from scratch",
            cfg.checkpoint_dir,
        )
    else:
        logger.info("starting from scratch")
        warn_about_foreign_checkpoints(cfg)

    return ppo.build_algo(), callback_instance


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


def train(cfg: TrainConfig) -> Tuple[Algorithm, dict]:
    """Run the full training loop.

    Returns:
        (algorithm, last_result) - the trained Algorithm and the result dict of
        the final iteration. The result is returned because inspecting the
        league otherwise costs a whole extra `algo.train()` call: one more
        iteration of real sampling and learning, run for its return value, and
        one that falls outside this function's checkpointing. An empty dict is
        returned when nothing was run, i.e. when a restore is already at or past
        the target.

    Iteration numbers are the algorithm's own, which a restore brings back with
    the weights, so `num_iters` is a target: a run resumed at iteration 9 of 16
    does 7 more, not 16 more, and the total length of a run no longer depends on
    how many times it was interrupted. `num_iters_is_delta` opts back into
    counting from wherever the restore landed.
    """
    algo, _callback = build_algo(cfg)

    start = int(algo.iteration)
    target = start + cfg.num_iters if cfg.num_iters_is_delta else cfg.num_iters

    if start:
        logger.info(
            "resuming at iteration %s, training through %s", start, target,
        )

    if start >= target:
        logger.warning(
            "checkpoint is already at iteration %s, at or past the target of "
            "%s - nothing to do. Raise num_iters, or set num_iters_is_delta to "
            "run %s more from here.", start, target, cfg.num_iters,
        )
        return algo, {}

    os.makedirs(cfg.checkpoint_dir, exist_ok=True)

    iteration = start
    saved_at = None
    result: dict = {}
    for _ in range(target - start):
        # Provisional, so anything the driver logs *during* the iteration is
        # tagged with the one being worked on rather than the one before it.
        # RLlib's own count is authoritative and replaces it below; the two
        # agree unless a restore left the counter somewhere unexpected.
        set_iteration(iteration + 1)
        # And on the runners, before they sample: the episode callbacks run
        # there, so the NAV tables and the conservation ERROR are emitted in a
        # process that otherwise has no idea which iteration it is serving.
        _broadcast_iteration(algo, iteration + 1)
        result = algo.train()
        iteration = int(result.get("training_iteration", iteration + 1))
        set_iteration(iteration)
        _log_iteration(iteration, target, result, cfg)
        _append_progress(result, cfg)

        if cfg.chkpt_freq and iteration % cfg.chkpt_freq == 0:
            saved_at = iteration
            logger.info(
                "checkpoint at iter %s: %s",
                iteration, save_checkpoint(algo, cfg, iteration),
            )

    if saved_at != iteration:
        logger.info(
            "final checkpoint: %s", save_checkpoint(algo, cfg, iteration),
        )
    return algo, result


def _apply_iteration(iteration: Optional[int]):
    """A callable that tags an env runner's process with `iteration`.

    Module level rather than a lambda in the loop so it is picklable by name
    and readable in a traceback; the closure carries only an int.
    """
    def _apply(_env_runner):
        set_iteration(iteration)
        return True

    return _apply


def _broadcast_iteration(algo, iteration: int) -> None:
    """Tell every env runner which iteration it is sampling for.

    Until this existed, every line a runner logged read `iter=-`. That is the
    half of the run log that matters most under `num_env_runners > 0`: the
    episode callbacks run on the runners, so the per-episode NAV tables and the
    conservation ERROR are emitted *only* there, and none of them could be
    joined to a `progress.jsonl` row except by wall-clock order.

    doc/11 1.9 described recovering that association as "a change to what RLlib
    hands the callbacks". It is not - the driver already knows the number, and
    `foreach_env_runner` already reaches every runner. It only had to be sent.

    Best-effort, and quiet about it. This is instrumentation: a runner that is
    restarting, or an RLlib version that renames the group, must degrade to the
    old `iter=-` rather than stop a training run. `local_env_runner=False`
    because the driver's own runner shares this process and `set_iteration` has
    already tagged it.
    """
    group = getattr(algo, "env_runner_group", None)
    if group is None:
        return
    try:
        group.foreach_env_runner(
            _apply_iteration(iteration),
            local_env_runner=False,
            timeout_seconds=_BROADCAST_TIMEOUT_S,
        )
    except Exception:
        logger.debug(
            "could not broadcast iteration %s to the env runners; their log "
            "lines will read iter=-", iteration, exc_info=True,
        )


def _json_safe(value):
    """Recursively coerce a result dict into something `json.dump` accepts.

    RLlib fills results with numpy scalars, numpy arrays, and the occasional
    object with no JSON form at all. `default=` on json.dump would catch the
    last of those, but it would also stringify every numpy float, turning a
    column of numbers into a column of quoted numbers that whatever reads the
    file has to parse back. Converting first keeps numbers as numbers and
    reserves `str()` for the genuinely unserialisable.

    Non-finite floats become null: NaN and Infinity are what Python's json emits
    by default but are not valid JSON, and a NaN early in training - an
    untrained critic's `vf_explained_var`, say - should not produce a file that
    a strict parser rejects.
    """
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    # numpy scalars (.item()) before numpy arrays (.tolist()): a 0-d array has
    # both, and .item() gives the scalar rather than a bare number in a list.
    # A multi-element array has .item() too and raises on it, so a failed
    # attempt has to fall through to the next rather than give up - that is the
    # difference between logging [1, 2, 3] and logging the string "[1 2 3]".
    for unwrap in ("item", "tolist"):
        method = getattr(value, unwrap, None)
        if callable(method):
            try:
                return _json_safe(method())
            except Exception:
                continue
    return str(value)


def _append_progress(result: dict, cfg: TrainConfig) -> None:
    """Append one iteration's full result dict to `progress.jsonl`.

    Opened, written, and closed per iteration rather than held open for the run:
    a training run that is killed - a Colab disconnect, an OOM, a Ctrl-C - is
    the normal way these runs end, and this way it keeps every iteration it had
    finished instead of losing a buffer.

    Every failure here is swallowed with a warning. Logging is instrumentation;
    a full disk or a value that defeats `_json_safe` must never take down a run
    that is otherwise training fine.
    """
    try:
        os.makedirs(os.path.dirname(cfg.progress_path), exist_ok=True)
        with open(cfg.progress_path, "a") as fh:
            json.dump(_json_safe(result), fh)
            fh.write("\n")
            fh.flush()
    except Exception:
        logger.warning(
            "could not append to %s - the run continues without a progress "
            "record for this iteration", cfg.progress_path, exc_info=True,
        )


def vf_explained_var(result: dict, cfg: TrainConfig) -> dict:
    """`vf_explained_var` per trainable module, as far as the result has it.

    Only the modules in `policies_to_train` appear in the learner block, so the
    frozen champions and the random baselines are absent by construction and
    this is keyed on `trainable_policy_ids` rather than on every policy.

    A module missing from the result is omitted rather than reported as 0.0:
    absent and "the critic explains nothing" are different states, and this
    metric exists precisely to tell them apart.
    """
    from ray.rllib.utils.metrics import LEARNER_RESULTS

    learners = result.get(LEARNER_RESULTS) or {}
    out = {}
    for pid in trainable_policy_ids(cfg.num_trained_agents):
        stats = learners.get(pid)
        if isinstance(stats, dict) and VF_EXPLAINED_VAR_KEY in stats:
            out[pid] = float(stats[VF_EXPLAINED_VAR_KEY])
    return out


def _log_iteration(i: int, total: int, result: dict, cfg: TrainConfig) -> None:
    from ray.rllib.utils.metrics import ENV_RUNNER_RESULTS

    env_runners = result.get(ENV_RUNNER_RESULTS, {})
    returns = env_runners.get("module_episode_returns_mean", {})
    steps = env_runners.get("num_env_steps_sampled", "n/a")
    # vf_explained_var sits beside the returns because it is the one number that
    # says whether the critic is learning at all. A run whose returns drift
    # while every critic sits in the noise is a run whose advantages are noise,
    # and that is worth seeing at iteration 3 rather than in a post mortem.
    #
    # Formatted to 3 significant figures rather than rounded to 3 decimals:
    # this metric's whole diagnostic range is near zero, and `round(3.8e-05, 3)`
    # prints `0.0` - which is how a critic that is merely dead ends up looking
    # identical to one that reported nothing at all.
    vf = ", ".join(
        f"{pid}={value:.3g}" for pid, value in vf_explained_var(result, cfg).items()
    )
    logger.info(
        "iter %s/%s | env steps sampled: %s | module returns: %s | "
        "vf_explained_var: %s",
        i, total, steps, {k: round(float(v), 1) for k, v in returns.items()},
        vf or "n/a",
    )

    # An iteration with no env_runners block sampled nothing the learner could
    # use, which is silent otherwise: the loop still counts the iteration, still
    # checkpoints, and produces a run whose weights never moved. The usual cause
    # is sample_timeout_s elapsing before the runners have produced
    # train_batch_size steps, so say that here rather than leaving it to be
    # inferred from RLlib's "No samples returned from remote workers" warning.
    if not env_runners and cfg.num_env_runners:
        logger.warning(
            "iter %s trained on no samples: the result has no %r block. The "
            "%s env runners did not deliver %s env steps within "
            "sample_timeout_s=%s. Raise sample_timeout_s, or lower max_step "
            "(%s) / num_episodes_per_iter (%s) to shrink the batch.",
            i, ENV_RUNNER_RESULTS, cfg.num_env_runners, cfg.train_batch_size,
            cfg.sample_timeout_s, cfg.max_step, cfg.num_episodes_per_iter,
        )


def _parse_args(argv=None) -> TrainConfig:
    """Resolve a TrainConfig from the command line.

    Precedence is `config/train_config.json` -> `--config <other file>` ->
    explicit flags.

    Every flag below defaults to `argparse.SUPPRESS`, so an unset flag is
    absent from the namespace entirely. That distinction is what makes the
    precedence work: with ordinary argparse defaults, the config file could set
    `num_agents=4` and an unpassed `--agents` would immediately overwrite it.
    It is also why no flag carries a default value of its own - an argparse
    default would be exactly the hardcoded value `train_config.json` exists to
    hold.
    """
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument(
        "--config",
        type=str,
        default=None,
        help="Alternative JSON config file. config/train_config.json already "
             "supplies every default; pass this to run against a different "
             "file. Flags override it.",
    )
    p.add_argument("--agents", type=int, dest="num_agents", default=argparse.SUPPRESS)
    p.add_argument("--trained-agents", type=int, dest="num_trained_agents", default=argparse.SUPPRESS)
    p.add_argument("--iters", type=int, dest="num_iters", default=argparse.SUPPRESS)
    p.add_argument("--max-step", type=int, default=argparse.SUPPRESS)
    p.add_argument("--env-runners", type=int, dest="num_env_runners", default=argparse.SUPPRESS)
    p.add_argument("--envs-per-runner", type=int, dest="num_envs_per_env_runner", default=argparse.SUPPRESS)
    p.add_argument("--gpus-per-learner", type=float, dest="num_gpus_per_learner", default=argparse.SUPPRESS)
    p.add_argument(
        "--sample-timeout",
        type=float,
        dest="sample_timeout_s",
        default=argparse.SUPPRESS,
        help="Seconds to wait for a remote env runner's share of the batch. "
             "Too low and the iteration discards its rollouts and trains on "
             "nothing; watch for 'No samples returned from remote workers'.",
    )
    p.add_argument("--restore", action="store_true", dest="is_restore", default=argparse.SUPPRESS)
    p.add_argument(
        "--from-checkpoint",
        type=str,
        dest="restore_path",
        default=argparse.SUPPRESS,
        help="Resume from this checkpoint directory (one iter_* save, not the "
             "directory holding them) instead of the newest. Implies --restore.",
    )
    p.add_argument("--chkpt-freq", type=int, default=argparse.SUPPRESS)
    p.add_argument(
        "--chkpt-keep",
        type=int,
        default=argparse.SUPPRESS,
        help="How many iter_* checkpoints to retain (<= 0 keeps all).",
    )
    p.add_argument(
        "--iters-is-delta",
        action="store_true",
        dest="num_iters_is_delta",
        default=argparse.SUPPRESS,
        help="Treat --iters as iterations to run from a restore point, rather "
             "than the iteration to train through.",
    )
    p.add_argument("--log-base-dir", type=str, default=argparse.SUPPRESS)
    p.add_argument(
        "--run-id", type=str, dest="run_id", default=argparse.SUPPRESS,
        help="Name of this run's directory under log_base_dir, holding "
             "progress.jsonl and the run logs. Generated from the date, time "
             "and four random hex digits when unset. Pass the id of an earlier "
             "run to write into its directory and extend its progress.jsonl.",
    )
    p.add_argument("--log-level", type=str, default=argparse.SUPPRESS)
    p.add_argument("--seed", type=int, default=argparse.SUPPRESS)
    p.add_argument(
        "--no-episode-data",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Disable per-episode step pickles (large I/O at long episodes).",
    )
    p.add_argument(
        "--no-strict-nav-check",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Log an episode-end NAV conservation violation instead of raising "
             "on it. The nav_conservation_error metric is emitted either way.",
    )
    args = p.parse_args(argv)

    overrides = {
        k: v for k, v in vars(args).items()
        if k not in ("config", "no_episode_data", "no_strict_nav_check")
    }
    if getattr(args, "no_episode_data", False):
        overrides["episode_data_dir"] = None
    if getattr(args, "no_strict_nav_check", False):
        overrides["strict_nav_check"] = False
    if "restore_path" in overrides:
        # Naming a checkpoint on the command line is unambiguous about intent,
        # so it does not also need --restore. In the config file the two keys
        # must agree - see restore_candidates.
        overrides.setdefault("is_restore", True)

    base = TrainConfig.from_json(args.config) if args.config else TrainConfig()
    return dataclasses.replace(base, **overrides)


def configure_run_logging(cfg: TrainConfig) -> None:
    """Attach this run's log files and export the settings for Ray's workers.

    Call it once, before `ray.init`, and before anything else logs. The order
    matters in both directions: `configure` exports `$CDA_LOG_LEVEL` and
    `$CDA_LOG_DIR`, which is what a locally started raylet passes to its
    workers and what `merge_runtime_env` reads for a cluster that was already
    running, so a `ray.init` that happens first gets neither.

    Shared with the notebook, which calls `train()` directly rather than going
    through `main()` and so used to leave no run log at all - the one output a
    disconnected Colab session most needs.

    `force=True` because importing the module already configured this process
    from the environment or the config default, and neither of those knows
    about `cfg.run_dir`.
    """
    # cfg.run_dir, not cfg.log_base_dir: the per-worker file names keep two
    # processes of *this* run apart, but two concurrent runs would still have
    # collided on the driver's own `run.log`, which carries no pid. The run
    # directory is what keeps runs apart.
    configure_logging(cfg.cda_log_level, log_dir=cfg.run_dir, force=True)
    logger.info("run id: %s (%s)", cfg.run_id, cfg.run_dir)
    if log_file_path():
        logger.info("run log: %s", log_file_path())


def main(argv=None) -> None:
    cfg = _parse_args(argv)

    # Before anything else logs, and before ray.init: `configure` exports the
    # level so the worker processes Ray is about to start come up at the same
    # one. force=True because importing this module already configured the
    # process from the environment or the config default, and the level just
    # parsed from the command line is the one the user asked for.
    #
    # log_dir is passed only here, and only by the driver: it adds the rotating
    # run log beside progress.jsonl, and RotatingFileHandler cannot be shared
    # across processes without workers racing each other's rotations.
    #
    configure_run_logging(cfg)

    # Shared with the notebook, which has to export these before it imports
    # ray. Imported here rather than at module scope: runtime.py reads
    # TrainConfig's fields, so a top-level import would be circular.
    from gym_continuousDoubleAuction.train.runtime import apply_env_vars

    apply_env_vars()

    # runtime_env carries the log level and directory to the workers Ray starts
    # for this job. The os.environ export configure() already did covers a
    # cluster this process starts, because the raylet inherits our environment;
    # it does not cover `ray.init(address=...)` against a cluster that was
    # running first. See logging_setup.worker_env_vars.
    ray.init(
        ignore_reinit_error=True,
        include_dashboard=False,
        runtime_env=merge_runtime_env(),
    )
    try:
        train(cfg)
    except BaseException:
        # The excepthook installed by configure() would catch this too, but only
        # after `finally` has already run ray.shutdown() and cleared the
        # iteration - so the traceback would be logged out of order, after the
        # teardown lines, and untagged. Logging it here keeps it where it
        # happened, with `iter=` still naming the iteration that failed.
        logger.exception("run %s failed", cfg.run_id)
        raise
    finally:
        # Shutdown is not part of any iteration; leaving the last one set would
        # tag teardown lines with a number they had nothing to do with.
        set_iteration(None)
        ray.shutdown()


if __name__ == "__main__":
    main()
