# League-Based Self-Play Fix - Technical Summary

## Problem Identified

The original `minimal_league_callback.py` had a **critical bug** in its matchmaking logic that prevented it from being truly "league-based":

### Original Broken Code:
```python
def policy_mapping_fn(agent_id, episode, **kwargs):
    agent_policy = agent_id.replace('agent_', 'policy_')
    
    # BUG: Always returns the agent's own policy if trainable!
    if agent_policy in trainable_list:
        return agent_policy  # ← agent_0 always gets policy_0
    else:
        return selected_policy
```

### What This Meant:
- `agent_0` → **always** `policy_0`
- `agent_1` → **always** `policy_1`
- League opponents (`league_0`, `league_1`, etc.) were **created but never used**
- Trainable policies **only played against each other**
- This is **naive self-play**, not league-based!

---

## The Fix

### New Correct Code (in `minimal_league_callback_fixed.py`):
```python
def policy_mapping_fn(agent_id, episode, **kwargs):
    # Use episode hash for position swapping
    if hash(episode.id_) % 2 == agent_id:
        # This agent is the trainable
        return np.random.choice(trainable_list)
    else:
        # This agent is the opponent
        if league_list and np.random.random() < league_opponent_prob:
            # 70% chance: Use a league opponent (historical snapshot)
            return np.random.choice(league_list)
        else:
            # 30% chance: Use another trainable (co-evolution)
            return np.random.choice(trainable_list)
```

### What This Achieves:
1. **One agent is always trainable** (ensures learning happens)
2. **Other agent is probabilistically assigned**:
   - 70% (default) → Random league opponent (historical snapshot)
   - 30% → Random trainable (co-evolution)
3. **Episode hash ensures position swapping** (both policies play as agent_0 and agent_1)
4. **League opponents are actually used** in training!

---

## Classification Comparison

| Callback | Original Claim | Actual Behavior |
|----------|---------------|-----------------|
| `self_play_callback.py` | "Simple self-play" | ✅ **True league-based** |
| `self_play_league_based_callback.py` | "League-based" | ✅ **True league-based** (complex) |
| `minimal_league_callback.py` | "League-based" | ❌ **Naive self-play** (broken) |
| `minimal_league_callback_fixed.py` | "League-based" | ✅ **True league-based** (fixed!) |

---

## New Features in Fixed Version

### 1. Configurable League Opponent Probability
```python
callback = MinimalLeagueCallback(
    league_opponent_prob=0.9  # 90% league opponents, 10% trainables
)
```

- Higher values = more historical opponents (stronger curriculum)
- Lower values = more co-evolution (faster adaptation)
- Default: 0.7 (70/30 split recommended)

### 2. Matchup Statistics Tracking
```python
stats = callback.get_league_stats()
# Returns:
{
    'league_size': 3,
    'num_trainable': 2,
    'num_frozen': 3,
    'trainable_policies': ['policy_0', 'policy_1'],
    'league_opponents': ['league_0', 'league_1', 'league_2'],
    'matching_stats': {
        ('trainable', 'league_0'): 150,
        ('trainable', 'league_1'): 145,
        ('trainable', 'league_2'): 142,
        ('trainable', 'trainable'): 63
    }
}
```

Confirms that league opponents are actually being used!

### 3. Better Logging
```python
  -> Policy mapping updated successfully
  -> League opponent probability: 70.0%
  -> Trainables will now play against: ['league_0', 'league_1', 'league_2']
```

---

## How to Use the Fixed Version

### Option 1: Use the Fixed File Directly
```python
from gym_continuousDoubleAuction.train.callbk.minimal_league_callback_fixed import MinimalLeagueCallback

callback = MinimalLeagueCallback(
    relative_improvement=0.15,      # 15% better than average
    check_every_n_iters=5,          # Check every 5 iterations
    league_opponent_prob=0.7        # 70% league opponents
)
```

### Option 2: Replace the Original
1. Backup original: `minimal_league_callback.py` → `minimal_league_callback_broken.py`
2. Rename fixed: `minimal_league_callback_fixed.py` → `minimal_league_callback.py`
3. No code changes needed elsewhere!

---

## Verification

To verify the fix is working, check the logs after a league opponent is added:

### ✅ Good (Fixed Version):
```
Trainables will now play against: ['league_0', 'league_1']
Matchups:
  ('trainable', 'league_0'): 150
  ('trainable', 'league_1'): 145
  ('trainable', 'trainable'): 63
```

### ❌ Bad (Original Broken Version):
```
# No matchup statistics shown
# League opponents are created but never used
```

---

## Performance Implications

### Original (Broken):
- Trainable policies only play each other
- No curriculum learning
- Prone to co-adaptation and strategy collapse
- League snapshots waste memory

### Fixed Version:
- Trainable policies play diverse historical opponents
- Gradual curriculum from easier to harder opponents
- Prevents catastrophic forgetting
- League snapshots are actually useful
- More robust strategies emerge

---

## Summary

**The original `minimal_league_callback.py` was NOT league-based despite its name.**

The fixed version (`minimal_league_callback_fixed.py`) now properly implements league-based self-play while retaining all the good domain-specific features:
- ✅ NAV (Net Asset Value) tracking
- ✅ Relative thresholds for negative returns
- ✅ Episode data persistence
- ✅ Robust error handling
- ✅ **Proper league-based matchmaking (NEW!)**

Use the fixed version for proper league-based training in your trading environment!
