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

**Every finding here is fixed, and all eight recommendations in §6 are implemented.** §1 and §4–§5
describe what was audited; each §2–§3 finding now says what the code does instead, and the defect
it replaced is in [29_fixed_issues.md](29_fixed_issues.md#from-21--logging-review). §6 records
what was built and where it departed from the recommendation.

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

The table is the audited state. Channel 4 is Parquet now, bounded and run-scoped (§6 items 3, 5 and 6),
and channel 3 carries 27 values rather than 6 (§6 item 8).

Channel 4 was the only per-step *persistence*, and it was entirely bespoke — no Ray or RLlib
machinery was involved in it. That is the crux of §4 and §5.

The plumbing that makes channel 1 work across processes is worth naming, because §2's problems are
all failures of the same plumbing applied to the other channels:

* the level and the log directory travel to workers as `$CDA_LOG_LEVEL` / `$CDA_LOG_DIR`, exported
  by `configure()` **and** passed through `ray.init(runtime_env=...)` by `merge_runtime_env()`, so
  they arrive whether or not this process started the cluster;
* the log directory is made **absolute** before export (`configure` in `logging_setup.py`);
* each process writes its own file, tagged with pid *and* Ray worker id, because
  `RotatingFileHandler` has no cross-process interlock;
* the training iteration is pushed to the runners each iteration by `train._broadcast_iteration`,
  so a worker's lines can be joined to a `progress.jsonl` row.

None of channels 2–5 has any of that.

---

## 2. Problems under multiple env runners

### 2.1 `strict_nav_check` stops the run from the driver

the episode hook reports a violation as the `nav_conservation_violations` metric and the driver
raises `NavConservationError` after `algo.train()`, so the check stops a run at every runner count
(§6 item 1). (#212.) The defect is in
[29](29_fixed_issues.md#21-21--strict_nav_check-restarted-a-worker-instead-of-stopping-the-run).

### 2.2 No per-step store when episode data is disabled

with `episode_data_dir: null` the callback retains nothing per step (§6 item 2). (#213.) The
defect is in
[29](29_fixed_issues.md#21-22--the-per-step-store-accumulated-with-episode-data-disabled).

### 2.3 `episode_data_dir` is absolute and run-scoped

`TrainConfig.episode_data_path` resolves `<episode_data_dir>/<run_id>` to an absolute path,
pickled into the callback every runner receives (§6 item 3). (#214.) The defect is in
[29](29_fixed_issues.md#21-23--episode_data_dir-was-neither-absolute-nor-run-scoped).

### 2.4 The episode record is written off the sampling thread

the record is Parquet, written from one background thread, and every failure in the writer is a
warning (§6 items 3, 5 and 6). (#215.) The defect is in
[29](29_fixed_issues.md#21-24--the-pickle-write-was-synchronous-on-the-sampling-hot-path).

### 2.5 Worker log files are bounded, and each keeps its head

`file_max_worker_files` bounds the number of worker logs in the directory, and `file_keep_head`
keeps the first `file_max_bytes` of every log as `<name>.head`. Size the pruning above the number of
runners plus learners: an idle live runner whose file is older than the newest N would lose its
file. (#216.) The defect is in
[29](29_fixed_issues.md#21-25--log-files-proliferated-with-worker-restarts).

### 2.6 What the learner processes get

`_broadcast_iteration` also reaches remote learners (`num_learners > 0`); a learner that does
not answer within the timeout is a warning. The repository's profiles use `num_learners=0`, so no
real remote learner has run this path. (#217.) The defect is in
[29](29_fixed_issues.md#21-26--learner-processes-never-received-an-iteration).

### 2.7 The cluster's own logging reaches the run log

the driver warns in `run.log` when a process that should write a run log has none, and
`capture_ray_logs` attaches the run-log file handler to the Ray loggers, so RLlib's diagnostics land
in the same file with the same `pid=` and `iter=` fields. Ray prints its own records to the console;
the stream handler is not mirrored. (#218.) The defect is in
[29](29_fixed_issues.md#21-27--the-runtime_env-did-not-cover-the-clusters-own-logging).

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

### 3.2 In-flight episodes are bounded in `store` and `_activity`

both live-episode dicts are bounded, oldest evicted first (§6 item 4). (#219.) The defect is in
[29](29_fixed_issues.md#21-32--in-flight-episodes-leaked-from-store-and-_activity).

### 3.3 A runner the broadcast misses reads `iter=-`

a remote runner clears its tag in `on_sample_end`, so a runner the next broadcast misses reads
`iter=-`, not the previous iteration. The local runner shares the driver's process and is left
alone. (#220.) The defect is in
[29](29_fixed_issues.md#21-33--the-iteration-tag-was-stale-after-a-missed-broadcast).

### 3.4 One copy of the narrative on the console

a worker writing its own file echoes only `worker_console_level` (default `WARNING`) and above
to stdout, so the NAV table is in its file and not twice. Set `worker_console_level` to `INFO` (or
empty) to see the remote runners' per-episode narrative live on the console. (#221.) The defect is
in [29](29_fixed_issues.md#21-34--duplicate-narrative-on-the-console).

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

## 6. Recommendations — all eight implemented

Ordered as they were written: 1–3 defects, 4–6 the format work, 7–8 adoption of Ray built-ins. Each
now records what was actually built and where it differed from the recommendation.

**1. `strict_nav_check` stops a distributed run.** ✅ The callback no longer raises. It logs the
ERROR, `nav_conservation_error`, and a new `nav_conservation_violations` counter
(`reduce="sum"`, emitted on conserved episodes too so the key always exists); the driver reads it
after `algo.train()` and raises `NavConservationError` — a subclass of `AssertionError`, so any
existing `except` still catches. The check runs after `_append_progress`, so the failing iteration's
numbers are on disk, and before the checkpoint, because a corrupt ledger is not a state worth
saving. Non-strict now warns *on the driver*, which previously said nothing at all about a violated
run — the per-episode ERROR is in a worker's file.

*Beyond the recommendation:* the raise had to go entirely, not merely be supplemented. A throwing
`sample()` means `get_metrics()` never runs, so the raise would have destroyed the very metric the
driver check reads. At `num_env_runners=0` the stop is now one iteration later than it used to be;
that is the price of one code path that works at every runner count.

**2. Accumulation stops when the record is off.** ✅ `on_episode_step` no longer touches
observations or actions when `episode_data_dir` is None. Verified by the test that caught it:
1,000 steps with the record off now retains nothing.

**3. The write is guarded, absolute and run-scoped.** ✅ `TrainConfig.episode_data_path` resolves
`<episode_data_dir>/<run_id>` to an absolute path. Every failure in the writer is a warning. No
env-var plumbing was needed after all — the absolute path is pickled into the callback that every
runner already receives, which is simpler than the `runtime_env` channel the recommendation
proposed and has the same effect.

**4. The live-episode dicts are bounded.** ✅ Both of them: the recorder evicts the oldest buffered
episode past `max_live_episodes`, and the callback's activity tallies past `_MAX_LIVE_EPISODES`.
Insertion-ordered, so "oldest" means the episode that started first.

**5. Parquet instead of `pickle`.** ✅ One row per (episode, step, agent), a declared schema, and
`run_id` / `iteration` / `wall_time` / `module_id` columns — which also closes "the files carry no
timestamp or iteration metadata" from docs/11 §3 and makes champion matchups a group-by. An `info`
key with no column is preserved as JSON in `info_extra`, and a test fails if `InfoBuilder` grows a
field the schema does not cover.

*Deliberate deviation:* this writes with `pyarrow.parquet` from one background thread, **not** via
`ray.data` as the recommendation said. Starting a Ray Data execution inside an env runner is the
objection §5 raises against RLlib's own offline recording — it clamps to `num_cpus_per_env_runner`
and competes with sampling on a two-core profile. The output is byte-for-byte the same thing
`ray.data.read_parquet` consumes, so nothing downstream is lost.

**6. The record is bounded.** ✅ `episode_sample_every` (default 10, chosen by `crc32` of the
episode id so every runner picks the same subset without coordinating) and `episode_max_bytes`
(default 2 GiB per writer, oldest deleted first). Both were needed: at ~34 MB per episode the
default was previously "record until the disk fills".

**7. `ray.LoggingConfig`, and propagation off.** ✅ `ray_log_encoding` (`TEXT` by default, `JSON`
available, empty to leave Ray alone), feature-detected so an older or newer Ray degrades to its own
formatting. Setting it also passes `propagate=False`, since `LoggingConfig` configures the root
logger and both handlers would otherwise print every package line twice. Propagation stays on by
default — `caplog` and any other root-attached handler depend on it — so it is a `configure()`
argument rather than a constant.

**8. The per-step `info` is reduced into metrics.** ✅ Six metrics became 27. Per episode:
`reward_term_mean_*` and `reward_term_var_share_*` for all five contributions, `episode_nav_mean` /
`_min` / `_max`, `mean_agent_drawdown`, `mean_abs_net_position`, `mean_num_trades`,
`maker_fill_ratio`. Per iteration: `champions_promoted`, `iterations_since_champion` — the number
`_should_create_champion` had computed and thrown away on every call — `available_modules` and
`idle_modules`.

The variance shares are computed from running sums, not a retained series, which matters for the
same reason item 2 does. On a real 2-iteration run they read `nav_term` 0.95, `drawdown_penalty`
0.05, and the other three below 1e-8 — the docs/07 §6.4 split, live, from a run rather than from a
post mortem.

---

## 7. What was found while implementing, and while checking the implementation

More defects turned up while the recommendations were being built and checked: a 30-second hang at
process exit (#222), league metrics one iteration late (#223, now written to `result["league"]` in the row
they describe), live episode state pickled into every runner (#224), and `maker_fill_ratio` measuring a
conservation identity (#225, now `maker_fill_ratio_max`). All are fixed; the narratives, and the lesson
that an aggregate over all agents of a two-sided quantity is a conservation identity, not an observation,
are in [29](29_fixed_issues.md#21-7--what-was-found-while-implementing).

---

## 8. What the console records

**The console is not a complete record under multiple runners, and never was.** A two-runner run put
6 NAV tables in the per-worker log files and 2 on the console. Ray forwards worker stdout to the
driver on a best-effort basis and stops when the worker is killed, so the tail is lost. This is
pre-existing Ray behaviour rather than anything this work introduced — and it is exactly the reason
docs/11 §1.9 gives for the per-process files existing. Worth stating because it makes the console
misleading as a record: the files are complete, the terminal is a sample.

The corrections this audit made to other documents, and three defects found by cross-checking the
channels (unmarked episode fragments, a racy excepthook guard, and the notebook path turning
propagation off without a `LoggingConfig`), are in [29](29_fixed_issues.md#21-8--corrections-to-other-documents-and-three-more-defects).
