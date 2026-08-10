# Plan: Add `log_mid` and `log1p_spread_ticks` to the Observation

**Status:** planned, not implemented.
**Generated:** 2026-08-10 09:01:53

Adds two scalar market features to every observation snapshot, in addition to the existing
40-element orderbook block.

Related: [`observation_analysis_20260810_074327.md`](observation_analysis_20260810_074327.md)
(motivates both features), [`CHANGES_obs_normalization.md`](CHANGES_obs_normalization.md)
(current normalization), [`problems_identified_20260810_070226.md`](problems_identified_20260810_070226.md).

---

## 1. Decisions locked in

| Decision | Choice |
|---|---|
| Delivery | **Always-on.** No config flag, no second code path. |
| Spread transform | **`log1p(spread_ticks)`**, not raw `spread/tick`. |
| Placement | Per-frame, appended at the end of each snapshot. |
| `agg_LOB_raw` | Unchanged at 40 elements. |

Rationale for always-on: the observation shape has already changed twice recently (normalization,
then history stacking), neither of which was gated, so a flag now would create an inconsistent
convention. This codebase's dominant maintenance problem is unexercised alternative code paths
(`policy_handler` vs `policy_handler_0`, old/new RLlib stacks side by side); a second observation
width would become another. If an ablation is needed later, a git branch is the cheaper way to get
it than a permanent runtime switch.

---

## 2. Feature definitions

### 2.1 `log_mid`

$$\texttt{log\_mid} = \ln(M)$$

`M` is the Level-1 midpoint **already computed** inside `set_agg_LOB`
([`state_helper.py:112-121`](../envs/exchg/state_helper.py)), reusing its existing fallback chain:

| condition | `M` |
|---|---|
| both L1 sides present | `(l1_bid + l1_ask) / 2` |
| bid side only | `l1_bid` |
| ask side only | `l1_ask` |
| empty book | `self.last_price` |
| result `<= 0` | `100.0` |

`M` is therefore guaranteed strictly positive and `ln(M)` never faults.

**Range:** initial price is drawn from [10, 100], so `log_mid` sits in roughly **2.3 – 4.6**.

**Why:** the current observation is entirely scale-free — normalization by `M` discards `M`
itself. Two markets at price 10 and price 100 produce identical observations, yet `min_tick` is
absolute (=1), so one tick is a 10% move in the first and a 1% move in the second. The agent is
currently asked to choose tick-denominated price offsets without being able to perceive what a tick
is worth. `log_mid` restores that anchor. See §2.4 of the observation analysis.

### 2.2 `log1p_spread_ticks`

$$\texttt{log1p\_spread\_ticks} = \ln\!\left(1 + \frac{P_{ask,1} - P_{bid,1}}{\texttt{min\_tick}}\right) \quad\text{if both L1 sides exist, else } 0.0$$

Computed from the `l1_bid` / `l1_ask` locals already derived for `M` — no extra `get_best_bid()` /
`get_best_ask()` calls, and guaranteed consistent with the top-of-book actually present in the
observation.

**`min_tick`, not `tick_size`** — deliberate. `self.tick_size` is never stored, and `reset()`
hardcodes `OrderBook(1, ...)`, so the `tick_size` config is silently discarded (§3.6 of the
problems doc). `Action_Helper.min_tick` (=1) is the tick the action space actually quotes in, so
this choice makes observation units match action units.

**Sentinel:** `0.0` for a one-sided or empty book. This stays unambiguous under `log1p`:

- A resting two-sided book always has `spread >= 1` tick — `process_limit_order` fills any bid
  `>= best ask`, so the book can never rest locked or crossed.
- Therefore any real spread maps to `log1p(x) >= log1p(1) = 0.693`.
- `log1p(0) = 0` exactly, sitting cleanly below the valid range.

**Range:** 0 (sentinel), then **0.693 – ~4.6** for spreads of 1 to 100 ticks.

**Why `log1p` over raw:** raw `spread/tick` is unbounded — a thin early-episode book can produce
50+, which would sit next to price features of magnitude ~0.5. `log1p` compresses this to the same
order as `log_mid`, keeps the zero sentinel exact, and preserves monotonicity. The cost is
diminishing sensitivity at wide spreads, which is acceptable: the difference between a 40- and
50-tick spread matters far less than between 1 and 2.

---

## 3. Layout and shape

Each snapshot grows from 40 to **42** elements:

```
index    0:10   normalized bid prices     (unchanged)
        10:20   normalized bid sizes      (unchanged)
        20:30   normalized ask prices     (unchanged)
        30:40   normalized ask sizes      (unchanged)
           40   log_mid                   (new)
           41   log1p_spread_ticks        (new)
```

Stacked observation: `n_hist * 42`. Default `n_hist = 4` → **(168,)**, up from (160,).

**Per-frame, not once per stack.** Each frame becomes self-describing, and stacking `log(M_t)` per
frame lets the agent recover each frame's own normalizer — which partially repairs the
varying-denominator defect described in §2.1 of the observation analysis, where frames normalized
by different `M` values cannot be compared. This is a real secondary benefit and the reason the
scalars are not appended once at the end of the stacked vector.

**Appended at the end**, so all existing `[0:10] / [10:20] / [20:30] / [30:40]` block slicing
remains correct.

**`agg_LOB_raw` stays at 40.** Action price resolution
(`np.array(agg_LOB_source).reshape(4, 10)` at
[`action_helper.py:256`](../envs/exchg/action_helper.py) and
[`:266`](../envs/exchg/action_helper.py)) is untouched. This is the key safety property of the
design: only the normalized observation changes.

---

## 4. Files to change

### 4.1 `envs/exchg/state_helper.py` — core change

- Add module-level constants: `K_ROWS = 10`, `BOOK_DIM = 4 * K_ROWS` (40), `EXTRA_DIM = 2`,
  `SNAPSHOT_DIM = BOOK_DIM + EXTRA_DIM` (42). Exported so nothing downstream hardcodes the width
  again.
- In `set_agg_LOB`, after the four normalized blocks are built, compute `log_mid` and
  `log1p_spread_ticks` from the existing `M`, `l1_bid`, `l1_ask` locals and concatenate them onto
  `flattened`.
- `self.agg_LOB_raw` assignment stays exactly as-is.

### 4.2 `envs/continuousDoubleAuction_env.py` (lines 66-80)

Replace the `obs_row = 4` / `obs_col = 10` literals with `self.n_hist * SNAPSHOT_DIM` in the
`Box` shape.

### 4.3 `envs/exchg/exchg_helper.py` `print_table` (lines 80-94) — **crashes otherwise**

Current code:

```python
k = len(data) // 4
reshaped = data.reshape(4, k).T
```

With 42 elements: `42 // 4 = 10`, and `reshape(4, 10)` on a 42-element array raises `ValueError`.
`render()` runs on **every step** with `is_render` defaulting to `True`, so this would break
immediately.

Fix: slice the first `BOOK_DIM` elements for the level table, and print any trailing scalars as a
separate labeled line.

### 4.4 Tests — **silent breakage, the real hazard**

| File | Line(s) | Problem |
|---|---|---|
| `test_obs_normalization.py` | 53 | `obs[agent_id][-40:]` would return the last 38 book values plus the 2 new scalars, misaligning every block slice by 2 while still passing some assertions. Change to `[-SNAPSHOT_DIM:]`. |
| `test_obs_normalization.py` | 94, 274 | Assert the empty book equals `np.zeros(40)`. No longer true: `log_mid` is non-zero on an empty book (it falls back to `last_price`). Assert the *book portion* is zero and check the two scalars explicitly. |
| `test_observation_history.py` | 14, 15, 21, 33, 35, 44, 52, 54, 58 | `40` → `42`, `160` → `168`. |

New tests to add:

- `log_mid` equals `np.log(M)` for a known two-sided book.
- `log1p_spread_ticks` equals `np.log1p((ask - bid) / min_tick)` for a known two-sided book.
- Sentinel is exactly `0.0` on a bid-only book, an ask-only book, and an empty book.
- Sentinel is distinguishable: any populated two-sided book yields `>= log1p(1)`.
- Both scalars are present in **every** frame of the stacked observation, not just the last.
- Shape is `(n_hist * 42,)` across `n_hist` in {1, 2, 4, 6, 10}.
- No NaN/Inf in the full observation across a random rollout.

### 4.5 `visualize/visualize_orderbook.py` (lines 42-47)

`agent_obs[-40:]` has the same silent-misalignment problem. Change to `[-42:]` and update the
layout comment block at lines 36-40.

### 4.6 Documentation

- README observation section: shape `(160,)` → `(168,)`, and the snapshot layout diagram.
- An addendum to `CHANGES_obs_normalization.md` (or a sibling changes doc) recording the two new
  features, their formulas, ranges, and sentinel semantics.

---

## 5. Out of scope

Explicitly not touched by this change:

- `agg_LOB_raw` and action price resolution.
- The reward function.
- The `tick_size`-dropped-on-reset bug (noted, worked around by using `min_tick`).
- Size normalization, the zero-collision issue, the dead tape loop, private state, or any other
  defect from the observation analysis.

---

## 6. Known caveat: these features may not help until size normalization is fixed

Both new features land in the **0 – 4.6** range, comparable to each other and to the normalized
price block (~0.5). But the `sqrt(volume)` size block spans roughly **±430** for the volumes this
environment generates (§2.5 of the observation analysis). All 22 well-scaled features are therefore
still two to three orders of magnitude smaller than the 20 size features they share a linear layer
with.

The features are correct and worth adding, but the measurable benefit may be small until the size
block is rescaled (`V / sum(V)` or `log1p(V)`). That is a separate change; flagging it here so a
null result from this one is not misread as evidence the features are useless.

---

## 7. Other notes

- **Checkpoint incompatibility.** Any existing trained policy or saved `episode_data` pickle is
  built against a 160-dim observation and will not load against 168. Unavoidable when the dimension
  changes.
- **Verification.** `gymnasium` and `ray` are not installed in the current environment, so
  env-level tests cannot run as-is. `continuousDoubleAuction_env.py` imports `ray`, so running the
  full suite requires installing both (ray is a heavy install). Alternative: install `gymnasium`
  only and exercise `set_agg_LOB` against a stub book, bypassing the env import. To be confirmed
  before implementation.

---

## 8. Implementation order

1. `state_helper.py` — constants and the two features.
2. `continuousDoubleAuction_env.py` — observation space shape.
3. `exchg_helper.py` — `print_table` fix (before running anything with `is_render=True`).
4. Update the two affected test files; add the new test cases.
5. `visualize_orderbook.py` slicing and comments.
6. README and changes-doc updates.
7. Run the suite and report results.
