"""Per-iteration progress: the progress log, the NAV conservation check and metrics (issue #254)."""

from __future__ import annotations
import json
import math
import os
from typing import Optional
from gym_continuousDoubleAuction.logging_setup import (
    get_logger,
    log_dir_env_var,
    log_file_path,
    set_iteration,
)
from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import (
    NAV_VIOLATIONS_METRIC,
)
from gym_continuousDoubleAuction.train.returns import usable_return
from gym_continuousDoubleAuction.train.policy.policy_handler import trainable_policy_ids
from gym_continuousDoubleAuction.train.config import (
    TrainConfig,
    _BROADCAST_TIMEOUT_S,
    VF_EXPLAINED_VAR_KEY,
)

logger = get_logger("gym_continuousDoubleAuction.train.train")


class NavConservationError(AssertionError):
    """A run stopped because the NAV conservation invariant broke.

    Subclasses AssertionError rather than replacing it: that is what this
    failure has always been raised as, what doc/11 §1.5 documents, and what any
    existing `except` around a training call is written for.
    """


def nav_violations(result: dict) -> float:
    """How many episodes failed the conservation check this iteration.

    Read from the env-runner metrics block, which is where a metric logged in
    `on_episode_end` lands regardless of which process ran the hook. That is the
    whole point: with `num_env_runners > 0` the check runs on the runners, and
    the metric is the only part of it that reliably crosses back to the driver
    (see `NAV_VIOLATIONS_METRIC`).

    A missing key is 0.0 rather than an error. The metric appears once an
    episode has ended, so an iteration that produced no complete episode - or a
    result from an RLlib version that nests this differently - must read as "no
    violations seen", not as a failure of its own.
    """
    from ray.rllib.utils.metrics import ENV_RUNNER_RESULTS

    env_runners = result.get(ENV_RUNNER_RESULTS) or {}
    try:
        return float(env_runners.get(NAV_VIOLATIONS_METRIC, 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _check_nav_conservation(iteration: int, result: dict, cfg: TrainConfig) -> None:
    """Stop the run if the ledger broke, wherever the episode that broke it ran.

    This is the driver half of the check `on_episode_end` reports. The callback
    logs the ERROR and the per-episode numbers; this decides whether the run
    continues, because the driver is the only process whose exceptions end one.

    At `num_env_runners=0` this is strictly later than the old in-hook raise -
    the iteration finishes first. That is the price of an answer that is the
    same at every runner count, and it is a small one: the invariant has already
    broken, and everything downstream of it was already meaningless.

    Non-strict is not silent here either. The per-episode ERROR is written in
    the *worker's* log file, so before this the driver's own `run.log` said
    nothing at all about a violated run.
    """
    violations = nav_violations(result)
    if violations <= 0:
        return

    message = (
        f"NAV conservation was violated in {violations:.0f} episode(s) during "
        f"iteration {iteration}. The ledger has created or destroyed cash, so "
        f"every reward computed from NAV after this point is meaningless. The "
        f"per-episode detail is in the log of the process that ran the episode "
        f"(with num_env_runners > 0 that is an env runner's "
        f"run.<pid>.<worker>.log, not this file)."
    )
    if not cfg.strict_nav_check:
        logger.warning("%s Continuing: strict_nav_check is off.", message)
        return
    logger.error(message)
    raise NavConservationError(message)


def _apply_iteration(iteration: Optional[int]):
    """A callable that tags an env runner's process with `iteration`.

    Module level rather than a lambda in the loop so it is picklable by name
    and readable in a traceback; the closure carries only an int.
    """

    def _apply(_target):
        set_iteration(iteration)
        # The path of the run log this process writes, "" when it writes none: the same
        # round trip tells the driver where each process's narrative went (issue #218).
        return log_file_path() or ""

    return _apply


#: Run logs the driver has already told the console about, and whether it has warned that a
#: process could not open one. Per driver process, so a run says each once.
_seen_runner_logs: set = set()
_warned_missing_runner_log = False


def _report_runner_logs(paths, who: str) -> None:
    """Say where the env runners' (or learners') run logs are, and warn about any with none.

    A worker echoes only warnings and errors to the console (`worker_console_level`), so the
    per-episode narrative is in its file, and this is the one place the console learns the
    path (issue #221). A worker that was told to write a log and could not - the directory
    must exist and be writable on its node - used to warn on its own stdout, which never
    reaches `run.log`; here it is a warning in the driver's log (issue #218).
    """
    global _warned_missing_runner_log
    for path in paths:
        if isinstance(path, str) and path and path not in _seen_runner_logs:
            _seen_runner_logs.add(path)
            logger.info("%s log: %s", who, path)
    expecting = bool(os.environ.get(log_dir_env_var()))
    missing = [p for p in paths if isinstance(p, str) and not p]
    if expecting and missing and not _warned_missing_runner_log:
        _warned_missing_runner_log = True
        logger.warning(
            "%s of %s %s processes have no run log: the directory %s may not exist or be writable on "
            "their node, so their NAV tables reach no file",
            len(missing),
            len(paths),
            who,
            os.environ.get(log_dir_env_var()),
        )


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
    _broadcast_to_learners(algo, iteration)
    group = getattr(algo, "env_runner_group", None)
    if group is None:
        return
    try:
        acked = group.foreach_env_runner(
            _apply_iteration(iteration),
            local_env_runner=False,
            timeout_seconds=_BROADCAST_TIMEOUT_S,
        )
    except Exception:
        logger.debug(
            "could not broadcast iteration %s to the env runners; their log lines will read iter=-",
            iteration,
            exc_info=True,
        )
        return

    _report_runner_logs(list(acked), "env runner")

    # A runner that did not answer within the timeout is skipped silently by
    # `foreach_env_runner` (healthy_only defaults to True), and it keeps
    # whatever iteration it was last told - so its lines and its recorded rows
    # are labelled with the *previous* iteration rather than with `-`. A stale
    # but plausible number is worse than a missing one, because nothing about it
    # looks wrong. This does not fix that, which would mean blocking sampling on
    # a log field; it makes it visible, so a reader who finds two iterations'
    # NAV tables sharing a number has a line saying which one to distrust.
    try:
        expected = group.num_healthy_remote_env_runners()
    except Exception:
        return
    if len(acked) < expected:
        logger.warning(
            "iteration %s reached only %s of %s env runners within %ss; the "
            "rest will label this iteration's lines and recorded rows with "
            "whatever iteration they were last told",
            iteration,
            len(acked),
            expected,
            _BROADCAST_TIMEOUT_S,
        )


def _broadcast_to_learners(algo, iteration: int) -> None:
    """Tell the remote learner actors which iteration they are updating for (issue #217).

    `foreach_env_runner` never reaches them, so at `num_learners > 0` every line a learner
    logged read `iter=-` for the whole run. With no remote learners (`num_learners=0`, the
    GPU profile) the learner is in this process and already tagged. Best-effort, like the
    env-runner broadcast: a failure costs the tag, never the run.
    """
    group = getattr(algo, "learner_group", None)
    if group is None or getattr(group, "is_local", True):
        return
    try:
        results = group.foreach_learner(
            _apply_iteration(iteration), timeout_seconds=_BROADCAST_TIMEOUT_S
        )
    except Exception:
        logger.debug(
            "could not broadcast iteration %s to the learners; their log lines will read iter=-",
            iteration,
            exc_info=True,
        )
        return
    try:
        returned = [r.get() if hasattr(r, "get") else r for r in results]
    except Exception:
        returned = list(results)
    _report_runner_logs(returned, "learner")
    try:
        expected = len(group)
    except Exception:
        return
    if len(returned) < expected:
        logger.warning(
            "iteration %s reached only %s of %s learners within %ss; the rest keep the "
            "iteration they were last told",
            iteration,
            len(returned),
            expected,
            _BROADCAST_TIMEOUT_S,
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
            "record for this iteration",
            cfg.progress_path,
            exc_info=True,
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
    vf = ", ".join(f"{pid}={value:.3g}" for pid, value in vf_explained_var(result, cfg).items())
    logger.info(
        "iter %s/%s | env steps sampled: %s | module returns: %s | vf_explained_var: %s",
        i,
        total,
        steps,
        {
            k: (None if usable_return(v) is None else round(usable_return(v), 1))
            for k, v in returns.items()
        },
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
            i,
            ENV_RUNNER_RESULTS,
            cfg.num_env_runners,
            cfg.train_batch_size,
            cfg.sample_timeout_s,
            cfg.max_step,
            cfg.num_episodes_per_iter,
        )
