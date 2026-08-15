# 10. Testing

Every test file, what each case pins down, how to run the suite, what CI enforces, and what is
not covered.

Related: [03_matching_engine.md](03_matching_engine.md), [04_accounting.md](04_accounting.md),
[05_observation_space.md](05_observation_space.md), [06_action_space.md](06_action_space.md),
[07_reward_function.md](07_reward_function.md), [08_self_play_league.md](08_self_play_league.md).

---

## 0. Running the suite

Every suite is pytest-native: plain classes (no `unittest.TestCase`), `assert` statements instead
of `self.assertX(...)`, and pytest's built-in xunit-style hooks (`setup_method` / `setup_class` /
`teardown_class`) instead of `setUp` / `setUpClass` / `tearDownClass`. Converted from a
`unittest`-based suite; see [17_changelog.md](17_changelog.md).

```bash
# everything (279 tests: 253 unit + 26 integration)
python -m pytest gym_continuousDoubleAuction/test -q

# unit tests only, skipping the slow RLlib ones
python -m pytest gym_continuousDoubleAuction/test -q \
    --ignore=gym_continuousDoubleAuction/test/integration

# RLlib wiring, the real save/restore, and the progress log (26 tests,
# builds real Algorithms; one is an xfail pinning S1-1)
python -m pytest gym_continuousDoubleAuction/test/integration -q

# a single file
python -m pytest gym_continuousDoubleAuction/test/test_orderbook_new.py -v
```

**pytest is now required to run any of this**, not just a convenient runner. Two things that used
to work no longer do, because there is no `unittest.main()` call left to trigger them:

- `python gym_continuousDoubleAuction/test/test_orderbook_new.py` — exits immediately with no
  output; it only *defines* the test classes now.
- `%run ../gym_continuousDoubleAuction/test/test_observation_history.py` from a notebook — same
  no-op. Use `%run -m pytest -- ../gym_continuousDoubleAuction/test/test_observation_history.py`
  (or a shell cell) instead.

`python -m unittest discover` also no longer finds anything here — `unittest`'s loader only
collects `TestCase` subclasses, and none of these classes are one any more. **[verified]**:
`python -m unittest discover -s gym_continuousDoubleAuction/test -p "test_*.py"` reports
`Ran 0 tests`.

**[verified]** — `278 passed, 1 xfailed` (the xfail pins S1-1; see §6.2.2).

### File inventory

Counts re-measured with `--collect-only`; the earlier `90` predated the config and runtime suites.

| File | Tests | Area |
|---|---|---|
| `test_orderbook_new.py` | 12 | Matching engine components and integration |
| `test_orderbook_crossed_book.py` | 1 | Crossed-book invariant |
| `test_orderbook_volume_sync.py` | 1 | Volume cache synchronization |
| `test_accounting.py` | 13 | Cash, position, NAV, position flips |
| `test_cash_check.py` | 7 | Order approval and cash gating |
| `test_modify_order.py` | 6 | Modify-order accounting scenarios |
| `test_new_action_space.py` | 10 | Action decoding and ghost pricing |
| `test_obs_normalization.py` | 12 | Price/volume normalization, action unnormalization |
| `test_observation_history.py` | 3 | Temporal stacking |
| `test_obs_market_features.py` | 17 | `log_mid`, `log1p_spread_ticks` |
| `test_reward_logic.py` | 4 | Reward formula components |
| `test_nav_callback.py` | 6 | Episode-end NAV conservation check: raises, tolerance, metric, strict off |
| `test_logging_setup.py` | 10 | Level resolution and export, handler setup, no `print` in `envs/` or `train/` |
| `test_probabilistic_mapping.py` | 1 | League matchmaking distribution |
| `test_config_loading.py` | 15 | `train_config.json` → `TrainConfig` → env |
| `test_config_sources.py` | 26 | No literal copy of a configured value survives in Python |
| `test_config_wiring.py` | 11 | Config keys reaching their consumers |
| `test_runtime_profiles.py` | 23 | `runtime_profiles.json` → hardware sets, platform paths |
| `test_checkpointing.py` | 50 | Checkpoint retention, restore selection, league state across a save |
| `test_champion_trigger.py` | 6 | League statistics with modules that played no episodes |
| `test_progress_log.py` | 19 | `progress.jsonl` writer, numpy/NaN handling, `vf_explained_var` extraction |
| **unit total** | **253** | |
| `integration/test_league_wiring.py` | 13 | RLlib wiring, 3 topologies |
| `integration/test_checkpoint_roundtrip.py` | 7 | One real save and restore: weights, league, iteration, optimizer |
| `integration/test_progress_and_vf.py` | 6 | A real short run's `progress.jsonl`; `vf_explained_var` reported and finite (1 xfail pins S1-1) |
| **integration total** | **26** | |

> **Stale references in older docs.** `test_orderbook.py`, `repro_orderbook_crossed_book.py`,
> `test_OrderBook.py`, `test_cda_nsp.py` and `test_orderbook_double_delete_order.py` do not exist.
> The current names are in the table above.

> **Side effect note, now resolved.** The suite no longer writes `episode_data/` at all:
> `test_nav_callback` builds its callback with `episode_data_dir=None`, so the per-episode pickle
> dump never runs. (That dump is where the two committed `episode_data/test_ep_*.pkl` files came
> from — output of the old tests, not fixtures anything reads.) Both `episode_data` and
> `gym_continuousDoubleAuction/episode_data` remain in `.gitignore`, since a *training* run still
> writes there by default.

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
| `test_modify_order_price_change` | Moving an order from 100 to 101 leaves `get_best_bid() == 101` — the order is correctly removed from one level and inserted into the other |

> **Correction.** `doc/testing.md` described `test_modify_order_price_change` as
> `@unittest.expectedFailure`, "documenting a known limitation rather than asserting
> correctness". There is no `expectedFailure` anywhere in the repository; the test asserts and
> passes.

**Group C — invariants (`TestOrderBookInvariants`)**

| Test | Verifies |
|---|---|
| `test_empty_book_market_order` | A market order against an empty book returns zero trades instead of crashing |
| `test_order_id_uniqueness` | Every processed order gets a unique, incrementing ID |

### 1.2 Crossed-book invariant — `test_orderbook_crossed_book.py`

`test_modify_order_does_not_cross_book`:

1. Place an ask: limit, 10 @ 100, `S1`. Best ask = 100.
2. Place a bid: limit, 10 @ 90, `B1`. Best bid = 90, spread = 10. Capture the `order_id`.
3. **Modify the bid to 110 @ 10** — a price well above the best ask.
4. Read back `best_bid` and `best_ask`. If both exist, assert `best_bid < best_ask`.

Either the engine matches the crossing modification immediately, or it must at minimum refuse to
leave `best_bid >= best_ask` resting. A failure here means the matching engine corrupted market
state during modification — and the `log1p_spread_ticks` sentinel would stop being unambiguous.

### 1.3 Double-delete regression — `test_orderbook_double_delete_order.py` (removed)

**This file no longer exists**; the case it describes is covered by
`test_modify_order_price_change` in §1.1. The description is kept because the failure mode is
worth knowing about when touching `modify_order`.

`test_modify_order_price_no_double_delete`. Changing an order's price is two micro-steps —
**remove** from the `OrderList` at 100, **insert** into the one at 101. The bug guarded against is
the update logic attempting the removal *again* after the order has already moved, surfacing as a
`ValueError` (removing an item not in the list) or an internal volume/length counter going
negative. The `modify_order` call is wrapped in `try/except`; the test asserts no `ValueError`.

### 1.4 Volume synchronization — `test_orderbook_volume_sync.py`

`test_partial_fill_volume_sync` verifies that `OrderTree`'s **cached** volume stays equal to the
**actual** sum of order volumes after a partial fill. A helper, `get_calculated_volume(side)`,
iterates `price_map` and sums every `OrderList` to produce ground truth.

1. Place an ask: limit, 10 @ 100. Assert `OrderTree.volume == 10` **and**
   `get_calculated_volume('ask') == 10`.
2. Place a bid: limit, 4 @ 100 — a marketable limit that partially fills the ask.
3. Assert `OrderTree.volume == 6` **and** `get_calculated_volume('ask') == 6`.

If the cached figure stays at 10, the cache has desynchronized from reality.

---

## 2. Accounting

### 2.1 `test_accounting.py` (13 tests)

Concepts under test are described in [04_accounting.md](04_accounting.md). Starting NAV is 1000
in most scenarios.

| # | Test | Verifies |
|---|---|---|
| 1 | `test_limit_order_placement_hold` | A limit buy 1 @ 100 moves 100 from cash to hold, NAV unchanged at 1000. A limit **sell** 1 @ 102 does the same with 102 as margin — shorts are cash-collateralised |
| 2 | `test_limit_order_cancellation` | Cancelling returns cash to its original balance and hold to zero, long or short |
| 3 | `test_market_short_matching` | A market sell hitting a passive bid: the maker's hold releases, position becomes +1, value 100; the taker pays 100 margin, position −1, value 100. Both NAVs stay 1000 |
| 4 | `test_market_long_matching` | The mirror image — a market buy against a passive ask |
| 5 | `test_partial_fill` | A bids 2 @ 100 (200 held), B sells 1. One unit stays held (100), one becomes position value (100) |
| 6 | `test_mark_to_market_long` | Long 1 @ 100: price → 110 gives NAV 1010; price → 90 gives 990 |
| 7 | `test_mark_to_market_short` | Short 1 @ 100: price → 110 gives NAV 990; price → 90 gives 1010 |
| 8 | `test_insufficient_funds` | **Empty `pass`** — see §7 |
| 9 | `test_market_order_empty_book` | No accounting changes when a market order finds no liquidity |
| 10–13 | `test_position_flip_{long_to_short,short_to_long}_{aggressor,passive}` | Flipping closes one position and opens the other atomically. Long 1, sell 2 → the first unit closes the long (releasing capital), the second opens the short (locking capital). `net_position` moves +1 → −1 (or the reverse) with cash and NAV preserved |

### 2.2 `test_cash_check.py` (7 tests)

Covers `Trader._order_approved` specifically ([04_accounting.md](04_accounting.md) §3). A trader
is initialised with only $100.

| Test | Verifies |
|---|---|
| `test_limit_buy_insufficient_cash` | A limit buy is blocked when `cash < size × price` |
| `test_limit_buy_sufficient_cash` | The same order is approved when cash suffices |
| `test_market_buy_insufficient_cash` | Market buys are gated too, using an estimated price |
| `test_cover_short_no_cash` | Covering an existing short needs **no** cash — `opening_size` is 0 |
| `test_sell_long_no_cash` | Selling out of an existing long likewise needs no cash |
| `test_position_flip_insufficient_cash` | On a flip, only the *opening* portion beyond flattening is cash-checked |
| `test_price_estimation_fallback_to_tape` | With no opposite-side quote, the market-order price estimate falls back to the last tape price |

### 2.3 `test_modify_order.py` (6 tests)

Mathematically verifies all six modify-order accounting scenarios — price cross, price move,
quantity increase, quantity decrease, and the two cross-plus-quantity combinations — for both the
initiator and the counter-party, asserting exact `cash`, `cash_on_hold` and `net_position` after
each. The scenario table with expected figures is in
[03_matching_engine.md](03_matching_engine.md) §3.4.

---

## 3. Action space

### `test_new_action_space.py` (8 tests)

| Test | Verifies |
|---|---|
| `test_initial_price_integrity` | Across repeated resets, `last_price` is a `float` (Gym compatibility), is a whole number so ghost levels start on tick boundaries, and falls inside the configured `[min, max]` range |
| `test_bid_ghost_pricing` | With an empty book, sweeping `price` 0–9 with `price_offset=1` (join) gives `Anchor − (index + 1) × tick` |
| `test_ask_ghost_pricing` | The symmetric case: `Anchor + (index + 1) × tick` |
| `test_price_offsets_bid` | With `last_price` pinned, passive is 1 tick **lower** than the ghost level (98 vs 99), join matches exactly (99), aggressive is 1 tick **higher** (100) |
| `test_price_offsets_ask` | Passive is 1 tick **higher** (102 vs 101), join matches (101), aggressive is 1 tick **lower** (100) — validating the inverted sense of aggression on the sell side |
| `test_market_order_mapping` | A market category submitted with a deliberately "dirty" price level 9 and offset 0 still produces `type: 'market'` and `price: -1.0` |
| `test_trading_updates_anchor` | With `last_price` set to 100, an aggressive sell limit at 100 followed by a market buy updates `env.last_price` to the actual trade price on `LOB.tape` |
| `test_neutral_action` | `category: 0` leaves `env.LOB_actions` empty — neutral agents are filtered out before any price calculation or matching |

Modify and cancel accounting (categories 3, 4, 7, 8) is verified separately in
`test_modify_order.py`.

---

## 4. Observation

### 4.1 `test_obs_normalization.py` (12 tests)

**Group 1 — `agg_LOB_raw`**

| Test | Verifies |
|---|---|
| `test_agg_LOB_raw_exists_after_reset` | The attribute exists, is an `ndarray`, and has shape `(BOOK_DIM,)` after `reset()`. Without it `_set_price()` would silently fall back to normalized values and place orders at wildly wrong prices |
| `test_agg_LOB_raw_updated_after_step` | It refreshes after an order changes the book |

**Group 2 — sign preservation**

| Test | Verifies |
|---|---|
| `test_obs_signs_empty_book` | An empty book yields an all-zero **book block** with no NaN |
| `test_bid_obs_non_negative_with_orders` | After 4 bid orders, `snapshot[0:10]` and `snapshot[10:20]` are all `>= 0` |
| `test_ask_obs_non_positive_with_orders` | After 4 ask orders, `snapshot[20:30]` and `snapshot[30:40]` are all `<= 0` — catching a dropped negation |

**Group 3 — midpoint correctness**

| Test | Verifies |
|---|---|
| `test_midpoint_price_normalization_correctness` | With `last_price` pinned to 100, a bid at 99 and an ask at 101 give `M = 100`. Level-1 bid = `(100 − 99)/100 = 0.01`; level-1 ask = `−((101 − 100)/100) = −0.01` |
| `test_level1_bid_ask_symmetric_distance` | Same book: `\|norm_bid[0]\| == \|norm_ask[0]\|` |

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
| `test_action_price_is_positive` | Over 10 random multi-agent steps, every resolved non-market price is strictly positive |

### 4.2 `test_observation_history.py` (5 tests)

| Test | Verifies |
|---|---|
| `test_default_n_hist_observation_space` | Default `n_hist=4` gives a space and a `reset()` observation of `(4 × SNAPSHOT_DIM,)`. Also asserts `mkt_size_mean_mul` is initialised — an MRO chain health check |
| `test_configurable_n_hist` | `n_hist ∈ {1, 2, 6, 10}` resizes the space correctly |
| `test_reset_padding_identical_copies` | All *N* segments after reset are identical copies of *O₀* — no zero-padding artefacts |
| `test_sliding_window_updates` | After each `step()`, the trailing `SNAPSHOT_DIM` elements match the newest snapshot and the total shape is unchanged |
| `test_shared_history_multi_agent_uniformity` | All agents receive the same observation at reset and after each step |

> **The last test cements a design flaw as if it were a requirement.** It is currently true, but
> the moment private state is added to the observation (S1-2) it must be deleted. See
> [05_observation_space.md](05_observation_space.md) §7.7.

### 4.3 `test_obs_market_features.py` (17 tests)

Covers the two market-level scalars ([05_observation_space.md](05_observation_space.md) §3):

- Constant arithmetic: `SNAPSHOT_DIM == BOOK_DIM + EXTRA_DIM`.
- Observation shape across `n_hist ∈ {1, 2, 4, 6, 10}`.
- `agg_LOB_raw` stays `(BOOK_DIM,)` before and after book changes
  (`test_agg_LOB_raw_still_book_sized`).
- `log_mid` correctness for two-sided, bid-only, ask-only and empty books, plus the non-positive
  `last_price` fallback to 100.0.
- `log1p_spread_ticks` correctness on a known two-sided book, the 1-tick floor, and monotonicity
  across widening spreads.
- The sentinel is exactly `0.0` for one-sided and empty books, and every real spread is
  `>= log1p(1)`, so the sentinel is separable.
- Both scalars appear in **every** frame of the stack, not just the last.
- Existing block slicing and sign conventions are unaffected.
- No NaN or Inf across a random multi-agent rollout.

These tests build books by inserting directly via `env.LOB.process_order(...)` at known prices
rather than going through the action pipeline, so expected values are exact rather than dependent
on stochastic size sampling.

---

## 5. Reward

### `test_reward_logic.py` (4 tests)

| Test | Verifies |
|---|---|
| `test_max_nav_high_water_mark` | The peak NAV is maintained correctly through gains and losses |
| `test_trade_and_passive_counters` | Aggressive versus passive fills are counted separately |
| `test_reward_formula_components` | The full multi-factor formula against a known scenario |
| `test_asymmetric_loss_reward` | Losses are penalised more heavily than equivalent gains |

The suite instantiates a bare `Reward_Helper()` with a `MockTrader`, which works only because
`set_reward` touches nothing else on `self` — a symptom of the mixin design, not a property of it.

---

## 6. Training and league

### 6.1 Unit level

`test_probabilistic_mapping.py` (matchmaking distribution) and `test_nav_callback.py`
(episode-end NAV conservation: raising by default, the tolerance, the metric, and the non-strict
path) are described in [08_self_play_league.md](08_self_play_league.md) §9.

Note `test_probabilistic_mapping.py` is a bare module-level function rather than a class — it was
already pytest-native before the rest of the suite was converted, and needed no changes. It
collects the same way as everything else under `pytest`, but — like every file in this suite now
— running it directly (`python test_probabilistic_mapping.py`, or `%run` from a notebook) does
nothing, since there is no `unittest.main()` call left anywhere to trigger execution. See §0.

### 6.1.1 `test_checkpointing.py` — 11 classes, 50 tests

What survives a save/restore, and what a restore is allowed to change. RLlib's loader and the
env build are stubbed, so these run in seconds; the same behaviours were also exercised against
real checkpoints in [16 §16.8.1](16_verification_log.md). The stubbing is what §6.2.1 exists to
complete: nothing here touches RLlib's own serialisation.

| Class | What it pins |
|---|---|
| `TestCheckpointDiscovery` | Saves are ordered oldest-first; `iter_N.tmp` (an interrupted save) and non-checkpoint directories are skipped; a checkpoint in the old single-directory layout is still found, and sorts oldest |
| `TestRetention` | Each save is its own directory; `chkpt_keep` prunes the **least recently written**; `<= 0` keeps all; a stale higher-numbered save from an earlier run never prunes a fresh one (S3-17); the old-layout checkpoint is never pruned; the save is staged then renamed; re-saving an iteration replaces it |
| `TestLeagueSidecar` | `league_state.json` is written beside every checkpoint; `algo_callback` finds the live instance |
| `TestLeagueStateReconciliation` | Agreement repairs nothing; a callback that lost its history is rebuilt from the sidecar; a champion with no module is dropped; a module with no champion entry is adopted; the ID counter never goes backwards |
| `TestRestoreCandidates` | `restore_path` null means every checkpoint; a path narrows it to that one; not restoring ignores the tree; a path without `is_restore` raises; a path that is not a checkpoint raises and lists the ones that are, newest first |
| `TestCommandLine` | `--from-checkpoint` implies `--restore`; `--restore` alone leaves the path unset |
| `TestForeignCheckpoints` | A fresh run names the checkpoints it found and did not write, newest first, and deletes none of them; a restoring run is not warned; `build_algo` warns on the scratch path |
| `TestRestoreSelection` | The newest checkpoint is picked; an unreadable one falls back to the previous; a **pinned** one raises instead of falling back; the **algorithm's own** callback is returned, not the fresh one; no checkpoint starts from scratch |
| `TestIterationAccounting` | `num_iters` is a target, not an amount; `num_iters_is_delta` counts from the restore point; a completed run trains nothing; checkpoints land on true iteration numbers; the final save is not duplicated |
| `TestTrainReturnsTheLastResult` | `train()` returns the final iteration's result beside the algo, so inspecting the league costs no extra `algo.train()`; a run with nothing to do returns an empty one |
| `TestEmptyIterationIsReported` | An iteration whose result has no `env_runners` block trained on no samples and warns, naming `sample_timeout_s` and the batch; silent when `num_env_runners=0`, where there is no timeout to miss |

Two of these encode bugs that were live in the codebase rather than hypothetical:

- **`test_counter_never_goes_backwards`** — the monotonic champion ID counter lives on the
  cloudpickled callback. If it restarts, `add_module` re-mints `champion_1` over a champion that
  is already playing.
- **`test_returns_the_algorithms_own_callback`** — S3-8. Training was never affected, which is
  what made it survive: only code *inspecting* the returned league saw the empty one.

### 6.2 `integration/test_league_wiring.py` — 3 classes, 13 tests

The module docstring names the three real bugs the suite exists to prevent:

1. Baseline opponents declared as `PolicySpec(RandomPolicy, ...)` built as
   `DefaultPPOTorchRLModule` instead.
2. Champion snapshots getting their trained weights written into the LearnerGroup but never
   synced to the EnvRunners.
3. The champion trigger reading old-API-stack metric keys that no longer exist.

| Class | Topology | Covers |
|---|---|---|
| `TestLeagueWiring` | local (0/0) | Module classes, `policies_to_train` exclusion, champion creation, weight equality, mapping-fn draws, metric keys |
| `TestLeagueWiringRemoteEnvRunners` | `num_env_runners=1` | Module presence on the remote actor, weight equality across the process boundary, `config.policy_mapping_fn` draw distribution |
| `TestLeagueWiringRemoteLearner` | `num_learners=1` | Champion snapshotting through `learner_group.get_state` rather than `_learner` |

Both remote classes **guard their own premise** — `test_sampling_actually_happens_remotely`
asserts `num_healthy_remote_workers() == 1`, and `test_learner_group_is_actually_remote` asserts
`not learner_group.is_local`. Without those, a silently-degraded remote setup would make every
other assertion pass vacuously over an empty list. That is a level of test discipline most
codebases lack.

The remote probe is also written with real care: the nested closure in
`TestLeagueWiringRemoteEnvRunners.setUpClass` carries a comment explaining both pickling traps —
closing over `cls`, and module-level helpers being pickled by reference into a worker that cannot
import `test_league_wiring`.

These tests build real `Algorithm`s and run real training iterations, so they take minutes.

### 6.2.1 `integration/test_checkpoint_roundtrip.py` — 1 class, 7 tests

`test_checkpointing.py` (§6.1.1) pins the driver logic around checkpointing against a `FakeAlgo`
whose `save()` writes a one-key marker file and whose loader is monkeypatched out. That left the
thing checkpoints exist for untested: whether a restored run resumes with its learned weights or
quietly starts over from a random initialisation. This module does **one real save and one real
restore** through `save_checkpoint` and `build_algo`, on a PPO sized for speed (~26s).

| Test | What it pins |
|---|---|
| `test_the_checkpoint_is_where_the_driver_expects_it` | The save lands at `chkpt/iter_NNNNN` with its `league_state.json` sidecar |
| `test_trained_weights_survive` | Every LearnerGroup parameter of `policy_0` is bit-identical after the restore |
| `test_the_champion_module_comes_back_and_acts_the_same` | The champion is present **on the EnvRunner** with the acting weights it was saved with — a champion restored only into the LearnerGroup leaves the league matchmaking against a random network |
| `test_league_bookkeeping_comes_back` | The returned callback is the algorithm's own; champion history, pool membership and the monotonic ID counter all survive |
| `test_iteration_count_comes_back` | `num_iters`-as-a-target depends on this |
| `test_optimizer_betas_are_plain_floats` | `_fix_checkpoint_optimizer_betas` — stubbed out everywhere else in the suite, so this is its only execution |
| `test_the_restored_algorithm_trains_further` | The resumed run takes another gradient step, gets an `env_runners` block, and moves its weights |

Two things this suite had to get right, and which are worth preserving in any edit:

- **Weights are compared on the LearnerGroup, not the EnvRunner.** RLlib syncs only the acting
  path to runners, so a runner's `critic_encoder` and `vf.*` tensors sit at their initial values
  even in a run that never restarts. The first draft compared runner state and "failed" against a
  perfectly good checkpoint. `_acting_only()` names the subset a runner does keep current, and the
  champion test uses it.
- **The iteration under test creates a champion of its own**, so the assertions record whatever
  champion IDs exist at save time rather than a hardcoded `champion_1`.

Verified to fail for the right reason: flipping the restore to `is_restore=False` fails 5 of the
7, the two survivors being the ones that do not depend on the restore.

### 6.2.2 `integration/test_progress_and_vf.py` — 1 class, 6 tests (1 xfail)

`test_progress_log.py` (§6.1) covers the `progress.jsonl` writer and the `vf_explained_var`
extraction against a `FakeAlgo` whose results are hand-built, which leaves the assumption
underneath both untested: that a *real* PPO iteration on this env produces a `learners` block
containing that key, and that a real result dict survives the JSON round trip. A rename in RLlib
would sail past every unit test and leave the run logging nothing. This trains a real PPO for
three iterations (~15s) and reads the file back.

| Test | What it pins |
|---|---|
| `test_one_line_per_iteration` | The file exists and `training_iteration` runs 1..N with no gaps |
| `test_a_real_result_survives_the_json_round_trip` | The nested `env_runners` and `learners` blocks are still *in* the line, not merely that it parses |
| `test_vf_explained_var_is_reported_for_every_trainable_module` | The key RLlib really emits, for exactly the modules in `policies_to_train` |
| `test_the_metric_is_finite` | A NaN is a diverged value loss |
| `test_the_critic_actually_explains_something` | **strict xfail** — `\|vf_explained_var\| >= 1e-3`. Fails today because S1-1 is open |
| `test_the_file_carries_it_too` | The on-disk record, not just the returned result, has the metric for every iteration |

The one thing worth preserving in any edit here is the assertion that is deliberately *absent*.
`!= 0.0` is the obvious guard against a critic that never received a gradient, and it is worthless
on this repository: a run reports values around 1e-5 — the S1-1 signature [17](17_changelog.md)
§17.3 records as "0.0 to 1.8e-07" — and every one of them is nonzero, so it passes on a critic
that is entirely dead. Floating-point noise is not evidence of learning. The strict xfail is what
carries the real claim: when S1-1 is fixed it XPASSes and fails the build, and removing the marker
at that point turns it into a live regression guard.

### 6.3 `test_runtime_profiles.py` — 23 tests

Covers [`config/runtime_profiles.json`](../config/runtime_profiles.json) and
[`train/runtime.py`](../gym_continuousDoubleAuction/train/runtime.py), the pair that lets
`CDA_NSP.ipynb` run unchanged on Colab and in the docker image
([18_configuration.md](18_configuration.md) §8). Four groups:

| Group | Asserts |
|---|---|
| `TestHardwareProfiles` | Exactly the two sets `gpu` / `cpu` exist; both stay inside the stated bounds (≤2 CPUs, ≤1 GPU, ≥1 CPU); the gpu set asks for a GPU and the cpu set does not; every override names a real `TrainConfig` field, and one that does not raises |
| `TestResolution` | The `USE_GPU` toggle in all three states; `$CDA_PLATFORM` / `$CDA_USE_GPU` pinning; an unknown platform raising by name; `ray_init_common` merging; a platform missing a required key raising |
| `TestApply` | Profile fields land on the `TrainConfig`; output roots are applied and `null` ones are not; `episode_data_dir=None` is never re-enabled by a root |
| `TestEnvVars` | `apply_env_vars()` exports the configured names, and an already-exported value wins |

Two of these are the ones that would actually catch a regression:

- **`test_env_runners_fit_the_cpu_budget`** — asserts
  `num_env_runners × num_cpus_per_env_runner ≤ ray_init.num_cpus` for both sets. Env runners are
  Ray actors: ask for more CPUs than `ray.init()` was given and they sit **pending forever**
  rather than failing, which reads as a hang with no error.
- **`test_training_values_are_untouched`** — asserts a profile moves no field that changes the
  learning problem (agent counts, batch sizes, `lr`, reward coefficients, `seed`). This is the
  property that makes a Colab run and a docker run comparable; without it, "runs anywhere" would
  quietly mean "trains differently anywhere".

Both fixtures monkeypatch `runtime.cuda_available`, so the suite tests both hardware paths on a
machine with no GPU — and gives the same result on one with a GPU.

---

## 7. Continuous integration

[`.github/workflows/tests.yml`](../.github/workflows/tests.yml), replacing the old `.travis.yml`
(which pinned Python 3.7.7 and ran two scripts that no longer exist):

| Trigger | `push` to `master` / `update_lib`, any `pull_request`, `workflow_dispatch` |
|---|---|
| Matrix | Python 3.11, 3.12 on `ubuntu-latest`, `fail-fast: false` |
| Install | CPU torch wheel explicitly first (so the CUDA wheel is not pulled transitively), then `requirements.txt`, then `pip install -e ".[dev]"` |

Three staged jobs, so an env-level break and an RLlib-level break are distinguishable from the
job name alone:

1. **Env + order book unit tests** — `pytest gym_continuousDoubleAuction/test -q`
2. **Random-agent env smoke run** — `python gym_continuousDoubleAuction/CDA_env_rand.py`
3. **RLlib integration** — `pytest gym_continuousDoubleAuction/test/integration -q`

> **Correction.** `doc/known_issues.md` §4 and `doc/testing.md` §7 stated that "nothing enforces
> the test suite — there is no CI". That has not been true since the Ray 2.56 migration.

---

## 8. Gaps

Honest accounting of what the suite does **not** cover.

| Gap | Risk |
|---|---|
| **The learning-signal assertion is an xfail, not a guard** | `integration/test_progress_and_vf.py` now checks `vf_explained_var` is reported and finite, and pins the substantive threshold (`>= 1e-3`) as a strict xfail because S1-1 is open — so the suite records the frozen critic rather than catching it. Note what does *not* work here: asserting `!= 0.0` passes today on a critic sitting in the 1e-5 noise floor. `vf_loss` saturation and "returns improve" are still unchecked. |
| **`test_accounting.py::test_insufficient_funds` is an empty `pass`** | The body is a 15-line comment debating what the behaviour *should* be, ending "Will implement based on observed behavior or re-read code carefully." A TODO shipped as a test. The behaviour it was meant to cover is in fact tested by `test_cash_check.py`. |
| **No information-content tests for the observation** | The suite would pass unchanged with the varying-denominator stack, the zero-collision ambiguity and the dead tape loop all present — and all three are present ([05](05_observation_space.md) §7). |
| **`test_shared_history_multi_agent_uniformity` encodes a defect as a requirement** | See §4.2. |
| **Reproducibility is untested because it does not work** | Seeding is non-functional (S3-5); no test asserts two identically-seeded runs match. |
| **Edge cases in league matchmaking** | Empty pools and zero weights are untested. |
| **No property-based tests** | The order book is an ideal Hypothesis target: "tree volume == Σ level volumes", "no crossed book", "Σ NAV == Σ initial cash" hold for *any* order sequence. |
| **No coverage measurement** | No `pytest-cov`, no threshold. |
| **No performance regression test** | Nothing catches a 10× slowdown in the matching engine. |
| **`envs/orderbook/test/example.py` and `genOrders.py`** | 353 LOC of standalone scripts not collected by pytest and not run by CI. |
