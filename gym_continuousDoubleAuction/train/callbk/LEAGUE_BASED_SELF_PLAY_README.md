# League-Based Self-Play Implementation

## Overview

This implementation extends the competitive self-play training with **champion snapshotting** - a league-based approach where exceptional policy performances are preserved as frozen opponents.

## Key Changes

### What Changed

**BEFORE (Competitive Weight Copying):**
- `policy_0` and `policy_1` compete
- Winner's weights copied to loser each iteration
- Both policies converge to same strategy
- No historical diversity

**AFTER (Independent Evolution + Champions):**
- `policy_0` and `policy_1` evolve independently (NO weight copying)
- Exceptional performers snapshotted as frozen `champion_N` modules
- Champions added to league as tough opponents
- Rolling window maintains last 5 champions

### Modified Files

1. **`self_play_callback_mod.py`**
   - Extended `__init__` with champion configuration
   - Replaced weight copying with champion snapshotting in `on_train_result`
   - Added `_create_champion_snapshot()` - creates frozen module copies
   - Added `_should_create_champion()` - checks threshold and cooldown
   - Added `_remove_oldest_champion()` - maintains rolling window
   - Added `get_mapping_fn()` - dynamic agent-to-module mapping with champions

## Usage

### Basic Configuration

```python
from gym_continuousDoubleAuction.train.callbk.self_play_callback_mod import SelfPlayCallback
from ray.rllib.algorithms.ppo import PPOConfig

# Create callback with custom thresholds
callback = SelfPlayCallback(
    std_dev_multiplier=2.0,     # Snapshot when return > mean + 2*std
    max_champions=5,            # Keep last 5 champions (rolling window)
)

config = (
    PPOConfig()
    .environment("continuousDoubleAuction-v0", env_config={...})
    .callbacks(lambda: callback)
    .multi_agent(
        policies={...},
        policy_mapping_fn=SelfPlayCallback.get_mapping_fn(callback),
        policies_to_train=["policy_0", "policy_1"],
    )
)

algo = config.build()
```

### Running Training

See `example_league_based_training.py` for a complete runnable example.

```bash
python gym_continuousDoubleAuction/train/callbk/example_league_based_training.py
```

## Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `std_dev_multiplier` | 2.0 | Multiplier for relative ranking (`mean + N * std`) |
| `max_champions` | 5 | Maximum champions in league (rolling window) |
| `min_iterations_between_champions` | 10 | Minimum iterations between champion snapshots |

### Tuning Guidelines

**`std_dev_multiplier`:**
- **Too low (e.g., 0.5)**: Snapshots mediocre policies, bloats league
- **Too high (e.g., 4.0)**: Rarely finds champions
- **Recommended:** 1.5 - 2.5 (Snapshot only exceptional outliers)

**Note on Returns:**
This method works well even with **negative returns** (common in trading). 
Example: Mean = -1000, Std = 200. Threshold = -600.
A policy with return -500 is "exceptional" relative to the mean.

**`max_champions`:**
- Too small (2-3) → Limited diversity
- Too large (15+) → Memory overhead
- **Recommended:** 5-8 for balance

**`min_iterations_between_champions`:**
- Too short (1-2) → Same policy snapshotted repeatedly  
- Too long (50+) → Miss intermediate strategies
- **Recommended:** 10-20 iterations

## How It Works

### Training Flow

```
Iteration 1-20:
  Agents: [policy_0, policy_1, random, random]
  - Both trainable policies compete independently
  
Iteration 21 (policy_0 return > mean + 2*std):
  Create champion_1 (frozen snapshot of policy_0)
  Agents: [policy_0, policy_1, random, champion_1]
  
Iteration 40 (policy_1 achieves exceptional relative return):
  Create champion_2 (frozen snapshot of policy_1)
  Agents: [policy_0, policy_1, champion_1, champion_2]
  
Iteration 60+:
  Rolling window maintains last 5 champions
  Old champions phased out, new ones added
```

### League Evolution

As training progresses:
1. Trainable policies (`policy_0`, `policy_1`) continuously improve
2. When one exceeds threshold → snapshot created
3. Champion provides consistent strong opposition
4. Difficulty increases as more champions added
5. Oldest champions removed when max reached (rolling window)

## Benefits

✅ **Strategy Diversity**: Two independent learning trajectories  
✅ **Historical Opponents**: Past strong strategies preserved  
✅ **Continuous Challenge**: League difficulty grows over time  
✅ **Prevents Forgetting**: Old strategies remain in league  
✅ **Better Exploration**: No convergence to single strategy  

## Monitoring Training

### Console Output

```
================================================================================
Iteration 25: Best agent agent_0 with return 1250.45
All returns: {'agent_0': 1250.45, 'agent_1': 850.23, ...}
Current league size: 4 (2 trainable + 2 champions)
================================================================================

********************************************************************************
🏆 CREATING CHAMPION SNAPSHOT 🏆
Champion ID: champion_3
Source Policy: policy_0
Return: 1250.45
Iteration: 25
********************************************************************************

✓ Champion champion_3 created successfully!
✓ League size now: 5 (2 trainable + 3 champions)
✓ Active champions: ['champion_1', 'champion_2', 'champion_3']
```

### Metrics (TensorBoard)

The callback logs:
- `league_size`: Total policies in league
- `best_return`: Best agent return (10-iteration window)
- `champion_count`: Number of active champions

## Troubleshooting

### Issue: No champions being created

**Cause:** Policies not exceeding threshold  
**Fix:** Lower `champion_threshold` or train longer

### Issue: All champions from same policy

**Cause:** One policy dominates  
**Fix:** Adjust learning rates or lower threshold

### Issue: Champions not appearing in episodes

**Cause:** Mapping function not using `get_mapping_fn`  
**Fix:** Ensure using `SelfPlayCallback.get_mapping_fn(callback)`

### Issue: Memory issues

**Cause:** Too many champions  
**Fix:** Reduce `max_champions` to 3-5

## Implementation Details

### Champion Snapshot Process

1. **Performance Check**: Compare agent returns to threshold
2. **Cooldown Check**: Ensure min iterations elapsed since last champion
3. **Rolling Window**: Remove oldest if at max capacity
4. **Module Creation**: Use `algorithm.add_module()` with `RLModuleSpec.from_module()`
5. **Weight Copy**: Use `algorithm.set_state()` to copy weights
6. **Update Tracking**: Add to `champion_history` and `available_modules`

### Agent-to-Module Mapping

```python
agent_0 → policy_0 (trainable)
agent_1 → policy_1 (trainable)
agent_2 → random OR champion (rotates via episode hash)
agent_3 → random OR champion (rotates via episode hash)
```

## Migration from Old Approach

### Option 1: Parallel Testing

Keep old callback as backup:
```bash
cp self_play_callback_mod.py self_play_callback_mod_old.py
# Use new version in training
```

### Option 2: Gradual Adoption

1. Start with low `champion_threshold` to create many champions quickly
2. Monitor for 100 iterations
3. Adjust thresholds based on performance
4. Compare final results with baseline

## Next Steps

1. **Test on your environment** - Run `example_league_based_training.py`
2. **Tune thresholds** - Adjust based on your return distributions
3. **Monitor diversity** - Track if policy_0 and policy_1 diverge
4. **Compare performance** - Baseline vs league-based after 500+ iterations

## Questions?

Refer to `implementation_plan.md` for detailed technical specifications.
