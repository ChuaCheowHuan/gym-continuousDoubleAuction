# Implementation Report: `log_mid` and `log1p_spread_ticks` Observation Features

**Generated:** 2026-08-10 09:50:17
**Status:** implemented, tested, all green.

A session record of what was installed, changed, and verified.

## Relationship to the other docs

These four are complementary, not duplicates:

| Document | Answers |
|---|---|
| [`plan_obs_extra_features_20260810_090153.md`](plan_obs_extra_features_20260810_090153.md) | What was going to be done, and why |
| [`CHANGES_obs_market_features.md`](CHANGES_obs_market_features.md) | What the feature **is** (stable name; linked from README) |
| **this file** | What was actually **done and verified** in this session |
| [`observation_analysis_20260810_074327.md`](observation_analysis_20260810_074327.md) | Why these features were needed |

---

## 1. Scope

Add two market-level scalars to every observation snapshot, in addition to the existing 40-element
orderbook block:

- `log_mid` = `log(M)`
- `log1p_spread_ticks` = `log1p(spread / min_tick)`, `0.0` when the book is not two-sided

Confirmed decisions: **always-on** (no config flag), and **`log1p`** rather than raw `spread/tick`.

Snapshot: **40 → 42**. Default stacked observation: **(160,) → (168,)**.

---

## 2. Environment setup

The pinned `requirements.txt` includes `torch==2.7.1+cu126`, the full NVIDIA CUDA stack, and
JupyterLab — roughly 3 GB, none of which the environment or its tests import. Installed only the
actual import closure:

```
gymnasium==1.0.0
ray[tune,rllib]==2.48.0
dm-tree==0.1.9
numpy==2.2.6
scipy==1.15.3
pandas==2.3.0
scikit-learn==1.7.2
sortedcontainers==2.4.0
tabulate==0.9.0
six==1.17.0
lz4==4.4.4
```

Two non-obvious findings, recorded for anyone repeating the setup:

1. **Bare `ray` is not enough to import `MultiAgentEnv`.** `ray.rllib.env.multi_agent_env` pulls in
   `ray.rllib.utils`, which imports `tree` (the `dm-tree` package) and then `ray.tune`. Installing
   plain `ray==2.48.0` fails with `ModuleNotFoundError: No module named 'tree'`, and after fixing
   that, `ImportError: Can't import ray.tune as some dependencies are missing`. The `[tune,rllib]`
   extras are required even to construct the env.
2. **numpy needs pinning.** Installing without a pin resolved to 2.5.2; `requirements.txt` pins
   2.2.6, which was restored.

---

## 3. Baseline before any change

Verified the repository worked *before* editing, so any later failure could be attributed:

```
72 tests ... OK
```

Smoke test — 4 agents, 5 random steps:

```
env import OK
reset OK; obs shape (160,)
5 steps OK; obs shape (160,)
total NAV 4000000.0        <- conserved (4 agents x 1,000,000)
```

---

## 4. Changes made

### 4.1 `envs/exchg/state_helper.py` — core change

Added module-level layout constants so the width is defined in exactly one place:

```python
K_ROWS = 10
BOOK_DIM = 4 * K_ROWS       # 40
EXTRA_DIM = 2               # log_mid, log1p_spread_ticks
SNAPSHOT_DIM = BOOK_DIM + EXTRA_DIM   # 42
```

`set_agg_LOB()` now computes both scalars from the `M`, `l1_bid`, `l1_ask` locals it already had —
no extra book queries — and appends them:

```python
log_mid = np.log(M)

if l1_bid > 0 and l1_ask > 0:
    min_tick = getattr(self, 'min_tick', 1)
    if min_tick <= 0:
        min_tick = 1
    spread_ticks = (l1_ask - l1_bid) / min_tick
    log1p_spread_ticks = np.log1p(max(0.0, spread_ticks))
else:
    log1p_spread_ticks = 0.0

extras = np.array([log_mid, log1p_spread_ticks])
flattened = np.concatenate([norm_bid_price, norm_bid_size,
                            norm_ask_price, norm_ask_size, extras]).astype(np.float32)
```

`getattr(self, 'min_tick', 1)` matches the existing `getattr(self, 'last_price', 100.0)` convention
in the same function, keeping `State_Helper` importable on its own despite the mixin coupling.

### 4.2 `envs/continuousDoubleAuction_env.py`

Observation space now derives its width from the constant; the `obs_row = 4` / `obs_col = 10`
literals and their commented-out predecessors were removed.

```python
shape=(self.n_hist * SNAPSHOT_DIM,)
```

### 4.3 `envs/exchg/exchg_helper.py` — a real crash, as predicted

`print_table` did `k = len(data) // 4` then `data.reshape(4, k)`. With 42 elements that is
`reshape(4, 10)` on a 42-element array → `ValueError`. `render()` runs every step with `is_render`
defaulting to `True`, so this would have broken immediately on the first rendered run.

Now slices the book block before reshaping and prints the scalars on their own line:

```
log_mid = 4.269698; log1p_spread_ticks = 2.302585
```

Also hoisted the function-local `import numpy as np` to module scope.

### 4.4 Tests

| File | Change |
|---|---|
| `test/test_obs_normalization.py` | `_get_snapshot` uses `SNAPSHOT_DIM`; the two empty-book assertions now check the book block is zero **and** verify the scalars explicitly (an empty book is no longer all-zero — `log_mid` falls back to `last_price`). |
| `test/test_observation_history.py` | All `40` / `160` literals replaced with `SNAPSHOT_DIM`. |
| `test/test_obs_market_features.py` | **New**, 17 tests. |

New coverage: constant arithmetic; shape across `n_hist` ∈ {1, 2, 4, 6, 10}; `agg_LOB_raw` remains
`(40,)`; `log_mid` for two-sided / bid-only / ask-only / empty books and the non-positive
`last_price` fallback; `log1p_spread_ticks` correctness, the 1-tick floor, and monotonicity across
widening spreads; sentinel is exactly `0.0` when not two-sided and every real spread is
`>= log1p(1)`; both scalars present in every frame of the stack; existing block slicing and sign
conventions unaffected; no NaN/Inf across a random rollout.

Tests build books by inserting directly via `env.LOB.process_order(...)` at known prices, rather
than going through the action pipeline, so expected values are exact rather than dependent on the
stochastic size sampling.

### 4.5 `visualize/visualize_orderbook.py`

`agent_obs[-40:]` → `agent_obs[-SNAPSHOT_DIM:]`, layout comment extended with indices 40 and 41.

### 4.6 Documentation

- `README.md` — observation section: shape, 42-element layout, and an explanation of both scalars.
- `doc/CHANGES_obs_market_features.md` — new feature changelog, linked from the README.

---

## 5. Verification

```
89 tests ... OK          (72 pre-existing + 17 new, no regressions)
```

End-to-end run with `is_render=True`, which exercises the `print_table` path on every step:

```
OBS SHAPE          = (168,)
best bid/ask raw   = 67.0 / 76.0
exp(log_mid)       = 71.500015     <- matches (67 + 76) / 2 = 71.5
expm1(log1p_spread)= 9.0           <- matches 76 - 67 = 9 ticks
total NAV          = 4,000,000     <- conserved
all finite         = True
```

The round trip is the strongest check available: inverting both transforms recovers the actual
midpoint and tick spread of the live book.

Also grepped for surviving hardcoded observation widths (`[-40:]`, `(160,)`, `n_hist * 40`,
`reshape(4, k)`) across the package — none remain.

---

## 6. Discoveries and deviations

Nothing in the plan had to be abandoned. Four things worth recording:

1. **The `print_table` crash was real, not theoretical.** Confirmed by the arithmetic and by the
   fact that the rendered run now prints correctly through that path.
2. **The `[-40:]` slicing would have failed silently, not loudly.** After the change it returns the
   last 38 book values plus the 2 new scalars — every block slice misaligned by 2, with several
   assertions still passing. This is why every such site was migrated to `SNAPSHOT_DIM` rather than
   having its number bumped.
3. **Test-count correction.** Earlier documents in this series stated "39 unit tests", taken from a
   `head`-truncated grep. The real baseline is **72**. Corrected in two places in
   [`problems_identified_20260810_070226.md`](problems_identified_20260810_070226.md).
4. **Running the suite creates `episode_data/`.** `test_nav_callback` triggers the league callback's
   unconditional per-episode pickle dump (flagged as §3.9 in the problems doc). Two `.pkl` files
   were written into the repository root; removed. The directory is **not** in `.gitignore`, so it
   reappears on every test run and will show up as untracked noise.

---

## 7. Files touched

```
M  README.md
M  gym_continuousDoubleAuction/doc/problems_identified_20260810_070226.md
M  gym_continuousDoubleAuction/envs/continuousDoubleAuction_env.py
M  gym_continuousDoubleAuction/envs/exchg/exchg_helper.py
M  gym_continuousDoubleAuction/envs/exchg/state_helper.py
M  gym_continuousDoubleAuction/test/test_obs_normalization.py
M  gym_continuousDoubleAuction/test/test_observation_history.py
M  gym_continuousDoubleAuction/visualize/visualize_orderbook.py
?? gym_continuousDoubleAuction/doc/CHANGES_obs_market_features.md
?? gym_continuousDoubleAuction/test/test_obs_market_features.py
?? gym_continuousDoubleAuction/doc/implementation_report_obs_market_features_20260810_095017.md
```

Not touched, by design: `agg_LOB_raw`, action price resolution, the reward function, the
`tick_size`-dropped-on-reset bug (worked around by using `min_tick`), size normalization, and every
other defect listed in the analysis documents.

---

## 8. Caveats and follow-ups

- **Scale.** Both new features sit in 0 – 4.6, comparable to each other and to the normalized price
  block (~0.5). The `sqrt(volume)` size block spans roughly ±430. All 22 well-scaled features
  remain two to three orders of magnitude smaller than the 20 size features sharing their linear
  layer, so the measurable benefit may be small until the size block is rescaled
  (`V / sum(V)` or `log1p(V)`). Flagged so a null result here is not misread as the features being
  useless.
- **Checkpoints.** Any policy or `episode_data` pickle built against 160 dims will not load against
  168. Unavoidable when the observation dimension changes.
- **Suggested next steps**, in order of value: add private state (position, cash, NAV, VWAP,
  drawdown, own resting orders); normalize the whole stack by the current `M_t` instead of storing
  pre-normalized frames; finish the dead tape loop to add trade-flow features. See §7 of the
  observation analysis.
- **Add `episode_data/` to `.gitignore`**, or gate the callback's pickle dump behind a flag.
