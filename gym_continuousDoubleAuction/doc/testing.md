# Testing

The complete unit test suite: what each file covers, what invariants it pins down, and how to run
it.

This consolidates what were previously eight separate per-test-file walkthroughs. Every suite uses
the standard-library `unittest` module — **no pytest dependency** — so tests run directly from a
notebook via `%run` as well as from a shell.

Related: [matching_engine.md](matching_engine.md), [accounting.md](accounting.md),
[observation_space.md](observation_space.md), [action_space.md](action_space.md),
[reward_function.md](reward_function.md).

---

## 0. Running the suite

From the repository root:

```bash
python -m unittest discover -s gym_continuousDoubleAuction/test -p "test_*.py" -v
```

Or an individual file:

```bash
python gym_continuousDoubleAuction/test/test_orderbook_new.py
python gym_continuousDoubleAuction/test/test_accounting.py
python gym_continuousDoubleAuction/test/test_obs_normalization.py
```

Or from `test.ipynb`:

```python
%run ../gym_continuousDoubleAuction/test/test_observation_history.py
%run ../gym_continuousDoubleAuction/test/test_new_action_space.py
```

Expected output per file:

```
.....
----------------------------------------------------------------------
Ran N tests in X.XXXs

OK
```

### File inventory

| File | Tests | Area |
|---|---|---|
| `test_orderbook_new.py` | 12 | Matching engine components and integration |
| `test_orderbook_crossed_book.py` | 1 | Crossed-book invariant |
| `test_orderbook_double_delete_order.py` | 1 | Double-delete regression |
| `test_orderbook_volume_sync.py` | 1 | Volume cache synchronization |
| `test_accounting.py` | 13 | Cash, position, NAV, position flips |
| `test_cash_check.py` | 7 | Order approval and cash gating |
| `test_modify_order.py` | 6 | Modify-order accounting scenarios |
| `test_new_action_space.py` | 8 | Action decoding and ghost pricing |
| `test_obs_normalization.py` | 12 | Price/volume normalization, action unnormalization |
| `test_observation_history.py` | 5 | Temporal stacking |
| `test_obs_market_features.py` | 17 | `log_mid`, `log1p_spread_ticks` |
| `test_reward_logic.py` | 4 | Reward formula components |
| `test_nav_callback.py` | 2 | Episode-end NAV conservation check |
| `test_probabilistic_mapping.py` | script | League matchmaking distribution |

> **Note on a stale reference.** Older documentation referred to `test_orderbook.py` and
> `repro_orderbook_crossed_book.py`. Neither file exists; the current names are
> `test_orderbook_new.py` and `test_orderbook_crossed_book.py`.

> **Side effect.** Running the suite creates `episode_data/` in the repository root —
> `test_nav_callback` triggers the league callback's unconditional per-episode pickle dump. The
> directory is not in `.gitignore`, so it reappears as untracked noise on every run. See
> [known_issues.md](known_issues.md) §3.9.

---

## 1. Matching engine

### 1.1 `test_orderbook_new.py`

**Group A — component validation (`TestOrderComponents`)**

| Test | Verifies |
|---|---|
| `test_order_init` | `Order` parses a quote dict, casting every field to the right type (`Decimal` for price/quantity) |
| `test_order_list_append_remove` | FIFO time priority: first order is head *and* tail; a second becomes the new tail; `Order1.next` points at `Order2`; removing the head promotes `Order2` |
| `test_order_tree_insert_remove` | Prices map to `OrderList` objects, total volume increments on insert, and the price level is removed entirely when its last order leaves |

**Group B — trading logic (`TestOrderBookIntegration`)**

| Test | Verifies |
|---|---|
| `test_limit_order_placement` | A passive bid below every ask generates no trade and becomes the best bid |
| `test_limit_order_full_match` | An aggressive bid at 100 against a resting ask at 100 produces exactly one trade and empties the ask |
| `test_limit_order_partial_match` | A bid for 15 against a resting ask for 10 trades 10 and rests the remaining 5 on the bid side |
| `test_market_order_execution` | A market bid larger than the top level sweeps 100 then 101 |
| `test_cancel_order` | Cancelling by `order_id` returns that price level's volume to zero |
| `test_modify_order_quantity_decrease` | Reducing 10 → 5 updates book volume without losing priority |
| `test_modify_order_price_change` | **Marked `@unittest.expectedFailure`** — moving an order between price levels corrupts internal counters. Documents a known limitation rather than asserting correctness |

**Group C — invariants (`TestOrderBookInvariants`)**

| Test | Verifies |
|---|---|
| `test_empty_book_market_order` | A market order against an empty book returns zero trades instead of crashing |
| `test_order_id_uniqueness` | Every processed order gets a unique, incrementing ID |

### 1.2 Crossed-book invariant — `test_orderbook_crossed_book.py`

`test_modify_order_does_not_cross_book` checks that a resting book can never be left crossed by a
modification.

1. Place an ask: limit, 10 @ 100, `S1`. Best ask = 100.
2. Place a bid: limit, 10 @ 90, `B1`. Best bid = 90, spread = 10. Capture the `order_id`.
3. **Modify the bid to 110 @ 10** — a price well above the best ask.
4. Read back `best_bid` and `best_ask`. If both exist, assert `best_bid < best_ask`.

Either the engine matches the crossing modification immediately, or it must at minimum refuse to
leave `best_bid >= best_ask` resting. A failure here means the matching engine corrupted market
state during modification.

### 1.3 Double-delete regression — `test_orderbook_double_delete_order.py`

`test_modify_order_price_no_double_delete` guards a specific internal-consistency bug.

1. Place a bid: limit, 10 @ 100, `B1`. It lands in the `OrderList` at price 100.
2. Modify it to 101 @ 10 at timestamp 2.

Changing an order's price is two micro-steps — **remove** from the `OrderList` at 100, **insert**
into the one at 101. The bug the test guards against is the update logic attempting the removal
*again* after the order has already moved, which surfaces as a `ValueError` (removing an item not
in the list) or as an internal volume/length counter going negative.

The `modify_order` call is wrapped in `try/except`; the test asserts no `ValueError` is raised.

### 1.4 Volume synchronization — `test_orderbook_volume_sync.py`

`test_partial_fill_volume_sync` verifies that `OrderTree`'s **cached** volume stays equal to the
**actual** sum of order volumes after a partial fill. A helper, `get_calculated_volume(side)`,
iterates `price_map` and sums every `OrderList` to produce ground truth.

1. Place an ask: limit, 10 @ 100, `S1`. Assert `OrderTree.volume == 10` **and**
   `get_calculated_volume('ask') == 10`.
2. Place a bid: limit, 4 @ 100, `B1` — a marketable limit that partially fills the ask.
   - 4 units trade; the resting ask drops from 10 to 6; the ask tree's total must decrease by 4.
3. Assert `OrderTree.volume == 6` **and** `get_calculated_volume('ask') == 6`.

If the cached figure stays at 10, the cache has desynchronized from reality — the exact class of bug
this test exists to catch.

---

## 2. Accounting

### 2.1 `test_accounting.py` (13 tests)

Concepts under test are described in [accounting.md](accounting.md). Starting NAV is 1000 in most
scenarios.

| # | Test | Verifies |
|---|---|---|
| 1 | `test_limit_order_placement_hold` | Placing a limit buy 1 @ 100 moves 100 from cash to hold, NAV unchanged at 1000. A limit sell 1 @ 102 does the same with 102 as margin |
| 2 | `test_limit_order_cancellation` | Cancelling returns cash to its original balance and hold to zero, long or short |
| 3 | `test_market_short_matching` | A market sell hitting a passive bid: the maker's hold releases, position becomes +1, value 100; the taker pays 100 margin, position −1, value 100. Both NAVs stay 1000 |
| 4 | `test_market_long_matching` | The mirror image — a market buy against a passive ask |
| 5 | `test_partial_fill` | A bids 2 @ 100 (200 held), B sells 1. One unit stays held (100), one becomes position value (100). Total wealth consistent |
| 6 | `test_mark_to_market_long` | Long 1 @ 100: price → 110 gives NAV 1010; price → 90 gives 990 |
| 7 | `test_mark_to_market_short` | Short 1 @ 100: price → 110 gives NAV 990; price → 90 gives 1010 |
| 8 | `test_insufficient_funds` | Orders exceeding available equity are rejected |
| 9 | `test_market_order_empty_book` | No accounting changes when a market order finds no liquidity |
| 10–13 | `test_position_flip_{long_to_short,short_to_long}_{aggressor,passive}` | Flipping closes one position and opens the other atomically. Long 1, sell 2 → the first unit closes the long (releasing capital), the second opens the short (locking capital). `net_position` moves +1 → −1 (or the reverse) with cash and NAV preserved throughout |

### 2.2 `test_cash_check.py` (7 tests)

Covers `Trader._order_approved` specifically — the gating logic described in
[accounting.md](accounting.md) §3. A trader is initialised with only $100.

| Test | Verifies |
|---|---|
| `test_limit_buy_insufficient_cash` | A limit buy is blocked when `cash < size × price` |
| `test_limit_buy_sufficient_cash` | The same order is approved when cash suffices |
| `test_market_buy_insufficient_cash` | Market buys are gated too, using an estimated price |
| `test_cover_short_no_cash` | Covering an existing short needs **no** cash — `opening_size` is 0 |
| `test_sell_long_no_cash` | Selling out of an existing long likewise needs no cash |
| `test_position_flip_insufficient_cash` | On a flip, only the *opening* portion beyond flattening is cash-checked |
| `test_price_estimation_fallback_to_tape` | With no opposite-side quote, the market-order price estimate falls back to the last tape price |

> This suite supersedes an older documentation claim that the system "only validates `nav > 0`,
> potentially allowing high leverage." A real cash check exists and is tested.

### 2.3 `test_modify_order.py` (6 tests)

Mathematically verifies all six modify-order accounting scenarios — price cross, price move,
quantity increase, quantity decrease, and the two cross-plus-quantity combinations — for both the
initiator and the counter-party, asserting exact `cash`, `cash_on_hold`, and `net_position` after
each. The scenario table and full walkthroughs are in [matching_engine.md](matching_engine.md) §3.4.

---

## 3. Action space

### `test_new_action_space.py` (8 tests)

Verifies action decoding and deterministic pricing ([action_space.md](action_space.md) §2).

| Test | Verifies |
|---|---|
| `test_initial_price_integrity` | Across repeated resets, `last_price` is a `float` (required for Gym compatibility), is a whole number so ghost levels start on tick boundaries, and falls inside the configured `[min, max]` range |
| `test_bid_ghost_pricing` | With an empty book, sweeping `price` 0–9 with `price_offset=1` (join) gives `Anchor − (index + 1) × tick` — index 0 targets level 1, index 9 targets level 10 |
| `test_ask_ghost_pricing` | The symmetric case: `Anchor + (index + 1) × tick` |
| `test_price_offsets_bid` | With `last_price` pinned, passive is 1 tick **lower** than the ghost level (98 vs 99), join matches exactly (99), aggressive is 1 tick **higher** (100) |
| `test_price_offsets_ask` | Passive is 1 tick **higher** (102 vs 101), join matches (101), aggressive is 1 tick **lower** (100) — validating the inverted sense of aggression on the sell side |
| `test_market_order_mapping` | A market category submitted with a deliberately "dirty" price level 9 and offset 0 still produces `type: 'market'` and `price: -1.0`, proving the agent's price selection is ignored |
| `test_trading_updates_anchor` | With `last_price` set to 100, an aggressive sell limit at 100 followed by a market buy updates `env.last_price` to the actual trade price on `LOB.tape` |
| `test_neutral_action` | `category: 0` leaves `env.LOB_actions` empty — neutral agents are filtered out before any price calculation or matching |

Modify and cancel accounting (categories 3, 4, 7, 8) is verified separately in
`test_modify_order.py` (§2.3).

---

## 4. Observation

### 4.1 `test_obs_normalization.py` (12 tests)

Validates the normalization pipeline in `set_agg_LOB()`, the unnormalization in `_set_price()`, and
the safety guards. Formulas are in [observation_space.md](observation_space.md) §2.

**Group 1 — `agg_LOB_raw`**

| Test | Verifies |
|---|---|
| `test_agg_LOB_raw_exists_after_reset` | The attribute exists, is an `ndarray`, and has shape `(BOOK_DIM,)` after `reset()`. Without it `_set_price()` would silently fall back to normalized values and place orders at wildly wrong prices |
| `test_agg_LOB_raw_updated_after_step` | It refreshes after an order changes the book — stale raw data would make action prices reference outdated levels |

**Group 2 — sign preservation**

| Test | Verifies |
|---|---|
| `test_obs_signs_empty_book` | An empty book yields an all-zero **book block** with no NaN. Empty levels map to 0, not to a normalized value of `M` |
| `test_bid_obs_non_negative_with_orders` | After 4 bid orders, `snapshot[0:10]` and `snapshot[10:20]` are all `>= 0` |
| `test_ask_obs_non_positive_with_orders` | After 4 ask orders, `snapshot[20:30]` and `snapshot[30:40]` are all `<= 0` — catching a dropped negation |

**Group 3 — midpoint correctness**

| Test | Verifies |
|---|---|
| `test_midpoint_price_normalization_correctness` | With `last_price` pinned to 100, a bid at 99 and an ask at 101 give `M = 100`. Level-1 bid = `(100 − 99)/100 = 0.01`; level-1 ask = `−((101 − 100)/100) = −0.01` |
| `test_level1_bid_ask_symmetric_distance` | Same book: `|norm_bid[0]| == |norm_ask[0]|`. Both sides are equidistant from `M` — a failure means the two formulas have drifted apart |

**Group 4 — volume**

| Test | Verifies |
|---|---|
| `test_volume_normalization_sqrt` | `snapshot[10] == +sqrt(raw_bid_size)` and `snapshot[30] == −sqrt(raw_ask_size)`, read back against `agg_LOB_raw` |

**Group 5 — division-by-zero safety**

| Test | Verifies |
|---|---|
| `test_empty_book_uses_last_price_anchor` | With an empty book and `last_price = 50.0`, no NaN or Inf appears; the `np.where` mask prevents division on empty levels |
| `test_zero_last_price_fallback` | With a corrupted `last_price = 0.0`, `M` clamps to `100.0` and no NaN or Inf appears |

**Group 6 — action unnormalization**

| Test | Verifies |
|---|---|
| `test_action_price_from_populated_book_is_raw` | With a bid resting at 99, selecting level 0 (join) resolves to `agg_LOB_raw[0]` = 99, **not** the normalized 0.01 |
| `test_action_price_is_positive` | Over 10 random multi-agent steps, every resolved non-market price (`price != -1.0`) is strictly positive — catching edge cases in ghost pricing, offsets, or unnormalization |

### 4.2 `test_observation_history.py` (5 tests)

| Test | Verifies |
|---|---|
| `test_default_n_hist_observation_space` | Default `n_hist=4` gives an observation space and a `reset()` observation of `(4 × SNAPSHOT_DIM,)`. Also asserts `mkt_size_mean_mul` is initialised — an MRO chain health check |
| `test_configurable_n_hist` | `n_hist ∈ {1, 2, 6, 10}` resizes the space correctly |
| `test_reset_padding_identical_copies` | All *N* segments after reset are identical copies of *O₀* — no zero-padding artefacts |
| `test_sliding_window_updates` | After each `step()`, the trailing `SNAPSHOT_DIM` elements match the newest snapshot and the total shape is unchanged |
| `test_shared_history_multi_agent_uniformity` | All agents receive the same observation at reset and after each step |

> The last test cements a design flaw as if it were a requirement. It is currently true, but the
> moment private state is added to the observation it must be deleted. See
> [known_issues.md](known_issues.md) §5.8.

### 4.3 `test_obs_market_features.py` (17 tests)

Covers the two market-level scalars ([observation_space.md](observation_space.md) §3):

- Constant arithmetic: `SNAPSHOT_DIM == BOOK_DIM + EXTRA_DIM`.
- Observation shape across `n_hist ∈ {1, 2, 4, 6, 10}`.
- `agg_LOB_raw` stays `(BOOK_DIM,)` before and after book changes
  (`test_agg_LOB_raw_still_book_sized`).
- `log_mid` correctness for two-sided, bid-only, ask-only, and empty books, plus the non-positive
  `last_price` fallback to 100.0.
- `log1p_spread_ticks` correctness on a known two-sided book, the 1-tick floor, and monotonicity
  across widening spreads.
- The sentinel is exactly `0.0` for one-sided and empty books, and every real spread is
  `>= log1p(1)`, so the sentinel is separable.
- Both scalars appear in **every** frame of the stack, not just the last.
- Existing block slicing and sign conventions are unaffected.
- No NaN or Inf across a random multi-agent rollout.

These tests build books by inserting directly via `env.LOB.process_order(...)` at known prices
rather than going through the action pipeline, so expected values are exact rather than dependent on
stochastic size sampling.

---

## 5. Reward

### `test_reward_logic.py` (4 tests)

| Test | Verifies |
|---|---|
| `test_max_nav_high_water_mark` | The peak NAV is maintained correctly through gains and losses |
| `test_trade_and_passive_counters` | Aggressive versus passive fills are counted separately |
| `test_reward_formula_components` | The full multi-factor formula against a known scenario |
| `test_asymmetric_loss_reward` | Losses are penalised more heavily than equivalent gains |

---

## 6. Training and league

`test_probabilistic_mapping.py` (matchmaking distribution) and `test_nav_callback.py` (episode-end
NAV conservation) are documented in [self_play_league.md](self_play_league.md) §6.

---

## 7. Gaps

Honest accounting of what the suite does **not** cover:

- **Nothing enforces it.** There is no CI. `.travis.yml` targets a defunct service and names test
  files that do not exist. See [known_issues.md](known_issues.md) §4.
- **No information-content tests for the observation.** The suite would pass unchanged with the
  varying-denominator stack, the zero-collision ambiguity, and the dead tape loop all present — and
  all three are present ([known_issues.md](known_issues.md) §5).
- **No end-to-end training test.** No test asserts that any training entry point builds, let alone
  completes an iteration.
- **Edge cases in league matchmaking** — empty pools and zero weights are untested.
- **Reproducibility is untested because it does not work** — see
  [known_issues.md](known_issues.md) §3.5.
