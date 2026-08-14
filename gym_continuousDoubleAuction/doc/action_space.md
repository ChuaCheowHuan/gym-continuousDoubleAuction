# Action Space

The current `Dict` action space, its deterministic price anchoring, and the legacy `Tuple` design it
replaced.

This consolidates what were previously five documents: the current design, the legacy design, the
legacy price-code mechanism, a critique of the legacy design, and the proposal that became the fix.

Related: [observation_space.md](observation_space.md) (prices resolve against `agg_LOB_raw`),
[testing.md](testing.md) §3, [known_issues.md](known_issues.md) §2.3 (defects that remain).

---

## 1. Current structure

Each agent's action is a `gymnasium.spaces.Dict`
([`action_helper.py`](../envs/exchg/action_helper.py)):

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

Category 0 is filtered out before any price calculation or matching, so "do nothing" costs nothing.

### 1.2 Size

The final size is drawn from `Normal(mean_mul × size_mean, size_sigma)`, taken as an absolute value,
rounded, and incremented by 1 so it is at least 1. `mean_mul` differs by order type — market orders
have a smaller maximum size than limit orders (`mkt_max_size = 100`, `limit_max_size = 1000`).

> Both size dimensions are effectively degenerate in the current implementation: `size_sigma`
> perturbs a size of up to 500 by less than one unit, and `size_mean` is sign-folded by `abs()`.
> See [known_issues.md](known_issues.md) §2.3.

### 1.3 `price_offset`

| Value | Bid | Ask |
|---|---|---|
| 0 — Passive | 1 tick **below** the level price | 1 tick **above** the level price |
| 1 — Join | exactly the level price | exactly the level price |
| 2 — Aggressive | 1 tick **above** the level price | 1 tick **below** the level price |

"Aggressive" is inverted between the sides, as it must be: buying higher and selling lower both
mean paying up for immediacy.

### 1.4 Market orders ignore price

If `category` is 1 or 5 (market), `price` and `price_offset` are ignored and the internal order
price is set to `-1.0`, the sentinel telling the matching engine to execute immediately at whatever
is available.

### 1.5 Multi-order targeting

- **Modify** uses FIFO: it targets the agent's **oldest existing order** on that side. See
  [matching_engine.md](matching_engine.md) §3.5.
- **Cancel** matches the specific price level named by the `price` + `price_offset` combination.

---

## 2. Deterministic price anchoring

The mechanism that makes every action code carry a stable economic meaning, even when the book is
thin or empty.

### 2.1 The anchor

- **Initial:** at `reset()`, `last_price` is sampled as an integer from
  `[initial_price_min, initial_price_max]`.
- **Dynamic:** `last_price` updates to the **last traded price** from the LOB tape after every
  trade.

### 2.2 Populated levels

If the targeted book level exists, its price is read from the **unnormalized** `agg_LOB_raw`
([observation_space.md](observation_space.md) §5), and `price_offset` is applied.

### 2.3 Ghost levels

If the targeted level is empty, the price is extrapolated deterministically from the anchor:

- **Bid:** `Anchor − (Level × min_tick)`
- **Ask:** `Anchor + (Level × min_tick)`

So level index 0 targets 1 tick from the anchor and index 9 targets 10 ticks away.

**Why this matters.** "Price level 1" always means "the most aggressive price near the current
valuation"; "price level 10" always means "a very passive price far from the centre." An agent can
learn that level 10 is where patient orders go even when nobody else is quoting there. There is no
discontinuity when the book goes thin — which is precisely the failure of the legacy design (§3.1).

---

## 3. The legacy design and why it was replaced

Retained because it explains the shape of the current design and because several critiques in
[known_issues.md](known_issues.md) refer back to it.

### 3.1 What it was

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

### 3.2 The flaws that motivated the redesign

**The empty-book randomness trap — the most serious.** If a targeted level was empty, the
environment generated a completely random price:

```python
if price == 0:
    set_price = random.randrange(min_tick, max_price, min_tick)
```

An agent could learn that "price code 3" was a safe passive placement; when liquidity vanished,
price code 3 became a lottery ticket. That non-stationarity makes it extremely hard for a network to
converge on a stable value function. **Resolved** by the ghost-level anchoring in §2.3.

**Forced aggression.** Codes 1–10 always offset by 1 tick, so an agent could never *join* a level at
exactly its price. This designed-in penny war prevented agents from learning passive
liquidity-providing strategies. **Resolved** by the `price_offset` dimension, whose "join" value is
exactly the level price.

**Redundant boundary codes.** Codes 0 and 11 became unnecessary once levels and offsets could be
combined freely, and were dropped.

**Sparse and redundant space.** Many combinations were dead actions — if side was 0 (none), the
other four components were ignored; if type was 0 (market), the price code was ignored. A large
fraction of the mathematical action space had zero effect on the environment. **Partly resolved**
by collapsing side × type into a single `category`, which removes the side-0 dead branch.

**Blindness to market macro-structure.** The price code was hardcoded to the top 10 levels, so an
agent could not place deep orders far outside the current spread — no fishing for flash-crash
fills. **Not resolved**; the current space has the same 10-level horizon, now measured in ticks from
the anchor rather than in occupied levels.

**Discrete–continuous hybrid.** Mixing discrete and `Box` components in one space is awkward for
some algorithms — DQN cannot handle the continuous parts, and PPO/SAC need branching heads. **Not
resolved**; the current `Dict` has the same heterogeneity, though a flat `Dict` is easier for RLlib
to handle than a nested `Tuple`.

---

## 4. Why relative pricing at all

By selecting *levels and offsets* rather than absolute currency values, the agent never has to learn
what a price of 10,000 means. It only needs to learn relative concepts — "be one tick better than
the current best," "quote at the third level of depth." The policy then generalizes across price
regimes instead of memorising one. This is the one part of the original design that survived the
redesign intact.

The corresponding cost, worth being explicit about: level index *k* means "the *k*-th occupied
price," not a fixed distance, so the coordinate system is non-stationary. See
[known_issues.md](known_issues.md) §5.6.
