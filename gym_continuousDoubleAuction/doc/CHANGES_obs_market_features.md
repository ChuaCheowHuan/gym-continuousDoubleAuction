# Market-Level Observation Features (`log_mid`, `log1p_spread_ticks`) — Change Log

Implements the plan in
[`plan_obs_extra_features_20260810_090153.md`](plan_obs_extra_features_20260810_090153.md).
Motivation is documented in
[`observation_analysis_20260810_074327.md`](observation_analysis_20260810_074327.md) §2.4.

---

## 1. Summary

Two scalar market features are appended to every observation snapshot, in addition to the existing
40-element orderbook block. The snapshot grows from **40 to 42** elements; the default stacked
observation grows from **(160,) to (168,)**.

The features are **always on** — there is no config flag and no second code path.

---

## 2. Feature definitions

### 2.1 `log_mid` (index 40)

$$\texttt{log\_mid} = \ln(M)$$

`M` is the Level-1 midpoint already computed inside `set_agg_LOB`, reusing its existing fallback
chain:

| condition | `M` |
|---|---|
| both L1 sides present | `(l1_bid + l1_ask) / 2` |
| bid side only | `l1_bid` |
| ask side only | `l1_ask` |
| empty book | `self.last_price` |
| result `<= 0` | `100.0` |

`M` is therefore always strictly positive and `ln(M)` never faults.

**Range:** ~2.3 – 4.6 for the [10, 100] initial-price range.

**Why:** midpoint normalization makes the observation scale-free and discards `M` itself. Two
markets at price 10 and price 100 were previously indistinguishable, yet `min_tick` is absolute
(=1), so one tick is a 10% move in the first and a 1% move in the second. Agents were being asked
to choose tick-denominated price offsets without being able to perceive what a tick was worth.

### 2.2 `log1p_spread_ticks` (index 41)

$$\texttt{log1p\_spread\_ticks} = \ln\!\left(1 + \frac{P_{ask,1} - P_{bid,1}}{\texttt{min\_tick}}\right) \quad\text{if both L1 sides exist, else } 0.0$$

Computed from the `l1_bid` / `l1_ask` locals already derived for `M`, so it needs no extra book
queries and is guaranteed consistent with the top-of-book actually present in the observation.

**`min_tick`, not `tick_size`** — deliberate. `self.tick_size` is never stored and `reset()`
hardcodes `OrderBook(1, ...)`, so the `tick_size` config is silently discarded. `Action_Helper.min_tick`
(=1) is the tick the action space actually quotes in, so this choice makes observation units match
action units.

**Sentinel:** `0.0` for a one-sided or empty book, and it cannot collide with a real measurement:

- A resting book can never be locked or crossed — `process_limit_order` fills any bid `>= best ask`
  on arrival — so a two-sided book always has `spread >= 1` tick.
- Therefore every real spread maps to `log1p(x) >= log1p(1) = 0.693`.
- `log1p(0) = 0` exactly, sitting cleanly below the valid range.

**Range:** 0 (sentinel), then ~0.693 – 4.6 for spreads of 1 to 100 ticks.

**Why `log1p` rather than raw `spread/tick`:** raw spread is unbounded — a thin early-episode book
can produce 50+, which would sit beside price features of magnitude ~0.5. `log1p` compresses it to
the same order as `log_mid`, keeps the zero sentinel exact, and preserves monotonicity. The cost is
diminishing sensitivity at wide spreads, which is acceptable: the difference between a 40- and a
50-tick spread matters far less than between 1 and 2.

---

## 3. Layout

```
index    0:10   normalized bid prices     (unchanged)
        10:20   normalized bid sizes      (unchanged)
        20:30   normalized ask prices     (unchanged)
        30:40   normalized ask sizes      (unchanged)
           40   log_mid                   (new)
           41   log1p_spread_ticks        (new)
```

**Per-frame, not once per stack.** Each frame is self-describing, and stacking `log(M_t)` per frame
lets an agent recover each frame's own normalizer — which partially mitigates the varying-denominator
issue described in §2.1 of the observation analysis, where frames normalized by different `M` values
cannot be compared directly.

**Appended at the end**, so all existing `[0:10] / [10:20] / [20:30] / [30:40]` block slicing stays
correct.

**`agg_LOB_raw` is unchanged at 40 elements.** Action price resolution
(`np.array(agg_LOB_source).reshape(4, 10)`) is untouched — only the normalized observation changed.
This invariant is covered by `test_agg_LOB_raw_still_book_sized`.

---

## 4. Code changes

| File | Change |
|---|---|
| `envs/exchg/state_helper.py` | Added `K_ROWS`, `BOOK_DIM`, `EXTRA_DIM`, `SNAPSHOT_DIM` module constants. `set_agg_LOB()` computes and appends the two scalars. |
| `envs/continuousDoubleAuction_env.py` | Observation `Box` shape now `(n_hist * SNAPSHOT_DIM,)`; removed the `obs_row`/`obs_col` literals. |
| `envs/exchg/exchg_helper.py` | `print_table()` now slices the book block before reshaping and prints trailing scalars on their own line. Without this, `reshape(4, 42 // 4)` raises `ValueError` on every render. |
| `test/test_obs_normalization.py` | Snapshot slicing uses `SNAPSHOT_DIM`; the two empty-book assertions now check the book block plus the scalars explicitly. |
| `test/test_observation_history.py` | Shape literals replaced with `SNAPSHOT_DIM`. |
| `test/test_obs_market_features.py` | **New** — 17 tests for the two features. |
| `visualize/visualize_orderbook.py` | Snapshot slicing uses `SNAPSHOT_DIM`; layout comment updated. |
| `README.md` | Observation space section updated. |

### Silent-breakage note

The `[-40:]` slicing in the tests and the visualizer would **not** have raised an error after this
change — it would have returned the last 38 book values plus the 2 new scalars, misaligning every
block slice by 2 while still passing several assertions. All such sites were migrated to
`SNAPSHOT_DIM`.

---

## 5. Test coverage

`test/test_obs_market_features.py` (17 tests):

- `SNAPSHOT_DIM == BOOK_DIM + EXTRA_DIM`; observation shape across `n_hist` in {1, 2, 4, 6, 10}.
- `agg_LOB_raw` remains `(40,)` before and after book changes.
- `log_mid` correctness for two-sided, bid-only, ask-only, and empty books, plus the
  non-positive `last_price` fallback to 100.0.
- `log1p_spread_ticks` correctness for a known two-sided book, the 1-tick floor, and monotonicity
  across widening spreads.
- Sentinel is exactly `0.0` for one-sided and empty books, and every real spread is
  `>= log1p(1)`, so the sentinel is separable.
- Both scalars present in every frame of the stacked observation.
- Existing book-block slicing and sign conventions unaffected.
- No NaN/Inf across a random multi-agent rollout.

**Suite result:** 89 tests pass (72 pre-existing + 17 new). Verified end-to-end with `is_render=True`,
including the round trip `exp(log_mid)` and `expm1(log1p_spread_ticks)` recovering the actual
midpoint and tick spread from the live book, with total NAV conserved.

---

## 6. Known caveat

Both new features land in the **0 – 4.6** range, comparable to each other and to the normalized
price block (~0.5). But the `sqrt(volume)` size block spans roughly **±430** for the volumes this
environment generates. All 22 well-scaled features are therefore still two to three orders of
magnitude smaller than the 20 size features they share a linear layer with.

The features are correct and worth having, but the measurable benefit may be small until the size
block is rescaled (`V / sum(V)` or `log1p(V)`). That is a separate change; recorded here so a null
result from this one is not misread as evidence the features are useless.

---

## 7. Compatibility

Any policy checkpoint or saved `episode_data` pickle built against the 160-dim observation will not
load against 168. This is unavoidable when the observation dimension changes.
