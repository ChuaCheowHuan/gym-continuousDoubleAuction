# 11. Logging and Observability

An audit of what training records, where it goes, and the gap between what is computed and what
is surfaced.

Related: [08_self_play_league.md](08_self_play_league.md) (the callback that does most of the
logging), [09_distributed_training.md](09_distributed_training.md) (what changes with multiple
workers), [14_perspective_ai_engineer.md](14_perspective_ai_engineer.md) §5.4.

**Status.** This used to be the weakest engineering area in the repository: no logging framework
at all, ~86 `print()` calls, and a conservation check that reported a corrupt ledger by printing
`FAILED`. Both are fixed - see §1.3 and §1.5. Coverage was the next gap and is largely closed:
27 custom metrics (§1.2) and a typed, queryable per-step record (§1.1). What is left in §2 now needs
new computation rather than aggregation of something already in hand.

**Concurrency.** §1.10 is the answer to "is this thread safe or process safe", which is a separate
question from coverage and was for a long time answered only in prose. It now has tests.

**Distribution.** [21_logging_review.md](21_logging_review.md) is the audit of what all of the above
does once `num_env_runners > 0`, which is the shape the GPU profile runs. Three of its findings were
defects rather than gaps - a stop signal that stopped nothing, a switch that switched nothing off,
and the one output path with no absolute resolution - and §1.5, §1.1 and §1.15 here are what they
became.

---

## 1. What is currently logged

### 1.1 The per-step episode record (Parquet)

**Where:** `on_episode_step` hands the step to
[`train/episode_record.py`](../gym_continuousDoubleAuction/train/episode_record.py);
`on_episode_end` releases the episode to a background writer thread, which writes
`<episode_data_dir>/<run_id>/episodes.<pid>.<worker>.<n>.parquet`. **One row per (episode, step,
agent)**, with a declared schema.

| Column group | Columns |
|---|---|
| Identity | `run_id`, `iteration`, `episode_id`, `step`, `agent_id`, `module_id`, `wall_time` |
| NAV | `nav` (float, for arithmetic), `nav_str` (the exact `Decimal` string) |
| Account | `net_position`, `VWAP`, `cash`, `cash_on_hold`, `position_val`, `drawdown`, `max_nav`, `num_trades`, `num_trades_step`, `num_passive_fills_step`, `order_step_placed`, `num_rejected_step`, `is_pass_action` |
| Market | `last_price`, `best_bid`, `best_ask`, `spread` |
| Reward | `reward`, and `reward_term_*` for each of the five signed contributions |
| Raw | `obs` (list), `action` (list), `info_extra` (JSON for any `info` key with no column) |

This replaced a `pickle.dump` of the whole episode performed inline in `on_episode_end`. Five
things changed, and each was a defect ([21 §2.2–2.4, §5–6](21_logging_review.md)):

* **Typed and queryable.** `ray.data.read_parquet`, pandas or DuckDB read it without this package
  installed, and `pickle`'s arbitrary-code-execution-on-load is gone. The schema is *declared*, not
  inferred — inference would let two files of one run disagree about a column's type whenever an
  episode happened to hold only nulls in it. An `info` key with no column is preserved as JSON in
  `info_extra` rather than dropped, and `test_episode_record.py` fails if `Info_Helper` grows a
  field the schema does not cover.
* **Off the hot path.** A bounded queue hands rows to one background thread, so the env runner's
  step loop pays a buffer append. A full queue drops a batch with a warning rather than blocking —
  putting the filesystem into the sampling loop is the failure this exists to remove.
* **It cannot raise into the hook.** Every failure is a warning. On a remote env runner an
  exception out of `on_episode_end` is a killed and restarted worker, not a stopped run.
* **`--no-episode-data` now costs nothing.** `on_episode_step` no longer touches observations or
  actions when the record is off. Previously the flag disabled the write and kept the ~34 MB per
  episode of accumulation.
* **It is bounded.** `episode_sample_every` (default **10**) records one episode in N, chosen by
  `crc32` of the episode id so every runner samples the same subset without coordinating;
  `episode_max_bytes` (default 2 GiB) caps what each writer keeps, deleting its own oldest files
  first. Per writer, not per directory: deleting another worker's files is a cross-process race for
  no benefit, so a run with N runners keeps up to N × the cap.

The path is **absolute and run-scoped** (`TrainConfig.episode_data_path`). It is neither by
accident: the callback is pickled into every env runner, and a relative path is resolved against
whatever working directory that worker inherited. It stays outside `run_dir` deliberately —
`runtime_profiles.json` splits `results_root` from `episode_data_root` so the bulky record can be
kept off the Drive FUSE mount the checkpoints need.

**Why pyarrow and not Ray Data.** [21 §6](21_logging_review.md) item 5 said "Parquet via Ray Data";
this writes Parquet with `pyarrow.parquet` directly. The reason is the objection §5 raised against
RLlib's own offline recording: it starts a Ray Data execution *inside* the env runner, clamped to
`num_cpus_per_env_runner`, competing with sampling on a profile with two cores. The output is
identical — `ray.data.read_parquet` reads these files natively — so nothing downstream is given up.
pyarrow is not a new dependency; `ray[rllib]` already requires it.

**The measurement that made the bounds necessary.** At `max_step=4096` and 8 agents a step is 8,314
pickled bytes, so an episode was **~34 MB** — held in memory and then serialised, per episode, per
worker. `runtime_profiles.json` had estimated ~10 MB.

Two `.pkl` files remain committed under `episode_data/`. They are leftover output from an older
version of `test_nav_callback.py`, not fixtures anything reads, and nothing regenerates them.

### 1.2 RLlib `metrics_logger` custom metrics

| Metric | Value | Window | Emitted in |
|---|---|---|---|
| `nav_conservation_error` | `abs(total NAV − total initial cash)`, as a float | 1 | `on_episode_end` |
| `pass_action_fraction` | Share of agent-steps where the agent chose `category=0` | 10 | `on_episode_end` |
| `order_rejection_fraction` | Share of agent-steps where an order was refused for want of cash | 10 | `on_episode_end` |
| `nav_conservation_violations` | Episodes that failed the check | `reduce="sum"` | `on_episode_end` |
| `reward_term_mean_<term>` × 5 | Mean of each signed reward contribution | 10 | `on_episode_end` |
| `reward_term_var_share_<term>` × 5 | That term's share of the reward's variance | 10 | `on_episode_end` |
| `episode_nav_mean` / `_min` / `_max` | Per-agent NAV at episode end | 10 | `on_episode_end` |
| `mean_agent_drawdown` | Mean per-agent drawdown at episode end | 10 | `on_episode_end` |
| `mean_abs_net_position` | Mean absolute inventory at episode end | 10 | `on_episode_end` |
| `mean_num_trades` | Mean trades per agent over the episode | 10 | `on_episode_end` |
| `maker_fill_ratio` | Passive share of fills, when anything traded | 10 | `on_episode_end` |
| `league_size` | `num_trainable + num_random + champion_count` | 1 | `on_train_result` |
| `league_mean_return` | Mean module return across the league | 10 | `on_train_result` |
| `league_std_return` | Std dev of module returns | 10 | `on_train_result` |
| `champions_promoted` | Champions created this iteration | `reduce="sum"` | `on_train_result` |
| `available_modules` | Size of the matchmaking pool | 1 | `on_train_result` |
| `idle_modules` | Modules that played no episode this iteration | 1 | `on_train_result` |
| `iterations_since_champion` | Iterations since the last snapshot | 1 | `on_train_result` |

**27 metrics**, up from six. What was missing was never capture — it was aggregation: §2.3, §2.4
and §2.5 all described numbers already sitting in `info` or already computed in the callback and
then dropped.

The split matters. The `on_train_result` metrics are per *iteration* and are emitted on the driver.
The `on_episode_end` ones are per *episode* and are emitted **on the env runners**, which is where
the episode hooks run. `nav_conservation_error` keeps `window=1` because an error in one episode out
of many must not be averaged away (§1.5); the fractions and the per-episode reductions use
`window=10`, matching the league metrics, because a single episode is noisy and the question they
answer is the trend.

**The `on_train_result` metrics are one iteration late.** The hook is handed a `result` that has
already been compiled, so a value logged there is reduced on the following pass:
`champions_promoted` reads `1.0` in the row for the iteration *after* the promotion. This has always
been true of `league_size` and the return statistics; the champion metrics simply make it visible.
The lag is uniform, so joining on `training_iteration` with one documented offset is better than a
correction that would have to be undone if RLlib changed the order.

**Two of them exist to be alerted on, not plotted.** `nav_conservation_violations` is how a broken
ledger reaches the driver at all (§1.5), and `idle_modules` is the S3-12 signature — a league
quietly shrinking to whichever modules the mapping fn happens to draw.

**The variance shares are the doc/07 §6.4 split, live.** Measured on a real 2-iteration run:
`nav_term` 0.95, `drawdown_penalty` 0.05, the other three below 1e-8. That is the answer to "which
term is actually driving the signal", and it previously required reading a file back afterwards. A
term that is large but constant contributes no variance and correctly reports no share — which is
why the shares, not the means, are the diagnostic.

**Why the two activity fractions exist.** They separate the two behaviours a return series cannot
tell apart. An agent that stops trading looks identical in its returns whether it *chose* to pass
or whether every order it sent was refused. The first is S1-3: `entropy_coeff` is 0.0, policies can
collapse to always-pass, and such a policy still clears the champion promotion threshold because 0
beats a negative league mean — so the pool fills with do-nothing snapshots while the returns series
looks unremarkable. `pass_action_fraction` trending to 1.0 states it outright. The second is a
policy quoting past its cash; `order_step_placed` cannot express it, being 0 both for an agent that
never tried and for one whose order was refused.

**[verified]** on a real 2-iteration run: `pass_action_fraction` reported `0.122` and `0.130`,
consistent with 1 of 9 action categories being the pass code for near-uniform untrained policies.

### 1.3 Logging (stdout and a run log, filterable)

Every module reports through the standard library's `logging`, configured in one place by
[`logging_setup.py`](../gym_continuousDoubleAuction/logging_setup.py):

```python
from gym_continuousDoubleAuction.logging_setup import get_logger

logger = get_logger(__name__)
```

**[verified]** no `print()` survives in `envs/` or `train/`; `test_logging_setup.py` asserts it,
so a new one fails CI. `visualize/` is deliberately exempt - those are one-shot terminal tools
whose stdout *is* the product - as are the demo scripts under `envs/orderbook/test/`.

| Level | What goes here |
|---|---|
| `DEBUG` | Per-step detail: the env's `_render` dumps, LOB and account tables, mark-to-market, the episode hooks' derived parameters, the policy map at episode start |
| `INFO` | Per-episode and per-iteration events: the NAV table, league statistics, champion creation and removal, checkpoint writes, iteration summaries |
| `WARNING` | A recoverable surprise: a requested GPU that is absent, an unreadable checkpoint, a repaired league state |
| `ERROR` | A broken invariant: NAV conservation failing, a champion that could not be created |

Three properties this buys that `print` could not:

* **Worker attribution.** The format carries the pid, so with `num_env_runners > 0` the
  interleaved episode hooks are separable by process. Previously eight workers wrote
  indistinguishable text into one stream.
* **An off switch.** `cda_log_level` in `train_config.json` (or `$CDA_LOG_LEVEL`, or
  `--log-level` on the random runner) sets the level. Remote EnvRunners are separate interpreters
  that never run `main()`, so `configure()` exports the level into the environment and each
  worker's first `get_logger` call picks it up. That export reaches a worker only when this
  process starts the cluster, because the raylet inherits our environment; against
  `ray.init(address=...)` on a cluster that was already running it never arrives. So the same
  variables are also passed as a `runtime_env`, which Ray applies to the workers it starts for the
  job whoever started the cluster - see `logging_setup.worker_env_vars`.
* **A record that outlives the terminal.** See §1.9 - the log is written to a rotating file under
  `log_base_dir` as well as stdout.

Each line is stamped `<date> <time> <level> pid=<pid> iter=<iteration> <module>: <message>`. The
date is there because a training run outlasts a day and a time-only stamp cannot be ordered across
midnight; `iter=` is the training iteration, which is what lets a line be joined to the
`progress.jsonl` row for the same iteration. It reads `-` in any process that does not know the
iteration - see §1.9.

`cda_log_level` is deliberately separate from `log_level`, which is Ray's: Ray at INFO is noise,
while this package at INFO is the output a run is meant to produce.

The env's per-step render is now gated on both `is_render` **and** DEBUG being enabled, so the
tabulate tables and pandas DataFrames of the whole book, tape and every account are not built for
output that would be dropped. `env.render()` still defaults to `is_render=True` on a bare env, but
at the default INFO level that no longer produces anything.

### 1.4 Legacy Ray actor storage (`g_store`) - removed

`train/storage/store_handler.py`, `train/logger/log_handler.py` and `train/plotter/plot_handler.py`
were ~270 LOC that looked like a telemetry pipeline and were a broken one: all three depended on a
detached Ray actor named `g_store` that **was never created anywhere**, so every entry point into
them would have raised at call time. They have been deleted, along with the now-orphaned
`plot_defaults` group in `tunable_constants.json` that only `plot_handler` read. Git history has
them if the design is ever wanted back.

### 1.5 The NAV conservation check

The sum of every agent's NAV must equal the cash the system started with: the ledger is `Decimal`
end to end, so trading moves cash and never creates it. This was a good idea implemented as a
`print("... FAILED ...")`. It now reports on the runner and stops on the driver:

```python
# on the env runner, in on_episode_end
if metrics_logger:
    metrics_logger.log_value("nav_conservation_error", float(abs(error)), window=1)
    metrics_logger.log_value(NAV_VIOLATIONS_METRIC, 0.0 if conserved else 1.0, reduce="sum")
if not conserved:
    logger.error(message)

# on the driver, in train(), after algo.train()
if nav_violations(result) and cfg.strict_nav_check:
    raise NavConservationError(message)
```

The check is **`Decimal` end to end**. `info["NAV"]` is the exact `str()` of a `Decimal`
(§2.6), so it is parsed back with `Decimal`, and `total_initial_cash` is built as a `Decimal`
too; `float()` is applied only where the value leaves for the metrics stack, which reduces with
NumPy and will not take a `Decimal`. The comparison that decides the raise is therefore exact.

* The **metric goes out either way**, so a run has a series to inspect rather than only the moment
  it broke. `window=1` keeps it per-iteration: an error in one episode out of many must not be
  averaged away.
* **`strict_nav_check` defaults to true.** A conservation break means the ledger is corrupt and
  every reward computed from NAV afterwards is meaningless, so the run stops. Set it false in
  `train_config.json`, or pass `--no-strict-nav-check`, for a run that would rather finish and be
  inspected afterwards; the ERROR log and the metrics still happen.
* **The stop is the driver's, not the hook's.** The callback reports - ERROR,
  `nav_conservation_error`, and a `nav_conservation_violations` count - and
  `train._check_nav_conservation` raises `NavConservationError` on the driver after the iteration,
  before the checkpoint. Raising inside `on_episode_end` worked only at `num_env_runners=0`: the
  hook runs on the env runner, so the raise arrives as a `RayTaskError` from `sample()`, and
  `restart_failed_env_runners` (True by default) makes `EnvRunnerGroup` log it through Ray's own
  logger and restart the actor - `algo.train()` returns normally. The raise also destroyed the
  evidence, since `synchronous_parallel_sample` asks each runner for `(sample(), get_metrics())` in
  one call. See [21 §2.1](21_logging_review.md).
  `NavConservationError` subclasses `AssertionError`, so anything written to catch the old
  behaviour still does.
* **`nav_tolerance`** (default `1e-6`) is headroom for a change that legitimately removes cash
  from the system, such as fees - see
  [13_perspective_financial_trader.md](13_perspective_financial_trader.md) §4. It is **not**
  absorbing arithmetic noise: with the check exact, the expected error is `0`, and the tolerance
  can be set to `0` to enforce that — the comparison is `abs(error) <= nav_tolerance`, inclusive,
  so `0` means "conservation must be exact" rather than "every episode is a violation". At the
  default the inclusive and exclusive forms differ only on an error of exactly `1e-6`.
  The `float()` round trip it was previously credited with
  absorbing was harmless at the default `init_cash` — but above `init_cash ≈ 1e10` it made the
  check unable to resolve this very tolerance, passing corrupt ledgers silently. See
  [16 §16.10](16_verification_log.md).

Covered by `test_nav_callback.py` (18 tests) in two halves: the hook reports a violation without
raising, counts it, keeps the error exact at an account size `float` cannot resolve, and emits the
counter on conserved episodes too; the driver raises under the default, warns and continues when
non-strict, says which file holds the detail, and reads a missing or unparseable metric as "nothing
seen" rather than as a failure. `test/integration/test_distributed_observability.py` then runs a
real `num_env_runners=1` iteration and asserts the counter actually arrives on the driver — which
is the claim the in-process tests cannot make.

### 1.6 Per-iteration training history (`progress.jsonl`)

`train()` calls `algo.train()` directly rather than through `tune.Tuner`, so nothing writes
`progress.csv` or TensorBoard event files. Each iteration's result dict used to be summarised into
one log line and dropped, which left a finished run with checkpoints, scrollback, and no queryable
record of how it got there.

Every iteration now appends one JSON object to `<run_dir>/progress.jsonl` (§1.11):

```python
result = algo.train()
_log_iteration(iteration, target, result, cfg)
_append_progress(result, cfg)
```

* **The whole result dict**, not a chosen subset. The loss terms, KL, entropy, timers and learner
  stats are all in there; deciding today which of them a future question needs is exactly the
  mistake that produced this gap.
* **`_json_safe` runs first.** RLlib results carry numpy scalars and arrays, occasional objects
  with no JSON form, and NaNs. Numbers stay numbers (a bare `default=str` would write `"1.5"` and
  make every reader parse it back), non-finite floats become `null` — `NaN` and `Infinity` are not
  valid JSON — and anything left over is stringified.
* **Opened and closed per iteration.** These runs normally end by being killed, so a buffer held
  open for the run would lose the iterations it had already finished. Append mode also means a
  resumed run extends its history rather than truncating it.
* **Every failure is swallowed with a warning.** A full disk must not take down a run that is
  otherwise training fine.
* It sits under `log_base_dir`, not with the per-step episode record: one short line per iteration
  belongs with the things that must survive a disconnect, which is why `runtime_profiles.json`
  splits `results_root` from `episode_data_root` in the first place. It is one level further down
  than it used to be, in this run's own directory - see §1.11 for why sharing one file across runs
  was not safe.

Covered by `test_progress_log.py` (one line per iteration, appends across a restart, numbers
survive as numbers, awkward values, and a write failure that must not stop the loop) and by
`test/integration/test_progress_and_vf.py`, which trains a real PPO and reads the file back.

### 1.7 Per-step `info` (account, market and reward decomposition)

`Info_Helper.set_info` reported three fields — `reward`, `NAV`, `num_trades`. Everything else a
step knew about itself was computed, consumed and dropped: the position, the drawdown the penalty
had just been charged on, the spread, and the five reward components. §2.2–2.4 below were that
gap; what follows is what closes it.

**The original three are unchanged** — same names, same types, same order. `NAV` stays a *string*,
the exact `str()` of a `Decimal`, because the conservation check parses it back with `Decimal`
(§1.5) and `visualize_nav.py` with `float()`. §2.6 tracks that round trip as its own question and
is not settled here.

| Group | Fields |
|---|---|
| Account (§2.3) | `net_position`, `VWAP`, `cash`, `cash_on_hold`, `position_val`, `drawdown`, `max_nav`, `num_trades_step`, `num_passive_fills_step`, `order_step_placed`, `num_rejected_step` |
| Activity (§2.2) | `is_pass_action` — did this agent choose to do nothing this step |
| Market (§2.2) | `last_price`, `best_bid`, `best_ask`, `spread` |
| Reward (§2.4) | `reward_terms`: `nav_term`, `order_penalty`, `trade_penalty`, `drawdown_penalty`, `passive_bonus` |
| Action | `model_action` — as the model emitted it, before `set_actions` reshapes it for the book |

Four decisions worth stating, because each could reasonably have gone the other way:

* **The reward terms are signed contributions that sum to `reward`, and the sum *is* the reward.**
  `set_reward` accumulates the dict rather than evaluating a second expression, so the logged
  split cannot drift from the number the agent was trained on. The accumulation is a left-to-right
  loop, deliberately **not** `sum()`: on Python 3.12+ the builtin applies Neumaier compensated
  summation to floats, which disagrees with plain accumulation on ~44% of random inputs (~1e-13
  relative). Instrumenting the reward must not change it.
* **New numeric fields go out as plain numbers, not strings.** They are diagnostics, not
  invariants — nothing reconstructs the ledger from them, and `float` is what the metrics stack
  and `json` consume. `NAV` alone keeps the string treatment, for the reason above.
* **`net_position` is reported as a float** even though `account.py` initialises it to `int` 0. The
  account rebuilds it as a `Decimal` on the first fill, so the underlying type changes partway
  through an episode; the reported field holds one type throughout.
* **`spread` is `None`, not `0.0`, on a one-sided book.** The observation needs a finite sentinel
  and uses `0.0`; a log does not, and `0.0` there would be indistinguishable from a book whose
  touch is one tick wide — the ambiguity [15 S3-14](15_findings_and_recommendations.md) is about.

Covered by `test_info_dict.py` (18 tests): back-compat of the original three, the terms summing
exactly, penalties matching coefficient × counter, the counters being read *before*
`set_step_outputs` zeroes them, `spread` on a one-sided book, and the whole dict surviving
`json.dumps`.

### 1.8 The type policy

Everything above assumes a field means one thing and holds one type. Before this, four did not.

| Kind | Type | Fields |
|---|---|---|
| Money | `Decimal` | `cash`, `cash_on_hold`, `position_val`, `init_nav`, `nav`, `prev_nav`, `max_nav`, `profit`, `total_profit` |
| Price | `Decimal` | order and trade `price`, `VWAP`, `best_bid`, `best_ask`, `spread` |
| Size | `int` | order and trade `quantity`, `net_position`, `num_trades`, the per-step counters |
| Signal | `float` | `reward`, `drawdown` |

**Why it is not cosmetic.** `Decimal * float` raises `TypeError`; `Decimal * int` does not. The
orderbook carries two local workarounds for exactly that error, both commented with the traceback
they came from (`orderbook.py:76-79`, `:99-100`), and `cash_processor.py:78` computes
`Decimal(str(price)) * qoute['quantity']`, which would raise on the modify path with a float size.
Sizes being `int` makes that class of failure unreachable rather than worked around.

The second failure is a field that changes type partway through an episode, which breaks any
consumer that checks it. Measured over a real run, before the fix: `net_position` was `int` until
the first fill and `Decimal` after; `VWAP` was `Decimal` until a position went flat, then `int`
(a bare `0` at `account.py:136`); `reward` was `int` until the first `set_reward`; `drawdown` was
`Decimal` until the first step.

**Signals are the deliberate exception.** `reward` must be a `float` — RLlib requires it — and
`drawdown` feeds the reward. They are learning signals, not money. The observation is `float32`
by construction, so prices and sizes are converted at that boundary too.

**`last_price` is the other exception**, and it stays a `float`. It never reaches the ledger:
`mark_to_mkt` passes the tape's `Decimal` to the account, while `last_price` is a separate anchor
consumed only by `_set_price`'s NumPy arithmetic and by `state_helper`, which already wraps it in
`float()`. Making it a `Decimal` would mean converting back at both consumers and buys no
exactness.

**`envs/orderbook/` is deliberately not changed** — see `ec1f5ea`, "Intentional revert because I
don't want code in orderbook folder to change." The book stores sizes as `Decimal` (`order.py:12`
coerces on the way in), and a fill reports whichever type its branch happened to hold:
`quantity_to_trade` (int) on a partial or exact fill, `head_order.quantity` (Decimal) when the
incoming order is larger — 84 against 10 on one tape. That mixing is absorbed at the single point
every trade passes through, `trader._normalise_trade_sizes`, before any account arithmetic sees
it. The coercion is lossless by construction rather than by luck: ints go in, the book only
subtracts whole sizes from whole sizes, and a fractional size raises instead of truncating
silently.

Sizes are `int` at ingress too (`action_helper.py:250`), which is a separate guarantee: the old
`(size + min_size) * 1.0` — commented *"\*1 for float"* — was the single character that made every
downstream size a float. Egress normalisation hides an ingress regression completely, so both ends
are pinned by `test_type_policy.py` (15 tests); the ingress tests exist precisely because a
mutation restoring that `* 1.0` left every other test in the file green.

**`info` is a serialisation boundary, not part of the policy.** JSON has no `Decimal`, so money
and prices are emitted as `float` there, except `NAV`, which pays the string cost because the
conservation check (§1.5) depends on its exactness. Sizes need no conversion — `int` is JSON-native.

### 1.9 The run log

§1.6 gave the run a machine-readable history and §1.7 gave the step one, but the log itself was
still written only to stdout. So a finished run left its *numbers* on disk and its *narrative* in
scrollback — the per-episode NAV tables, the league statistics, and the ERROR that immediately
precedes a `strict_nav_check` raise. [17 §17](17_changelog.md) records two GPU runs diagnosed
exactly that way, after the fact, from a terminal buffer.

Every process now writes a rotating log file under `log_base_dir`, beside `progress.jsonl`:

| File | Written by | Contains |
|---|---|---|
| `run.log` | the driver | iteration summaries, league statistics, champion events, checkpoint writes |
| `run.<pid>.<worker>.log` | each env runner | the per-episode NAV tables and the conservation ERROR |

**Why one file per process rather than one shared file.** `RotatingFileHandler` is not safe across
processes: two of them crossing the size threshold together rename and truncate the same file
underneath each other, losing lines from both. That rules out sharing — and sharing is not
something to give up lightly here, because the split is not cosmetic. The episode callbacks run on
the env runners, so with `num_env_runners > 0` the NAV tables and the conservation ERROR are
emitted in a worker and *nowhere else*. **[verified]** against a real two-runner run: a
driver-only file captured 7 lines and none of the NAV tables; with per-process files the worker
logs carry them. `log_base_dir` reaches the workers through `$CDA_LOG_DIR`, the same channel the
level takes, because an env runner never executes `train.main`.

Rotation bounds the output: `file_max_bytes` per file, `file_backup_count` older files kept. This
is the one item from §3's persistence table that the run log could otherwise have re-created.
Setting `file_name` to `""` disables file logging entirely.

A failure to open the file is a **warning, not an exception**. Logging is instrumentation, and a
run that cannot write its log should still train — the same rule `_append_progress` follows.

**The `iter=` field.** `progress.jsonl` is keyed by iteration and the log was keyed by nothing, so
joining them meant matching on wall-clock order. Log lines now carry the training iteration,
tracked in a `ContextVar` — per-thread rather than a module global, since the driver loop may not
be the only thread. It reads `-` where the iteration is unknown, which is every env runner and the
driver before the first iteration and after the last. Not `0`, which is a real iteration number.

A worker's NAV table is therefore dated, attributed and durable. It used to read `iter=-` as well,
on the reasoning that the worker genuinely does not know which iteration its episode belongs to -
§1.12 sends it the number instead. The dash remains for a process that legitimately has no
iteration: the driver before the first one and after the last.

Covered by `test_logging_setup.py` (49 tests): the file appears beside the metrics and mirrors
stdout, rotation bounds it, an unwritable destination warns instead of raising, a worker resolves
the directory from the environment and writes its own uniquely tagged file, the driver keeps the
plain name, the iteration tag follows `set_iteration` and defaults to a dash, the timestamp
carries the date, and - see §1.10 - concurrent configuration, two-process isolation, unhandled
exceptions and warning capture.

### 1.10 Thread safety and process safety

The short answer: **thread safe on both the write and the setup path; process safe by not sharing
files rather than by locking them.** The long answer is worth stating, because three of the four
holes below were real and none of them was covered by a test.

**Writes, within a process.** Safe, and always were. `logging.Handler.handle()` acquires the
handler's `RLock` around `emit()`, and `RotatingFileHandler.doRollover()` runs inside `emit`, so
concurrent `logger.info` from several threads can neither interleave a line nor rotate the file
twice. `test_concurrent_writers_do_not_tear_a_line` pins it.

**Setup, within a process.** Was *not* safe. `get_logger` checks `_configured` and then acts on
it, and `configure()` closes and removes the existing handlers before adding replacements.
`addHandler` is individually atomic under logging's own module lock, but that *sequence* is not:
two threads inside it produce duplicate handlers, or one closes a handler the other is emitting
through. The whole swap is now under `_configure_lock`. The window was small - the first
`get_logger` normally happens at import, which the import lock serialises - but "small" is not a
property a test can hold you to.

**Across processes.** `RotatingFileHandler` has no cross-process interlock, and the design's answer
is not to make sharing safe but to stop processes sharing a file:

| Writer | File | What keeps it apart |
|---|---|---|
| Driver | `run.log` | its own run directory (§1.11) |
| Env runner | `run.<pid>.<worker>.log` | pid *and* Ray worker id |
| Driver | `progress.jsonl` | its own run directory (§1.11) |
| Env runner | `episodes.<pid>.<worker>.<n>.parquet` | pid, Ray worker id *and* a per-writer sequence number, under a run-scoped directory (§1.1) |

Three of those were previously weaker than they looked:

* **A pid is not a unique key.** It is unique per *node*. On a multi-node run with `log_base_dir`
  on a shared filesystem - NFS, or the Drive mount Colab uses - two workers on different nodes can
  hold the same pid and open the same `run.<pid>.log`, which is the exact rotation race the
  per-worker name exists to prevent. The name now carries Ray's worker id, which is unique
  cluster-wide, behind the pid, which is what the `pid=` field of each line matches. Ray is read
  out of `sys.modules` rather than imported: `runtime.apply_env_vars()` must run before ray is
  first imported, and `configure()` runs before *that*.
* **The driver's own files were not covered at all.** `run.log` carries no pid, and `log_base_dir`
  defaulted to a fixed `results`, so two concurrent runs - or a notebook session alongside a CLI
  run - shared both it and `progress.jsonl`. §1.11 is the fix.
* **The episode record's directory was not covered either.** The episode id kept two *writers*
  apart, which was never the weak part; the *path* was a bare relative string, resolved inside each
  worker against whatever working directory it inherited, and shared by every concurrent run. It is
  absolute and run-scoped now (§1.1, [21 §2.3](21_logging_review.md)). The per-writer file naming
  is what lets each process enforce its own byte cap without deleting another's files.

**Why a shared `progress.jsonl` is worse than a shared log.** Not just rotation: line integrity.
`_append_progress` calls `json.dump(result, fh)`, which writes incrementally - 61 `write()` calls
for a trivial dict. Python's `TextIOWrapper` coalesces those into ~8 KiB chunks, so a small record
is a single `O_APPEND` write and atomic; a real RLlib result dict with learner stats and timers is
larger than the buffer and splits (measured: 31 KB → 4 syscalls, 314 KB → 39). Two drivers
appending would interleave *inside* one JSON line and produce a record nothing can parse.

**The `iter=` tag is process-wide, not per-thread.** It was a `ContextVar`, chosen so it would be
per-thread. That was the wrong model twice over: a new thread starts from an empty context, so a
line the driver logged from any thread but the loop read `iter=-` while the process knew the
answer; and a value set inside a Ray actor task is not guaranteed to still be in context for the
next task, which is what §1.12's broadcast needs. It is now a module global - one training loop per
process, so the iteration is a property of the process. Assignment of an int is atomic under the
GIL, so it needs no lock.

Covered by `TestConcurrentConfiguration` and `TestSeparateProcesses` in `test_logging_setup.py`,
which spawn real subprocesses because that is the one thing threads cannot stand in for.

### 1.11 One directory per run

Everything above keeps the *processes of one run* from colliding. Nothing kept two runs apart:
`log_base_dir` was a fixed `results`, so a second run wrote the same `run.log` and appended to the
same `progress.jsonl`.

Each run now gets a directory under `log_base_dir`, named by `run_id`:

```
results/                          <- log_base_dir
  chkpt/iter_000010/              <- shared across runs, deliberately
  run_20260816_094500_a3f9/       <- run_dir
    progress.jsonl
    run.log
    run.4231.01000000.log
```

`run_id` is generated from the local date, time and four random hex digits - the timestamp so a
listing is readable and orderable, the random suffix because two runs launched by the same script
in the same second would otherwise collide on the second, which is the case being fixed. Setting
`run_id` in `train_config.json` or passing `--run-id` reuses an existing directory, which is how a
restored run extends the `progress.jsonl` it left behind.

**The checkpoint tree is deliberately *not* run-scoped.** Restoring from a disconnect means finding
the newest `iter_*` written by an *earlier* run; a per-run checkpoint tree would hide it and every
resumed run would start from nothing. So the thing that must be shared is shared, and the two files
that cannot tolerate sharing are not. `warn_about_stale_checkpoints` already covers the cost of
that sharing.

`run_id` is out of `TrainConfig.__eq__`: it names the run rather than configuring it, and since one
is generated per instance, comparing it would make no two configs equal - including the checked-in
file against its own defaults, which `test_config_sources.py` asserts, and a restored checkpoint's
config against the current one, which `config_divergence` reports on.

### 1.12 The iteration reaches the env runners

§1.9 noted that a worker's lines read `iter=-` because "the worker genuinely does not know which
iteration its episode belongs to", and put recovering that association down as a change to what
RLlib hands the callbacks. That was too pessimistic. The driver knows the number, and
`foreach_env_runner` already reaches every runner; it only had to be sent.

`_broadcast_iteration` does that at the top of each iteration, before `algo.train()` starts
sampling. It is best-effort and quiet: a runner that is restarting, or an RLlib rename, degrades to
the old `iter=-` rather than stopping a training run. `local_env_runner=False`, because the
driver's own runner shares its process and `set_iteration` has already tagged it.

This is what makes the run log joinable to `progress.jsonl` under `num_env_runners > 0`, which is
the configuration where it matters: the episode callbacks run on the runners, so the per-episode
NAV tables and the conservation ERROR are emitted there and nowhere else.

### 1.13 A run that dies says why, in the log

`main()` was `try: train(cfg) / finally: ray.shutdown()`, with no `except`. An unhandled exception
- including the `strict_nav_check` `AssertionError` whose entire purpose is to stop a run loudly
enough to be diagnosed afterwards - unwound to Python's default hook, which writes to `sys.stderr`
outside logging. So `run.log` ended mid-narrative and the reason for the ending was in scrollback,
which is the failure §1.9 exists to fix.

Three things now catch it:

* `main()` logs the traceback where it happens, so it is tagged with the `iter=` that failed rather
  than appearing after the teardown lines;
* `sys.excepthook`, for anything that gets past that - and for every *worker* process, which no
  try/except on the driver could reach;
* `threading.excepthook`, for a thread dying, which Python handles separately again.

The previous hooks are chained rather than replaced, so stderr and any debugger still see what they
always did. `KeyboardInterrupt` is logged as a one-line INFO with no stack: these runs are normally
ended by being killed, and a full traceback for an intentional Ctrl-C is noise at the end of every
session.

`warnings.warn` is captured too, via `logging.captureWarnings(True)`. A `DeprecationWarning` from
Ray or gymnasium is the earliest signal that an upgrade is about to break this repository, and it
was going to stderr unrecorded and unrotated. Capture alone is not enough - it logs to
`py.warnings`, which is outside this package's namespace and inherits none of its handlers, so the
record would fall through to logging's last-resort handler and reach stderr anyway. The package's
handlers are mirrored onto it.

### 1.14 The stream handler writes to stdout

`logging.StreamHandler()` with no argument writes to **stderr**, which is what this package did
while §1.3, §1.9 and `tunable_constants.json` all described it as stdout. It matters:
`python -m gym_continuousDoubleAuction.train.train > run.txt` captured none of the output a run
exists to produce. It is now explicitly `sys.stdout`. Warnings and errors are not split onto stderr
separately - they are part of the same narrative, and two streams reorder against each other.

### 1.15 Ray's own logging, and propagation

Everything above concerns *this package's* logging. Ray's is a separate stream, and until now
nothing configured it in the processes where it matters most: an env runner's restart notices,
RLlib's "No samples returned from remote workers", and the traceback `EnvRunnerGroup` swallows when
a runner dies ([21 §2.1](21_logging_review.md)) are emitted by Ray's loggers in workers this package
never touches.

`ray.init(logging_config=ray.LoggingConfig(...))` is the one lever that reaches them: Ray applies it
to the driver and to every process it starts for the job. `ray_log_encoding` in `train_config.json`
selects `TEXT` (default, human-readable with job and worker ids attached) or `JSON`; an empty string
leaves Ray's logging alone. It is feature-detected - a Ray without the API, or one that rejects an
argument, costs the run its log formatting and nothing else.

Setting it also turns **propagation off** on this package's logger. `LoggingConfig` configures the
*root* logger, and this package's handler hangs off `gym_continuousDoubleAuction` with propagation
on, so every line would otherwise be printed twice. Propagation stays on by default, because that is
what any root-attached handler depends on - `caplog`, which is how most of the test suite reads log
output, among them. It is a `configure()` argument rather than a constant for exactly that reason:
the duplication exists only once Ray has configured root.
---

## 2. What is not logged but should be

### 2.1 Training metrics

Done, and no longer on this list: **`vf_explained_var`** — the one metric that exposes the frozen
critic (S1-1), and whose absence is why that defect survived. `_log_iteration` now prints it per
trainable module on every iteration, read from `result["learners"][<module_id>]` and keyed on
`trainable_policy_ids`, since only the modules in `policies_to_train` appear in that block.

`test/integration/test_progress_and_vf.py` asserts in CI that a real run reports it, finite, for
every trainable module. It deliberately does **not** assert `!= 0.0`: this repository currently
reports values around 1e-5, so that assertion passes on a critic that is entirely dead. The
substantive threshold (`>= 1e-3`) is there as a strict xfail that pins S1-1 as a known failure and
becomes a live guard the moment it is fixed.

Everything else on this list is *computed* by RLlib and reaches `progress.jsonl` (§1.6) as part of
the full result dict. What is still missing is surfacing: none of it is in the iteration log line
or aggregated into a metric worth alerting on.

| Missing | Why it matters |
|---|---|
| `vf_loss` vs `vf_loss_unclipped` | The saturation is invisible from `total_loss` alone |
| Per-policy reward mean / min / max / std | Only league aggregates are logged; individual trends are invisible |
| Policy win rate versus random and versus champion | The key signal for league-based training |
| Loss values (policy, value, entropy) | Fundamental for diagnosing learning pathologies |
| KL divergence / clip fraction | Detects excessively large policy updates |
| Iteration wall-clock time, sample throughput | Throughput analysis and scaling decisions |

### 2.2 Environment and market data

`last_price` and the bid-ask spread are **done** — both are in the per-step `info` dict (§1.7),
alongside `best_bid` and `best_ask`. What is still missing:

The do-nothing count and the rejection rate are **done**, and are metrics rather than only
fields: `is_pass_action` and `num_rejected_step` per agent-step in `info`, aggregated into
`pass_action_fraction` and `order_rejection_fraction` (§1.2). The pass flag is set where
`_CATEGORY_MAP` lives, so a reader of `info` does not need to know that `category=0` means pass;
`test_info_dict.py` cross-checks the two agree.

| Missing | Why it matters |
|---|---|
| Order book depth per level | Liquidity analysis |
| Market / limit / modify / cancel action counts per episode | Reveals strategy evolution — the *pass* share is now covered, the breakdown across the other four types is not |

### 2.3 Agent and account state

**Done, both halves.** All of these are in the per-step `info` dict (§1.7), and the end-of-episode
state is now reduced into metrics as well: `episode_nav_mean`/`_min`/`_max`, `mean_agent_drawdown`,
`mean_abs_net_position`, `mean_num_trades` and `maker_fill_ratio` (§1.2). Aggregated across agents
rather than emitted per agent, because the league reassigns opponents every episode - a metric named
for `agent_3` would be a different policy each time, the same mislabelling
`module_episode_returns_mean` exists to avoid.

The per-step fields: current `drawdown` and `max_nav`,
`net_position` (every step, not only at episode end), `VWAP`, `cash`, `cash_on_hold`,
`position_val`, and the three per-step counters `order_step_placed`, `num_passive_fills_step` and
`num_trades_step`, read before `set_step_outputs` zeroes them.

Passive fill ratio is not emitted as its own field: it is exactly
`num_passive_fills_step / num_trades_step`, and both are now logged, so deriving it needs no
further instrumentation. A field would only add a division-by-zero convention to argue about.

### 2.4 Reward decomposition

**Done.** All five terms — `nav_term`, order penalty, trade penalty, drawdown penalty, passive
bonus — are in `info["reward_terms"]` as signed contributions that sum exactly to `reward`
(§1.7). The variance split in [07_reward_function.md](07_reward_function.md) §6.4 is measurable
from the per-step record without further instrumentation, as is over- or under-trading,
risk-aversion learning and market-making uptake.

The aggregation is **done too**. `reward_term_mean_<term>` and `reward_term_var_share_<term>` are
emitted per episode (§1.2), computed from running sums rather than a retained series - an episode is
`max_step` × `num_agents` agent-steps, and keeping all of them to produce five numbers is the memory
cost §1.1 is about. The shares are normalised across the five terms, so a term that is large but
*constant* correctly reports no share: what the split answers is which term is driving the signal,
not which is biggest.

### 2.5 League and self-play state

Three of the five are **done** and are metrics now (§1.2): `champions_promoted`,
`iterations_since_champion` - the number `_should_create_champion` had computed and discarded on
every call - and `available_modules`, joined by `idle_modules`. Champion *matchups* are also
recoverable without new instrumentation: the episode record's `module_id` column says which module
played each agent slot in each episode (§1.1), so "who played whom" is a group-by rather than a
missing field.

| Missing | Why it matters |
|---|---|
| Per-champion win rate over time | Without it, champion pool management is blind. The raw material is now in the episode record; nothing computes the rate |

### 2.6 The `info["NAV"]` string round-trip

`Info_Helper` serialises NAV as a **string**
([`info_helper.py:18`](../gym_continuousDoubleAuction/envs/exchg/info_helper.py#L18)) —
presumably to survive `Decimal` JSON encoding — and every consumer parses it back with `float()`
(the league callback, `visualize_nav.py`). That round trip discards the exactness `Decimal` was
chosen for, and it makes the info dict awkward for RLlib metric aggregation.

---

## 3. Persistence problems

| Issue | Impact |
|---|---|
| `progress.jsonl` grows without rotation | One line per iteration is small, but nothing bounds it across a run that pins its `run_id` and resumes repeatedly |
| Rotation discards the *earliest* output first | `file_backup_count` × `file_max_bytes` caps the run log at 60 MB, which at DEBUG is reached quickly — and it is the start of a run, where divergence usually begins, that is dropped. A time-based handler, or archiving the run directory, keeps it |

Seven things are no longer in this table.

The three about the episode record all went with `pickle` (§1.1): the files are Parquet, so there is
no arbitrary code execution on load; every row carries `run_id`, `iteration` and `wall_time`, so
correlating with training progress is a join rather than a filename sort; and growth is bounded by
`episode_sample_every` and `episode_max_bytes` rather than being off/on.

The other four: logging itself is levelled, attributable, switchable and durable, written to a
rotating file per process as well as stdout (§1.3, §1.9), and the `g_store` dead code is gone
(§1.4); `progress.jsonl` is the per-iteration machine-readable record (§1.6); the run log does not
re-create the unbounded-growth problem it would otherwise have added, because `file_max_bytes` and
`file_backup_count` bound it; and two runs no longer write into each other's files (§1.11) - never
listed here, but the more serious of the two, since a shared `run.log` loses lines to a rotation
race and a shared `progress.jsonl` can interleave two writers inside one JSON line.

One new entry, from the same design: **the run log's file *count* is unbounded even though each file
is capped.** Every restarted env runner opens a new `run.<pid>.<worker>.log`, and RLlib restarts
runners as a matter of course. See [21 §2.5](21_logging_review.md).

---

## 4. Recommended additions

Done, and no longer on this list: `logging` in place of `print`; stopping a run on a NAV
conservation violation with a `nav_conservation_error` metric (§1.5 - the *stop* moved to the
driver, the metric did not); writing each iteration's result dict to `progress.jsonl` (§1.6);
logging `vf_explained_var` per trainable module with a CI assertion behind it (§2.1); and the four
metric calls this section used to sketch, all four of which now exist:

```python
# in on_train_result / on_episode_end - all of these are live
metrics_logger.log_value("champions_promoted", promoted, reduce="sum")
metrics_logger.log_value("mean_agent_drawdown", dd, window=10)
metrics_logger.log_value("pass_action_fraction", n_pass / n_actions, window=10)
metrics_logger.log_value(f"reward_term_var_share_{term}", variance / total, window=10)
```

The shape of this document has changed with them. It used to end "capture is now good, aggregation
is four league-and-NAV metrics"; aggregation is now 27 metrics (§1.2), and what is left is
genuinely different in kind - things that need a *new computation*, not a reduction of something
already in hand.

What remains, in order:

1. **Surface the §2.1 training metrics** (`vf_loss` vs unclipped, KL, clip fraction, per-policy
   reward spread, throughput) in the iteration log line. All are already in `progress.jsonl`; none
   is in the one line a person actually reads while a run is going.
2. **Per-champion win rate over time** (§2.5). The raw material is in the episode record now - the
   `module_id` column says who played which slot in which episode - so this is a query someone has
   to write, not instrumentation someone has to add.
3. **Per-episode desk metrics** that need a series rather than an endpoint: Sharpe, max drawdown
   over the episode, turnover. The account state at episode end is a metric now (§1.2), but these
   need the whole NAV trajectory, which is what the episode record is for. See
   [13_perspective_financial_trader.md](13_perspective_financial_trader.md) §7.
4. **Action-type counts per episode** (§2.2): the pass share is covered, the breakdown across
   market / limit / modify / cancel is not.
5. **Order book depth per level** (§2.2), the one item on this list that needs a new field in
   `info` rather than a reduction of an existing one.
