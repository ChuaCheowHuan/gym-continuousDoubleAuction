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

### 1.2 RLlib `metrics_logger` custom metrics (per training iteration)

**Where:** `on_train_result`.

| Metric | Value | Window |
|---|---|---|
| `league_size` | `num_trainable + num_random + champion_count` | 1 |
| `league_mean_return` | Mean module return across the league | 10 |
| `league_std_return` | Std dev of module returns | 10 |

**Three metrics** is the entirety of what reaches RLlib's structured logger, alongside RLlib's
own built-ins.

### 1.3 Logging (stdout, filterable)

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

Two properties this buys that `print` could not:

* **Worker attribution.** The format carries the pid, so with `num_env_runners > 0` the
  interleaved episode hooks are separable by process. Previously eight workers wrote
  indistinguishable text into one stream.
* **An off switch.** `cda_log_level` in `train_config.json` (or `$CDA_LOG_LEVEL`, or
  `--log-level` on the random runner) sets the level. Remote EnvRunners are separate interpreters
  that never run `main()`, so `configure()` exports the level into the environment and each
  worker's first `get_logger` call picks it up.

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
    metrics_logger.log_value("nav_conservation_error", abs(error), window=1)
if not conserved:
    logger.error(message)
    if self.strict_nav_check:
        raise AssertionError(message)
```

* The **metric goes out either way**, so a run has a series to inspect rather than only the moment
  it broke. `window=1` keeps it per-iteration: an error in one episode out of many must not be
  averaged away.
* **`strict_nav_check` defaults to true.** A conservation break means the ledger is corrupt and
  every reward computed from NAV afterwards is meaningless, so the run stops. Set it false in
  `train_config.json`, or pass `--no-strict-nav-check`, for a run that would rather finish and be
  inspected afterwards; the ERROR log and the metric still happen.
* **`nav_tolerance`** (default `1e-6`) absorbs the `float()` round trip through the info dict
  (§2.6), nothing larger. Widen it only for a change that legitimately removes cash from the
  system, such as fees - see [13_perspective_financial_trader.md](13_perspective_financial_trader.md)
  §4.

Covered by `test_nav_callback.py` (6 tests): conservation passes and logs a zero error, a
violation raises under the default, the metric is emitted before the raise, non-strict logs ERROR
and continues, the tolerance admits what is inside it and not what is outside, and both knobs come
from the config file.

---

## 2. What is not logged but should be

### 2.1 Training metrics

| Missing | Why it matters |
|---|---|
| **`vf_explained_var`** | The one metric that exposes the frozen critic (S1-1). Nothing surfaces it, which is why the defect survived. |
| `vf_loss` vs `vf_loss_unclipped` | The saturation is invisible from `total_loss` alone |
| Per-policy reward mean / min / max / std | Only league aggregates are logged; individual trends are invisible |
| Policy win rate versus random and versus champion | The key signal for league-based training |
| Loss values (policy, value, entropy) | Fundamental for diagnosing learning pathologies |
| KL divergence / clip fraction | Detects excessively large policy updates |
| Iteration wall-clock time, sample throughput | Throughput analysis and scaling decisions |

### 2.2 Environment and market data

| Missing | Why it matters |
|---|---|
| Last traded price per step | The central price signal; needed to reconstruct the price series |
| Bid-ask spread | Key market-quality metric |
| Order book depth per level | Liquidity analysis |
| Market / limit / modify / cancel action counts per episode | Reveals strategy evolution |
| Count of `category=0` (do-nothing) actions | **Directly detects the passivity collapse predicted by S1-3** |
| Order rejection / no-op rate | Signals cash constraints or blind modify/cancel actions ([04](04_accounting.md) §3) |

### 2.3 Agent and account state

| Missing | Why it matters |
|---|---|
| Per-agent drawdown, current and max | The reward uses `max_nav − nav` but never logs it |
| Per-agent `net_position` at episode end | Reveals held inventory risk |
| Per-agent `VWAP` | Average fill quality |
| Per-agent `cash_on_hold` | How much capital is locked in open orders |
| `order_step_placed`, `num_passive_fills_step` | Reward sub-components computed, consumed, then zeroed |
| Passive fill ratio | Distinguishes market-making from taking |

### 2.4 Reward decomposition

None of the five terms is logged individually — `nav_term`, order penalty, trade penalty,
drawdown penalty, passive bonus. The largest reward driver is invisible, and there is no way to
detect over- or under-trading, risk-aversion learning, or market-making uptake from the logs. It
also makes the tuning guidance in [07_reward_function.md](07_reward_function.md) §6.4
unmeasurable without adding instrumentation first.

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
| No per-iteration training history on disk | `algo.train()` runs outside `tune.Tuner`, so nothing writes `progress.csv` or TensorBoard events; each result dict is logged in summary and dropped |

Logging itself is no longer in this table: output is levelled, attributable and switchable, and
the `g_store` dead code is gone (§1.3, §1.4). What is still missing is a *machine-readable* record
of training progress - see §4.

---

## 4. Recommended additions

Done, and no longer on this list: `logging` in place of `print`, and raising on a NAV conservation
violation with a `nav_conservation_error` metric.

```python
# in on_train_result / on_episode_end
metrics_logger.log_value("champions_promoted", self.champion_count, window=1)
metrics_logger.log_value("mean_agent_drawdown", dd, window=10)
metrics_logger.log_value("pass_action_fraction", n_pass / n_actions, window=10)
metrics_logger.log_value("vf_explained_var", ...,  window=1)
```

Highest-value additions, in order:

1. **Write each iteration's result dict to `results/progress.jsonl`**, so a run leaves a queryable
   history behind without adopting `tune.Tuner`.
2. **Log `vf_explained_var`** and assert on it in CI — it is the one metric that would have
   caught S1-1.
3. **Log reward sub-components** into `metrics_logger` from `on_episode_step` / `on_episode_end`.
4. **Log per-agent final account state** — NAV, position, drawdown, VWAP — at episode end.
5. **Log the do-nothing action fraction and the order rejection rate**, so passivity collapse and
   blind modify/cancel actions become measurable.
6. **Export market price and spread** into the info dict — already in env state, just not
   surfaced.
7. **Per-episode desk metrics** (Sharpe, max drawdown, turnover, maker ratio, inventory) through
   `metrics_logger`, so they land in TensorBoard alongside returns. The `on_episode_end` hook
   already has everything it needs. See
   [13_perspective_financial_trader.md](13_perspective_financial_trader.md) §7.
