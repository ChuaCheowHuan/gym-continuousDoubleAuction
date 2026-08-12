# 17. Changelog

Modernizations made to `gym-continuousDoubleAuction` since the `original_v1` branch (released
2020), in rough chronological order.

Each entry links to the document that describes the *current* state of that area; this file
records what changed and why, not how things work today.

---

## Version 2

### 1. Dependency modernization

- **Gymnasium migration** — switched from the legacy `gym` package to `gymnasium`.
- **Ray RLlib update** — compatibility with Ray 2.4+, notably the transition from `dones` to
  `terminated` and `truncated`.

### 2. Environment API (Ray 2.4+)

`step` and `reset` now follow the current multi-agent environment standard:

- `reset()` returns `(observations, infos)` instead of just `observations`.
- `step()` returns the 5-tuple `(obs, rewards, terminateds, truncateds, infos)` instead of the
  old 4-tuple.

See [02_architecture.md](02_architecture.md) §2.5.

### 3. Self-play: league-based replaces naive

| | Approach |
|---|---|
| `original_v1` | **Naive self-play** with competitive weight copying — two policies competed and the winner's weights were periodically copied onto the loser |
| Current | **League-based self-play** with champion snapshotting |

Multiple learning policies now evolve independently with no weight copying; exceptional
performances are frozen as "champions" and added to a rotating opponent pool, with a rolling
window maintaining diversity. This prevents catastrophic forgetting and stops agents
over-optimizing against a single opponent.

See [08_self_play_league.md](08_self_play_league.md).

### 4. Redesigned action space

| | Structure |
|---|---|
| Original | Nested `Tuple` — `(side, type, size_mean, size_sigma, price_code)` with a 12-value price code |
| Current | Flat `Dict` per agent |

- **Category mapping** — separate `side` and `type` collapsed into one `category` (0–8) covering
  none plus buy/sell × market/limit/modify/cancel.
- **Price offsets** — a new `price_offset` dimension (passive / join / aggressive) makes it
  possible to *join* a price level, which the old forced ±1-tick mapping prevented.
- **Deterministic anchoring** — "ghost levels" replaced the old random-price fallback for empty
  book levels, eliminating the non-stationarity that made price codes behave like a lottery in
  thin books.

See [06_action_space.md](06_action_space.md), which retains the legacy design and the full
rationale.

### 5. Robust testing

- **Granular unit testing** — moved from manual scripts to a formal `unittest` suite covering
  every component (`Order`, `OrderList`, `OrderTree`) and process (NAV calculation, position
  tracking).
- **Precision accounting** — replaced floats with `Decimal` throughout the accounting layer,
  eliminating rounding error in financial simulation.
- **Complex scenario coverage** — dedicated tests for position flips (atomic long-to-short
  transitions), crossed books, and volume synchronization.

See [10_testing.md](10_testing.md).

### 6. Order modification fix

`OrderBook.modify_order` previously updated price and quantity in place without re-running the
matching engine, so a modification could leave the book crossed. Modifications that can trigger a
trade are now removed and re-processed through `process_limit_order`; only a quantity *decrease*
at the *same* price is updated in place and keeps queue priority. The trader's accounting gained
an "undo-then-process" flow so balances stay exact when a modification fills.

See [03_matching_engine.md](03_matching_engine.md) §3.

### 7. Reward function refinement

Replaced raw NAV change with a multi-factor formula: asymmetric loss aversion, an
order-placement penalty for selectivity, a per-trade execution penalty, a drawdown penalty, and a
passive-fill bonus for liquidity provision. The account gained `max_nav` and three per-step
counters to support it.

See [07_reward_function.md](07_reward_function.md). Two structural defects in this formula are
recorded as S1-3 and S2-1 in
[15_findings_and_recommendations.md](15_findings_and_recommendations.md).

### 8. Observation pipeline — three successive changes

The observation has changed shape twice and gained two transforms. All are described in
[05_observation_space.md](05_observation_space.md).

**8a. Midpoint normalization and action unnormalization** — price depth scaled relative to the
Level-1 midpoint `M`: bids `(M − P)/M ≥ 0`, asks `−((|P| − M)/M) ≤ 0`, preserving the sign
convention. Volumes scaled `±√V` to stabilize variance. Because agents now perceive normalized
values but must submit real prices, the unnormalized book is kept in parallel as `agg_LOB_raw`
and used for action price resolution.

**8b. Temporal history stacking** — the environment now returns the last *N* sequential snapshots
as one flat vector instead of a single frame. Default `n_hist = 4`. This change also exposed and
fixed cooperative-multiple-inheritance bugs across `State_Helper`, `Action_Helper` and
`Exchg_Helper` (kwargs reaching `object.__init__`), and required a `print_table` fix for the new
flat array format.

Observation shape: `(40,)` → `(160,)`.

**8c. Market-level scalars** — `log_mid` and `log1p_spread_ticks` appended to every frame, always
on with no config flag. These restore the price anchor that midpoint normalization discards, so
agents can perceive what an absolute tick is worth.

Observation shape: `(160,)` → `(168,)`; snapshot 40 → 42. Widths are now derived from
`SNAPSHOT_DIM` constants rather than hardcoded, because the previous `[-40:]` slicing failed
*silently* rather than loudly when the width changed.

> **Checkpoint compatibility:** any policy checkpoint or `episode_data` pickle built against an
> older observation width will not load against the current one.

---

## Ray 2.56.1 upgrade + new API stack migration

Dependency upgrade from ray 2.48.0 / gymnasium 1.0.0 / torch 2.7.1 to ray 2.56.1 /
gymnasium 1.2.2 / torch 2.13 / pandas 3.0 / numpy 2.5, plus the RLlib new-API-stack migration
that the upgrade required.

### Self-play correctness fixes

Three defects meant no self-play was actually taking place. All are now covered by
`test/integration/test_league_wiring.py`.

* **Baseline opponents were not random.** They were declared as
  `PolicySpec(RandomPolicy, ...)`, but the new API stack reads only the *keys* of
  `multi_agent(policies=...)` and fills `module_class` from the algorithm default, so every
  opponent was built as `DefaultPPOTorchRLModule` and frozen at its random initialisation. Module
  classes are now declared through `MultiRLModuleSpec`, and the baselines use a real
  `RandomRLModule`.
* **Champion snapshots never reached the EnvRunners.** `add_module` syncs weights before the
  snapshot's weights are copied in, and PPO's per-iteration sync only covers modules that
  produced losses — never a frozen champion. The champion *playing in the environment* therefore
  stayed randomly initialised while the trained copy sat unused in the LearnerGroup. The callback
  now force-pushes the champion state to the EnvRunners. Note this cannot go through
  `sync_weights()`, which carries a `WEIGHTS_SEQ_NO` the runner already has and is dropped
  silently.
* **Champion trigger read dead metric keys.** `policy_reward_mean` and `custom_metrics` are
  old-API-stack only. The fallback remapped `agent_X -> policy_X`, which is wrong for opponent
  slots since those play whichever module the pool assigned. Now reads
  `module_episode_returns_mean`, already keyed by real ModuleID.

### Other callback fixes

* Evicted champions are now dropped via `Algorithm.remove_module` instead of being left in memory
  for the run's lifetime.
* `add_module` / `remove_module` now pass `new_agent_to_module_mapping_fn`, so champions are
  selectable when `num_env_runners > 0` (remote workers hold a pickled copy of the callback
  frozen at construction).
* Per-episode step data is keyed by episode ID; previously one shared list was corrupted, and
  crashed with `None.append`, under `num_envs_per_env_runner > 1`.
* The episode-start "Policy Map" log now calls the real mapping function instead of a divergent
  reimplementation, so it reports the actual opponents.
* Opponent selection seeds from `zlib.crc32` rather than the builtin `hash()`, which is salted
  per process and made the documented determinism hold only within a single interpreter.
* Per-episode step pickles became optional via `episode_data_dir=None` / `--no-episode-data`.

### Removed

* `train/weight/` (`cp_weight` et al) — superseded by the league callback, which already ranks
  learners; the two schemes are redundant. Was dead code reading `result["hist_stats"]`, which no
  longer exists.
* `train/policy/policy_handler_0.py` — imported `ray.rllib.agents.ppo`, deleted in Ray 2.0.
* `train/callbk/callbk_handler.py`, `train/policy/league_policies.py`,
  `train/callbk/example_league_based_training.py` — dead old-stack code.
* `CustomRLModule` — never instantiated (`ModelCatalog` is not read on the new stack) and would
  have crashed on this env's `Dict` action space.
* `docker/ml/dockerfile` (duplicate), `dockerfile_ray_tf` + `test_rrlib_tf.ipynb` (TF cannot run
  the new API stack), `.travis.yml` (replaced by GitHub Actions).

### Other

* Env exposes `observation_spaces` / `action_spaces` (new stack) instead of the `@OldAPIStack`
  singular attributes; agent ordering is now stable across processes (built from a sorted list
  rather than iterating a set of salted-hash strings).
* Training extracted from `CDA_NSP.ipynb` into `train/train.py` with a `TrainConfig` dataclass
  and CLI; the notebook is now a thin driver.
* GPU count falls back to CPU when `torch.cuda.is_available()` is False (was hardcoded `0.75`,
  which hard-failed on CPU machines).
* `setup.py` uses `find_packages()` with real `install_requires` and extras; missing `__init__.py`
  files added, so tests no longer need `PYTHONPATH`.
* `CDA_env_rand.py` fixed — it had been broken independently of this upgrade (positional
  constructor args, iterating agent IDs as `Trader` objects).
* **CI added** — `.github/workflows/tests.yml`, Python 3.11/3.12 matrix, three staged jobs.
* `episode_data` added to `.gitignore` (both the repo-root and package-relative paths).

### Distributed-training fixes (post-migration commits)

Four narrow commits on `update_lib`, each with a regression test:

| Commit | Fix |
|---|---|
| `9c1c6da` | Champion propagation to remote EnvRunners (`num_env_runners > 0`) — the `available_modules`-before-`add_module` ordering |
| `d53c9fd` | `TestLeagueWiringRemoteEnvRunners` added, with its premise guard |
| `a446281` | Champion snapshotting with a remote LearnerGroup (`num_learners > 0`) — read state through `learner_group.get_state` rather than the private `_learner` |
| `3dcfc53` | Documented `num_env_runners` / `num_learners`; fixed a section-numbering collision |

See [09_distributed_training.md](09_distributed_training.md) §4 for the full analysis of why
these bugs were invisible at the default `0/0` configuration.

---

## 9. Documentation

The `/doc` folder was expanded with deep dives on the action space, accounting, temporal stacking
and observation normalization, then **restructured** into a set of topic-based documents indexed
by `doc/README_v2.md`, replacing an earlier mix of per-test walkthroughs, dated analysis
snapshots, plans and implementation reports. Four one-line redirect shims (`change.md`,
`CHANGES_obs_normalization.md`, `CHANGES_temporal_obs_history.md`,
`CHANGES_obs_market_features.md`) were kept solely because the top-level `README.md` links to
them.

A second, independent analysis was then produced in `doc_new/` — eight documents derived
exclusively from source code, with executed verification.

**This folder merges both sets**, resolving fifteen points of disagreement against the source
tree and re-running every behavioural probe. It was originally created as `doc_new_2/` alongside
the two source folders; once complete, both `gym_continuousDoubleAuction/doc/` and `doc_new/`
were deleted and `doc_new_2/` was renamed to `doc/`, taking their place at the repository root.
The reconciliation table is in [README.md](README.md#reconciliation-of-the-two-source-sets).

The top-level `README.md` was not part of this restructuring and still links to
`gym_continuousDoubleAuction/doc/change.md` and the three `CHANGES_*.md` redirect shims — those
paths are now broken, since the folder they pointed into no longer exists. Fixing the top-level
`README.md` is follow-up work, not something this merge did.

## 10. Test suite: unittest → pytest

The entire test suite (90 unit tests across 13 files, plus the 13-test RLlib integration file)
was converted from `unittest.TestCase` to plain pytest-native classes: `self.assertX(...)` calls
became `assert` statements, `setUp` / `tearDown` / `setUpClass` / `tearDownClass` became pytest's
built-in xunit-style `setup_method` / `teardown_method` / `setup_class` / `teardown_class` hooks
(no decorator needed — pytest recognises these names on any class), and `self.assertAlmostEqual`
became `pytest.approx`. `test_probabilistic_mapping.py` needed no changes — it was already a
bare pytest-style function.

One behavioural consequence: every file previously ended with
`if __name__ == "__main__": unittest.main()`, which let a test file be run directly
(`python test_foo.py`) or via a notebook's `%run`. That block is gone, since pytest doesn't need
it and it would have called `unittest.main()` against classes that no longer inherit
`TestCase`. Running a file directly, or `python -m unittest discover`, now does nothing — `pytest`
is required. See [10_testing.md](10_testing.md) §0.
