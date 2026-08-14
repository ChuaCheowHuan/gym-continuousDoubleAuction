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

import logging
import os
from typing import Optional

from gym_continuousDoubleAuction.config_loader import constants

#: Root logger for the package. Module loggers are children of it, so one
#: handler and one level here cover everything.
ROOT_NAME = "gym_continuousDoubleAuction"

_configured = False


def _settings() -> dict:
    return constants("logging")


def level_env_var() -> str:
    """Name of the environment variable that carries the level to workers."""
    return _settings()["env_var"]


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


def configure(level: Optional[str] = None, *, force: bool = False) -> str:
    """Attach the package handler and set the level. Idempotent per process.

    Also exports the resolved level into the environment, so Ray workers
    started after this call inherit it. Returns the level applied.

    `force` reconfigures a process that is already set up, which is what a
    caller that has just parsed a new level needs; ordinary `get_logger` calls
    leave an existing configuration alone.
    """
    global _configured

    settings = _settings()
    resolved = resolve_level(level)

    root = logging.getLogger(ROOT_NAME)
    if not _configured or force:
        for handler in list(root.handlers):
            root.removeHandler(handler)
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(settings["format"], datefmt=settings["datefmt"])
        )
        root.addHandler(handler)
        _configured = True

    root.setLevel(resolved)
    os.environ[level_env_var()] = resolved
    return resolved


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
