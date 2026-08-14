# Reward Function

The multi-factor reward, the account plumbing that feeds it, and how to tune its coefficients.

Related: [accounting.md](accounting.md) (where the inputs come from), [testing.md](testing.md) §5,
[known_issues.md](known_issues.md) §2.1–2.2 (two structural defects in this formula).

---

## 1. Objectives

The reward is shaped to encourage five behaviours:

1. **Maximize NAV** — the primary growth objective.
2. **Minimize over-trading** — per-step penalty on executions.
3. **High selectivity** — a penalty for entering the market at all, making "hold" the default best
   action unless conviction is high.
4. **Risk management** — drawdown penalty plus asymmetric loss aversion.
5. **Liquidity provision** — a bonus for passive fills, to encourage capturing the spread.

---

## 2. The formula

From [`reward_helper.py`](../envs/exchg/reward_helper.py):

```python
nav_change = float(trader.acc.nav - trader.acc.prev_nav)

order_penalty    = 0.1
trade_penalty    = 0.05
drawdown_penalty = 0.2
passive_bonus    = 0.1
loss_multiplier  = 1.5

# Asymmetric loss aversion
nav_term = nav_change * (loss_multiplier if nav_change < 0 else 1.0)

# Distance from peak NAV
current_drawdown = float(max(0, trader.acc.max_nav - trader.acc.nav))

reward = (nav_term
          - order_penalty    * trader.acc.order_step_placed
          - trade_penalty    * trader.acc.num_trades_step
          - drawdown_penalty * current_drawdown
          + passive_bonus    * trader.acc.num_passive_fills_step)
```

| Term | Sign | Driven by |
|---|---|---|
| `nav_term` | ± | NAV change, scaled 1.5× when negative |
| Order penalty | − | `order_step_placed` — 1 if a market or limit order was approved this step |
| Trade penalty | − | `num_trades_step` — actual fill events this step |
| Drawdown penalty | − | `max_nav - nav`, the *current* distance from the high-water mark |
| Passive bonus | + | `num_passive_fills_step` — fills where this agent was the `counter_party` |

The coefficients are internal defaults and are not currently configurable.

> **The reward is not zero-sum.** NAV *is* conserved across traders, but the four shaping terms are
> not, so returns are not comparable across policies playing different roles. The league callback
> nevertheless ranks policies against a pooled threshold — see
> [known_issues.md](known_issues.md) §1.3.

---

## 3. Account plumbing

The formula needs per-step and high-water-mark state that the account did not originally track.

**[`account.py`](../envs/account/account.py)** — added:

- `max_nav` — historical peak NAV, for the drawdown term.
- `num_trades_step` — fill events within one environment step.
- `num_passive_fills_step` — fills where the agent was the passive `counter_party`.
- `order_step_placed` — flag (0/1), set when a new market or limit order is approved.

**[`calculate.py`](../envs/account/calculate.py)** — `cal_nav` updates `max_nav` automatically
whenever a new peak is reached.

**[`trader.py`](../envs/agent/trader.py)** — in `place_order`, `order_step_placed` is set **only**
for `market` and `limit` types. `modify` and `cancel` are cost-free, so an agent can manage risk
without being penalised for it.

**[`exchg_helper.py`](../envs/exchg/exchg_helper.py)** — the three per-step counters are reset to 0
at the end of each step, *after* rewards are computed.

---

## 4. Tuning guide

Objective values for these scalars come from aligning them with the environment's financial scale
(tick size, order size, initial cash).

### 4.1 Conviction threshold — `order_penalty`

Defines the minimum expected profit required to justify moving at all.

```
order_penalty ≈ Avg_Expected_Profit_Per_Share × Min_Trade_Size
```

If an agent should only enter for a 2-tick move on 10 shares at a 0.01 tick:
`0.01 × 2 × 10 = 0.20`.

Recommended range: **0.01% – 0.1% of the average capital deployed per trade**.

### 4.2 Loss aversion — `loss_multiplier`

Prospect theory puts human loss aversion at roughly 2×.

| Setting | Value |
|---|---|
| Conservative | 1.5 (current) |
| Standard | 2.0 |

Multipliers above 1.0 create a gravity toward neutral positions, discouraging high-variance
gambling.

### 4.3 Drawdown matching

Scale `drawdown_penalty` so that a deep drawdown (say 5%) exerts negative pressure equivalent to
several steps of normal profit:

1. Estimate `Avg_Daily_Profit`.
2. Set the coefficient so `Penalty(5% drawdown) ≈ 2 × Avg_Daily_Profit`.

**Warning:** set too high, the agent becomes catatonic the moment a drawdown begins. This term is
also the one with a structural problem — it charges a *level* every step rather than a *delta*, so
a single drawdown is paid for repeatedly until recovered. See
[known_issues.md](known_issues.md) §2.1.

### 4.4 Component balance

During training, monitor each term's contribution to total reward variance. A healthy split:

| Component | Target share of variance |
|---|---|
| NAV change | ~70% |
| Penalties | ~20% |
| Bonuses | ~10% |

> **Tip — make coefficients scale-invariant.** Instead of hardcoding `0.1`, use a relative value
> such as `0.0001 * trader.acc.init_nav`. Hyperparameters then stay meaningful regardless of the
> absolute cash level of the simulation. With `init_cash = 1e6` the current absolute constants are
> numerically irrelevant against NAV changes of order 1e5–1e6 — *except* the drawdown term, which is
> the one that should not be a level. See [known_issues.md](known_issues.md) §2.2.
