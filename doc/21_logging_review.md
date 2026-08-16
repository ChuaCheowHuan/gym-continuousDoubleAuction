# 21. Logging Review: Multiple Env Runners, Multiple Learners, and Ray's Built-ins

A review of the logging implementation as it stands on `master`, focused on the three questions
[11_logging_and_observability.md](11_logging_and_observability.md) does not answer: what breaks when
the run is distributed, what the concurrency story actually is once Ray's fault tolerance is in the
picture, and whether Ray/RLlib already provide the per-step recording this repository hand-rolls.

Doc 11 is the inventory and the design rationale; this is the audit. Where the two disagree, the
disagreement is called out explicitly below and doc 11 has been corrected.

Related: [09_distributed_training.md](09_distributed_training.md),
[15_findings_and_recommendations.md](15_findings_and_recommendations.md),
[16_verification_log.md](16_verification_log.md).

Everything marked **[verified]** was checked against Ray 2.56.1 as pinned in `requirements.txt`,
either by reading the installed source at the line cited or by running the code.

---

## 1. What is logged, and by what mechanism

Five separate channels, with different writers, different destinations, and different failure
modes. Conflating them is the main reason the multi-runner behaviour is hard to reason about.

| # | Channel | Mechanism | Payload | Written by | Destination |
|---|---|---|---|---|---|
| 1 | Run narrative | stdlib `logging` via `logging_setup.get_logger` | NAV tables, league stats, champion events, iteration summaries, tracebacks | driver **and** every env runner | stdout + `run.log` / `run.<pid>.<worker>.log` under `run_dir` |
| 2 | Per-iteration history | `json.dump` append | the entire `algo.train()` result dict | driver only | `<run_dir>/progress.jsonl` |
| 3 | Custom metrics | RLlib `MetricsLogger.log_value` | 6 values (§1.2 of doc 11) | env runners (3) + driver (3) | RLlib result dict → channel 2 |
| 4 | Per-step episode record | `pickle.dump` | `obs`/`act`/`reward`/`info` for every step | env runners | `<episode_data_dir>/<episode_id>.pkl` |
| 5 | Per-step `info` | returned from `env.step` | 21 fields per agent per step | the env | consumed by 3 and 4; otherwise dropped |

Channel 4 is the only per-step *persistence*, and it is entirely bespoke — no Ray or RLlib
machinery is involved in it. That is the crux of §4 and §5.

The plumbing that makes channel 1 work across processes is worth naming, because §2's problems are
all failures of the same plumbing applied to the other channels:

* the level and the log directory travel to workers as `$CDA_LOG_LEVEL` / `$CDA_LOG_DIR`, exported
  by `configure()` **and** passed through `ray.init(runtime_env=...)` by `merge_runtime_env()`, so
  they arrive whether or not this process started the cluster;
* the log directory is made **absolute** before export (`logging_setup.py:269`);
* each process writes its own file, tagged with pid *and* Ray worker id, because
  `RotatingFileHandler` has no cross-process interlock;
* the training iteration is pushed to the runners each iteration by `train._broadcast_iteration`,
  so a worker's lines can be joined to a `progress.jsonl` row.

None of channels 2–5 has any of that.

---

## 2. Problems under multiple env runners

### 2.1 `strict_nav_check` does not stop a distributed run — it restarts a worker

This is the most serious finding, because the feature's stated purpose is to stop a corrupt run
loudly, and at the repository's own GPU profile (`num_env_runners=2`) it does not.

`on_episode_end` runs on the env runner. Its `raise AssertionError(message)` therefore surfaces as a
`RayTaskError` from the remote `sample()` call, and:

* `EnvRunnerGroup._ignore_ray_errors_on_env_runners = config.ignore_env_runner_failures or
  config.restart_failed_env_runners` **[verified]** `env/env_runner_group.py:181-183`;
* `restart_failed_env_runners` defaults to **True** **[verified]** `algorithms/algorithm_config.py:600`;
* `foreach_env_runner` passes that flag into
  `FaultTolerantActorManager.handle_remote_call_result_errors`, whose `ignore_ray_errors` branch is
  `logger.exception(result_or_error.get())` — log and continue **[verified]**
  `utils/actor_manager.py:779-788`.

So on a distributed run the assertion kills one env-runner actor, RLlib restarts it (tolerating 100
consecutive failures by default), and `algo.train()` returns normally. The run continues training on
a ledger the check just declared corrupt.

Two aggravating details:

* The traceback is logged through **Ray's** logger, not this package's, so it does not reach
  `run.log`. With `log_level: "WARN"` it reaches Ray's stderr and nothing else. The one line the
  whole §1.13 excepthook machinery exists to preserve is the one line that escapes it.
* A restarted env runner is a fresh process: it has lost `set_iteration`, so its lines read `iter=-`
  until the next `_broadcast_iteration`, and it opens a *new* `run.<pid>.<worker>.log` (see §2.5).

At `num_env_runners=0` — the default and what CI runs — the callback executes in the driver and the
assertion does stop the run. That is why this has never been observed.

### 2.2 The per-step store accumulates even when episode data is disabled

`on_episode_step` appends to `self.store[episode.id_]` unconditionally
(`league_based_self_play_callback.py:304`); only the *write* is guarded by `episode_data_dir is not
None` (`:336`). So `--no-episode-data` / `episode_data_dir: null` removes the I/O and keeps the
memory.

**[verified]** by driving the callback with `episode_data_dir=None` for 1000 steps: 1000 step dicts
retained.

The cost is not small. A step dict for this repository's training shape (8 agents, `obs` of
`(168,) float32`, the full 21-field `info`) pickles to **8,314 bytes** **[verified]**, so one
4,096-step episode is **~34 MB** on disk and appreciably more live in Python objects, held per
concurrent episode per runner. `runtime_profiles.json` estimated ~10 MB; it is off by 3.4×, and has
been corrected.

### 2.3 `episode_data_dir` is the one output path that is not made absolute or exported

Compare the two paths a worker writes:

| Path | Made absolute | Reaches the worker via | Run-scoped |
|---|---|---|---|
| log dir | yes, `os.path.abspath` at `logging_setup.py:269` | `$CDA_LOG_DIR` **and** `runtime_env` | yes (`run_dir`) |
| `episode_data_dir` | no | pickled into the callback | **no** |

`episode_data_dir` defaults to the relative string `"episode_data"`, and `os.makedirs` +
`open` in the callback resolve it against **the worker process's cwd**. Today that is usually the
driver's cwd, because nothing sets `runtime_env["working_dir"]` — but it is an accident, not a
guarantee: any future use of `working_dir`, any Ray job submission, or any multi-node run scatters
the pickles into per-worker directories with no error and no log line. The log directory was given
`abspath` for exactly this reason; the episode directory was not.

It is also not run-scoped, so two concurrent runs write into one directory. Collision is unlikely
(episode IDs are UUID-ish) but "unlikely" is what §1.11 of doc 11 rejected for `run.log`.

### 2.4 Writing the pickle is synchronous, on the sampling hot path

`pickle.dump` of ~34 MB happens inside `on_episode_end`, in the env runner, between sampling steps.
On the Colab/GPU profile that is 4 episodes × 2 runners per iteration — ~136 MB of blocking,
uninstrumented I/O per iteration, against a `sample_timeout_s` budget the config file already warns
is tight. A slow or FUSE-backed filesystem (`episode_data_root` on Drive is explicitly called out as
something to avoid, and the profile does avoid it) turns into timed-out iterations that train on
nothing — the exact failure `_log_iteration`'s "trained on no samples" warning was added for, with a
cause nothing currently points at.

There is also no `try`/`except` around it. Every other instrumentation writer in this repository
(`_append_progress`, `_build_file_handler`) refuses to take down a run that is otherwise fine; this
one raises into `on_episode_end`, and by §2.1 that means a killed and restarted env runner.

### 2.5 Log files proliferate with worker restarts, and rotation is per file

The per-process naming that makes concurrent writes safe also means the *set* of files is unbounded:
every restarted env runner (§2.1 makes restarts a normal event, not an exceptional one) opens a new
`run.<pid>.<worker>.log`. `file_backup_count` bounds each file at 6 × 10 MB; it does not bound the
number of files. A long run that loses runners repeatedly accumulates 60 MB of quota per incarnation.

The related point doc 11 §3 already makes — rotation discards the *start* of a run, where divergence
begins — is worse here, because a worker's file is where the NAV tables live.

### 2.6 What the learner processes get

`_broadcast_iteration` targets `algo.env_runner_group` only. At `num_learners > 0` the learner
actors are separate processes that: receive `$CDA_LOG_LEVEL` / `$CDA_LOG_DIR` through the
`runtime_env` (so they do write a `run.<pid>.<worker>.log`), but never receive an iteration, so
every line they emit reads `iter=-` forever. This package logs little from the learner today, so the
impact is cosmetic — but the repository's own GPU profile sets `num_learners=0`, which means the
path is untested rather than fine.

### 2.7 The `runtime_env` covers workers, not the cluster's own logging

`merge_runtime_env()` correctly closes the `ray.init(address=...)` gap for env vars. Two residual
cases:

* `$CDA_LOG_DIR` is exported as an **absolute** path. On a multi-node cluster that path must exist,
  and be writable, on every node — otherwise `_build_file_handler` warns (correctly, non-fatally)
  and that node's NAV tables exist nowhere. The warning goes to the worker's stdout, which is
  forwarded to the driver console but not into `run.log`.
* Nothing captures Ray's *own* logger output into the package's run log, so RLlib's diagnostics —
  "No samples returned from remote workers", the swallowed traceback from §2.1, env-runner restart
  notices — are in a different stream from the narrative they explain.

---

## 3. Concurrency and parallelism

### 3.1 What is genuinely safe

Doc 11 §1.10 is accurate and this review found nothing to add to it:

* **writes within a process** — `logging.Handler.handle()` takes the handler `RLock` around
  `emit()`, and `doRollover` runs inside `emit`, so lines cannot tear and the file cannot rotate
  twice;
* **setup within a process** — the remove-close-add sequence in `configure()` is under
  `_configure_lock`;
* **across processes** — safety is by *not sharing files*: `run_dir` separates runs, pid + Ray worker
  id separates runners, episode id separates pickles. `run.log` and `progress.jsonl` are the driver's
  alone.

`_iteration` as a module global with atomic int assignment is the right model, for the reasons
stated. All of this has tests (`TestConcurrentConfiguration`, `TestSeparateProcesses`).

### 3.2 In-flight episodes leak from `store` and `_activity`

Both dicts are keyed by episode id and pruned only in `on_episode_end`. An episode that is discarded
without ending never gets pruned. That happens whenever the runner force-resets:
`MultiAgentEnvRunner._sample` calls `_reset_envs_and_episodes()` when `force_reset or num_episodes
is not None or self._needs_initial_reset` **[verified]** `env/multi_agent_env_runner.py:290`, and it
sets `_needs_initial_reset = True` after any episode-count sampling call and after env creation.
`on_episode_end` is not called for what it throws away.

At this repository's settings (timestep-based sampling, `max_step` truncation guaranteeing episode
ends) the leak is bounded and rare. It is worth fixing anyway because the leaked unit is not a
counter, it is up to 4,096 step dicts × `num_envs_per_env_runner` — ~34 MB per event, never freed
for the life of the worker.

### 3.3 The iteration tag is only as fresh as the last broadcast

`_broadcast_iteration` is best-effort with a 10 s timeout and `healthy_only=True`. A runner that is
restarting, unhealthy, or slow at that moment is skipped silently (correctly — it must not stop
training), and its lines carry the *previous* iteration, not `-`, because the global is still set
from last time. A stale-but-plausible number is harder to spot than a dash. Applying the broadcast is
safe with respect to sampling: PPO's `synchronous_parallel_sample` blocks, so the broadcast cannot
land mid-episode.

### 3.4 Duplicate narrative on the console

The package logger's `propagate` is deliberately left on, and Ray forwards worker stdout to the
driver console (`log_to_driver` defaults True). So a worker's NAV table appears once in that
worker's file and again on the driver's console prefixed `(MultiAgentEnvRunner pid=...)`. Harmless,
but it makes the console misleading as a record of *what the driver knows*, and it is why the
per-worker files matter more than the console suggests.

---

## 4. What Ray and RLlib already offer

| Facility | What it does | Fit here |
|---|---|---|
| `MetricsLogger` | Per-episode/iteration scalars, reduced across runners, merged into the result dict | **Already used** (6 metrics). Correct tool for aggregates. **Not** a per-step store — in 2.56 `reduce=None` silently becomes `"ema"` when no window is given **[verified]** `utils/metrics/metrics_logger.py:409-411`, so "keep every value" is not a supported mode |
| Tune loggers / TensorBoard | `progress.csv`, TB event files | Unavailable as used: `algo.train()` is called directly, and outside Tune `Trainable` points `_logdir` at a `tempfile.mkdtemp()` **[verified]** `ray/tune/trainable/trainable.py:663-671` with no result logger attached. `progress.jsonl` is the deliberate replacement |
| `ray.LoggingConfig` | Configures the **root** logger of the driver and every task/actor of the job; `encoding="JSON"`, plus `additional_log_standard_attrs` **[verified]** `ray.LoggingConfig` in 2.56 | Genuinely useful for §2.7 — one switch gives structured logs with job/worker/actor/task ids in every Ray process. Needs care: it configures the *root* logger, and this package's logger propagates to root, so naive adoption double-prints every line |
| Ray Data | Distributed Parquet/JSONL writing | The right substrate for channel 4, but it must be driven deliberately (see §5) |
| **RLlib offline recording** (`config.offline_data(output=...)`) | Records sampled experience to Parquet via `OfflineSingleAgentEnvRunner` | See §5 — **blocked** |

---

## 5. Is Ray's Offline Dataset Logging suitable for the per-step record?

**No, not in Ray 2.56.1, and not for a reason that can be worked around by configuration.** It is
still the right destination to aim at, and the gap is worth stating precisely so the decision can be
revisited on a version bump.

**The blocker.** Setting `output` selects the recording env-runner class in `EnvRunnerGroup`, and
that selection begins with an explicit multi-agent refusal **[verified]**
`env/env_runner_group.py:151-163`:

```python
if config.output:
    # No multi-agent support.
    if config.is_multi_agent:
        raise ValueError("Multi-agent recording is not supported, yet.")
```

This environment is multi-agent by construction (8 agents, league self-play). Enabling `output`
would not degrade — it would raise at `build()`.

**Three further mismatches, which matter even after that lands.**

1. **The columnar format drops `info` entirely.** `_map_episodes_to_data` writes exactly
   `EPS_ID, AGENT_ID, MODULE_ID, OBS, ACTIONS, REWARDS, NEXT_OBS, TERMINATEDS, TRUNCATEDS` plus
   extra *model* outputs **[verified]** `offline/offline_env_runner.py:307-341`. This repository's
   per-step record is *mostly* `info` — NAV, `reward_terms`, the account state, the market touch.
   Recording in episode format (`output_write_episodes=True`, the default) does preserve infos,
   since they are part of `SingleAgentEpisode`'s state, but that format is msgpack blobs meant to be
   read back by RLlib, not something `visualize_nav.py` or a notebook can query.
2. **Episode format constrains `batch_mode`.** `output and output_write_episodes and batch_mode !=
   "complete_episodes"` is a config error **[verified]** `algorithms/algorithm_config.py:5433-5440`.
   That is a real constraint on a 4,096-step environment.
3. **It runs Ray Data inside the env runner.** `OfflineSingleAgentEnvRunner.__init__` clamps the
   Data execution resources to `num_cpus_per_env_runner` **[verified]**
   `offline/offline_env_runner.py:40-45` — 0.25 in `train_config.json`, 1.0 on the GPU profile.
   Recording competes with sampling for the same core, on a profile with two cores total. The
   synchronous-write problem of §2.4 does not disappear; it changes shape.

**Verdict.** Offline recording is designed for *producing training datasets for offline RL*, not for
diagnostics. This repository's per-step record is diagnostic: it exists so `reward_terms` variance,
NAV trajectories and rejection behaviour can be examined after a run. Even with multi-agent support,
the columnar path would not carry the fields that motivate it. The parts genuinely worth adopting
are the *substrate* (Ray Data, Parquet, one directory per worker per write event, `filesystem=` for
cloud storage) rather than the RLlib feature.

---

## 6. Recommendations

Ordered by (damage prevented) ÷ (effort). Items 1–3 are defects; 4–6 are the format work; 7–8 are
adoption of Ray built-ins.

**1. Make `strict_nav_check` fatal on a distributed run.** (§2.1) Raising in the callback is not a
stop signal once the runner is remote. Emit the violation the way the run can act on it: keep the
ERROR and the `nav_conservation_error` metric where they are, and have the driver stop the loop.
Concretely — log the violation with a distinguishing metric (e.g. `nav_conservation_violations`,
`reduce="sum"`), then in `train()` check that metric in the result after each `algo.train()` and
raise on the driver when `strict_nav_check` is set. That path is where an exception genuinely ends
the run, and it also puts the message into `run.log`. Test it at `num_env_runners=1`; the existing
`test_nav_callback.py` tests only the in-process case.

**2. Stop accumulating steps when the pickles are off.** (§2.2) One guard on
`self.store[...].append(...)`. `--no-episode-data` currently buys none of what it advertises. The
activity tallies are already independent of `store`, so nothing else changes.

**3. Guard the pickle write, and make its path absolute and run-scoped.** (§2.3, §2.4) Wrap the
`makedirs`/`open`/`dump` in `try`/`except` with a `logger.warning`, matching `_append_progress`.
Resolve `episode_data_dir` to an absolute path in `TrainConfig` (as `run_dir` already is), and put
the per-episode files under a run-scoped subdirectory. Export it to the workers through the same
`runtime_env` channel the log directory uses, so the resolution never depends on worker cwd.

**4. Prune `store`/`_activity` defensively.** (§3.2) Either cap the dict (evict the oldest episode
id when it exceeds `num_envs_per_env_runner` + slack) or hook `on_environment_created` /
`on_sample_end` to drop ids no longer live. Cheap, and it converts an unbounded leak into a bounded
one.

**5. Replace `pickle` with Parquet via Ray Data, keeping the `info` fields.** (§5, doc 11 §3) This
is the item Ray's offline recording *would* have provided. Write one flattened row per
(episode, step, agent) with the `info` fields as columns, `obs`/`act` as list columns. It fixes four
listed problems at once: arbitrary code execution on load, no schema, no queryability, and no
timestamp/iteration metadata (add `run_id` and `iteration` columns — the runner now knows the
iteration, per §1.12 of doc 11). Buffer to a row threshold and write from a background thread so the
sampling loop is not blocked. Do this *before* revisiting RLlib's `output=`, since the schema is the
part that has to be right either way.

**6. Bound the per-episode record.** (doc 11 §3) A sampling rate (every Nth episode), a per-run byte
cap, or a retention count. The flag is on/off today, and "on" is the default at ~34 MB per episode.

**7. Adopt `ray.LoggingConfig` for cluster-wide structure.** (§2.7, §3.4) Pass
`ray.init(logging_config=ray.LoggingConfig(encoding="JSON", log_level=...))` so Ray's own diagnostics
in every process are structured and carry job/worker/actor ids. Set the package logger's
`propagate = False` in the same change, or every package line prints twice. This is the cleanest fix
for "the swallowed env-runner traceback is in a different stream from the narrative it explains".

**8. Reduce the per-step `info` into metrics.** (doc 11 §4, unchanged and still the largest gap)
Capture is good; aggregation is six values. The `reward_terms` variance split, per-agent end-of-
episode account state, and the champion/league events in §2.5 of doc 11 all belong in
`MetricsLogger`, which is the one channel that already survives multiple runners correctly and
lands in `progress.jsonl` for free.

---

## 7. Corrections made to existing docs

| Doc | Was | Now |
|---|---|---|
| `11 §1.5` | "`strict_nav_check` defaults to true … so the run stops" | Qualified: true at `num_env_runners=0`; a remote runner's raise is swallowed and the runner restarted (§2.1 here) |
| `11 §1.1` | The `episode_data_dir` flag described as switching the per-episode record off | Notes that the flag switches off the *write*, not the accumulation (§2.2 here) |
| `config/runtime_profiles.json` | "~10MB per 4096-step episode" | ~34 MB, measured at the training shape |
