"""The `python -m gym_continuousDoubleAuction.train.train` command line (issue #254)."""

from __future__ import annotations
import argparse
import dataclasses
import logging
import ray
from gym_continuousDoubleAuction.logging_setup import configure as configure_logging
from gym_continuousDoubleAuction.logging_setup import get_logger
from gym_continuousDoubleAuction.logging_setup import (
    ROOT_NAME,
    log_file_path,
    merge_runtime_env,
    set_iteration,
)
from gym_continuousDoubleAuction.train.config import TrainConfig

logger = get_logger("gym_continuousDoubleAuction.train.train")


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
    p = argparse.ArgumentParser(
        description="Training entry point for the CDA environment with league-based self-play."
    )
    p.add_argument(
        "--config",
        type=str,
        default=None,
        help="Alternative JSON config file. config/train_config.json already "
        "supplies every default; pass this to run against a different "
        "file. Flags override it.",
    )
    p.add_argument("--agents", type=int, dest="num_agents", default=argparse.SUPPRESS)
    p.add_argument(
        "--trained-agents", type=int, dest="num_trained_agents", default=argparse.SUPPRESS
    )
    p.add_argument("--iters", type=int, dest="num_iters", default=argparse.SUPPRESS)
    p.add_argument("--max-step", type=int, default=argparse.SUPPRESS)
    p.add_argument("--env-runners", type=int, dest="num_env_runners", default=argparse.SUPPRESS)
    p.add_argument(
        "--envs-per-runner", type=int, dest="num_envs_per_env_runner", default=argparse.SUPPRESS
    )
    p.add_argument(
        "--gpus-per-learner", type=float, dest="num_gpus_per_learner", default=argparse.SUPPRESS
    )
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
        "--run-id",
        type=str,
        dest="run_id",
        default=argparse.SUPPRESS,
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
        help="Disable the per-step episode record entirely - both the Parquet "
        "files and the buffering behind them.",
    )
    p.add_argument(
        "--episode-sample-every",
        type=int,
        dest="episode_sample_every",
        default=argparse.SUPPRESS,
        help="Record one episode in N. 1 records every episode (~34MB each at "
        "max_step 4096 and 8 agents).",
    )
    p.add_argument(
        "--episode-max-bytes",
        type=int,
        dest="episode_max_bytes",
        default=argparse.SUPPRESS,
        help="Cap the episode record each writer keeps, oldest deleted first. 0 keeps everything.",
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
        k: v
        for k, v in vars(args).items()
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
    #
    # propagate=False whenever Ray is about to be given a LoggingConfig: that
    # configures the *root* logger of this process and of every worker Ray
    # starts for the job, so a package record travelling on to root would be
    # printed twice - once by the handler attached here and once by Ray's.
    # Turned back ON otherwise, explicitly: `configure` leaves propagation as
    # it found it for None, so a process that ran once with an encoding (a
    # notebook, a `compare` sweep) kept it off for every later run without one
    # (issue #238). Propagation is what any root-attached handler (pytest's
    # caplog among them) depends on.
    configure_logging(
        cfg.cda_log_level,
        log_dir=cfg.run_dir,
        force=True,
        propagate=not cfg.ray_log_encoding,
    )
    logger.info("run id: %s (%s)", cfg.run_id, cfg.run_dir)
    if log_file_path():
        logger.info("run log: %s", log_file_path())
    if cfg.episode_data_path:
        logger.info("episode record: %s", cfg.episode_data_path)


def ray_logging_config(cfg: TrainConfig):
    """`ray.LoggingConfig` for this run, or None to leave Ray's logging alone.

    This is the only lever that reaches the Ray-side output of a *worker*. The
    package's own logging already crosses to the runners (`$CDA_LOG_LEVEL`,
    `$CDA_LOG_DIR`, and the `runtime_env`), but Ray's does not: an env-runner
    restart notice, the "No samples returned from remote workers" warning, and
    the traceback `EnvRunnerGroup` swallows when a runner dies (docs/21 §2.1) are
    all emitted by Ray's own loggers in a process this package never configured.
    A `LoggingConfig` is applied by Ray to the driver and to every process it
    starts for the job, which is exactly that set.

    Feature-detected rather than assumed. `ray.LoggingConfig` is a young API;
    a Ray without it, or one that rejects an argument, must cost this run its
    log formatting and nothing else - which includes undoing what
    `configure_run_logging` did in expectation of one: it turned propagation
    to root off because Ray was going to configure root. With no LoggingConfig
    nothing does, so propagation is turned back on (its default) rather than
    leaving package records unable to reach a root handler at all.
    """
    if not cfg.ray_log_encoding:
        return None
    factory = getattr(ray, "LoggingConfig", None)
    if factory is None:
        logger.debug("this Ray has no LoggingConfig; leaving its logging alone")
        logging.getLogger(ROOT_NAME).propagate = True
        return None
    try:
        return factory(
            encoding=cfg.ray_log_encoding.upper(),
            log_level=cfg.log_level,
        )
    except Exception:
        logger.warning(
            "could not build a ray.LoggingConfig(encoding=%r, log_level=%r) - "
            "continuing with Ray's default logging",
            cfg.ray_log_encoding,
            cfg.log_level,
            exc_info=True,
        )
        logging.getLogger(ROOT_NAME).propagate = True
        return None


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
    logging_config = ray_logging_config(cfg)
    ray.init(
        ignore_reinit_error=True,
        include_dashboard=False,
        runtime_env=merge_runtime_env(),
        # Only when there is one: passing logging_config=None is not the same
        # as omitting it on every Ray version, and "leave Ray's logging alone"
        # has to mean exactly that.
        **({"logging_config": logging_config} if logging_config else {}),
    )
    # Imported here: `train.train` re-exports this module's names, so importing it at the
    # top would be a cycle.
    from gym_continuousDoubleAuction.train.train import train

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
