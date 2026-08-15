# 11. Logging and Observability

An audit of what training records, where it goes, and the gap between what is computed and what
is surfaced.

Related: [08_self_play_league.md](08_self_play_league.md) (the callback that does most of the
logging), [09_distributed_training.md](09_distributed_training.md) (what changes with multiple
workers), [14_perspective_ai_engineer.md](14_perspective_ai_engineer.md) §5.4.

**Status.** This used to be the weakest engineering area in the repository: no logging framework
at all, ~86 `print()` calls, and a conservation check that reported a corrupt ledger by printing
`FAILED`. Both are fixed - see §1.3 and §1.5. What remains open is *coverage*: the set of things
worth recording is still much larger than the set actually recorded (§2).

---

## 1. What is currently logged

### 1.1 Per-step episode data (persisted)

**Where:** `on_episode_step` accumulates into `self.store[episode.id_]`; `on_episode_end`
serialises that episode's steps to `<episode_data_dir>/<episode_id>.pkl` and drops them from
memory.

| Field | Source |
|---|---|
| `episode_id` | `episode.id_` |
| `obs` | `episode.get_observations(-1)` |
| `act` | `episode.get_actions(-1)` |
| `reward` | `episode.get_rewards(-1)` |
| `info` | `episode.get_infos(-1)` — carries `reward`, `NAV`, `num_trades` per agent |

Configurable via `SelfPlayCallback(episode_data_dir=...)` / `TrainConfig.episode_data_dir` /
`--no-episode-data`. **Default: on.** At `max_step=4096` and 8 agents this is ~4,096 dicts per
episode held in memory then serialised, per episode, per worker.

Two further notes:
- The store is keyed by episode ID, which is what makes it safe under
  `num_envs_per_env_runner > 1` (see [09](09_distributed_training.md) §2.4).
- The files carry no timestamp or iteration metadata, so correlating them with training progress
  means parsing filenames against wall-clock order.
- `pickle` executes arbitrary code on load. Fine for self-produced files; unsafe if episode data
  is ever shared. Two `.pkl` files are committed under `episode_data/`; they are leftover output
  from an older version of `test_nav_callback.py`, not fixtures anything reads, and the suite no
  longer regenerates them.

### 1.2 RLlib `metrics_logger` custom metrics

| Metric | Value | Window | Emitted in |
|---|---|---|---|
| `nav_conservation_error` | `abs(total NAV − total initial cash)`, as a float | 1 | `on_episode_end` |
| `league_size` | `num_trainable + num_random + champion_count` | 1 | `on_train_result` |
| `league_mean_return` | Mean module return across the league | 10 | `on_train_result` |
| `league_std_return` | Std dev of module returns | 10 | `on_train_result` |

**Four metrics** is the entirety of what reaches RLlib's structured logger, alongside RLlib's
own built-ins.

Three are per *iteration*, from `on_train_result`. `nav_conservation_error` is per *episode*, from
`on_episode_end`, which is why its window is 1: an error in one episode out of many must not be
averaged away (§1.5). It is also the only one of the four emitted on the env runners rather than
the driver.

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
  worker's first `get_logger` call picks it up.
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
`print("... FAILED ...")`. It now raises:

```python
if metrics_logger:
    metrics_logger.log_value("nav_conservation_error", float(abs(error)), window=1)
if not conserved:
    logger.error(message)
    if self.strict_nav_check:
        raise AssertionError(message)
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
  inspected afterwards; the ERROR log and the metric still happen.
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

Covered by `test_nav_callback.py` (6 tests): conservation passes and logs a zero error, a
violation raises under the default, the metric is emitted before the raise, non-strict logs ERROR
and continues, the tolerance admits what is inside it and not what is outside, and both knobs come
from the config file.

### 1.6 Per-iteration training history (`progress.jsonl`)

`train()` calls `algo.train()` directly rather than through `tune.Tuner`, so nothing writes
`progress.csv` or TensorBoard event files. Each iteration's result dict used to be summarised into
one log line and dropped, which left a finished run with checkpoints, scrollback, and no queryable
record of how it got there.

Every iteration now appends one JSON object to `<log_base_dir>/progress.jsonl`:

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
* It sits beside `chkpt/` under `log_base_dir`, not with the per-episode pickles: one short line
  per iteration belongs with the things that must survive a disconnect, which is why
  `runtime_profiles.json` splits `results_root` from `episode_data_root` in the first place.

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
| Account (§2.3) | `net_position`, `VWAP`, `cash`, `cash_on_hold`, `position_val`, `drawdown`, `max_nav`, `num_trades_step`, `num_passive_fills_step`, `order_step_placed` |
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
| `run.<pid>.log` | each env runner | the per-episode NAV tables and the conservation ERROR |

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

So with remote runners a worker's NAV table is dated, attributed to its pid and durable, but reads
`iter=-`: the worker genuinely does not know which iteration its episode belongs to. Recovering
that association means passing the iteration to the runners, which is a change to what RLlib hands
the callbacks rather than a logging change.

Covered by `test_logging_setup.py` (29 tests): the file appears beside the metrics and mirrors
stdout, rotation bounds it, an unwritable destination warns instead of raising, a worker resolves
the directory from the environment and writes its own pid-suffixed file, the driver keeps the
plain name, the iteration tag follows `set_iteration` and defaults to a dash, and the timestamp
carries the date.

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

| Missing | Why it matters |
|---|---|
| Order book depth per level | Liquidity analysis |
| Market / limit / modify / cancel action counts per episode | Reveals strategy evolution |
| Count of `category=0` (do-nothing) actions | **Directly detects the passivity collapse predicted by S1-3** |
| Order rejection / no-op rate | Signals cash constraints or blind modify/cancel actions ([04](04_accounting.md) §3) |

### 2.3 Agent and account state

**Done** — all of these are in the per-step `info` dict (§1.7): current `drawdown` and `max_nav`,
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

What remains is *aggregation*: the terms are per step and per agent, so a per-episode variance
share is a reduction a consumer still has to perform. Doing that through `metrics_logger` is
[15](15_findings_and_recommendations.md) Phase 4 item 15.

### 2.5 League and self-play state

| Missing | Why it matters |
|---|---|
| Champion matchup history (who played whom) | Needed to verify league diversity |
| Per-champion win rate over time | Without it, champion pool management is blind |
| Champion promotion events as a metric | Currently only a stdout banner |
| Time since last champion snapshot | Already computed in `_should_create_champion`, never logged |
| `available_modules` per iteration | Debugging matchmaking |

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
| Per-episode `.pkl` files grow without rotation or size cap | Disk fills over long runs; the flag is off/on, not bounded |
| Episode `.pkl` files carry no timestamp or iteration metadata | Hard to correlate with training progress |
| `pickle` format | Arbitrary code execution on load; prefer `npz` / `parquet` / `jsonl` |
| `progress.jsonl` grows without rotation | One line per iteration is small, but nothing bounds it across a long series of resumed runs |

Three things are no longer in this table. Logging itself: output is levelled, attributable,
switchable and now durable, written to a rotating file per process as well as stdout (§1.3, §1.9),
and the `g_store` dead code is gone (§1.4). The absence of a per-iteration training history:
`progress.jsonl` is that machine-readable record (§1.6). And the run log does not re-create the
unbounded-growth problem it would otherwise have added — `file_max_bytes` and `file_backup_count`
bound it.

---

## 4. Recommended additions

Done, and no longer on this list: `logging` in place of `print`; raising on a NAV conservation
violation with a `nav_conservation_error` metric; writing each iteration's result dict to
`progress.jsonl` (§1.6); and logging `vf_explained_var` per trainable module with a CI assertion
behind it (§2.1).

```python
# in on_train_result / on_episode_end
metrics_logger.log_value("champions_promoted", self.champion_count, window=1)
metrics_logger.log_value("mean_agent_drawdown", dd, window=10)
metrics_logger.log_value("pass_action_fraction", n_pass / n_actions, window=10)
metrics_logger.log_value("vf_explained_var", ...,  window=1)
```

Highest-value additions, in order:

1. **Log reward sub-components** into `metrics_logger` from `on_episode_step` / `on_episode_end`.
2. **Log per-agent final account state** — NAV, position, drawdown, VWAP — at episode end.
3. **Log the do-nothing action fraction and the order rejection rate**, so passivity collapse and
   blind modify/cancel actions become measurable.
4. **Export market price and spread** into the info dict — already in env state, just not
   surfaced.
5. **Per-episode desk metrics** (Sharpe, max drawdown, turnover, maker ratio, inventory) through
   `metrics_logger`, so they land in TensorBoard alongside returns. The `on_episode_end` hook
   already has everything it needs. See
   [13_perspective_financial_trader.md](13_perspective_financial_trader.md) §7.
