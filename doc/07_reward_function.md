# 7. Reward Function

The five-term formula, the account plumbing that feeds it, its measured decomposition, and how to
tune it.

Related: [04_accounting.md](04_accounting.md) (where the inputs come from),
[12_perspective_rl_researcher.md](12_perspective_rl_researcher.md) §3 (the analysis),
[10_testing.md](10_testing.md) §5.

---

## 1. Stated objectives

From the function's own docstring
([`reward_helper.py:10-21`](../gym_continuousDoubleAuction/envs/exchg/reward_helper.py#L10-L21)),
the reward is shaped to encourage five behaviours:

1. **Maximize NAV** — the primary growth objective.
2. **Reduce the number of trades** — a per-fill penalty on execution.
3. **Selective order placement** — a penalty for entering the market at all, making "hold" the
   default best action unless conviction is high.
4. **Lower drawdown risk** — a drawdown penalty plus asymmetric loss aversion.
5. **Capture spread** — a bonus for passive fills, to encourage liquidity provision.

The intent is sound and reads like it was written by someone who trades. §5 shows how much of it
actually binds.

---

## 2. The formula

From
[`reward_helper.py:45-68`](../gym_continuousDoubleAuction/envs/exchg/reward_helper.py#L45-L68).
The five coefficients are `env_config` keys, set on the helper in
[`reward_helper.py:6-25`](../gym_continuousDoubleAuction/envs/exchg/reward_helper.py#L6-L25) —
see [18_configuration.md](18_configuration.md) §2.2:

```python
nav_change = float(trader.acc.nav - trader.acc.prev_nav)

# Set from the env config; the values below are the defaults.
order_penalty    = self.order_penalty      # 0.1
trade_penalty    = self.trade_penalty      # 0.05
drawdown_penalty = self.drawdown_penalty   # 0.2
passive_bonus    = self.passive_bonus      # 0.1
loss_multiplier  = self.loss_multiplier    # 1.5

# 1. Asymmetric loss aversion
nav_term = nav_change * (loss_multiplier if nav_change < 0 else 1.0)

# 2. Distance from peak NAV
current_drawdown = float(max(0, trader.acc.max_nav - trader.acc.nav))

# 3. Comprehensive reward formula
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

The five coefficients are **function-local literals**, not configuration — with a code comment
acknowledging they "can be moved to config". For a research repository, reward-shaping
coefficients are the primary experimental axis and should live in `env_config` so they are
captured in checkpoints and sweepable by Tune.

> **The reward is not zero-sum.** NAV *is* conserved across traders, but the four shaping terms
> are not, so returns are not comparable across policies playing different roles. The league
> callback nevertheless ranks policies against a pooled `mean + k·std` that includes the random
> baselines. A policy can clear that threshold by trading *less*, not by trading *better* — see
> [12_perspective_rl_researcher.md](12_perspective_rl_researcher.md) §3.2.

---

## 3. Account plumbing

The formula needs per-step and high-water-mark state that the account did not originally track.

**[`account.py`](../gym_continuousDoubleAuction/envs/account/account.py)** — added:

- `max_nav` — historical peak NAV, for the drawdown term.
- `num_trades_step` — fill events within one environment step.
- `num_passive_fills_step` — fills where the agent was the passive `counter_party`.
- `order_step_placed` — flag (0/1), set when a new market or limit order is approved.

**[`calculate.py`](../gym_continuousDoubleAuction/envs/account/calculate.py)** — `cal_nav`
updates `max_nav` automatically whenever a new peak is reached.

**[`trader.py`](../gym_continuousDoubleAuction/envs/agent/trader.py)** — in `place_order`,
`order_step_placed` is set **only** for `market` and `limit` types. `modify` and `cancel` are
cost-free, so an agent can manage risk without being penalised for it.

**[`exchg_helper.py`](../gym_continuousDoubleAuction/envs/exchg/exchg_helper.py)** — the three
per-step counters are reset to 0 at the end of each step, *after* rewards are computed. That
ordering is correct and easy to break.

---

## 4. Measured behaviour

**[verified]** — 4 agents, `init_cash = 1,000,000`, 300 steps of uniformly random actions, with
the reward re-derived per step from account state:

```
--- reward decomposition, summed over 4 agents x 300 steps ---
  nav_term      -174,502
  drawdown      -416,473
  order / trade / passive terms          O(0.1)/step — negligible

per-step reward min/mean/max: -10,948.8 / -492.5 / 6,125.8
episode return per agent:  -104,683 / -81,466 / -244,468 / -160,410
sum of all agents' returns: -591,027

  total NAV: 4,000,000.00   expected: 4,000,000.00
```

and, with every agent playing `category = 0` on every step:

```
all-agents-pass total return over 300 steps x 4 agents = 0.0
```

Three conclusions follow directly.

### 4.1 The drawdown term is a level, not a delta

`max_nav` is monotone non-decreasing within an episode, so a drawdown opened at step 50 is
charged **every step until NAV recovers past the old peak**. Measured, it is ~2.4× the entire
(already negative) NAV term. At `max_step = 4096`, a 1,000-unit drawdown incurred early costs
`0.2 × 1000 × ~4000 ≈ 800,000` — three orders of magnitude more than the NAV move that caused it.

Three problems: (a) it is not potential-based, so it changes the optimal policy rather than only
shaping it; (b) its magnitude scales with episode length, so `max_step` silently becomes a
risk-aversion hyper-parameter; (c) it is non-Markov in the agent's observation, because `max_nav`
is a path functional the agent cannot see.

**Fix.** Charge the *increment*, which is potential-based and telescoping:

```python
new_dd = max(0, max_nav - nav)
reward += -drawdown_penalty * max(0.0, new_dd - prev_dd)   # penalise deepening only
```

### 4.2 The micro-terms are numerically irrelevant

`order_penalty = 0.1`, `trade_penalty = 0.05`, `passive_bonus = 0.1` sit against a NAV term whose
per-step magnitude is in the range −10,949 … +6,126. They are 5–6 orders of magnitude too small
to influence behaviour. Whatever economic intent they encode is simply not being expressed.

### 4.3 Doing nothing is a dominant strategy

Passing every step yields **exactly zero**, versus −591,027 for random trading. With no position
there is no mark-to-market change; with no orders there is no order penalty; with no fills there
is no trade penalty; NAV never falls below `max_nav`, so there is no drawdown.

Trading is therefore **strictly dominated unless an agent can extract more than its penalty
budget from the others** — and because the market is zero-sum in NAV, the population as a whole
never can. `(pass, …, pass)` is a Nash equilibrium that is also the *joint-optimal* outcome under
this reward, and it is reachable by pure gradient descent from a random start: the fastest way to
raise return early in training is to stop trading. Empty-market collapse is the most likely
training outcome as configured. Tracked as S1-3.

---

## 5. Stated objectives versus realised ones

| Stated objective | Achieved? |
|---|---|
| "Maximizing NAV" | Yes — `nav_change` is the dominant signed term |
| "Reducing number of trades" | No — the 0.05 penalty is ~10⁵× too small |
| "Selective order placement" | No — same, the 0.1 penalty |
| "Lowering drawdown risk" | **Over-achieved** — the penalty is ~2× the entire NAV term **[verified]** and drives the policy to inaction |
| "Capturing spread" | No — the 0.1 passive bonus is negligible, and with zero fees there are no spread economics to capture |

The implementation collapses to "NAV change, minus an enormous drawdown tax". Putting every term
on a common scale — fractional-NAV units — would make the stated objective the realised one.

---

## 6. Tuning guide

Objective values for these scalars come from aligning them with the environment's financial scale
(tick size, order size, initial cash).

### 6.1 Conviction threshold — `order_penalty`

Defines the minimum expected profit required to justify moving at all.

```
order_penalty ≈ Avg_Expected_Profit_Per_Share × Min_Trade_Size
```

If an agent should only enter for a 2-tick move on 10 shares at a 0.01 tick:
`0.01 × 2 × 10 = 0.20`.

Recommended range: **0.01% – 0.1% of the average capital deployed per trade**.

### 6.2 Loss aversion — `loss_multiplier`

Prospect theory puts human loss aversion at roughly 2×.

| Setting | Value |
|---|---|
| Conservative | 1.5 (current) |
| Standard | 2.0 |

Multipliers above 1.0 create a gravity toward neutral positions, discouraging high-variance
gambling. Note the interaction with §4.3: because NAV is conserved across the population, any
multiplier above 1.0 makes the *summed* reward strictly negative, which is part of what makes
passivity dominant. Reducing it toward 1.0 is one of the levers for fixing S1-3.

### 6.3 Drawdown matching

Scale `drawdown_penalty` so that a deep drawdown (say 5%) exerts negative pressure equivalent to
several steps of normal profit:

1. Estimate `Avg_Profit_Per_Step`.
2. Set the coefficient so `Penalty(5% drawdown) ≈ 2 × Avg_Profit_Per_Step`.

**Warning:** set too high, the agent becomes catatonic the moment a drawdown begins — which is
the current state. Fix the level-versus-delta problem (§4.1) *before* tuning the coefficient;
otherwise you are tuning a term whose magnitude depends on `max_step`.

### 6.4 Component balance

During training, monitor each term's contribution to total reward variance. A healthy split:

| Component | Target share of variance |
|---|---|
| NAV change | ~70% |
| Penalties | ~20% |
| Bonuses | ~10% |

All five terms are now logged individually, in `info["reward_terms"]`, as signed contributions
that sum exactly to the reward — see
[11_logging_and_observability.md](11_logging_and_observability.md) §1.7. The split above is
therefore measurable from the per-step record; computing the variance share per episode is a
reduction over that record, not a further instrumentation problem.

### 6.5 Make coefficients scale-invariant

Instead of hardcoding `0.1`, use a relative value such as `0.0001 * trader.acc.init_nav`.
Hyperparameters then stay meaningful regardless of the absolute cash level of the simulation.

Better still, **normalise the whole reward by `init_cash`** so rewards are O(10⁻³) and returns
are O(1). That single change fixes three separate problems at once:

- the frozen critic (S1-1) — value targets come back inside `vf_clip_param`;
- the drawdown scaling (S2-1);
- the micro-term irrelevance (S2-3).

It is the highest-leverage change in the repository. See
[12_perspective_rl_researcher.md](12_perspective_rl_researcher.md) §4.
