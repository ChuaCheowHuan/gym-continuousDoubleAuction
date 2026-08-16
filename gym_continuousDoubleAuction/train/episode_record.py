"""The per-step episode record: one Parquet row per (episode, step, agent).

This replaces the per-episode `pickle.dump` the league callback used to do
inline. Four things were wrong with that, and each maps onto a property of this
module (doc/21 §2.2-2.4, §5, §6):

* **`pickle` executes arbitrary code on load**, has no schema, and is queryable
  only by loading a whole episode into Python. Parquet is columnar, typed, safe
  to hand to someone else, and readable by `ray.data.read_parquet`, pandas or
  DuckDB without this package installed.
* **The write was synchronous, on the sampling hot path.** ~34 MB per 4096-step
  episode, written inside `on_episode_end`, against a `sample_timeout_s` budget
  `train_config.json` already warns is tight. Here a bounded queue hands the
  rows to a single background thread, so the env runner's step loop pays a
  buffer append and nothing else.
* **It was unguarded.** A full disk raised into `on_episode_end`, and on a
  remote env runner that means a killed and restarted worker. Every failure
  here is a warning: this is instrumentation, and a run that cannot write its
  diagnostics should still train - the rule `_append_progress` and
  `_build_file_handler` already follow.
* **It was unbounded.** `sample_every` records one episode in N and `max_bytes`
  caps what this process keeps, so "on" is no longer a synonym for "until the
  disk fills".

**Why pyarrow rather than `ray.data`.** doc/21 §6 item 5 said "Parquet via Ray
Data"; this writes Parquet with `pyarrow.parquet` directly, and the reason is
the objection §5 raised against RLlib's own offline recording:
`OfflineSingleAgentEnvRunner` clamps Ray Data's execution resources to
`num_cpus_per_env_runner` and then competes with sampling for them, on a profile
with two cores in total. Starting a Ray Data execution inside an env runner to
write a file that one thread can write is the same mistake. The *output* is
identical - `ray.data.read_parquet` reads these files natively - so nothing
downstream is given up. pyarrow is not a new dependency: `ray[rllib]` already
requires it.

**Schema stability.** The columns are declared, not inferred. Inference would
let two files from the same run disagree about a column's type whenever an
episode happened to contain only nulls in it, which is exactly the kind of
breakage a columnar format is chosen to avoid. Any `info` key not named in
`INFO_COLUMNS` is preserved as JSON in `info_extra` rather than dropped, so a
field added to `Info_Helper` is never silently lost; `test_episode_record.py`
asserts that the declared columns still cover what the env actually emits.
"""
from __future__ import annotations

import atexit
import json
import os
import queue
import threading
import time
import zlib
from typing import Any, Dict, List, Optional

import numpy as np

from gym_continuousDoubleAuction.logging_setup import (
    current_iteration,
    get_logger,
    worker_file_tag,
)

logger = get_logger(__name__)

#: `info` fields that get a column of their own, as (column name, pyarrow type
#: name). The names match `Info_Helper.set_info` one for one except `NAV`, which
#: is split: `nav` for arithmetic and `nav_str` for the exact `Decimal` string
#: the conservation check parses. Keeping only the float would discard the
#: exactness `info["NAV"]` pays a string for (doc/11 §2.6); keeping only the
#: string would make the column unusable in a query without a cast.
INFO_COLUMNS = (
    ("reward", "float64"),
    ("num_trades", "int64"),
    ("net_position", "int64"),
    ("VWAP", "float64"),
    ("cash", "float64"),
    ("cash_on_hold", "float64"),
    ("position_val", "float64"),
    ("drawdown", "float64"),
    ("max_nav", "float64"),
    ("num_trades_step", "int64"),
    ("num_passive_fills_step", "int64"),
    ("order_step_placed", "int64"),
    ("num_rejected_step", "int64"),
    ("is_pass_action", "bool"),
    ("last_price", "float64"),
    ("best_bid", "float64"),
    ("best_ask", "float64"),
    ("spread", "float64"),
)

#: The five signed reward contributions, each its own column, prefixed so a
#: `SELECT reward_term_*` gets the whole decomposition. They sum to `reward` by
#: construction (doc/11 §1.7), which is what makes the variance split in
#: doc/07 §6.4 computable from this file alone.
REWARD_TERMS = (
    "nav_term",
    "order_penalty",
    "trade_penalty",
    "drawdown_penalty",
    "passive_bonus",
)

#: How long `close` will wait for room in the writer's queue before giving the
#: tail up. Bounded, because a process on its way out must not hang on a slow
#: filesystem; non-zero, because the alternative is dropping exactly the
#: episodes a killed run most wants to keep.
_CLOSE_ENQUEUE_WAIT_S = 10.0

#: `info` keys handled outside `INFO_COLUMNS`, so they do not also land in
#: `info_extra`.
_HANDLED_KEYS = frozenset(
    [name for name, _ in INFO_COLUMNS] + ["NAV", "reward_terms", "model_action"]
)


def _schema():
    """The Arrow schema, built here so pyarrow is imported only when used."""
    import pyarrow as pa

    types = {
        "float64": pa.float64(),
        "int64": pa.int64(),
        "bool": pa.bool_(),
    }
    fields = [
        # Identity. `iteration` is nullable because a runner that has not yet
        # been reached by `_broadcast_iteration` genuinely does not know it, and
        # 0 is a real iteration number.
        pa.field("run_id", pa.string()),
        pa.field("iteration", pa.int32()),
        pa.field("episode_id", pa.string()),
        pa.field("step", pa.int32()),
        pa.field("agent_id", pa.string()),
        # Which module actually played this slot. The league assigns opponents
        # per episode, so without this a row cannot be attributed to a policy -
        # which is most of what one would ask this file.
        pa.field("module_id", pa.string()),
        pa.field("wall_time", pa.float64()),
        # False where sampling stopped before the episode did. Every
        # per-episode aggregate over this file wants it in the WHERE clause.
        pa.field("episode_complete", pa.bool_()),
        # The two representations of NAV; see INFO_COLUMNS.
        pa.field("nav", pa.float64()),
        pa.field("nav_str", pa.string()),
    ]
    fields += [pa.field(name, types[kind]) for name, kind in INFO_COLUMNS]
    fields += [pa.field(f"reward_term_{term}", pa.float64()) for term in REWARD_TERMS]
    fields += [
        pa.field("action", pa.list_(pa.float64())),
        pa.field("obs", pa.list_(pa.float32())),
        pa.field("info_extra", pa.string()),
    ]
    return pa.schema(fields)


def _floats(value) -> List[float]:
    """Flatten anything an action can be into a list of floats.

    Actions arrive as a tuple mixing `np.int32` with single-element `float32`
    arrays, and the shape differs by action category. A flat list is the one
    representation that survives all of them and is still a usable Arrow column.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        out: List[float] = []
        for item in value:
            out.extend(_floats(item))
        return out
    if isinstance(value, np.ndarray):
        return [float(v) for v in value.reshape(-1)]
    if isinstance(value, (np.generic, int, float, bool)):
        return [float(value)]
    return []


def _optional_float(value) -> Optional[float]:
    """float(value), or None. `spread` is None on a one-sided book by design."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None if value is None else int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class EpisodeRecorder:
    """Buffers per-step rows and writes them to Parquet off the sampling thread.

    One instance per *process*: the driver has one when it samples in-process,
    and each env runner builds its own on first use. Instances are deliberately
    not picklable - a thread and a queue are not state to ship to a worker - so
    `SelfPlayCallback` drops it from `__getstate__` and rebuilds it lazily on
    the far side.

    Args:
        output_dir: Where the files go. Absolute by the time it reaches here;
            the callback is pickled into every env runner, and a relative path
            would be resolved against whatever cwd that worker happened to have
            (doc/21 §2.3).
        run_id: Written into every row, so files from two runs sharing a
            directory can still be told apart.
        sample_every: Record one episode in N, chosen by a hash of the episode
            id so every worker makes the same decision without coordinating.
            1 records everything.
        max_bytes: Cap on what *this process* keeps. After each write the
            oldest of its own files are deleted until the total is under the
            cap. 0 disables the cap. Per process rather than per directory
            because deleting another worker's files is a cross-process race for
            no benefit - each writer owns the files carrying its own tag.
        rows_per_file: Rows to accumulate before a file is written. A floor
            rather than a size: rows are handed over a whole episode at a time,
            so a file holds every episode that finished since the last write and
            no episode is ever split across two files. That is worth the looser
            bound - an episode split down the middle makes every per-episode
            aggregate a two-file join.
        max_live_episodes: How many unfinished episodes to buffer. An episode
            that is discarded without ending - which happens on any force-reset
            (doc/21 §3.2) - never reaches `finish_episode`, so without this the
            buffer keeps up to `max_step` rows per lost episode for the life of
            the process.
        queue_size: Depth of the hand-off to the writer thread. When it is full
            the batch is dropped with a warning rather than blocking sampling.
    """

    def __init__(
        self,
        output_dir: str,
        *,
        run_id: str = "",
        sample_every: int = 1,
        max_bytes: int = 0,
        rows_per_file: int = 65536,
        max_live_episodes: int = 8,
        queue_size: int = 4,
    ):
        self.output_dir = output_dir
        self.run_id = run_id or ""
        self.sample_every = max(1, int(sample_every))
        self.max_bytes = max(0, int(max_bytes))
        self.rows_per_file = max(1, int(rows_per_file))
        self.max_live_episodes = max(1, int(max_live_episodes))

        # Insertion-ordered, which is what makes "evict the oldest" meaningful.
        self._live: "Dict[str, List[dict]]" = {}
        self._pending: List[dict] = []
        self._tag = worker_file_tag()
        self._seq = 0
        self._dropped_batches = 0
        self._written_rows = 0

        self._queue: "queue.Queue[List[dict]]" = queue.Queue(
            maxsize=max(1, int(queue_size))
        )
        # An Event rather than a sentinel value on the queue. A sentinel has to
        # be *put*, and the one moment `close` is called under load is the one
        # moment the queue is full - so the put fails, the writer never learns
        # to stop, and the join sits out its whole timeout on the way to exit.
        self._stopping = threading.Event()
        self._thread = threading.Thread(
            target=self._writer_loop,
            name="episode-recorder",
            daemon=True,
        )
        self._closed = False
        self._thread.start()
        atexit.register(self.close)

    # --- the sampling thread's side -----------------------------------------

    def wants(self, episode_id) -> bool:
        """Is this episode one of the sampled ones?

        `zlib.crc32`, not `hash()`: `hash()` on a str is salted by
        `PYTHONHASHSEED`, so every worker and every restart would sample a
        different subset and the record would be biased by process lifetime
        rather than uniform - the same reason the policy mapping fn uses crc32.
        """
        if self.sample_every == 1:
            return True
        return zlib.crc32(str(episode_id).encode("utf-8")) % self.sample_every == 0

    def record_step(self, episode, step_index: int) -> None:
        """Turn one env step into one row per agent and buffer them."""
        episode_id = str(episode.id_)
        if not self.wants(episode_id):
            return

        infos = episode.get_infos(-1) or {}
        if not isinstance(infos, dict):
            return
        observations = episode.get_observations(-1) or {}
        actions = episode.get_actions(-1) or {}
        rewards = episode.get_rewards(-1) or {}

        rows = self._live.get(episode_id)
        if rows is None:
            self._evict_stale()
            rows = self._live[episode_id] = []

        iteration = current_iteration()
        now = time.time()
        for agent_id, info in infos.items():
            if not isinstance(info, dict):
                continue
            rows.append(
                self._row(
                    episode=episode,
                    episode_id=episode_id,
                    step_index=step_index,
                    agent_id=str(agent_id),
                    info=info,
                    obs=observations.get(agent_id),
                    action=actions.get(agent_id),
                    reward=rewards.get(agent_id),
                    iteration=iteration,
                    now=now,
                )
            )

    def finish_episode(self, episode_id) -> None:
        """Hand a finished episode's rows to the writer."""
        rows = self._live.pop(str(episode_id), None)
        if not rows:
            return
        self._release(rows, complete=True)
        if len(self._pending) >= self.rows_per_file:
            self._enqueue(self._pending)
            self._pending = []

    def _release(self, rows: List[dict], *, complete: bool) -> None:
        """Move rows into the write buffer, saying whether the episode ended.

        The flag is what stops a truncated episode from looking like a whole
        one. `close` writes whatever was still in flight - a killed run's tail
        is often the part worth having - but those rows stop at whatever step
        sampling stopped at, and nothing in them says so. Any per-episode
        aggregate over the file (an episode's NAV trajectory, its return, a
        Sharpe over it) silently includes the fragment as though it were an
        episode.

        Found by cross-checking two channels against each other: a two-runner
        run recorded 8 distinct `episode_id`s while the run logs held 6 NAV
        tables, because `on_episode_end` fires only for episodes that actually
        end. The rows are real either way and are kept; they are labelled.
        """
        for row in rows:
            row["episode_complete"] = complete
        self._pending.extend(rows)

    def drop_episode(self, episode_id) -> None:
        """Forget an episode without writing it."""
        self._live.pop(str(episode_id), None)

    def flush(self, *, wait: float = 0.0) -> None:
        """Write whatever is buffered, without waiting for `rows_per_file`.

        `wait` is how long to block if the writer is behind. Zero everywhere
        except at `close`, where nothing is left to starve: dropping the tail
        there would lose exactly the episodes a killed run most wants, and the
        reason `_enqueue` never blocks - keeping the filesystem out of the
        sampling loop - has stopped applying by then.

        Episodes still in flight are written with `episode_complete=False`, not
        dropped and not silently mixed in with the finished ones - see
        `_release`.
        """
        for rows in list(self._live.values()):
            self._release(rows, complete=False)
        self._live.clear()
        if self._pending:
            self._enqueue(self._pending, wait=wait)
            self._pending = []

    def close(self) -> None:
        """Flush, stop the writer thread, and wait for it - briefly.

        Registered with `atexit`, so a killed run keeps the episodes it had
        finished. The join is bounded: a process on its way out must not hang
        on a slow filesystem, and the alternative to a partial record here is no
        record at all.
        """
        if self._closed:
            return
        self._closed = True
        try:
            self.flush(wait=_CLOSE_ENQUEUE_WAIT_S)
        except Exception:
            logger.warning("episode record: the final flush failed", exc_info=True)
        # After the flush, so everything already buffered is in the queue before
        # the writer is told there will be no more.
        self._stopping.set()
        self._thread.join(timeout=30.0)
        if self._dropped_batches:
            logger.warning(
                "episode record: %s batches were dropped because the writer "
                "could not keep up; %s rows were written",
                self._dropped_batches, self._written_rows,
            )

    # --- internals ----------------------------------------------------------

    def _evict_stale(self) -> None:
        """Drop the oldest live episode once too many are open at once.

        `on_episode_end` is not called for episodes a force-reset throws away
        (doc/21 §3.2), so without a cap those rows are held until the process
        dies. Evicting rather than writing them: a partial episode with no end
        is not a record anyone would trust, and writing it would make the file's
        episode boundaries a lie.
        """
        while len(self._live) >= self.max_live_episodes:
            episode_id, rows = next(iter(self._live.items()))
            del self._live[episode_id]
            logger.debug(
                "episode record: dropped %s buffered rows for episode %s, which "
                "never ended (%s episodes open, limit %s)",
                len(rows), episode_id, len(self._live) + 1, self.max_live_episodes,
            )

    def _row(
        self, *, episode, episode_id, step_index, agent_id, info, obs, action,
        reward, iteration, now,
    ) -> dict:
        terms = info.get("reward_terms") or {}
        nav_str = info.get("NAV")
        row = {
            "run_id": self.run_id,
            "iteration": iteration,
            "episode_id": episode_id,
            "step": int(step_index),
            "agent_id": agent_id,
            "module_id": _module_for(episode, agent_id),
            "wall_time": now,
            # Overwritten by `_release` when the episode leaves the buffer.
            # Pessimistic until then: a row that somehow reaches a file without
            # passing through there describes an episode nothing said ended.
            "episode_complete": False,
            "nav": _optional_float(nav_str),
            "nav_str": None if nav_str is None else str(nav_str),
            "action": _floats(action if action is not None
                              else info.get("model_action")),
            "obs": [] if obs is None else [float(v) for v in np.ravel(obs)],
        }
        for name, kind in INFO_COLUMNS:
            value = info.get(name)
            if kind == "float64":
                row[name] = _optional_float(value)
            elif kind == "int64":
                row[name] = _optional_int(value)
            else:
                row[name] = None if value is None else bool(value)
        # `reward` is the agent's own reward for the step. `info["reward"]` is
        # the account's copy of the same number; the episode's is authoritative,
        # so it wins where both exist.
        if reward is not None:
            row["reward"] = _optional_float(reward)
        for term in REWARD_TERMS:
            row[f"reward_term_{term}"] = _optional_float(terms.get(term))

        extra = {k: v for k, v in info.items() if k not in _HANDLED_KEYS}
        row["info_extra"] = _json_or_none(extra)
        return row

    def _enqueue(self, rows: List[dict], *, wait: float = 0.0) -> None:
        """Hand a batch to the writer, or drop it.

        Non-blocking by default: blocking here would put a slow filesystem
        directly into the env runner's step loop, which is the failure this
        module exists to remove. A dropped batch is counted and reported once at
        close rather than warned about per occurrence, because the condition
        that causes one causes many.

        `wait` is non-zero only on the close path - see `flush`.
        """
        try:
            if wait > 0:
                self._queue.put(rows, timeout=wait)
            else:
                self._queue.put_nowait(rows)
        except queue.Full:
            self._dropped_batches += 1
            if self._dropped_batches == 1:
                logger.warning(
                    "episode record: the writer is behind, dropping %s rows. "
                    "Lower episode_rows_per_file, raise episode_sample_every, "
                    "or point episode_data_dir at a faster filesystem.",
                    len(rows),
                )

    def _writer_loop(self) -> None:
        """Drain the queue until `close` says there will be no more.

        The poll is what lets `_stopping` be an Event: the thread wakes often
        enough to notice it, and "stopping *and* the queue is empty" is the only
        exit condition - so a batch handed over just before `close` is still
        written rather than abandoned.
        """
        while True:
            try:
                batch = self._queue.get(timeout=0.1)
            except queue.Empty:
                if self._stopping.is_set():
                    return
                continue
            try:
                self._write(batch)
            except Exception:
                # Instrumentation must not take down the process it instruments,
                # and this thread dying would silently stop the record for the
                # rest of the run.
                logger.warning(
                    "episode record: a batch could not be written", exc_info=True,
                )
            finally:
                self._queue.task_done()

    def _write(self, rows: List[dict]) -> None:
        import pyarrow as pa
        import pyarrow.parquet as pq

        if not rows:
            return

        os.makedirs(self.output_dir, exist_ok=True)
        self._seq += 1
        path = os.path.join(
            self.output_dir, f"episodes.{self._tag}.{self._seq:06d}.parquet"
        )
        schema = _schema()
        table = pa.Table.from_pylist(rows, schema=schema)
        pq.write_table(table, path, compression="snappy")
        self._written_rows += len(rows)
        logger.debug(
            "episode record: wrote %s rows to %s", len(rows), path,
        )
        self._enforce_cap()

    def _enforce_cap(self) -> None:
        """Delete this process's oldest files until it is under `max_bytes`.

        Only files carrying this process's own tag, so two workers writing into
        one directory never delete each other's output - which would be a race
        with no owner. The cap is therefore per writer: a run with N runners
        keeps up to N x max_bytes.
        """
        if not self.max_bytes:
            return
        prefix = f"episodes.{self._tag}."
        try:
            names = sorted(
                name for name in os.listdir(self.output_dir)
                if name.startswith(prefix)
            )
            sizes = []
            for name in names:
                path = os.path.join(self.output_dir, name)
                try:
                    sizes.append((path, os.path.getsize(path)))
                except OSError:
                    continue
            total = sum(size for _, size in sizes)
            for path, size in sizes:
                if total <= self.max_bytes:
                    break
                os.remove(path)
                total -= size
                logger.debug(
                    "episode record: removed %s to stay under %s bytes",
                    path, self.max_bytes,
                )
        except OSError:
            logger.warning(
                "episode record: could not enforce the %s byte cap in %s",
                self.max_bytes, self.output_dir, exc_info=True,
            )


def _module_for(episode, agent_id) -> Optional[str]:
    """The module that played this agent, if the episode can say.

    Best-effort by design: this is the one field that comes from RLlib's episode
    API rather than from this repository's own `info`, so an API rename must
    leave a null column behind rather than stop a training run.
    """
    getter = getattr(episode, "module_for", None)
    if not callable(getter):
        return None
    try:
        module_id = getter(agent_id)
    except Exception:
        return None
    return None if module_id is None else str(module_id)


def _json_or_none(payload: dict) -> Optional[str]:
    if not payload:
        return None
    try:
        return json.dumps(payload, default=str, sort_keys=True)
    except (TypeError, ValueError):
        return None
