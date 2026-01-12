# Reward Function Refinement

## Objective
Refine the reward function for the `gym-continuousDoubleAuction` environment to encourage specific agent behaviors:
1.  **Maximize Net Asset Value (NAV)**: Primary growth objective.
2.  **Minimize Over-trading**: Per-step penalties for trade executions.
3.  **High Selectivity**: Penalties for entering the market (Market/Limit orders), making "holding" the default best action unless conviction is high.
4.  **Risk Management**: Penalties for drawdowns (distance from peak NAV) and asymmetric loss aversion.
5.  **Liquidity Provision**: Bonuses for passive fills (resting limit orders) to encourage capturing the bid-ask spread.

## Refined Reward Formula

The new reward calculation in `reward_helper.py` follows this multi-factor approach:

```python
# Term 1: Loss-Aware NAV Change
# nav_term = nav_change * (1.5 if nav_change < 0 else 1.0)

# Term 2: Selectivity/Activity Friction
# order_penalty = -0.1 (if Market/Limit order was placed)

# Term 3: Execution Cost
# trade_penalty = -0.05 * num_trades_in_step

# Term 4: Risk/Drawdown Penalty
# drawdown_penalty = -0.2 * (peak_nav - current_nav)

# Term 5: Liquidity Bonus
# passive_bonus = +0.1 * num_passive_fills_in_step

reward = nav_term - order_penalty - trade_penalty - drawdown_penalty + passive_bonus
```

## Architectural Changes

### 1. Account Class Improvements (`account.py`)
Added new per-step and high-water mark metrics:
- `max_nav`: Tracks the historical peak NAV to calculate drawdowns.
- `num_trades_step`: Counts actual fill events within a single environment step.
- `num_passive_fills_step`: Counts when the agent was the `counter_party` (passive execution).
- `order_step_placed`: A flag (0 or 1) indicating if a new Market or Limit order was approved.

### 2. High-Water Mark Logic (`calculate.py`)
The `cal_nav` method now automatically updates `max_nav` whenever a new peak is reached.

### 3. Selectivity Enforcement (`trader.py`)
In `place_order`, the `order_step_placed` flag is set only for `market` and `limit` types. `modify` and `cancel` actions are cost-free, allowing the agent to manage risk without penalty.

### 4. Per-Step Reset Logic (`exchg_helper.py`)
Per-step metrics (`num_trades_step`, `num_passive_fills_step`, `order_step_placed`) are reset to 0 at the end of each environment step after rewards are calculated.

## Verification & Testing

### New Unit Test: `test_reward_logic.py`
A comprehensive suite was created to verify each component:
- **`test_max_nav_high_water_mark`**: Ensures the peak NAV is properly maintained through gains and losses.
- **`test_trade_and_passive_counters`**: Validates the counting of aggressive vs. passive fills.
- **`test_reward_formula_components`**: Exercises the full multi-factor formula with a known scenario.
- **`test_asymmetric_loss_reward`**: Confirms that losses are penalized more heavily than gains.

Run tests using:
```bash
python gym_continuousDoubleAuction/test/test_reward_logic.py
```
