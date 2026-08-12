# 5. Observation Space

The complete specification of what agents see — layout, normalization, temporal stacking, market
scalars, and the raw/normalized split — followed by the measured feature scales and the design
defects.

Related: [02_architecture.md](02_architecture.md) §2.5 (step 6),
[06_action_space.md](06_action_space.md) (price levels resolve against the *un*normalized book),
[10_testing.md](10_testing.md) §4.

---

## 1. Shape at a glance

```
snapshot (one frame) = 42 floats
  index    0:10   normalized bid prices
          10:20   normalized bid sizes
          20:30   normalized ask prices
          30:40   normalized ask sizes
             40   log_mid
             41   log1p_spread_ticks

observation = n_hist frames concatenated, flat 1-D float32
  default n_hist = 4  →  shape (168,)
  layout: [ O_{t-3} | O_{t-2} | O_{t-1} | O_t ]
  the most recent frame is always the last SNAPSHOT_DIM elements
```

Widths are defined once, in
[`state_helper.py:9-13`](../gym_continuousDoubleAuction/envs/exchg/state_helper.py#L9-L13):

```python
K_ROWS = 10
BOOK_DIM = 4 * K_ROWS                  # 40
EXTRA_DIM = 2                          # log_mid, log1p_spread_ticks
SNAPSHOT_DIM = BOOK_DIM + EXTRA_DIM    # 42
```

**Never hardcode 40, 42, 160, or 168.** Import `SNAPSHOT_DIM` (and `BOOK_DIM` when you
specifically mean the book block). The `[-40:]` slicing that predated `EXTRA_DIM` failed
*silently* rather than loudly when the width changed — it returned the last 38 book values plus
2 scalars, misaligning every block slice by 2 while still passing several assertions.

Ask prices and sizes are stored **negated**; the sign encodes side.

The declared space is `Box(-inf, inf, shape=(n_hist * SNAPSHOT_DIM,), dtype=float32)`
([`continuousDoubleAuction_env.py:80-87`](../gym_continuousDoubleAuction/envs/continuousDoubleAuction_env.py#L80-L87)).
Every quantity here is in fact boundable; infinite bounds disable RLlib's observation filters and
any space-based sanity checking. See §7.6.

---

## 2. Price and volume normalization

### 2.1 Level-1 midpoint `M`

Let `P_bid,1` and `P_ask,1 = |ask_price_list[0]|` be the Level-1 prices.

| Condition | `M` |
|---|---|
| both L1 sides present | `(P_bid,1 + P_ask,1) / 2` |
| bid side only | `P_bid,1` |
| ask side only | `P_ask,1` |
| empty book | `self.last_price` |
| result `<= 0` | `100.0` (hard floor) |

`M` is therefore always strictly positive, so no division or logarithm in the pipeline can fault.

### 2.2 Prices — fractional distance from `M`

For level *k* ∈ {0 … 9}:

$$\text{norm\_P\_bid}_k = \begin{cases} \dfrac{M - P_{bid,k}}{M} & P_{bid,k} > 0 \\ 0.0 & P_{bid,k} = 0 \end{cases}
\qquad
\text{norm\_P\_ask}_k = \begin{cases} -\left(\dfrac{|P_{ask,k}| - M}{M}\right) & |P_{ask,k}| \ne 0 \\ 0.0 & \text{otherwise} \end{cases}$$

Since `P_bid,k <= M <= |P_ask,k|`, bids come out `>= 0` and asks `<= 0` — the sign convention is
preserved, and the magnitude is the fractional distance from the top of the book.

This is the right instinct, and the same thing a practitioner does before feeding a book to a
model: it makes the representation invariant to the episode's random price anchor.

### 2.3 Volumes — square root

$$\text{norm\_V\_bid}_k = +\sqrt{V_{bid,k}} \ge 0 \qquad \text{norm\_V\_ask}_k = -\sqrt{V_{ask,k}} \le 0$$

This dampens extreme volume spikes while preserving relative liquidity signals.

> **Caveat.** `sqrt` stabilises variance *within* the size block but leaves the cross-block scale
> mismatch untouched — see §6 for measured ranges and §7.5 for why it matters.

### 2.4 Why normalize at all

Raw LOB snapshots carry large unbounded prices and high-variance volumes. Fed directly to a
network they cause gradient instability and slow convergence. Midpoint normalization makes the
price features scale-invariant; the `sqrt` transform compresses volume dynamic range.

---

## 3. Market-level scalars

Two scalars are appended to **every frame** (not once per stack). They are **always on** — there
is no config flag and no second code path.

### 3.1 `log_mid` (index 40)

$$\texttt{log\_mid} = \ln(M)$$

Reuses the `M` already computed for normalization — no extra book queries.

**Range:** ≈ 2.3 – 4.6 for the `[10, 100]` initial-price range.

**Why it exists.** Midpoint normalization makes the observation scale-free, which *discards `M`
itself*. Two markets at price 10 and price 100 were previously indistinguishable — yet `min_tick`
is absolute (= 1), so one tick is a 10% move in the first market and a 1% move in the second.
Agents were being asked to choose tick-denominated price offsets without being able to perceive
what a tick was worth. `log_mid` restores that anchor.

### 3.2 `log1p_spread_ticks` (index 41)

$$\texttt{log1p\_spread\_ticks} = \ln\!\left(1 + \frac{P_{ask,1} - P_{bid,1}}{\texttt{min\_tick}}\right)
\quad\text{if both L1 sides exist, else } 0.0$$

Computed from the same `l1_bid` / `l1_ask` locals as `M`, so it is guaranteed consistent with the
top of book actually present in the observation.

**`min_tick`, not `tick_size` — deliberate.** `self.tick_size` is never stored on the env and
`reset()` hardcodes `OrderBook(1, ...)`, so the `tick_size` config is silently discarded
([02_architecture.md](02_architecture.md) §2.7). `Action_Helper.min_tick` (= 1) is the tick the
action space actually quotes in, so this choice makes observation units match action units.

**The `0.0` sentinel is unambiguous.** A resting book can never be locked or crossed — any bid
`>= best ask` is filled on arrival ([03_matching_engine.md](03_matching_engine.md) §2.1) — so a
two-sided book always has `spread >= 1` tick, and every real measurement maps to
`log1p(x) >= log1p(1) = 0.693`. `log1p(0) = 0` sits cleanly below the valid range.

**Range:** 0 (sentinel), then ≈ 0.693 – 4.6 for spreads of 1 to 100 ticks.

**Why `log1p` rather than raw `spread / tick`:** raw spread is unbounded — a thin early-episode
book can produce 50+, which would sit beside price features of magnitude ~0.5. `log1p` compresses
it to the same order as `log_mid`, keeps the zero sentinel exact, and preserves monotonicity. The
cost is diminishing sensitivity at wide spreads, which is acceptable: the difference between a
40- and a 50-tick spread matters far less than between 1 and 2.

### 3.3 Why per-frame

Each frame becomes self-describing, and stacking `log(M_t)` per frame lets an agent recover each
frame's own normalizer. That partially mitigates the varying-denominator defect (§7.1). Appending
at the *end* also keeps all existing `[0:10] / [10:20] / [20:30] / [30:40]` block slicing correct.

---

## 4. Temporal history stacking

### 4.1 Why

A single snapshot at time *t* tells an agent nothing about **how the market arrived** at that
state — whether prices are trending, order flow is accelerating, or a large order is being
worked. A window of the *N* most recent snapshots enables learning momentum and mean-reversion
patterns, and distinguishes a stable book from a rapidly evolving one.

### 4.2 Design decisions

| Decision | Choice | Rationale |
|---|---|---|
| Observation format | Flat 1-D `(N × SNAPSHOT_DIM,)` | Maximum compatibility with RLlib built-in policies (FCNet, LSTM expect flat inputs) |
| History scope | One shared environment-level `obs_history` deque | All agents observe the same public market; per-agent history would be redundant |
| Default window *N* | 4 | Balances temporal context against input dimensionality |
| Configurability | `config["n_hist"]` | Consistent with the existing RLlib config pattern |

### 4.3 Mechanism

`State_Helper` holds `self.obs_history = deque(maxlen=n_hist)`.

- `reset_traders_agg_LOB()` generates the initial snapshot *O₀* and fills the deque with *N*
  copies of it, then concatenates. Padding with copies of *O₀* rather than zeros avoids
  misleading agents into thinking there was prior inactivity.
- `prep_next_state()` appends the new snapshot (the deque drops the oldest automatically) and
  concatenates.

Every agent receives the same array:

```python
states = {f'agent_{i}': stacked_obs for i in range(len(self.traders))}
```

**[verified]** — the number of distinct observation vectors across agents is **1**, at reset and
at every step.

---

## 5. The raw book: `agg_LOB_raw`

Alongside the normalized observation, `set_agg_LOB()` keeps an **unnormalized** 40-element
snapshot in `self.agg_LOB_raw`. This is what `Action_Helper._set_price()` reads to turn an
agent's discrete price-level selection into an actual market price.

**`agg_LOB_raw` is `BOOK_DIM` (40), not `SNAPSHOT_DIM`.** The market scalars are an
observation-only addition; action price resolution
(`np.array(agg_LOB_source).reshape(4, 10)`) is untouched by them. This separation is the key
safety property of the design and is pinned by `test_agg_LOB_raw_still_book_sized`.

`_set_price()` accesses it via `getattr(self, 'agg_LOB_raw', self.agg_LOB)` so `State_Helper`
stays importable independently of the mixin chain.

### Timing

The observation returned at the end of step *t* reflects the book after all of *t*'s orders, and
the `agg_LOB_raw` used to resolve action prices at *t+1* is recomputed from that same book state.
There is no off-by-one between what the agent sees and what its price-level selections resolve
against.

One consequence worth knowing: *within* a step, `agg_LOB_raw` is frozen at the start while orders
execute sequentially, so a trader executing fourth prices its levels against a stale book. That
is consistent with the environment's "all traders suffer the same lag" assumption, but it does
mean a chosen level can already be crossed by the time it executes.

---

## 6. Measured feature scales

**[verified]** — an independent 300-step, 4-agent random rollout (`init_cash=1e6`):

| Block | min | max |
|---|---|---|
| normalised bid price | 0.0000 | 0.4048 |
| sqrt bid size | 0.0000 | **47.01** |
| normalised ask price | −0.5802 | 0.0000 |
| sqrt ask size | **−40.29** | 0.0000 |
| `log_mid` | 3.6763 | 4.0431 |
| `log1p_spread` | 0.0000 | 2.7726 |

An earlier probe on the same code measured 0.2117 / 51.19 / −0.2593 / −44.01 / 4.1589 / 2.5649 —
the absolute numbers move with the book, the **ratio does not**. Across both runs the size block
exceeds the price block by roughly **80–250×**, feeding a `tanh` first layer with no
`MeanStdFilter` and no normalisation connector configured.

Round-trip verification of the transforms (inverting both must recover the live book):

```
OBS SHAPE          = (168,)
best bid/ask raw   = 67.0 / 76.0
exp(log_mid)       = 71.500015     ← matches (67 + 76) / 2 = 71.5
expm1(log1p_spread)= 9.0           ← matches 76 - 67 = 9 ticks
total NAV          = 4,000,000     ← conserved
all finite         = True
```

---

## 7. Design defects

The observation is where the largest remaining problems are. Ordered by cost.

### 7.1 Each frame in the stack is normalized by a different denominator

`set_agg_LOB` computes `M` from the book *at that moment*, and `prep_next_state` appends the
**already-normalized** frame to the deque. So frames *t−3 … t* each carry their own
`M_{t−3} … M_t`.

Consequence: **frames cannot be compared to each other.** A resting order whose absolute price
never changed appears to move whenever the midpoint moves; a real price move can appear as no
change if `M` moved with it. The entire purpose of stacking frames is to expose order flow — the
*differences* between frames — and those differences are contaminated by a time-varying
normalizer.

*Partially mitigated* by the per-frame `log_mid` scalar, which at least lets the agent recover
each frame's normalizer.

**Fix.** Keep raw snapshots in the deque and normalize the whole stack once, at emission, by the
current `M_t`. Additionally expose `M_t / M_{t−1} − 1` so the agent can reason about the anchor's
own motion.

### 7.2 Zero means three different things

`0.0` is the sentinel for "level absent". It is also the exact value of a price *at* the
midpoint. And on a one-sided book `M` falls back to that side's L1 price, so
`(M − P_bid,1)/M = 0` **exactly** — the best bid in a bid-only book is numerically identical to an
empty level. The same holds for an ask-only book.

This is not a corner case: the book starts empty every episode and is frequently one-sided early
on. There is no validity mask, so the network cannot disambiguate.

**Fix.** An explicit per-level occupancy channel (10 bits per side), or a clearly out-of-range
sentinel.

### 7.3 The tape loop is dead code — there is no trade-flow information at all

In `set_agg_LOB`
([`state_helper.py:104-112`](../gym_continuousDoubleAuction/envs/exchg/state_helper.py#L104-L112)):

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

The observation therefore contains **zero information about executions**: no last traded price,
no trade direction, no signed volume, no trade count. In a continuous double auction, aggressive
order flow is the single most predictive public signal — more so than the resting book, which is
largely stale intentions. This is the largest missing *public* feature, and the placeholder loop
suggests it was intended to be there.

### 7.4 Level index is a non-stationary coordinate

Position *k* in the vector means "the *k*-th occupied price", not a fixed price. The mapping from
index to distance-from-mid changes every step as levels are created and consumed. The action
space selects by the **same** unstable index, so a learned association such as "level 3 is a good
place to quote" has no fixed meaning across steps.

**Fix.** A fixed grid — one slot per tick offset from the midpoint, out to ±N ticks, holding the
volume at that price. This is stationary, makes empty levels naturally zero-volume rather than
sentinel-encoded, and makes observation and action share one coordinate system.

### 7.5 Feature scales differ by one to two orders of magnitude after "normalization"

See §6 for the measurements. The 22 well-scaled features (prices and the two scalars) feed the
same linear layer as the 20 size features and are up to ~250× smaller, so the price half is close
to invisible at initialization and the size units saturate `tanh` immediately.

`sqrt` stabilized variance *within* the size block and left the cross-block mismatch untouched —
arguably worse than no normalization, because the documentation asserts the observation is
normalized.

**Fix.** Give size the same units-free property as price — `V_k / sum(V)` (depth share),
`log1p(V)`, or `V` divided by a running mean — and centre `log_mid` on `log(55)`. Note that a
null result from the `log_mid` / `log1p_spread_ticks` features would *not* prove those features
useless: they are correct, but likely dominated until the size block is rescaled.

### 7.6 Redundancy and wasted capacity

- **The sign convention is redundant.** Side is already encoded by block position; negating asks
  adds no information. It does prevent weight sharing between the two sides, which is otherwise a
  natural symmetry to exploit.
- **4× stacking of slowly-changing absolute levels.** Consecutive frames are near-identical, so
  most of the 160 book dimensions are near-duplicates, while the informative quantity (the
  change) must be recovered as a difference of large, similar numbers — poor conditioning. A
  `state_diff` function that computes exactly this already exists, unused, with a comment saying
  it "should be used in obs preprocessing if needed". Either use it or delete it.
- **`Box(-inf, inf)` bounds.** Every quantity here is boundable.

### 7.7 No private state — the single biggest flaw

Nothing in the vector encodes the agent's own inventory, cash, NAV, drawdown, or resting orders,
yet the reward is a deterministic function of exactly those. This is covered in full in
[12_perspective_rl_researcher.md](12_perspective_rl_researcher.md) §2 and tracked as S1-2.

---

## 8. A recommended layout

Roughly, per frame, all in tick units and depth shares:

```
market (public):
  log(M)                                    1    restores the anchor  [DONE]
  spread in ticks                           1                         [DONE]
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

**Time remaining** (`t_step / max_step`) is missing and cheap. This is a finite-horizon episode,
so the optimal policy is genuinely time-dependent — inventory should be flattened toward the end
— and the agent cannot currently condition on it.

Stack raw snapshots, normalize the whole stack once at emission using the current `M_t`, and add
explicit frame deltas rather than relying on the network to difference them.

---

## 9. Consumers of the observation width

Anything that slices an observation must use `SNAPSHOT_DIM` / `BOOK_DIM`:

| Site | Usage |
|---|---|
| [`continuousDoubleAuction_env.py`](../gym_continuousDoubleAuction/envs/continuousDoubleAuction_env.py) | `Box` shape is `(n_hist * SNAPSHOT_DIM,)` |
| [`exchg_helper.py`](../gym_continuousDoubleAuction/envs/exchg/exchg_helper.py) `print_table` | Slices the book block before `reshape(4, K_ROWS)`, then prints trailing scalars on their own line. Without the slice, `reshape` raises `ValueError` on **every rendered step**. |
| [`visualize_orderbook.py`](../gym_continuousDoubleAuction/visualize/visualize_orderbook.py) | Takes `agent_obs[-SNAPSHOT_DIM:]` for the current book state |
| `test_obs_normalization.py`, `test_observation_history.py`, `test_obs_market_features.py` | All shape literals derive from the constants |

Rendered output for the scalars looks like:

```
log_mid = 4.269698; log1p_spread_ticks = 2.302585
```

---

## 10. Compatibility

Any policy checkpoint or saved `episode_data` pickle built against an older observation width
will not load against the current one. This is unavoidable whenever the observation dimension
changes; the width has changed twice (40 → 160 with stacking, 160 → 168 with market features).
`SNAPSHOT_DIM` is a good constant but is not recorded in the checkpoint, so the mismatch is not
detected — it just fails.
