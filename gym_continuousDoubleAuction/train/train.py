"""
Training entry point for the CDA environment with league-based self-play.

This was extracted from CDA_train.ipynb so the training path is importable and
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
import os
from typing import Tuple
from ray.rllib.algorithms.algorithm import Algorithm
from gym_continuousDoubleAuction.logging_setup import get_logger
from gym_continuousDoubleAuction.logging_setup import set_iteration

#: Every name this module defined before the split (issue #254) is still importable from
#: here; the code is in `config`, `build`, `checkpoint`, `progress` and `cli`.
from gym_continuousDoubleAuction.train.config import (
    generate_run_id,
    _default,
    TrainConfig,
    ENV_NAME,
    TRAIN_CONFIG_FILE,
    PROGRESS_FILE,
    _BROADCAST_TIMEOUT_S,
    VF_EXPLAINED_VAR_KEY,
)
from gym_continuousDoubleAuction.train.build import (
    register_env,
    make_spaces,
    _next_obs_connector,
    CBP_CONFIG_KEY,
    OPTIMIZER_CONFIG_KEY,
    _learner_class,
    _learner_config_dict,
    build_config,
    build_algo,
    log_module_sizes,
)
from gym_continuousDoubleAuction.train.checkpoint import (
    CHECKPOINT_PREFIX,
    CHECKPOINT_TMP_SUFFIX,
    LEAGUE_STATE_FILE,
    _NOTED_OLD_LAYOUT,
    _is_checkpoint,
    list_checkpoints,
    save_checkpoint,
    _prune_checkpoints,
    _mtime,
    _iteration_of,
    warn_about_foreign_checkpoints,
    algo_callback,
    _write_league_state,
    _read_league_state,
    _present_module_ids,
    _reconcile_league_state,
    STRUCTURAL_CONFIG_KEYS,
    UNRESTORABLE_CONFIG_KEYS,
    UNRESTORABLE_WHEN_ACTIVE_KEYS,
    PRE_FEATURE_BEHAVIOUR,
    _config_fingerprint,
    _encoder_fingerprint,
    _model_config_get,
    _check_restored_config,
    restore_candidates,
    _checkpoint_iteration,
    _fix_checkpoint_optimizer_betas,
)
from gym_continuousDoubleAuction.train.progress import (
    NavConservationError,
    nav_violations,
    _check_nav_conservation,
    _apply_iteration,
    _broadcast_iteration,
    _json_safe,
    _append_progress,
    vf_explained_var,
    _log_iteration,
)

logger = get_logger("gym_continuousDoubleAuction.train.train")


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
            "resuming at iteration %s, training through %s",
            start,
            target,
        )

    if start >= target:
        logger.warning(
            "checkpoint is already at iteration %s, at or past the target of "
            "%s - nothing to do. Raise num_iters, or set num_iters_is_delta to "
            "run %s more from here.",
            start,
            target,
            cfg.num_iters,
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
        # After the progress row is on disk - the failing iteration's numbers
        # are what the violation is diagnosed from - and before the checkpoint,
        # because a corrupt ledger is not a state worth saving.
        _check_nav_conservation(iteration, result, cfg)

        if cfg.chkpt_freq and iteration % cfg.chkpt_freq == 0:
            saved_at = iteration
            logger.info(
                "checkpoint at iter %s: %s",
                iteration,
                save_checkpoint(algo, cfg, iteration),
            )

    if saved_at != iteration:
        logger.info(
            "final checkpoint: %s",
            save_checkpoint(algo, cfg, iteration),
        )
    return algo, result


#: The command-line names, re-exported lazily: `cli` imports `train`, so importing it here
#: at module level would be a cycle.
_CLI_NAMES = ("_parse_args", "configure_run_logging", "ray_logging_config", "main")


def __getattr__(name):
    if name in _CLI_NAMES:
        from gym_continuousDoubleAuction.train import cli

        return getattr(cli, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "train",
    "generate_run_id",
    "_default",
    "TrainConfig",
    "ENV_NAME",
    "TRAIN_CONFIG_FILE",
    "PROGRESS_FILE",
    "_BROADCAST_TIMEOUT_S",
    "VF_EXPLAINED_VAR_KEY",
    "register_env",
    "make_spaces",
    "_next_obs_connector",
    "CBP_CONFIG_KEY",
    "OPTIMIZER_CONFIG_KEY",
    "_learner_class",
    "_learner_config_dict",
    "build_config",
    "build_algo",
    "log_module_sizes",
    "CHECKPOINT_PREFIX",
    "CHECKPOINT_TMP_SUFFIX",
    "LEAGUE_STATE_FILE",
    "_NOTED_OLD_LAYOUT",
    "_is_checkpoint",
    "list_checkpoints",
    "save_checkpoint",
    "_prune_checkpoints",
    "_mtime",
    "_iteration_of",
    "warn_about_foreign_checkpoints",
    "algo_callback",
    "_write_league_state",
    "_read_league_state",
    "_present_module_ids",
    "_reconcile_league_state",
    "STRUCTURAL_CONFIG_KEYS",
    "UNRESTORABLE_CONFIG_KEYS",
    "UNRESTORABLE_WHEN_ACTIVE_KEYS",
    "PRE_FEATURE_BEHAVIOUR",
    "_config_fingerprint",
    "_encoder_fingerprint",
    "_model_config_get",
    "_check_restored_config",
    "restore_candidates",
    "_checkpoint_iteration",
    "_fix_checkpoint_optimizer_betas",
    "NavConservationError",
    "nav_violations",
    "_check_nav_conservation",
    "_apply_iteration",
    "_broadcast_iteration",
    "_json_safe",
    "_append_progress",
    "vf_explained_var",
    "_log_iteration",
]


if __name__ == "__main__":
    from gym_continuousDoubleAuction.train.cli import main

    main()
