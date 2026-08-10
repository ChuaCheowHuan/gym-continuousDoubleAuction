# Logging and Observability

An audit of what training actually records, where it goes, and what is computed but never surfaced.

Related: [self_play_league.md](self_play_league.md) (the callback that does most of the logging),
[known_issues.md](known_issues.md) §3.9 (unbounded disk writes).

---

## 1. What is currently logged

### 1.1 Per-step episode data (persisted)

**Where:** [`league_based_self_play_callback.py`](../train/callbk/league_based_self_play_callback.py)
— `on_episode_step` accumulates into `self.store` (a list of dicts); `on_episode_end` serialises the
lot to `episode_data/<episode_id>.pkl`.

| Field | Source |
|---|---|
| `episode_id` | `episode.id_` |
| `obs` | `episode.get_observations(-1)` |
| `act` | `episode.get_actions(-1)` |
| `reward` | `episode.get_rewards(-1)` |
| `info` | `episode.get_infos(-1)` — carries `reward`, `NAV`, `num_trades` per agent |

### 1.2 RLlib `metrics_logger` custom metrics (per training iteration)

**Where:** the same callback, in `on_train_result`.

| Metric | Value | Window |
|---|---|---|
| `league_size` | Number of active policies | 1 |
| `league_mean_return` | Mean policy return across the league | 10 |
| `league_std_return` | Std dev of policy returns | 10 |

**Three metrics** is the entirety of what reaches RLlib's structured logger.

### 1.3 Console printing (ephemeral — stdout only)

| What | Where |
|---|---|
| Episode start and per-agent policy mapping | `on_episode_start` |
| NAV verification (total versus initial cash) at episode end | `on_episode_end` |
| Iteration league stats: mean, std, threshold, per-policy returns | `on_train_result` |
| Champion creation and removal events | `_create_champion_snapshot_from_policy`, `_remove_oldest_champion` |
| Per-step render: actions, rewards, terminateds, infos, LOB state, trades, accounts | `continuousDoubleAuction_env._render()` |
| Mark-to-market profit per trader per step | `exchg_helper.print_mark_to_mkt` |
| Full account table per step | `exchg_helper.print_accs` |
| Total system profit and NAV per step | `_render()` |

None of this is persisted or queryable. If stdout is not captured, it is gone.

### 1.4 Legacy Ray actor storage (`g_store`) — dead code

[`log_handler.py`](../train/logger/log_handler.py) and
[`store_handler.py`](../train/storage/store_handler.py) define a Ray remote actor plus functions to
serialise it to gzipped JSON. The schema supports `obs`, `act`, `reward`, `NAV`, `num_trades` per
step and `policy_reward`, `reward`, `NAV`, `num_trades` per episode.

**No active call site populates or reads it.** It is leftover architecture from an earlier design.

---

## 2. What is not logged but should be

### 2.1 Training metrics

| Missing | Why it matters |
|---|---|
| Per-policy reward mean / min / max / std | Only league aggregates are logged; individual policy trends are invisible |
| Policy win rate versus random and versus champion | The key signal for league-based training |
| Loss values (policy, value, entropy) | Fundamental for diagnosing learning pathologies |
| KL divergence / clip fraction (PPO) | Detects excessively large policy updates |
| Iteration wall-clock time | Throughput analysis |
| Sample throughput (steps/sec) | Scaling decisions |

### 2.2 Environment and market data

| Missing | Why it matters |
|---|---|
| Last traded price per step | The central price signal; needed to reconstruct the price series |
| Bid-ask spread | Key market-quality metric |
| Order book depth per level | Liquidity analysis |
| Market / limit / cancel action counts per episode | Action-type distribution reveals strategy evolution |
| Count of `None` (do-nothing) actions | Detects degenerate policies that stop trading |
| Order rejection rate | Signals cash constraints or degenerate NAV |

### 2.3 Agent and account state

| Missing | Why it matters |
|---|---|
| Per-agent drawdown, current and max | The reward uses `max_nav − nav` but never logs it |
| Per-agent `net_position` at episode end | Reveals held inventory risk |
| Per-agent `VWAP` | Average fill quality |
| Per-agent `cash_on_hold` | How much capital is locked in open orders |
| `order_step_placed`, `num_passive_fills_step` | Reward sub-components computed but never persisted |
| Passive fill ratio | Distinguishes market-making from taking |

### 2.4 Reward decomposition

None of the five terms in [reward_function.md](reward_function.md) §2 is logged individually —
`nav_term`, order penalty, trade penalty, drawdown penalty, passive bonus. The largest reward driver
is invisible, and there is no way to detect over- or under-trading, risk-aversion learning, or
market-making uptake from the logs.

### 2.5 League and self-play state

| Missing | Why it matters |
|---|---|
| Champion matchup history (who played whom) | Needed to verify league diversity |
| Per-champion win rate over time | Without it, champion pool management is blind |
| Time since last champion snapshot | Already computed in `_should_create_champion`, never logged |
| `available_modules` per iteration | Debugging matchmaking |

---

## 3. Persistence problems

| Issue | Impact |
|---|---|
| Per-episode `.pkl` files grow unboundedly | Disk fills over long runs; no rotation, no size cap, no flag |
| No structured logging (Python `logging` or TensorBoard) for most output | Console output is lost unless stdout is captured |
| Episode `.pkl` files carry no timestamp or iteration metadata | Impossible to correlate with training progress |
| `g_store` gzip logging is dead code | Architecture with no value |
| `episode_data/` is not in `.gitignore` | Untracked noise after every run, including test runs |

---

## 4. Summary and priorities

The codebase does log during training, but coverage is thin and fragmented: **three** metrics reach
RLlib's structured logger; episode obs/act/reward/info reaches `.pkl` files; a large amount of rich
data computed inside the env and accounts never surfaces anywhere; and `print` statements dominate,
producing nothing queryable.

Highest-value additions, in order:

1. **Log reward sub-components** into `metrics_logger` from `on_episode_step` / `on_episode_end`.
2. **Log per-agent final account state** — NAV, position, drawdown, VWAP — at episode end.
3. **Log per-policy win rate and action-type distribution.**
4. **Export market price and spread** into the info dict — already in env state, just not surfaced.
