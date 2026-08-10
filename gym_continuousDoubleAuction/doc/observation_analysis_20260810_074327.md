# Observation Space Analysis (generated 2026-08-10 07:43:27)

A focused review of the observation pipeline: what it contains, what is wrong with it, what is
missing, and what to change.

Sources reviewed: [`envs/exchg/state_helper.py`](../envs/exchg/state_helper.py),
[`CHANGES_obs_normalization.md`](CHANGES_obs_normalization.md),
[`CHANGES_temporal_obs_history.md`](CHANGES_temporal_obs_history.md),
[`test/test_obs_normalization.py`](../test/test_obs_normalization.py),
[`test/test_observation_history.py`](../test/test_observation_history.py).

Companion documents:
[`codebase_analysis_20260810_065207.md`](codebase_analysis_20260810_065207.md) (how the system
works) and [`problems_identified_20260810_070226.md`](problems_identified_20260810_070226.md)
(whole-repo critique).

---

## 1. What the observation actually is

Per step, the top 10 levels per side are flattened into 40 floats:

```
[ norm_bid_price(10), norm_bid_size(10), norm_ask_price(10), norm_ask_size(10) ]
```

- Prices are the **fractional distance from the Level-1 midpoint** `M`:
  bids `(M - P)/M >= 0`, asks `-((|P| - M)/M) <= 0`.
- Sizes are `+sqrt(V)` for bids and `-sqrt(V)` for asks.
- `n_hist` frames (default 4) are stacked into a `(160,)` vector.
- All agents receive the same array.

### What is correct

Worth stating before the criticism: **the timing is consistent.** The observation returned at the
end of step *t* reflects the book after all of *t*'s orders, and the `agg_LOB_raw` used to resolve
action prices at *t+1* is recomputed from that same book state. There is no off-by-one between
what the agent sees and what its price-level selections resolve against.

(One consequence worth knowing: within a step, `agg_LOB_raw` is frozen at the start while orders
execute sequentially, so a trader executing 4th prices its levels against a stale book. That is
consistent with the environment's stated "all traders suffer the same lag" assumption, but it does
mean a chosen level can already be crossed by the time it executes.)

---

## 2. Correctness problems

### 2.1 Each frame in the stack is normalized by a different denominator

**The most serious defect, and specific to the interaction of the two most recent changes.**

`set_agg_LOB` computes `M` from the book *at that moment*
([`state_helper.py:112-121`](../envs/exchg/state_helper.py)), and `prep_next_state` appends the
already-normalized frame to the deque ([`state_helper.py:34`](../envs/exchg/state_helper.py)). So
frames *t-3 … t* each carry their own `M_{t-3} … M_t`.

Consequence: **frames cannot be compared to each other.** A resting order whose absolute price
never changed appears to move whenever the midpoint moves; a real price move can appear as no
change if `M` moved with it. The entire purpose of stacking frames is to expose order flow — the
*differences* between frames — and those differences are contaminated by a time-varying normalizer
that is not itself observable.

**Fix:** keep raw snapshots in the deque and normalize the whole stack once, at emission, by the
current `M_t`. Additionally expose `M_t / M_{t-1} - 1` so the agent can reason about the anchor's
own motion.

### 2.2 Zero means three different things

`0.0` is the sentinel for "level absent"
([`state_helper.py:126-131`](../envs/exchg/state_helper.py)). It is also the exact value of a price
*at* the midpoint. On a one-sided book `M` falls back to that side's L1 price, so
`(M - P_bid_1)/M = 0` **exactly** — the best bid in a bid-only book is numerically identical to an
empty level. The same holds for an ask-only book.

This is not a corner case: the book starts empty every episode and is frequently one-sided early
on. There is no validity mask, so the network cannot disambiguate.

**Fix:** an explicit per-level occupancy channel (10 bits per side), or a clearly out-of-range
sentinel.

### 2.3 The tape loop is dead code — there is no trade-flow information at all

[`state_helper.py:94-102`](../envs/exchg/state_helper.py):

```python
if self.LOB.tape != None and len(self.LOB.tape) > 0:
    num = 0
    for entry in reversed(self.LOB.tape):
        if num < self.LOB.tape_display_length:
            #tempfile.write(...)
            num += 1
        else:
            break
```

`entry` is never used. The body is a commented-out `write` copy-pasted from `OrderBook.__str__`.
The loop increments a counter and discards it. It *looks* like it is building tape features; it
builds nothing.

The observation therefore contains **zero information about executions**: no last traded price, no
trade direction, no signed volume, no trade count. In a continuous double auction, aggressive order
flow is the single most predictive public signal — more so than the resting book, which is largely
stale intentions. This is the largest missing feature, and the placeholder loop suggests it was
intended to be there.

### 2.4 The price anchor `M` is discarded and never restored

Normalization is scale-free by design, and `M` is not in the observation. Combined with
`last_price` being drawn uniformly from [10, 100] each episode
([`continuousDoubleAuction_env.py:164-166`](../envs/continuousDoubleAuction_env.py)), this creates
a concrete pathology:

**Tick size is absolute (`min_tick = 1`) but the observation is relative.** At `M = 10` one tick is
a 10% price move; at `M = 100` it is 1%. The `price_offset` action (passive / join / aggressive,
±1 tick) is therefore ten times more aggressive in one episode than another — and the two
situations are *literally indistinguishable* in the observation. The agent must learn a policy over
a quantity it cannot perceive.

Related: at `t = 0` the book is empty, so the observation is 160 zeros in **every** episode,
regardless of whether this episode's price level is 10 or 100. The first action is necessarily
uninformed.

**Fix:** include `log(M)` (or `M / initial_price`), and express price distances in **ticks** rather
than fractions so that observation units match action units.

### 2.5 Feature scales differ by ~600x, after "normalization"

Using the README's own example book (bids 23…9, asks 36…48, `M ~ 29.5`, sizes 7,746…188,096):

| block | range |
|---|---|
| normalized prices | -0.63 … +0.69 |
| `sqrt(volume)` sizes | -434 … +434 |

Both halves feed the same `(160,)` vector and the same linear layer. The price half is effectively
invisible at initialization. `sqrt` stabilized variance *within* the size block and left the
cross-block mismatch untouched — arguably worse than no normalization, because the documentation
now asserts the observation is normalized.

**Fix:** give size the same units-free property as price — `V_k / sum(V)` (depth share),
`log1p(V)`, or `V` divided by a running mean. `sqrt` of an unbounded raw count is not a
normalization.

### 2.6 Level index is a non-stationary coordinate

Position *k* in the vector means "the k-th occupied price," not a fixed price. In the README
example, bid levels 0–9 span prices 23 down to 9; the mapping from index to distance-from-mid
changes every step as levels are created and consumed. The action space selects by the **same**
unstable index ([`action_helper.py:256`](../envs/exchg/action_helper.py)), so a learned association
such as "level 3 is a good place to quote" has no fixed meaning across steps.

**Fix:** a fixed grid — one slot per tick offset from the midpoint, out to ±N ticks, holding the
volume at that price. This is stationary, makes empty levels naturally zero-volume rather than
sentinel-encoded, and makes observation and action share one coordinate system. Ranked second in
priority after adding private state.

### 2.7 `Box(-inf, inf)` bounds

[`continuousDoubleAuction_env.py:74-75`](../envs/continuousDoubleAuction_env.py). Every quantity
here is boundable. Infinite bounds disable RLlib's observation filters and any space-based sanity
checking, and signal that the range was never analyzed.

---

## 3. Missing information

Beyond trade flow (§2.3) and the anchor (§2.4):

- **All private state.** Net position, cash, `cash_on_hold`, NAV, VWAP, unrealized P&L, drawdown.
  The reward is a function of these; the observation contains none of them. This is fundamentally
  an *observation* defect, not a reward defect.
- **The agent's own resting orders.** Without them, `modify` and `cancel` — 4 of the 9 action
  categories — are blind guesses.
- **Time remaining.** `t_step` and `max_step` appear nowhere in the observation. This is a
  finite-horizon episode, so the optimal policy is genuinely time-dependent (inventory should be
  flattened toward the end) and the agent cannot condition on it. Cheap to add: one scalar,
  `t_step / max_step`.
- **Spread and imbalance.** Derivable in principle, but they are the two features that actually
  drive short-horizon prediction; making the network rediscover them from a badly-scaled vector
  wastes capacity.

---

## 4. Redundancy and wasted capacity

- **The sign convention is redundant.** Side is already encoded by block position in the vector;
  negating asks adds no information. It does prevent weight sharing between the two sides, which is
  otherwise a natural symmetry to exploit.
- **4x stacking of slowly-changing absolute levels.** Consecutive frames are near-identical, so
  roughly 120 of the 160 dimensions are near-duplicates, while the informative quantity (the
  change) must be recovered as a difference of large, similar numbers — poor conditioning. A
  `state_diff` function that computes exactly this already exists, unused, with a comment saying it
  "should be used in obs preprocessing if needed"
  ([`state_helper.py:137-158`](../envs/exchg/state_helper.py)). Either use it or delete it.
- **Whatever survives is squeezed through `Linear(160, 8)`** in
  [`model_handler.py`](../train/model/model_handler.py). Even a well-designed 160-dimensional
  observation cannot pass through an 8-unit bottleneck.

---

## 5. What the tests encode

[`test_observation_history.py:60`](../test/test_observation_history.py) —
`test_shared_history_multi_agent_uniformity` — asserts that all agents receive byte-identical
observations. That is currently true, but writing it as a test cements the design flaw: the moment
private state is added, this test must be deleted. It tests an implementation accident as if it
were a requirement.

The normalization tests are otherwise sound — signs, `sqrt` correctness, NaN/Inf safety on empty
books, and the raw-price action mapping. What they do not check is anything about *information
content*, which is where the problems are. The suite would pass unchanged with the dead tape loop,
the varying-denominator stack, and the zero collision all present — and all three are present.

---

## 6. Recommended layout

Roughly, per frame, all in tick units and depth shares:

```
market (public):
  log(M)                                    1    restores the anchor
  spread in ticks                           1
  volume at +/-N tick offsets from mid     2N    fixed grid, stationary
  occupancy mask for that grid             2N    kills the zero collision
  signed traded volume last step            1    from the tape
  trade count / direction last step         2
  M_t / M_{t-1} - 1                         1    lets the agent undo rescaling

private (per agent):
  net position, VWAP, unrealized P&L        3
  cash, cash_on_hold, NAV/init_cash         3
  drawdown from peak                        1
  own resting volume on the same grid      2N
  t_step / max_step                         1
```

Stack raw snapshots, normalize the whole stack once at emission using the current `M_t`, and add
explicit frame deltas rather than relying on the network to difference them.

---

## 7. Priority order

| # | Change | Category |
|---|---|---|
| 1 | Add private state (position, cash, NAV, VWAP, drawdown, own resting orders) | correctness |
| 2 | Normalize the whole stack by the current `M_t`; stop storing pre-normalized frames | correctness |
| 3 | Finish the dead tape loop — add trade-flow features | correctness |
| 4 | Fixed tick-offset price grid shared with the action space | conditioning |
| 5 | Replace `sqrt(V)` with a units-free size normalization | conditioning |
| 6 | Occupancy mask; expose `log(M)` and `t_step / max_step`; finite `Box` bounds | conditioning |

Items 1–3 are correctness: without them the observation is missing information the policy provably
needs. Items 4–6 are conditioning: the information is present but presented in a form that makes it
hard to use.
