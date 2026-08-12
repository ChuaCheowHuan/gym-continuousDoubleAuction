# 6. Action Space

The current `Dict` action space, its deterministic price anchoring, the two degenerate
dimensions, and the legacy `Tuple` design it replaced.

Related: [05_observation_space.md](05_observation_space.md) §5 (prices resolve against
`agg_LOB_raw`), [03_matching_engine.md](03_matching_engine.md) §3.5 (order targeting),
[10_testing.md](10_testing.md) §3.

---

## 1. Current structure

Each agent's action is a `gymnasium.spaces.Dict`
([`action_helper.py:56-66`](../gym_continuousDoubleAuction/envs/exchg/action_helper.py#L56-L66)):

| Key | Space | Description |
|---|---|---|
| `category` | `Discrete(9)` | Trade action — side and type combined |
| `size_mean` | `Box(-1.0, 1.0)` | Mean for size sampling |
| `size_sigma` | `Box(0.0, 1.0)` | Sigma for size sampling |
| `price` | `Discrete(10)` | Market depth level index (0–9 for levels 1–10) |
| `price_offset` | `Discrete(3)` | Stance relative to that level: 0 passive, 1 join, 2 aggressive |

### 1.1 `category`

| Value | Meaning |
|---|---|
| 0 | Neutral — no action |
| 1 – 4 | Buy: market, limit, modify, cancel |
| 5 – 8 | Sell: market, limit, modify, cancel |

Category 0 sets `side = None`, and `set_actions` drops those entries before any price calculation
or matching — so "do nothing" costs nothing.

### 1.2 Size

Constants, from
[`action_helper.py:9-14`](../gym_continuousDoubleAuction/envs/exchg/action_helper.py#L9-L14):

```python
min_size            = 1
mkt_max_size        = 100
N                   = 10
limit_max_size      = mkt_max_size * N          # 1000
mkt_size_mean_mul   = (mkt_max_size - min_size) / 2      # 49.5
limit_size_mean_mul = (limit_max_size - min_size) / 2    # 499.5
```

The final size is
`rint(abs(N(mean_mul × size_mean, size_sigma)))`, then `+ min_size` so it is at least 1. A
full-scale limit draw (`size_mean = 1.0`) is therefore ≈ **500 contracts**, not 5,000.

> Both size dimensions are effectively degenerate — see §4.

### 1.3 `price_offset`

| Value | Bid | Ask |
|---|---|---|
| 0 — Passive | 1 tick **below** the level price | 1 tick **above** the level price |
| 1 — Join | exactly the level price | exactly the level price |
| 2 — Aggressive | 1 tick **above** the level price | 1 tick **below** the level price |

"Aggressive" is inverted between the sides, as it must be: buying higher and selling lower both
mean paying up for immediacy. Implemented as
`offset_multiplier = price_offset - 1`, added for bids and subtracted for asks.

### 1.4 Market orders ignore price

If `category` is 1 or 5 (market), `price` and `price_offset` are ignored and the internal order
price is set to `-1.0` — the sentinel telling the matching engine to execute immediately at
whatever is available. `test_market_order_mapping` proves this by submitting a deliberately
"dirty" price level with a market category.

### 1.5 Multi-order targeting

- **Modify** uses FIFO: it targets the agent's **oldest existing order** on that side, ignoring
  price.
- **Cancel** and **limit** match the specific price named by the `price` + `price_offset`
  combination.

See [03_matching_engine.md](03_matching_engine.md) §3.5 for why the two differ.

---

## 2. Deterministic price anchoring

The mechanism that makes every action code carry a stable economic meaning, even when the book is
thin or empty.

### 2.1 The anchor

- **Initial:** at `reset()`, `last_price` is sampled as an integer from
  `[initial_price_min, initial_price_max]` (default `[10, 100]`) and cast to `float`.
- **Dynamic:** `mark_to_mkt` sets `last_price` to the **last traded price** from the LOB tape
  after every step that produced a trade.

### 2.2 Populated levels

If the targeted book level exists, its price is read from the **unnormalized** `agg_LOB_raw`
([05_observation_space.md](05_observation_space.md) §5), and `price_offset` is applied.

### 2.3 Ghost levels

If the targeted level is empty, the price is extrapolated deterministically from the anchor:

- **Bid:** `Anchor − (level_idx + 1) × min_tick`
- **Ask:** `Anchor + (level_idx + 1) × min_tick`

So level index 0 targets 1 tick from the anchor and index 9 targets 10 ticks away. A final
`max(min_tick, set_price)` guard keeps prices strictly positive.

**Why this matters.** "Price level 1" always means "the most aggressive price near the current
valuation"; "price level 10" always means "a very passive price far from the centre." An agent
can learn that level 10 is where patient orders go even when nobody else is quoting there. There
is no discontinuity when the book goes thin — which is precisely the failure of the legacy design
(§5.2). It matters most early in an episode, when the book is empty.

---

## 3. Why relative pricing at all

By selecting *levels and offsets* rather than absolute currency values, the agent never has to
learn what a price of 10,000 means. It only needs to learn relative concepts — "be one tick
better than the current best", "quote at the third level of depth". The policy then generalizes
across price regimes instead of memorising one. This is the one part of the original design that
survived the redesign intact, and the `category × price-level × price-offset` factorisation is a
thoughtful piece of design: the passive/join/aggressive offset is exactly the decision a market
maker faces.

The corresponding cost, worth being explicit about: level index *k* means "the *k*-th occupied
price", not a fixed distance, so the coordinate system is non-stationary. See
[05_observation_space.md](05_observation_space.md) §7.4.

---

## 4. The two degenerate dimensions

### 4.1 Half the `size_mean` range is a no-op

`_set_size`
([`action_helper.py:206-226`](../gym_continuousDoubleAuction/envs/exchg/action_helper.py#L206-L226)):

```python
sample = np.random.normal(mean_mul * mean, sigma, 1)
return np.rint(np.abs(sample)).item()
```

The `abs()` folds the distribution. **[verified]**, same RNG seed:

```
mean=+0.5 -> [250.0, 250.0, 250.0, 250.0, 250.0]
mean=-0.5 -> [250.0, 250.0, 250.0, 250.0, 250.0]   identical: True
```

`size_mean` is declared on `Box(-1, 1)`, so the policy's Gaussian head spends half its range on a
mirror image. Worse, the optimum is bimodal at `±m`, which fights the unimodal Gaussian policy:
the head is pushed toward mean 0 by symmetric gradients, and mean 0 means *minimum* size. The
gradient also has a kink at exactly 0 — the worst possible place for one, since that is where a
Gaussian policy initializes.

**Fix:** declare the space as `Box(0, 1)`.

### 4.2 The `size_sigma` head is inert

`sigma` is passed straight to `np.random.normal` as an **absolute** standard deviation, while
means are 49.5·|m| (market) or 499.5·|m| (limit). **[verified]**:

```
sigma=0.0 -> [250.0, 250.0, 250.0];  sigma=1.0 -> [251.0, 249.0, 250.0]
```

Across `sigma ∈ [0,1]` the size varies by ±1 contract on a base of 250. The head is a null
control: the policy pays entropy cost forever for a parameter with no effect.

**Fix:** scale it (`sigma × mean_mul × k`) or delete it.

### 4.3 Environment-side sampling breaks the log-probability

Setting scale aside, the *architecture* of size selection is unusual: the policy emits
distribution **parameters**, and the environment draws the sample. The realised size is therefore
not part of the action whose log-probability PPO uses in the importance ratio. The policy is
credited or blamed for an outcome driven by an unrecorded random draw, and the agent never
observes the realisation.

This shows up as extra advantage variance that no amount of data removes. The standard
formulation is to have the policy emit the size directly (a `Box` action, with sampling handled
by the policy distribution, so `log π(a|s)` covers it), letting PPO's own exploration schedule
control the spread.

### 4.4 Dead helper methods

`_set_side`, `_set_type`, `_higher` and `_lower` are all superseded by the category mapping and
the offset arithmetic, and are never called. `max_price` is a parameter of `_set_price` that its
body never reads.

---

## 5. The legacy design and why it was replaced

Retained because it explains the shape of the current design.

### 5.1 What it was

A `gym.spaces.Tuple` of five components:

1. **Side** `Discrete(3)` — 0 none, 1 bid, 2 ask
2. **Type** `Discrete(4)` — 0 market, 1 limit, 2 modify, 3 cancel
3. **Size Mean** `Box(-1.0, 1.0)`
4. **Size Sigma** `Box(0.0, 1.0)`
5. **Price Code** `Discrete(12)`

The price code mapped as:

| Price code | Target | Bid | Ask |
|---|---|---|---|
| 11 | Beyond the best price | Best bid + 1 tick | Best ask − 1 tick |
| 1 – 10 | A specific LOB level | Level price + 1 tick | Level price − 1 tick |
| 0 | Behind the worst visible price | Worst bid − 1 tick | Worst ask + 1 tick |

The commented-out `act_space` at
[`action_helper.py:23-36`](../gym_continuousDoubleAuction/envs/exchg/action_helper.py#L23-L36)
still preserves it inline.

### 5.2 The flaws that motivated the redesign

**The empty-book randomness trap — the most serious.** If a targeted level was empty, the
environment generated a completely random price:

```python
if price == 0:
    set_price = random.randrange(min_tick, max_price, min_tick)
```

An agent could learn that "price code 3" was a safe passive placement; when liquidity vanished,
price code 3 became a lottery ticket. That non-stationarity makes it extremely hard for a network
to converge on a stable value function. **Resolved** by the ghost-level anchoring in §2.3.

**Forced aggression.** Codes 1–10 always offset by 1 tick, so an agent could never *join* a level
at exactly its price. This designed-in penny war prevented agents from learning passive
liquidity-providing strategies. **Resolved** by the `price_offset` dimension, whose "join" value
is exactly the level price.

**Redundant boundary codes.** Codes 0 and 11 became unnecessary once levels and offsets could be
combined freely, and were dropped.

**Sparse and redundant space.** Many combinations were dead actions — if side was 0 (none), the
other four components were ignored; if type was 0 (market), the price code was ignored. A large
fraction of the mathematical action space had zero effect on the environment. **Partly resolved**
by collapsing side × type into a single `category`, which removes the side-0 dead branch.

**Blindness to market macro-structure.** The price code was hardcoded to the top 10 levels, so an
agent could not place deep orders far outside the current spread — no fishing for flash-crash
fills. **Not resolved**; the current space has the same 10-level horizon, now measured in ticks
from the anchor rather than in occupied levels.

**Discrete–continuous hybrid.** Mixing discrete and `Box` components in one space is awkward for
some algorithms — DQN cannot handle the continuous parts, and PPO/SAC need branching heads.
**Not resolved**; the current `Dict` has the same heterogeneity, though a flat `Dict` is easier
for RLlib to handle than a nested `Tuple`.

---

## 6. Simultaneous-move semantics

All agents act on the same observation, and arrival order is randomised per step by
`rand_exec_seq`
([`action_helper.py:88-96`](../gym_continuousDoubleAuction/envs/exchg/action_helper.py#L88-L96)).
This makes the step a simultaneous-move stage game with a random tie-break — clean and
defensible, and it means no agent can be systematically faster.

Note that `step()` calls `rand_exec_seq(actions, None)`, so `random_state=None` and the shuffle
is **not** governed by RLlib's `seed`. Combined with the env drawing initial price and order
sizes from global `np.random`, **no episode is reproducible even with `--seed` set**. The
`rand_exec_seq` signature already accepts a seed; nothing passes one. Tracked as S3-5.
