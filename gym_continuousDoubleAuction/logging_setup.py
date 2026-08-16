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
import logging.handlers
import os
import sys
import threading
from typing import Optional

from gym_continuousDoubleAuction.config_loader import constants

#: Root logger for the package. Module loggers are children of it, so one
#: handler and one level here cover everything.
ROOT_NAME = "gym_continuousDoubleAuction"

_configured = False
_log_file_path: Optional[str] = None
_excepthooks_installed = False

#: Guards the handler swap in `configure`. The individual `addHandler` calls are
#: already atomic under logging's own module lock, but the sequence here is
#: remove-close-then-add, and two threads interleaving in it produce duplicate
#: handlers or a handler closed while another thread is emitting through it.
#: `get_logger`'s check-then-act on `_configured` has the same shape. Cheap to
#: hold: this runs once per process.
_configure_lock = threading.Lock()

#: The training iteration in progress, for the `iter=` field of every log line.
#: Unset in a process that does not know it, where it formats as "-".
#:
#: A plain module global, deliberately, having previously been a ContextVar.
#: The ContextVar was chosen to be per-thread, on the reasoning that an int
#: would be "shared by all of them" - but sharing is the correct model here.
#: There is one training loop per process, so the iteration is a property of
#: the *process*, and per-thread storage made that unreachable in two ways.
#: A new thread starts from an empty context, so it read `-` even on the driver,
#: which knows perfectly well which iteration it is on; and a value set inside a
#: Ray actor task is not guaranteed to still be in context for the next task,
#: which is what `train._broadcast_iteration` needs it to be.
#:
#: Assignment of an int is atomic under the GIL, so no lock is needed. The one
#: configuration this gets wrong is two concurrent training loops in threads of
#: one process, which RLlib does not support anyway.
_iteration: Optional[int] = None

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

    Process-wide, so every thread's lines carry it - including the ones the
    driver logs from somewhere other than the training loop. On an env runner
    this is called by `train._broadcast_iteration` rather than locally.
    """
    global _iteration
    _iteration = iteration


def current_iteration() -> Optional[int]:
    """The iteration tagging this process's log lines, or None."""
    return _iteration


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
        iteration = _iteration
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
    # The whole swap under one lock. Not for the individual addHandler calls -
    # logging locks those itself - but for the remove-close-then-add sequence,
    # which is where a second thread finds either no handler at all or one that
    # has just been closed underneath it.
    with _configure_lock:
        if not _configured or force:
            for handler in list(root.handlers):
                handler.close()
                root.removeHandler(handler)
            _log_file_path = None

            formatter = logging.Formatter(
                settings["format"], datefmt=settings["datefmt"]
            )
            iteration_filter = _IterationFilter()

            # Explicitly stdout. `logging.StreamHandler()` defaults to stderr,
            # which made `python -m ...train > run.txt` capture nothing of the
            # output a run exists to produce - the NAV tables, the league
            # statistics, the iteration summaries - while the docs described it
            # as stdout throughout. Warnings and errors are not routed
            # separately: they are part of the same narrative, and splitting
            # them across two streams reorders them against each other.
            stream = logging.StreamHandler(stream=sys.stdout)
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

        # Inside the lock: it copies `root.handlers`, which the block above is
        # what changes. Route warnings.warn through logging, so a
        # DeprecationWarning from Ray or gymnasium - the earliest signal that an
        # upgrade is about to break this repository - lands in the run log
        # instead of going to stderr unrecorded and unrotated. `py.warnings` is
        # a top-level logger and this package's handlers hang off
        # `gym_continuousDoubleAuction`, so the two are joined by copying the
        # handlers across rather than by propagation.
        _capture_warnings(root)

    # Every process, not just the driver: a worker that dies takes its
    # traceback with it otherwise, and the env runners are where the episode
    # callbacks - including the NAV conservation raise - actually run.
    install_excepthooks()

    os.environ[level_env_var()] = resolved
    if log_dir:
        os.environ[log_dir_env_var()] = os.path.abspath(log_dir)
    return resolved


def _capture_warnings(root: logging.Logger) -> None:
    """Point `py.warnings` at this package's handlers and turn capture on.

    `logging.captureWarnings(True)` alone would not be enough: it logs to
    `py.warnings`, which is outside `ROOT_NAME` and so inherits none of the
    handlers attached here. Without somewhere to go the record falls through to
    logging's last-resort handler, which writes to stderr - exactly what
    capturing it was meant to stop. So the package's handlers are mirrored onto
    it, replacing any set installed by an earlier `configure()` call.
    """
    warnings_logger = logging.getLogger("py.warnings")
    for handler in list(warnings_logger.handlers):
        warnings_logger.removeHandler(handler)
    for handler in root.handlers:
        warnings_logger.addHandler(handler)
    # Its own records must not also reach the real root logger, which would
    # print them a second time if anything ever calls basicConfig.
    warnings_logger.propagate = False
    logging.captureWarnings(True)


def _worker_file_tag() -> str:
    """A file-name tag unique across the cluster, not merely across this node.

    A pid alone is not a unique key. Two nodes number their processes
    independently, so on a multi-node run with `log_base_dir` on a shared
    filesystem - an NFS mount, or the Drive mount Colab uses - two workers can
    hold the same pid and open the same `run.<pid>.log`. That is the
    cross-process `RotatingFileHandler` race the per-worker name exists to
    prevent, reintroduced by the naming itself. Ray's worker id is unique
    cluster-wide, so it is the part that actually separates them; the pid stays
    in front of it because it is what the `pid=` field of every line matches,
    and dropping it would make a file hard to tie back to its lines.

    Ray is read from `sys.modules` rather than imported. Importing it here would
    break a documented ordering: `runtime.apply_env_vars()` must run *before*
    ray is first imported, and `configure()` runs before that in `main()`. In
    an env runner - the only process that takes this branch in earnest - ray is
    long since imported, so the lookup succeeds exactly where it matters.
    """
    pid = os.getpid()
    ray = sys.modules.get("ray")
    if ray is not None:
        try:
            worker_id = ray.get_runtime_context().get_worker_id()
        except Exception:
            # Not in a worker, or a Ray version that names this differently.
            # The pid alone is still correct on a single node.
            worker_id = None
        if worker_id:
            return f"{pid}.{str(worker_id)[:8]}"
    return str(pid)


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
        # A worker: same name with its own tag before the suffix, so run.log
        # has run.4231.a3f9c2d1.log beside it rather than several processes
        # fighting over one inode.
        stem, suffix = os.path.splitext(file_name)
        file_name = f"{stem}.{_worker_file_tag()}{suffix}"

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


def worker_env_vars() -> dict:
    """The logging settings a Ray worker needs, as an env-var mapping.

    `configure()` exports these into `os.environ`, which reaches workers only
    when this process is the one that starts the cluster - the raylet inherits
    the environment and forks workers from it. Against an existing cluster
    (`ray.init(address=...)`, or a Ray job submitted to a running head node)
    the raylet was started long before, so nothing exported here ever arrives:
    those workers come up at the config default level and write no run log at
    all. Since the episode callbacks run on the env runners, that is precisely
    where the NAV tables and the conservation ERROR are emitted - so they would
    reach no file anywhere.

    Passing this through `ray.init(runtime_env={"env_vars": ...})` closes that,
    because Ray applies a runtime_env to the worker processes it starts for the
    job regardless of who started the cluster.

    Only names that are actually set are returned: an unset variable must stay
    unset in the worker rather than arriving as an empty string, which
    `resolve_level` and the log-dir lookup would both have to special-case.
    """
    return {
        name: os.environ[name]
        for name in (level_env_var(), log_dir_env_var())
        if os.environ.get(name)
    }


def merge_runtime_env(runtime_env: Optional[dict] = None) -> dict:
    """`runtime_env` with this process's logging vars merged into `env_vars`.

    Call it at the `ray.init` site rather than storing the result: the vars are
    exported by `configure()`, so a copy taken before that call would be empty.
    Anything already in `env_vars` wins - a caller that set a variable
    explicitly means it.
    """
    merged = dict(runtime_env or {})
    env_vars = dict(worker_env_vars())
    env_vars.update(merged.get("env_vars") or {})
    if env_vars:
        merged["env_vars"] = env_vars
    return merged


def install_excepthooks() -> None:
    """Send an unhandled exception to the log before the process dies.

    Without this the most valuable line in a failed run is the one line that
    never reaches the run log. Python's default hook writes the traceback
    straight to `sys.stderr`, outside logging entirely, so `run.log` ends
    mid-narrative and the reason is only in scrollback - which is the exact
    failure the run log was added to fix (doc/11 1.9). It matters most for the
    `strict_nav_check` AssertionError, whose whole purpose is to stop a run
    loudly enough to be diagnosed afterwards.

    Both hooks are installed. `sys.excepthook` covers the main thread;
    `threading.excepthook` covers every other one, which the default handles
    separately and which no amount of try/except around `train()` would reach.

    The previous hooks are called afterwards rather than replaced, so whatever
    Ray or a debugger installed still runs and the traceback still reaches
    stderr. Idempotent: re-running `configure()` must not chain a second copy.

    KeyboardInterrupt is logged as a one-line INFO without a traceback. These
    runs are normally ended by being killed, and a full stack for an
    intentional Ctrl-C is noise at the end of every session.
    """
    global _excepthooks_installed
    if _excepthooks_installed:
        return

    logger = logging.getLogger(ROOT_NAME)
    previous_sys_hook = sys.excepthook
    previous_thread_hook = threading.excepthook

    def _hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            logger.info("interrupted")
        else:
            logger.error(
                "unhandled %s, the process is exiting", exc_type.__name__,
                exc_info=(exc_type, exc_value, exc_tb),
            )
        previous_sys_hook(exc_type, exc_value, exc_tb)

    def _thread_hook(args):
        if args.exc_type is not None and not issubclass(
            args.exc_type, SystemExit
        ):
            logger.error(
                "unhandled %s in thread %s", args.exc_type.__name__,
                getattr(args.thread, "name", "?"),
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )
        previous_thread_hook(args)

    sys.excepthook = _hook
    threading.excepthook = _thread_hook
    _excepthooks_installed = True


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
    # Racy on its own - two threads can both read False and both configure -
    # so the decision is re-made inside `configure` under the lock. This check
    # stays as the fast path, since it runs on every call and the answer is
    # True for all but the first.
    if not _configured:
        configure()
    if name != ROOT_NAME and not name.startswith(f"{ROOT_NAME}."):
        name = f"{ROOT_NAME}.{name}"
    return logging.getLogger(name)
