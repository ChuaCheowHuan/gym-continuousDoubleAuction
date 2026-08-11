# Observation Space

The complete specification of what agents see: layout, normalization, temporal stacking, and the
market-level scalars.

This consolidates what were previously three separate change logs (normalization, history stacking,
market features) plus a plan and an implementation report. Criticism of the design lives in
[known_issues.md](known_issues.md) §5; this document describes what the observation *is*.

Related: [architecture.md](architecture.md) §5, [action_space.md](action_space.md) (price levels are
resolved against the *un*normalized book), [testing.md](testing.md) §4.

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

observation = n_hist frames concatenated, flat 1-D
  default n_hist = 4  →  shape (168,)
  layout: [ O_{t-3} | O_{t-2} | O_{t-1} | O_t ]
  the most recent frame is always the last SNAPSHOT_DIM elements
```

Widths are defined once, in [`state_helper.py`](../envs/exchg/state_helper.py):

```python
K_ROWS = 10
BOOK_DIM = 4 * K_ROWS                  # 40
EXTRA_DIM = 2                          # log_mid, log1p_spread_ticks
SNAPSHOT_DIM = BOOK_DIM + EXTRA_DIM    # 42
```

**Never hardcode 40, 42, 160, or 168.** Import `SNAPSHOT_DIM` (and `BOOK_DIM` when you specifically
mean the book block). The `[-40:]` slicing that predated `EXTRA_DIM` failed *silently* rather than
loudly when the width changed — it returned the last 38 book values plus 2 scalars, misaligning
every block slice by 2 while still passing several assertions.

Ask prices and sizes are stored **negated**; the sign encodes side.

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
\text{norm\_P\_ask}_k = \begin{cases} -\left(\dfrac{|P_{ask,k}| - M}{M}\right) & |P_{ask,k}| > 0 \\ 0.0 & |P_{ask,k}| = 0 \end{cases}$$

Since `P_bid,k <= M <= |P_ask,k|`, bids come out `>= 0` and asks `<= 0` — the sign convention is
preserved, and the magnitude is the percentage distance from the top of the book.

### 2.3 Volumes — square root

$$\text{norm\_V\_bid}_k = +\sqrt{V_{bid,k}} \ge 0 \qquad \text{norm\_V\_ask}_k = -\sqrt{V_{ask,k}} \le 0$$

This dampens extreme volume spikes while preserving relative liquidity signals.

> **Caveat.** `sqrt` stabilises variance *within* the size block but leaves the cross-block scale
> mismatch untouched: normalized prices span roughly ±0.7 while `sqrt(volume)` spans roughly ±430
> for the volumes this environment generates. Both halves feed the same linear layer, so the price
> half is close to invisible at initialization. See [known_issues.md](known_issues.md) §5.5.

### 2.4 Why normalize at all

Raw LOB snapshots carry large unbounded prices and high-variance volumes. Fed directly to a network
they cause gradient instability and slow convergence. Midpoint normalization makes the price
features scale-invariant; the `sqrt` transform compresses volume dynamic range.

---

## 3. Market-level scalars

Two scalars are appended to **every frame** (not once per stack). They are **always on** — there is
no config flag and no second code path.

### 3.1 `log_mid` (index 40)

$$\texttt{log\_mid} = \ln(M)$$

Reuses the `M` already computed for normalization — no extra book queries.

**Range:** ≈ 2.3 – 4.6 for the [10, 100] initial-price range.

**Why it exists.** Midpoint normalization makes the observation scale-free, which *discards `M`
itself*. Two markets at price 10 and price 100 were previously indistinguishable — yet `min_tick`
is absolute (= 1), so one tick is a 10% move in the first market and a 1% move in the second. Agents
were being asked to choose tick-denominated price offsets without being able to perceive what a tick
was worth. `log_mid` restores that anchor.

### 3.2 `log1p_spread_ticks` (index 41)

$$\texttt{log1p\_spread\_ticks} = \ln\!\left(1 + \frac{P_{ask,1} - P_{bid,1}}{\texttt{min\_tick}}\right)
\quad\text{if both L1 sides exist, else } 0.0$$

Computed from the same `l1_bid` / `l1_ask` locals as `M`, so it is guaranteed consistent with the
top of book actually present in the observation.

**`min_tick`, not `tick_size` — deliberate.** `self.tick_size` is never stored and `reset()`
hardcodes `OrderBook(1, ...)`, so the `tick_size` config is silently discarded
([known_issues.md](known_issues.md) §3.7). `Action_Helper.min_tick` (= 1) is the tick the action
space actually quotes in, so this choice makes observation units match action units.

**The `0.0` sentinel is unambiguous.** A resting book can never be locked or crossed — any bid
`>= best ask` is filled on arrival ([matching_engine.md](matching_engine.md) §2) — so a two-sided
book always has `spread >= 1` tick, and every real measurement maps to `log1p(x) >= log1p(1) =
0.693`. `log1p(0) = 0` sits cleanly below the valid range.

**Range:** 0 (sentinel), then ≈ 0.693 – 4.6 for spreads of 1 to 100 ticks.

**Why `log1p` rather than raw `spread / tick`:** raw spread is unbounded — a thin early-episode book
can produce 50+, which would sit beside price features of magnitude ~0.5. `log1p` compresses it to
the same order as `log_mid`, keeps the zero sentinel exact, and preserves monotonicity. The cost is
diminishing sensitivity at wide spreads, which is acceptable: the difference between a 40- and a
50-tick spread matters far less than between 1 and 2.

### 3.3 Why per-frame

Each frame becomes self-describing, and stacking `log(M_t)` per frame lets an agent recover each
frame's own normalizer. That partially mitigates the varying-denominator defect
([known_issues.md](known_issues.md) §5.1), where frames normalized by different `M` values cannot be
compared directly. Appending at the *end* also keeps all existing `[0:10] / [10:20] / [20:30] /
[30:40]` block slicing correct.

---

## 4. Temporal history stacking

### 4.1 Why

A single snapshot at time *t* tells an agent nothing about **how the market arrived** at that state
— whether prices are trending, order flow is accelerating, or a large order is being worked. A
window of the *N* most recent snapshots enables learning momentum and mean-reversion patterns,
distinguishing a stable book from a rapidly evolving one, and aligns better with how human traders
process information.

### 4.2 Design decisions

| Decision | Choice | Rationale |
|---|---|---|
| Observation format | Flat 1-D `(N × SNAPSHOT_DIM,)` | Maximum compatibility with RLlib built-in policies (FCNet, LSTM expect flat inputs) |
| History scope | One shared environment-level `obs_history` deque | All agents observe the same public market; per-agent history would be redundant |
| Default window *N* | 4 | Balances temporal context against input dimensionality |
| Configurability | `config["n_hist"]` | Consistent with the existing RLlib config pattern |

### 4.3 Mechanism

`State_Helper` holds `self.obs_history = deque(maxlen=n_hist)`.

- `reset_traders_agg_LOB()` generates the initial snapshot *O₀* and fills the deque with *N* copies
  of it, then concatenates. Padding with copies of *O₀* rather than zeros avoids misleading agents
  into thinking there was prior inactivity.
- `prep_next_state()` appends the new snapshot (the deque drops the oldest automatically) and
  concatenates.

Every agent receives the same array.

---

## 5. The raw book: `agg_LOB_raw`

Alongside the normalized observation, `set_agg_LOB()` keeps an **unnormalized** 40-element snapshot
in `self.agg_LOB_raw`. This is what `Action_Helper._set_price()` reads to turn an agent's discrete
price-level selection into an actual market price.

**`agg_LOB_raw` is `BOOK_DIM` (40), not `SNAPSHOT_DIM`.** The market scalars are an observation-only
addition; action price resolution (`np.array(agg_LOB_source).reshape(4, 10)`) is untouched by them.
This separation is the key safety property of the design and is pinned by
`test_agg_LOB_raw_still_book_sized`.

`_set_price()` accesses it via `getattr(self, 'agg_LOB_raw', self.agg_LOB)` so `State_Helper` stays
importable independently of the mixin chain.

### Timing

The observation returned at the end of step *t* reflects the book after all of *t*'s orders, and the
`agg_LOB_raw` used to resolve action prices at *t+1* is recomputed from that same book state. There
is no off-by-one between what the agent sees and what its price-level selections resolve against.

One consequence worth knowing: *within* a step, `agg_LOB_raw` is frozen at the start while orders
execute sequentially, so a trader executing fourth prices its levels against a stale book. That is
consistent with the environment's stated "all traders suffer the same lag" assumption, but it does
mean a chosen level can already be crossed by the time it executes.

---

## 6. Consumers of the observation width

Anything that slices an observation must use `SNAPSHOT_DIM` / `BOOK_DIM`:

| Site | Usage |
|---|---|
| [`continuousDoubleAuction_env.py`](../envs/continuousDoubleAuction_env.py) | `Box` shape is `(n_hist * SNAPSHOT_DIM,)` |
| [`exchg_helper.py`](../envs/exchg/exchg_helper.py) `print_table` | Slices the book block before `reshape(4, K_ROWS)`, then prints trailing scalars on their own line. Without the slice, `reshape` raises `ValueError` on **every rendered step**. |
| [`visualize_orderbook.py`](../visualize/visualize_orderbook.py) | Takes `agent_obs[-SNAPSHOT_DIM:]` for the current book state |
| `test_obs_normalization.py`, `test_observation_history.py`, `test_obs_market_features.py` | All shape literals derive from the constants |

Rendered output for the scalars looks like:

```
log_mid = 4.269698; log1p_spread_ticks = 2.302585
```

---

## 7. Verification

The strongest available check is the round trip — inverting both transforms must recover the live
book:

```
OBS SHAPE          = (168,)
best bid/ask raw   = 67.0 / 76.0
exp(log_mid)       = 71.500015     ← matches (67 + 76) / 2 = 71.5
expm1(log1p_spread)= 9.0           ← matches 76 - 67 = 9 ticks
total NAV          = 4,000,000     ← conserved
all finite         = True
```

Test coverage is described in [testing.md](testing.md) §4.

---

## 8. Compatibility

Any policy checkpoint or saved `episode_data` pickle built against an older observation width will
not load against the current one. This is unavoidable whenever the observation dimension changes;
the width has changed twice (40 → 160 with stacking, 160 → 168 with market features).
