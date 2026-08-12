# 11. Logging and Observability

An audit of what training actually records, where it goes, and the substantial gap between what
is computed and what is surfaced.

Related: [08_self_play_league.md](08_self_play_league.md) (the callback that does most of the
logging), [09_distributed_training.md](09_distributed_training.md) (what changes with multiple
workers), [14_perspective_ai_engineer.md](14_perspective_ai_engineer.md) §5.4.

**Headline: this is the weakest engineering area in the repository.** There is no logging
framework at all — **[verified]** zero `import logging` anywhere — and roughly 86 `print()` calls
in `envs/` and `train/`, 42 of them in the self-play callback alone.

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
  is ever shared. Two `.pkl` fixtures are committed under `episode_data/`.

### 1.2 RLlib `metrics_logger` custom metrics (per training iteration)

**Where:** `on_train_result`.

| Metric | Value | Window |
|---|---|---|
| `league_size` | `num_trainable + num_random + champion_count` | 1 |
| `league_mean_return` | Mean module return across the league | 10 |
| `league_std_return` | Std dev of module returns | 10 |

**Three metrics** is the entirety of what reaches RLlib's structured logger, alongside RLlib's
own built-ins.

### 1.3 Console printing (ephemeral — stdout only)

| What | Where |
|---|---|
| Episode start + per-agent policy map (3+ lines per episode) | `on_episode_start` |
| `DEBUG:` lines for env type, runner type, `init_cash`, `num_agents`, `total_initial_cash` | `on_episode_end` |
| Full per-agent NAV table + verification verdict | `on_episode_end` |
| Iteration league stats: mean, std, threshold, per-module returns | `on_train_result` |
| Champion creation and removal banners | `_create_champion_snapshot_from_policy`, `_remove_oldest_champion` |
| Module inventory at build time | `create_multi_agent_config` |
| Per-step render: actions, rewards, terminateds, infos, LOB state, trades, accounts | `continuousDoubleAuction_env._render()` |
| Mark-to-market profit per trader per step | `exchg_helper.print_mark_to_mkt` |
| Full account table per step | `exchg_helper.print_accs` |
| Total system profit and NAV per step | `_render()` |

None of this is persisted or queryable. If stdout is not captured, it is gone.

With `num_env_runners > 0`, **every remote worker prints all of the episode hooks
independently** — no level filtering, no worker attribution, and no way to turn it off short of
editing the source. At 4 episodes/iteration × 8 workers that is a lot of interleaved stdout.

`env.render()` defaults to **`is_render=True`** on the env itself. `TrainConfig` overrides it to
`False`, but any direct `continuousDoubleAuctionEnv({...})` gets a full ASCII dump — book, tape,
every account — on every step, built through pandas DataFrames.

### 1.4 Legacy Ray actor storage (`g_store`) — dead code

[`train/storage/store_handler.py`](../gym_continuousDoubleAuction/train/storage/store_handler.py)
defines a Ray remote actor intended as a global metric store;
[`train/logger/log_handler.py`](../gym_continuousDoubleAuction/train/logger/log_handler.py) and
[`train/plotter/plot_handler.py`](../gym_continuousDoubleAuction/train/plotter/plot_handler.py)
call `ray.util.get_actor("g_store")` and serialise to gzipped JSON. The schema supports `obs`,
`act`, `reward`, `NAV`, `num_trades` per step and `policy_reward`, `reward`, `NAV`, `num_trades`
per episode.

**[verified]** — the detached actor is **never created anywhere**. `g_store` appears only inside
`log_handler.py` and `plot_handler.py`, both as `get_actor` lookups that would raise at call
time. Roughly 270 LOC that *looks* like a working telemetry pipeline and is a broken one.

Either revive it with a
`storage.options(name="g_store", lifetime="detached").remote(n)` call somewhere, or delete all
three modules.

### 1.5 The NAV conservation check

A good idea implemented as a print:

```python
if abs(total_nav - total_initial_cash) < 1e-6:
    print("  Verification: SUCCESS (Total NAV matches initial cash)")
else:
    print(f"  Verification: FAILED (Difference: {total_nav - total_initial_cash:,.2f})")
```

A conservation violation is a **hard invariant break** — it means the ledger is corrupt. It
should raise, or at minimum log at ERROR and emit a counter metric, not print `FAILED` into a
stream nobody reads.

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
| No structured logging for most output | Console output is lost unless stdout is captured |
| Episode `.pkl` files carry no timestamp or iteration metadata | Hard to correlate with training progress |
| `g_store` gzip logging is dead code | ~270 LOC of architecture with no value |
| `pickle` format | Arbitrary code execution on load; prefer `npz` / `parquet` / `jsonl` |

---

## 4. Recommended minimum

```python
import logging
logger = logging.getLogger(__name__)          # replace all print()

# in on_train_result / on_episode_end
metrics_logger.log_value("nav_conservation_error", err, window=1)
metrics_logger.log_value("champions_promoted", self.champion_count, window=1)
metrics_logger.log_value("mean_agent_drawdown", dd, window=10)
metrics_logger.log_value("pass_action_fraction", n_pass / n_actions, window=10)
metrics_logger.log_value("vf_explained_var", ...,  window=1)
```

Highest-value additions, in order:

1. **Replace `print` with `logging`**, so multi-worker runs become filterable, attributable and
   switchable off.
2. **Raise (or emit an ERROR metric) on a NAV conservation violation** rather than printing
   `FAILED`.
3. **Log `vf_explained_var`** and assert on it in CI — it is the one metric that would have
   caught S1-1.
4. **Log reward sub-components** into `metrics_logger` from `on_episode_step` / `on_episode_end`.
5. **Log per-agent final account state** — NAV, position, drawdown, VWAP — at episode end.
6. **Log the do-nothing action fraction and the order rejection rate**, so passivity collapse and
   blind modify/cancel actions become measurable.
7. **Export market price and spread** into the info dict — already in env state, just not
   surfaced.
8. **Per-episode desk metrics** (Sharpe, max drawdown, turnover, maker ratio, inventory) through
   `metrics_logger`, so they land in TensorBoard alongside returns. The `on_episode_end` hook
   already has everything it needs. See
   [13_perspective_financial_trader.md](13_perspective_financial_trader.md) §7.
