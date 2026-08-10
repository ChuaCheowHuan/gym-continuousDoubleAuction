# League-Based Self-Play

Champion snapshotting, matchmaking, configuration, monitoring, and verification.

Related: [architecture.md](architecture.md) §6, [testing.md](testing.md) §6,
[known_issues.md](known_issues.md) §3.3–3.4 (defects in champion selection and the debug output),
[logging.md](logging.md) (what this callback does and does not record).

---

## 1. What changed, and why

**Before — competitive weight copying.** `policy_0` and `policy_1` competed; the winner's weights
were copied onto the loser every iteration. Both policies converged to the same strategy, and no
historical diversity survived.

**Now — independent evolution plus champions.** The trainable policies evolve independently with no
weight copying. When one performs exceptionally, a frozen snapshot of its module is added to the
opponent pool as `champion_N`. A rolling window keeps the last few champions.

Benefits: two independent learning trajectories, past strong strategies preserved as opposition,
league difficulty that grows over time, and resistance to catastrophic forgetting.

All of this lives in
[`league_based_self_play_callback.py`](../train/callbk/league_based_self_play_callback.py):

- `on_train_result` — computes league mean/std of policy returns and decides on snapshotting.
- `_create_champion_snapshot()` — creates the frozen module copy.
- `_should_create_champion()` — checks threshold and cooldown.
- `_remove_oldest_champion()` — maintains the rolling window.
- `get_mapping_fn()` — dynamic agent-to-module mapping including champions.

---

## 2. Usage

```python
from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import SelfPlayCallback
from ray.rllib.algorithms.ppo import PPOConfig

callback = SelfPlayCallback(
    num_trainable_policies=2,             # k learning agents
    num_random_policies=2,                # m initial fixed/random agents
    std_dev_multiplier=2.0,               # snapshot when return > mean + 2*std
    max_champions=5,                      # rolling window size
    min_iterations_between_champions=10,  # cooldown
    original_opponent_weight=1.0,         # baseline selection priority
    champion_weight=3.0,                  # favour champions 3:1
)

config = (
    PPOConfig()
    .environment("continuousDoubleAuction-v0", env_config={...})
    .callbacks(lambda: callback)
    .multi_agent(
        policies={...},
        # CRITICAL: use the dynamic mapper from the callback
        policy_mapping_fn=SelfPlayCallback.get_mapping_fn(callback),
        policies_to_train=["policy_0", "policy_1"],   # the first k policies
    )
)

algo = config.build()
```

A complete runnable example:

```bash
python gym_continuousDoubleAuction/train/callbk/example_league_based_training.py
```

---

## 3. Configuration parameters

| Parameter | Default | Description |
|---|---|---|
| `num_trainable_policies` | 2 | Trainable policies (agents 0 … k−1) |
| `num_random_policies` | 2 | Initial random/fixed policies (agents k … n−1) |
| `std_dev_multiplier` | 2.0 | Threshold multiplier for `mean + N × std` |
| `max_champions` | 5 | Maximum champions in the league (rolling window) |
| `min_iterations_between_champions` | 10 | Cooldown between snapshots |
| `original_opponent_weight` | 1.0 | Selection priority for original fixed policies |
| `champion_weight` | 3.0 | Selection priority for champions |

### Tuning

**`std_dev_multiplier`** — too low (0.5) snapshots mediocre policies and bloats the league; too high
(4.0) rarely finds any. **Recommended 1.5 – 2.5.**

> Relative ranking works fine with **negative** returns, which are common in trading. With mean
> −1000 and std 200, the threshold is −600; a policy returning −500 is genuinely exceptional
> relative to its peers.

**`max_champions`** — too small (2–3) limits diversity; too large (15+) costs memory.
**Recommended 5 – 8.**

**`min_iterations_between_champions`** — too short (1–2) snapshots the same policy repeatedly; too
long (50+) misses intermediate strategies. **Recommended 10 – 20.**

**`champion_weight` : `original_opponent_weight`** — the goal is to focus training on the hardest
current opponents. Extreme bias (10:1) means agents rarely face baselines and may develop blind
spots to simple strategies; no bias (1:1) splits time evenly and slows progress against elite play.
**Recommended 3:1 to 5:1.**

---

## 4. How it works

### 4.1 Training flow

```
Iteration 1–20
  Agents: [policy_0 … policy_k-1] (trainable) + [policy_k … policy_n-1] (initial opponents)
  Trainable policies compete independently.

Iteration 21 — policy_0 return exceeds mean + 2*std
  Create champion_1 (frozen snapshot).
  Agents: [trainable] + [initial opponents + champion_1]

Iteration 40+
  Pool grows as champions are added; opponent slots rotate through it.
```

### 4.2 Snapshot process

1. **Performance check** — compare agent returns to the threshold.
2. **Cooldown check** — enough iterations elapsed since the last champion.
3. **Rolling window** — remove the oldest if at capacity.
4. **ID generation** — a monotonic counter (`champion_15`) prevents name collisions after removal.
5. **Module creation** — `algorithm.add_module()` with `RLModuleSpec.from_module()`.
6. **Weight copy** — `algorithm.set_state()`.
7. **Update tracking** — add to `champion_history` and `available_modules`.

### 4.3 Agent-to-module mapping

```python
# Trainable agents (0 … k-1) always play their own policy, for stable learning.
agent_0 → policy_0
...
agent_k-1 → policy_k-1

# Opponent agents (k … n-1) are drawn from [initial randoms + active champions],
# probabilistically per episode, weighted:
#   Pool    = [policy_2, policy_3, champion_1]
#   Weights = [1.0, 1.0, 3.0]  →  [20%, 20%, 60%]

seed = (abs(hash(episode_id)) + agent_num) % (2**32)
rng = np.random.RandomState(seed)
policy = rng.choice(pool, p=probs)
```

Seeding from the episode id makes the draw deterministic per episode while still varying across
episodes.

> **Caveat:** Python salts string hashes per process, so `hash(episode.id_)` differs across workers
> and across runs — this mapping is *not* reproducible in the way the comment implies. See
> [known_issues.md](known_issues.md) §3.5.

---

## 5. Monitoring

### Console output

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

`on_episode_start` also prints the per-episode policy map:

```text
========================================
Episode 12345 Started - Policy Map:
  agent_0 -> policy_0
  agent_1 -> policy_1
  agent_2 -> champion_1
  agent_3 -> policy_3
========================================
```

> **This printed map is computed by different logic than the real mapping** and is therefore
> unreliable — see [known_issues.md](known_issues.md) §3.4.

### TensorBoard metrics

| Metric | Meaning | Window |
|---|---|---|
| `league_size` | Number of active policies | 1 |
| `league_mean_return` | Mean policy return across the league | 10 |
| `league_std_return` | Std dev of policy returns | 10 |

Watch `league_size` and `league_mean_return` together: adding champions should raise difficulty and
depress mean return before agents adapt.

---

## 6. Verification

### Unit test: probabilistic mapping

`test/test_probabilistic_mapping.py` verifies the agent-to-policy mapping by statistical sampling —
it mocks a `SelfPlayCallback` and an `Episode`, simulates 1,000 episode starts, records which policy
a given agent is assigned, and compares the empirical distribution against expected thresholds.

```bash
python gym_continuousDoubleAuction/test/test_probabilistic_mapping.py
```

It checks three things: that weighted selection respects the configured weights, that raw weights
normalize correctly into a probability distribution, and that selection is stable given the episode
and agent IDs.

| Property | Coverage | Note |
|---|---|---|
| Logic verification | High | Catches errors in weight application and name parsing |
| Statistical validity | High | 1,000 samples give a narrow confidence interval |
| Determinism | Moderate | Verifies the distribution, not per-episode stability |
| Edge cases | Moderate | Empty pools and zero weights are not yet tested |

### NAV conservation

`test/test_nav_callback.py` covers the callback's episode-end check that total NAV equals total
initial cash, in both the passing and the failing direction.

---

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| No champions created | Returns never exceed the threshold | Lower `std_dev_multiplier` or train longer |
| All champions from one policy | One policy dominates | Adjust learning rates, or lower the threshold |
| Champions never appear in episodes | Static `policy_mapping_fn` from `policy_handler.py` is in use | Use `policy_mapping_fn=SelfPlayCallback.get_mapping_fn(callback)` |
| Module ID collision error | Champion names reused after removal | Fixed via the monotonic ID counter — ensure you are on current code |
| Memory growth | Too many champions; removed modules are never freed | Reduce `max_champions`; see [known_issues.md](known_issues.md) §3.9 |
