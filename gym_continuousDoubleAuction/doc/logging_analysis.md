# Logging Analysis — gym-continuousDoubleAuction

## What Is Currently Being Logged

### 1. Episode Step Data (Per-step, saved to disk)
**Location**: [`league_based_self_play_callback.py`](file:///c:/Users/User/Documents/Code/gym-continuousDoubleAuction/gym_continuousDoubleAuction/train/callbk/league_based_self_play_callback.py) — `on_episode_step` + `on_episode_end`

Each step is captured into `self.store` (a list of dicts), then serialized as a `.pkl` file in `episode_data/` at episode end.

| Field | Source |
|---|---|
| `episode_id` | `episode.id_` |
| `obs` | `episode.get_observations(-1)` |
| `act` | `episode.get_actions(-1)` |
| `reward` | `episode.get_rewards(-1)` |
| `info` | `episode.get_infos(-1)` — contains `reward`, `NAV`, `num_trades` per agent |

---

### 2. RLlib `metrics_logger` Custom Metrics (Per-training-iteration)
**Location**: [`league_based_self_play_callback.py`](file:///c:/Users/User/Documents/Code/gym-continuousDoubleAuction/gym_continuousDoubleAuction/train/callbk/league_based_self_play_callback.py#L387-L391) — `on_train_result`

| Metric Key | Value | Window |
|---|---|---|
| `league_size` | Number of active policies | 1 |
| `league_mean_return` | Mean policy return across all policies | 10 |
| `league_std_return` | Std dev of policy returns | 10 |

---

### 3. Console Print Logging (Ephemeral — stdout only, not persisted)
**Location**: Multiple files

| What | Where |
|---|---|
| Episode start / policy mapping per agent | `on_episode_start` |
| NAV verification (total vs. initial cash) at episode end | `on_episode_end` |
| Iteration league stats: mean, std, threshold, policy returns | `on_train_result` |
| Champion creation / removal events | `_create_champion_snapshot_from_policy`, `_remove_oldest_champion` |
| Per-step render: actions, rewards, terminateds, infos, LOB state, trades, accounts | `continuousDoubleAuction_env._render()` |
| Mark-to-market profit per trader per step | `exchg_helper.print_mark_to_mkt` |
| Full account table per step | `exchg_helper.print_accs` |
| Total system profit & NAV per step | `_render()` |

---

### 4. Legacy Ray Actor Storage (`g_store`) — Appears Unused in Active Code
**Location**: [`log_handler.py`](file:///c:/Users/User/Documents/Code/gym-continuousDoubleAuction/gym_continuousDoubleAuction/train/logger/log_handler.py) + [`store_handler.py`](file:///c:/Users/User/Documents/Code/gym-continuousDoubleAuction/gym_continuousDoubleAuction/train/storage/store_handler.py)

These files define a Ray remote actor (`g_store`) and functions to serialize/deserialize it to gzip'd JSON. The schema supports `obs`, `act`, `reward`, `NAV`, `num_trades` (per step) and `policy_reward`, `reward`, `NAV`, `num_trades` (per episode). However, **no active call site** (in the callback or env) populates or reads this actor — it appears to be leftover from an older architecture.

---

## What's NOT Being Logged (But Should Be)

### Training Metrics (RLlib Level)
| Missing | Rationale |
|---|---|
| Per-policy reward mean/min/max/std | Currently only league aggregates are logged; individual policy performance trends are invisible |
| Policy win rate vs. random / vs. champion | Key signal for league-based training |
| Loss values (policy loss, value loss, entropy) | Fundamental for diagnosing learning pathologies |
| KL divergence / clip fraction (PPO-specific) | Detects excessively large policy updates |
| Training iteration wall-clock time | For throughput analysis |
| Sample throughput (steps/sec) | Critical for scaling decisions |

### Environment / Market Data
| Missing | Rationale |
|---|---|
| Last traded price per episode/step | Central market price signal; needed to reconstruct price series |
| Bid-ask spread (best_bid vs. best_ask) | Key market quality metric |
| Order book depth (volumes at each level) | Needed for liquidity analysis |
| Number of market vs. limit vs. cancel actions per episode | Action-type distribution reveals strategy evolution |
| Number of `None` (do-nothing) actions per episode | Detects degenerate policies that stop trading |
| Order rejection rate (orders not approved) | Signals cash constraints or degenerate NAV |

### Agent / Account Information
| Missing | Rationale |
|---|---|
| Per-agent drawdown (current and max) | The reward function uses `max_nav - nav` but this is never logged |
| Per-agent `net_position` at end of episode | Reveals whether agents are holding open inventory risk |
| Per-agent `VWAP` | Reveals average fill quality |
| Per-agent `cash_on_hold` | Reveals how much capital is locked in open orders |
| Per-agent `order_step_placed`, `num_passive_fills_step` | Reward sub-components are computed but never persisted |
| Passive fill ratio (`num_passive_fills / num_trades`) | Critical for understanding market-making vs. taking behaviour |

### Reward Decomposition
| Missing | Rationale |
|---|---|
| `nav_term` (the core P&L component) | The biggest reward driver is invisible in logs |
| `order_penalty` contribution | Helps detect over/under trading |
| `drawdown_penalty` contribution | Shows risk aversion learning progress |
| `passive_bonus` contribution | Shows market-making incentive uptake |

### League / Self-Play State
| Missing | Rationale |
|---|---|
| Champion matchup history (who played who) | Needed to verify league diversity |
| Per-champion win rate over time | Without this, champion pool management is blind |
| Time since last champion snapshot | Already computed in `_should_create_champion` but not logged |
| `available_modules` at each iteration | Helps debug matchmaking |

### Persistence Gaps
| Issue | Impact |
|---|---|
| `.pkl` files saved per-episode grow unboundedly | Disk fills up over long runs; no rotation or size cap |
| No structured logging (Python `logging` module or TensorBoard) | Console output is lost if stdout isn't captured |
| Episode `.pkl` files have no timestamp or iteration metadata | Impossible to correlate with training progress |
| The `g_store` gzip logging is dead code | Wastes architecture but currently provides no value |

---

## Summary

The codebase **does** log data during training, but the coverage is thin and fragmented:
- **Only 3 metrics** make it into RLlib's structured logger (`league_size`, `league_mean_return`, `league_std_return`)
- **Episode-level** obs/act/reward/info data is saved correctly to `.pkl` files per episode via the callback
- **A large amount of rich data** (drawdown, position, VWAP, action breakdown, reward decomposition, market price series) is computed inside the env and accounts but **never surfaced to any logger**
- **Console `print` statements** dominate — meaningful for interactive debugging but produce no persistent, queryable log

The highest-value additions would be:
1. Log reward sub-components into `metrics_logger` from `on_episode_step` / `on_episode_end`
2. Log per-agent final account state (NAV, position, drawdown, VWAP) at episode end
3. Log per-policy win rate and action-type distribution
4. Add market price / spread logging to the info dict (already in env state, just not exported)
