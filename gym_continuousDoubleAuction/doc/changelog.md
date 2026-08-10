# Changelog

Modernizations made to `gym-continuousDoubleAuction` since the `original_v1` branch (released 2020),
in rough chronological order.

Each entry links to the document that describes the *current* state of that area; this file records
what changed and why, not how things work today.

---

## Version 2 (2025-12-24 onward)

### 1. Dependency modernization

- **Gymnasium migration** — switched from the legacy `gym` package to `gymnasium`.
- **Ray RLlib update** — compatibility with Ray 2.4+, notably the transition from `dones` to
  `terminated` and `truncated`.

### 2. Environment API (Ray 2.4+)

`step` and `reset` now follow the current multi-agent environment standard:

- `reset()` returns `(observations, infos)` instead of just `observations`.
- `step()` returns the 5-tuple `(obs, rewards, terminateds, truncateds, infos)` instead of the old
  4-tuple.

See [architecture.md](architecture.md) §5.

### 3. Self-play: league-based replaces naive

| | Approach |
|---|---|
| `original_v1` | **Naive self-play** with competitive weight copying — two policies competed and the winner's weights were periodically copied onto the loser |
| Current | **League-based self-play** with champion snapshotting |

Multiple learning policies now evolve independently with no weight copying; exceptional performances
are frozen as "champions" and added to a rotating opponent pool, with a rolling window maintaining
diversity. This prevents catastrophic forgetting and stops agents over-optimizing against a single
opponent.

See [self_play_league.md](self_play_league.md).

### 4. Redesigned action space

| | Structure |
|---|---|
| Original | Nested `Tuple` — `(side, type, size_mean, size_sigma, price_code)` with a 12-value price code |
| Current | Flat `Dict` per agent |

- **Category mapping** — separate `side` and `type` collapsed into one `category` (0–8) covering
  none plus buy/sell × market/limit/modify/cancel.
- **Price offsets** — a new `price_offset` dimension (passive / join / aggressive) makes it possible
  to *join* a price level, which the old forced ±1-tick mapping prevented.
- **Deterministic anchoring** — "ghost levels" replaced the old random-price fallback for empty book
  levels, eliminating the non-stationarity that made price codes behave like a lottery in thin
  books.

See [action_space.md](action_space.md), which retains the legacy design and the full rationale.

### 5. Robust testing

- **Granular unit testing** — moved from manual scripts to a formal `unittest` suite covering every
  component (`Order`, `OrderList`, `OrderTree`) and process (NAV calculation, position tracking).
- **Precision accounting** — replaced floats with `Decimal` throughout the accounting layer,
  eliminating rounding error in financial simulation.
- **Complex scenario coverage** — dedicated tests for position flips (atomic long-to-short
  transitions), crossed books, and volume synchronization.

See [testing.md](testing.md). Note the caveat in [known_issues.md](known_issues.md) §4: **no CI
runs any of it.**

### 6. Order modification fix

`OrderBook.modify_order` previously updated price and quantity in place without re-running the
matching engine, so a modification could leave the book crossed. Modifications that can trigger a
trade are now removed and re-processed through `process_limit_order`; only a quantity *decrease* at
the *same* price is updated in place and keeps queue priority. The trader's accounting gained an
"undo-then-process" flow so balances stay exact when a modification fills.

See [matching_engine.md](matching_engine.md) §3.

### 7. Reward function refinement

Replaced raw NAV change with a multi-factor formula: asymmetric loss aversion, an order-placement
penalty for selectivity, a per-trade execution penalty, a drawdown penalty, and a passive-fill bonus
for liquidity provision. The account gained `max_nav` and three per-step counters to support it.

See [reward_function.md](reward_function.md). Two structural defects in this formula are recorded in
[known_issues.md](known_issues.md) §2.1–2.2.

### 8. Observation pipeline — three successive changes

The observation has changed shape twice and gained two transforms. All are described in
[observation_space.md](observation_space.md).

**8a. Midpoint normalization and action unnormalization** — price depth scaled relative to the
Level-1 midpoint `M`: bids `(M − P)/M ≥ 0`, asks `−((|P| − M)/M) ≤ 0`, preserving the sign
convention. Volumes scaled `±√V` to stabilize variance. Because agents now perceive normalized
values but must submit real prices, the unnormalized book is kept in parallel as `agg_LOB_raw` and
used for action price resolution.

**8b. Temporal history stacking** — the environment now returns the last *N* sequential snapshots as
one flat vector instead of a single frame. Default `n_hist = 4`. This change also exposed and fixed
cooperative-multiple-inheritance bugs across `State_Helper`, `Action_Helper`, and `Exchg_Helper`
(kwargs reaching `object.__init__`), and required a `print_table` fix for the new flat array format.

Observation shape: `(40,)` → `(160,)`.

**8c. Market-level scalars** — `log_mid` and `log1p_spread_ticks` appended to every frame, always on
with no config flag. These restore the price anchor that midpoint normalization discards, so agents
can perceive what an absolute tick is worth.

Observation shape: `(160,)` → `(168,)`; snapshot 40 → 42. Widths are now derived from `SNAPSHOT_DIM`
constants rather than hardcoded, because the previous `[-40:]` slicing failed *silently* rather than
loudly when the width changed.

> **Checkpoint compatibility:** any policy checkpoint or `episode_data` pickle built against an
> older observation width will not load against the current one.

### 9. Documentation

The `/doc` folder was expanded with deep dives on the action space, accounting, temporal stacking,
and observation normalization, then **restructured** (this revision) into eleven topic-based
documents indexed by [README_v2.md](README_v2.md), replacing the previous mix of per-test
walkthroughs, dated analysis snapshots, plans, and implementation reports.
