"""The package's logging, in one place.

Every module that has something to say does::

    from gym_continuousDoubleAuction.logging_setup import get_logger

    logger = get_logger(__name__)

and then `logger.debug/info/warning/error`. Nothing in this codebase calls
`print` to report what it is doing; a `print` is output that cannot be filtered,
attributed to a process, or switched off without editing the source, which is
exactly what a training run with several env runners cannot afford.

Two facts shape this module:

* **Ray workers are separate interpreters.** With `num_env_runners > 0` the
  episode callbacks run in processes that never executed `train.main`, so a
  level set there does not reach them. The level therefore travels as an
  environment variable (`$CDA_LOG_LEVEL` by default, named in the config), which
  Ray propagates to workers on the node; each worker's first `get_logger` call
  reads it and configures that process. `configure()` exports the variable as
  well as applying it, so the driver and the workers agree.

* **Configuration happens once per process, lazily.** `get_logger` configures
  the package's root logger on first use rather than at import time, so
  importing the package never installs a handler behind the caller's back. A
  handler is attached to the `gym_continuousDoubleAuction` logger only, with
  propagation left on but Ray's own handlers unaffected.

Levels used across the package:

===========  =============================================================
`DEBUG`      Per-step detail: the env's `_render` dumps, account and
             mark-to-market tables, the episode hooks' derived parameters.
`INFO`       Per-episode and per-iteration events a run is expected to
             produce: the NAV table, league statistics, champion changes,
             checkpoint writes.
`WARNING`    A recoverable surprise, e.g. a requested GPU that is absent.
`ERROR`      A broken invariant, e.g. NAV conservation failing.
===========  =============================================================
"""
from __future__ import annotations

import contextvars
import logging
import logging.handlers
import os
from typing import Optional

from gym_continuousDoubleAuction.config_loader import constants

#: Root logger for the package. Module loggers are children of it, so one
#: handler and one level here cover everything.
ROOT_NAME = "gym_continuousDoubleAuction"

_configured = False
_log_file_path: Optional[str] = None

#: The training iteration in progress, for the `iter=` field of every log line.
#: A ContextVar rather than a global so it is per-thread: RLlib may run the
#: driver loop alongside other threads, and an int here would be shared by all
#: of them. Unset in any process that does not know the iteration - every env
#: runner - where it formats as "-".
_iteration: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "cda_log_iteration", default=None
)

#: Substituted for the iteration when it is unknown. Not "0", which is a real
#: iteration number, and not "" which would make the field vanish and misalign
#: every line.
_NO_ITERATION = "-"


def set_iteration(iteration: Optional[int]) -> None:
    """Tag subsequent log lines in this process with a training iteration.

    Lets a line in the run log be joined to the `progress.jsonl` row for the
    same iteration, which was previously guesswork: the file is keyed by
    iteration and the log was keyed by nothing.

    Pass None to clear it, which is what a process that has stopped training
    should do rather than leave a stale number on unrelated lines.
    """
    _iteration.set(iteration)


def current_iteration() -> Optional[int]:
    """The iteration tagging this process's log lines, or None."""
    return _iteration.get()


def log_file_path() -> Optional[str]:
    """The run log this process writes, or None if it logs only to stdout."""
    return _log_file_path


class _IterationFilter(logging.Filter):
    """Give every record an `iteration` attribute so the format can use it.

    Attached to the handlers rather than to the logger: a filter on a logger
    only sees records logged directly to it, while every record from a child
    module logger reaches the handler. Without this, one line from a module
    that never sets an iteration would raise a formatting error rather than
    print a dash.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        iteration = _iteration.get()
        record.iteration = _NO_ITERATION if iteration is None else iteration
        return True


def _settings() -> dict:
    return constants("logging")


def level_env_var() -> str:
    """Name of the environment variable that carries the level to workers."""
    return _settings()["env_var"]


def log_dir_env_var() -> str:
    """Name of the environment variable carrying the log directory to workers.

    The companion of `level_env_var`, and for the same reason: an env runner is
    a separate interpreter that never runs `train.main`, so anything the driver
    decided has to travel through the environment to reach it.
    """
    return _settings()["dir_env_var"]


def resolve_level(level: Optional[str] = None) -> str:
    """The level to use, in precedence order.

    An explicit argument wins, then `$CDA_LOG_LEVEL`, then the configured
    default. The argument comes first because a caller that passed one - the
    training entry point, reading `TrainConfig.cda_log_level` - is being
    specific on purpose.
    """
    if level:
        return str(level).upper()
    from_env = os.environ.get(level_env_var())
    if from_env:
        return from_env.upper()
    return str(_settings()["level"]).upper()


def configure(
    level: Optional[str] = None,
    *,
    log_dir: Optional[str] = None,
    force: bool = False,
) -> str:
    """Attach the package handlers and set the level. Idempotent per process.

    Also exports the resolved level into the environment, so Ray workers
    started after this call inherit it. Returns the level applied.

    `force` reconfigures a process that is already set up, which is what a
    caller that has just parsed a new level needs; ordinary `get_logger` calls
    leave an existing configuration alone.

    `log_dir` adds a rotating file handler writing `<log_dir>/<file_name>`,
    beside `progress.jsonl`, and exports the directory so the Ray workers
    started afterwards write there too. A worker resolves it from the
    environment and writes its own pid-suffixed file; passing no `log_dir` and
    having no exported one means stdout only, which is what a bare import gets.

    Each process writes a separate file on purpose. `RotatingFileHandler` is
    not safe across processes - two of them crossing the size threshold
    together rename and truncate the same file underneath each other - and
    sharing one is not optional-but-nice here: the episode callbacks run on the
    env runners, so with `num_env_runners > 0` the NAV tables and the
    conservation ERROR are emitted in a worker and would otherwise reach no
    file at all.
    """
    global _configured, _log_file_path

    settings = _settings()
    resolved = resolve_level(level)

    # A worker never runs train.main, so the directory reaches it the same way
    # the level does. `own_file` keeps the driver on the plain name.
    own_file = log_dir is not None
    if log_dir is None:
        log_dir = os.environ.get(log_dir_env_var()) or None

    root = logging.getLogger(ROOT_NAME)
    if not _configured or force:
        for handler in list(root.handlers):
            handler.close()
            root.removeHandler(handler)
        _log_file_path = None

        formatter = logging.Formatter(
            settings["format"], datefmt=settings["datefmt"]
        )
        iteration_filter = _IterationFilter()

        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        stream.addFilter(iteration_filter)
        root.addHandler(stream)

        if log_dir:
            file_handler = _build_file_handler(log_dir, settings, own_file)
            if file_handler is not None:
                file_handler.setFormatter(formatter)
                file_handler.addFilter(iteration_filter)
                root.addHandler(file_handler)

        _configured = True

    root.setLevel(resolved)
    os.environ[level_env_var()] = resolved
    if log_dir:
        os.environ[log_dir_env_var()] = os.path.abspath(log_dir)
    return resolved


def _build_file_handler(log_dir: str, settings: dict, own_file: bool):
    """A rotating handler under `log_dir`, or None if file logging is off.

    A failure to open the file is a warning, not an exception. Logging is
    instrumentation: a run that cannot write its log should still train, the
    same way `_append_progress` refuses to take down a run that is otherwise
    fine. The warning goes to the stream handler, which is already attached.
    """
    global _log_file_path

    file_name = settings.get("file_name")
    if not file_name:
        return None

    if not own_file:
        # A worker: same name with its pid before the suffix, so run.log has
        # run.4231.log beside it rather than several processes fighting over
        # one inode.
        stem, suffix = os.path.splitext(file_name)
        file_name = f"{stem}.{os.getpid()}{suffix}"

    path = os.path.join(os.path.abspath(log_dir), file_name)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            path,
            maxBytes=settings["file_max_bytes"],
            backupCount=settings["file_backup_count"],
            encoding="utf-8",
            delay=True,
        )
    except OSError:
        logging.getLogger(ROOT_NAME).warning(
            "could not open the run log at %s - continuing with stdout only",
            path, exc_info=True,
        )
        return None

    _log_file_path = path
    return handler


def get_logger(name: str) -> logging.Logger:
    """A logger for `name`, configuring this process on first use.

    `name` is normally `__name__`. A name outside the package namespace is
    re-homed beneath `ROOT_NAME`, because only names under it inherit the
    package's handler and level - anything else falls through to logging's
    last-resort handler, which drops everything below WARNING.

    That is not a hypothetical: `python -m gym_continuousDoubleAuction.train.train`
    sets `__name__` to `"__main__"` in the module it runs, so an entry point
    passing `__name__` would silently lose every INFO line it emitted. Entry
    points should pass an explicit dotted name so they stay attributable;
    re-homing is the safety net for the ones that do not.
    """
    if not _configured:
        configure()
    if name != ROOT_NAME and not name.startswith(f"{ROOT_NAME}."):
        name = f"{ROOT_NAME}.{name}"
    return logging.getLogger(name)
