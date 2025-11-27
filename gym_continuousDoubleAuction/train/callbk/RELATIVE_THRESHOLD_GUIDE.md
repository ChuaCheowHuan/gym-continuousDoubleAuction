# Using MinimalLeagueCallback with Relative Thresholds

## Overview

The `MinimalLeagueCallback` now supports **relative thresholds**, which are specifically designed for zero-sum trading environments where returns are typically **negative**.

## Why Relative Thresholds?

In your continuous double auction trading environment:
- Returns are typically NEGATIVE (due to transaction costs, spreads, etc.)
- Best agents achieve "least negative" returns (e.g., -20)
- Worst agents achieve "very negative" returns (e.g., -180)
- Average might be around -100

Using an absolute threshold like `return_threshold=100.0` would never trigger because no agent reaches positive returns!

## How It Works

### **Relative Threshold Mode** (Recommended)

```python
# Default: Uses relative improvement
callback = MinimalLeagueCallback(relative_improvement=0.15)
```

**Calculation:**
1. Calculate baseline = average return of all trainable agents
2. Calculate threshold based on baseline:
   - For negative returns: `threshold = baseline * (1 - relative_improvement)`
   - For positive returns: `threshold = baseline * (1 + relative_improvement)`

**Example with negative returns:**
```
Iteration 10:
- policy_0 return: -85.2
- policy_1 return: -120.5
- Baseline: (-85.2 + -120.5) / 2 = -102.85
- Threshold (15% improvement): -102.85 * (1 - 0.15) = -87.42
- Check policy_0: -85.2 > -87.42? YES ✓ (added to league)
- Check policy_1: -120.5 > -87.42? NO ✗ (not added)
```

### **Absolute Threshold Mode** (Legacy)

```python
# For positive reward environments only
callback = MinimalLeagueCallback(return_threshold=100.0)
```

Only use this if your returns are consistently positive.

## Usage Examples

### **Basic Usage (Trading Environment)**

```python
from gym_continuousDoubleAuction.train.callbk.minimal_league_callback import MinimalLeagueCallback

# Create callback with relative threshold
league_callback = MinimalLeagueCallback(
    relative_improvement=0.15,  # Require 15% better than average
    check_every_n_iters=5,      # Check every 5 iterations
)

# Configure PPO
config = (
    PPOConfig()
    .environment("continuousDoubleAuction-v0", env_config=env_config)
    .multi_agent(
        policies=policies,
        policy_mapping_fn=policy_mapping_fn,
        policies_to_train=policies_to_train,
    )
    # Use lambda to create callback instance
    .callbacks(lambda: MinimalLeagueCallback(relative_improvement=0.15))
    .framework("torch")
)

algo = config.build()
```

### **Tuning the Threshold**

Adjust `relative_improvement` based on how selective you want league expansion:

```python
# Very selective (only top performers, slow league growth)
callback = MinimalLeagueCallback(relative_improvement=0.25)  # 25% better

# Balanced (recommended starting point)
callback = MinimalLeagueCallback(relative_improvement=0.15)  # 15% better

# Aggressive (frequent snapshots, fast league growth)
callback = MinimalLeagueCallback(relative_improvement=0.05)  # 5% better
```

### **Understanding the Output**

When the callback runs, you'll see detailed output:

```
================================================================================
Iteration 15 - League Evaluation
================================================================================
Agent returns: {'agent_0': -85.23, 'agent_1': -120.47, 'agent_2': -95.12, 'agent_3': -110.88}

--- Relative Threshold Mode ---
Baseline (mean of trainable): -102.85
Required improvement: 15%
Calculated threshold: -87.42
  → Agents must achieve at least 15.43 less loss
  → Example: -87.42 or better (less negative)

--- Policy Evaluation ---
policy_0:   -85.23 | threshold:   -87.42 | diff:   +2.19 (+2.5%) | ✓ EXCEEDS
policy_1:  -120.47 | threshold:   -87.42 | diff:  -33.05 (-37.8%) | ✗ below

  → policy_0 qualifies for league!
  → League opponent 'league_0' created successfully!
  → Current league size: 1
  → Snapshot of policy_0 with return -85.23
  → Policy mapping updated successfully

================================================================================
```

## Interpreting Results

### **For Negative Returns**

When baseline is negative (e.g., -100):
- **Higher (less negative) is better**: -50 > -100 > -150
- **Threshold will be less negative**: -85 (15% better than -100)
- **Agents exceeding threshold**: return > -85 (e.g., -80, -70, -60)

### **Math Explanation**

```
baseline = -100
relative_improvement = 0.15

threshold = baseline * (1 - relative_improvement)
         = -100 * (1 - 0.15)
         = -100 * 0.85
         = -85

Interpretation:
- Agent needs to do 15% better than average
- Average loss is -100
- 15% less loss = -100 + 15 = -85
- Any return > -85 qualifies (less negative = better)
```

## Common Scenarios

### **Scenario 1: Both Agents Improve Together**

```
Iteration 5:
  Baseline: -150 → Threshold: -127.5
  policy_0: -140 (below threshold)
  policy_1: -160 (below threshold)

Iteration 10:
  Baseline: -100 → Threshold: -85
  policy_0: -80 (EXCEEDS! → league_0 created)
  policy_1: -120 (below threshold)

Iteration 15:
  Baseline: -90 → Threshold: -76.5  # Threshold increased (got harder!)
  policy_0: -75 (EXCEEDS! → league_1 created)
  policy_1: -105 (below threshold)
```

Notice: As agents improve, the threshold becomes stricter (adapts to improving performance).

### **Scenario 2: One Agent Dominates**

```
Iteration 10:
  Baseline: -75 (policy_0: -50, policy_1: -100)
  Threshold: -63.75
  policy_0: -50 (EXCEEDS! → league_0 created)
  policy_1: -100 (far below)

Iteration 15:
  Baseline: -60 (policy_0: -40, policy_1: -80)
  Threshold: -51
  policy_0: -40 (EXCEEDS! → league_1 created)
  policy_1: -80 (still below)
```

## Best Practices

1. **Start with default 0.15 (15%)**: Good balance between selectivity and frequency
2. **Monitor league growth**: Should add 1-3 opponents every 20-50 iterations
3. **If league grows too fast**: Increase `relative_improvement` (e.g., 0.20)
4. **If league never grows**: Decrease `relative_improvement` (e.g., 0.10) or `check_every_n_iters`
5. **Track baseline trend**: Should improve over time (less negative)

## Debugging

If league isn't growing as expected:

```python
# Check raw returns
print(f"Agent returns: {result['env_runners']['agent_episode_returns_mean']}")

# Manually calculate
baseline = np.mean(list(agent_returns.values()))
threshold = baseline * (1 - 0.15)
print(f"Baseline: {baseline}, Threshold: {threshold}")
```

## Switching Modes

You can switch between modes if needed:

```python
# Start with relative (for initial training with negative returns)
callback = MinimalLeagueCallback(relative_improvement=0.15)

# Later switch to absolute (if returns become positive)
callback = MinimalLeagueCallback(return_threshold=100.0)
```

But typically, **stick with relative mode for trading environments**.
