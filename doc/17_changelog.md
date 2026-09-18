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
The reconciliation table produced during that merge was not carried into the current
[README.md](../README.md), which indexes the merged set instead.

**Follow-up since done.** The top-level `README.md` was not part of that restructuring: it still
pointed at `gym_continuousDoubleAuction/doc/change.md` and three `CHANGES_*.md` redirect shims in
a folder that no longer existed, and every entry in its own document table omitted the `doc/`
prefix, so all 39 of those links resolved against the repository root and were broken. Both are
fixed; the table now lists every document, including [18](18_configuration.md), [19](19_docker.md), [20](20_colab.md) and [21](21_logging_review.md).

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

## 11. Configuration surface: `config/`, and knobs that were literals

Previously the project's parameters lived in three places with no map between them: the
`env_config` dict, the `TrainConfig` dataclass, and a scattering of hardcoded literals. Some of
the literals mattered a great deal — the five reward coefficients among them.

**`config/`** was added at the repository root, initially as four JSON files inventorying the
configuration surfaces. `env_config.json` has since been **merged into `train_config.json`**, whose
`environment` group is what `TrainConfig.env_config` forwards to the env, leaving three files.
Each carries `_source` keys naming the module its values come from, since JSON has no comments.

`train_config.json` is now a **real input**, loaded by `TrainConfig.from_json(path)` or
`--config`. Precedence is dataclass defaults → file → explicit flags, which required every flag to
declare `argparse.SUPPRESS` as its default so an unset flag cannot overwrite a value from the
file. Unknown keys raise; while the files were purely descriptive a misspelled key had no symptom.
`--config` is also the only way to reach fields with no flag, `num_learners` among them.
`cli_defaults.json` and `tunable_constants.json` remain descriptive.

The merge added `TrainConfig` fields for `initial_price_min` / `initial_price_max`, which `reset()`
read but no training run could set. One key changes name across the env boundary — the field is
`num_agents`, the env receives `num_of_agents` — and is covered by a test.
See [18_configuration.md](18_configuration.md).

**Promoted to config**, each with the wiring that makes the key real:

- The five reward coefficients (`order_penalty`, `trade_penalty`, `drawdown_penalty`,
  `passive_bonus`, `loss_multiplier`), from literals inside `Reward_Helper.set_reward` to
  `env_config` keys. See [07_reward_function.md](07_reward_function.md) §2.
- Order sizing (`min_size`, `mkt_max_size`, `limit_size_multiple` — the last previously the
  single-letter `Action_Helper.N`), likewise to `env_config` keys.
- `fcnet_activation` and `vf_share_layers`, from literals in `model_handler` to `TrainConfig`
  fields, next to the `fcnet_hiddens` field that was already there.

These reach their consumers through the mixin `__init__` chain. `State_Helper.__init__` called
`super().__init__()` with no arguments, which would have silently swallowed every new key; it now
forwards `**kwargs`.

**`tick_size` half-consolidated.** It was two independent values: a hardcoded
`Action_Helper.min_tick` that drove prices, and an `OrderBook` argument that was stored, never
read, and discarded anyway when `reset()` rebuilt the book as `OrderBook(1, ...)`. `tick_size` now
sets `min_tick`, so the key governs the price grid agents quote on. Both defaults were 1, so
behaviour at default config is unchanged.

The other half — deleting `OrderBook`'s inert copy so the action layer is the single definition —
was implemented and then **deliberately reverted**, because the `envs/orderbook/` package is
off-limits to changes. `OrderBook` still accepts and stores a `tick_size` it never reads, and
`reset()` still hardcodes `OrderBook(1, ...)`. `_set_price` performs no quantization. S3-4 in
[15_findings_and_recommendations.md](15_findings_and_recommendations.md) is therefore **partly
fixed**, not resolved, and carries the reasoning for the deferred half.

**Book depth de-duplicated.** `K_ROWS`, the action space's `price: Discrete(10)`, and two literal
`.reshape(4, 10)` calls in `action_helper` were four copies of one number. All now derive from
`K_ROWS`. Depth is still not an `env_config` key — that needs `SNAPSHOT_DIM` to become
per-instance — but changing it is now a one-line edit rather than a four-site one.

**`max_price` deleted.** It was stored on `Action_Helper`, passed into `_set_price`, and read by
nothing; `_higher` / `_lower` carried it as an unused parameter and have no callers at all. No
behaviour change. Closes half of S4-3.

`TestTickGrid` in `test_new_action_space.py` covers the tick reaching the action layer and the
depth/action-space agreement. Its assertion that `OrderBook` carries no tick was removed with the
revert described above.

## 12. `config/` became the only place values live

Section 11 left the project with one real input file and two descriptive inventories, and with
values still written twice — once in JSON, once as a Python default. That duplication had already
produced a live discrepancy: the `TrainConfig` dataclass said `num_cpus_per_env_runner = 1.0` and
`num_gpus_per_learner = 0.75`, while `train_config.json` said `0.25` and `0.25`. A run without
`--config` used the dataclass pair, so editing the file did nothing unless you also remembered the
flag.

The rule is now that **no module holds a literal copy of a configured value**. Python declares the
schema; `config/` holds every value.

**[`config_loader.py`](../gym_continuousDoubleAuction/config_loader.py)** was added as the single
entry point. A missing key raises — naming the file, the group and the keys that do exist — rather
than resolving to a default written in Python. `$CDA_CONFIG_DIR` repoints it at another config
tree, which is what makes the no-literals claim testable.

**All four files became inputs** (a fifth, `runtime_profiles.json`, arrived later — see §13).
`env_defaults.json` was added to hold the env's standalone
fallbacks, which deliberately differ from the training values and had been literals in
`continuousDoubleAuctionEnv.__init__`. `tunable_constants.json` and `cli_defaults.json` stopped
being inventories and became live. `train_config.json` is no longer opt-in: `TrainConfig()` reads
it, so `--config` now means "run against a *different* file" rather than "actually use the config".

**Structural constants became real.** `k_rows`, `book_rows` and `extra_dim` moved to config and
onto the env instance, so the observation space is built from `self.snapshot_dim` and book depth is
genuinely changeable — the refactor §11 deferred. `category_n` and `price_offset_n` moved too, and
are now **validated against the code that decodes them**: `category_n` against the `_CATEGORY_MAP`
table that replaced the hardwired `if`/`elif` chain, `price_offset_n` against the requirement that
it be odd. The offset is computed as `price_offset - price_offset_n // 2` instead of a literal
`- 1`, so widening it to 5 codes extends the range to ±2 ticks and works. A structural value the
code cannot honour now raises at env construction instead of being silently ignored.

**The two `100.0` price-anchor fallbacks are one value.** So are the plot figure sizes, the
visualizer paths, the `policy_` / `champion_` prefixes, and the `RAY_DEBUG_DISABLE_MEMORY_MONITOR`
setting. `reset()` builds the book with the configured `tick_size` rather than a literal `1`.

**Still hardcoded, deliberately:** `OrderBook`'s inert `tick_size` default of `0.0001`, because
`envs/orderbook/` remains off-limits. It is the one exception, recorded as such in
`tunable_constants.json`.

[`test_config_sources.py`](../gym_continuousDoubleAuction/test/test_config_sources.py) proves the
property rather than asserting current values: it copies `config/`, edits a value, points
`$CDA_CONFIG_DIR` at the copy, and checks the change reaches the observation space, the action
space, the env fallbacks and `TrainConfig`. A literal left behind would keep the old value and fail.
See [18_configuration.md](18_configuration.md).

---

## 13. The notebook runs on two machines, from config

`CDA_NSP.ipynb` was a Colab notebook that happened to also work elsewhere: a hand-flipped
`IS_COLAB = False`, a hardcoded pip list, a hardcoded Drive path, and a `TrainConfig(...)` call
passing eleven keyword arguments. It now runs unchanged on a Colab VM and inside the
[docker/ml image](19_docker.md).

**The config cell stopped holding values.** Ten of its eleven arguments restated
`train_config.json` exactly; the eleventh (`num_gpus_per_learner=0.75` against the file's `0.25`)
was a no-op, since with `num_learners=0` the fraction only selects a device and never becomes a
Ray resource request. The consequence was worse than the redundancy: editing `train_config.json`
changed nothing for those ten keys, and a config tree swapped in via `$CDA_CONFIG_DIR` applied to
every field *except* them. The cell is now `TrainConfig()` and reports what it read.

**`config/runtime_profiles.json` (new, the fifth file).** Two hardware parameter sets — `gpu`
(2 CPUs + 1 GPU) and `cpu` (1 CPU, none) — plus per-platform paths, resolved by the new
[`train/runtime.py`](../gym_continuousDoubleAuction/train/runtime.py). The split it introduces is
the point: `train_config.json` is *what the run does* and is identical everywhere;
`runtime_profiles.json` is *what the machine is*. A test asserts a profile moves no field that
changes the learning problem, so a Colab run and a docker run stay comparable.

**Two knobs left in the notebook**, `PLATFORM` and `USE_GPU`, both defaulting to `auto`. Detection
covers Colab (`COLAB_RELEASE_TAG`) and the docker image (`/.dockerenv` **and** the recorded
`repo_path` existing — `/.dockerenv` alone is true in any container, including a dev container that
is not this image). `$CDA_PLATFORM` / `$CDA_USE_GPU` pin either one for headless runs.

**Colab specifics that were previously left to the reader.** The bootstrap installs only what is
missing, at the pinned versions, then stops with a restart banner — the install moves packages
Colab has already imported, and continuing in the same session is the classic silent failure. It
is a no-op on the second run. Checkpoints go to the Drive-backed repo so `is_restore` survives a
disconnect, while the per-episode pickles (~10MB per 4096-step episode, measured) go to the VM's
local disk instead of crossing the Drive FUSE layer. `torch`, `numpy` and `pandas` are absent from
the install list on purpose: this repo's pins would replace Colab's preinstalled CUDA torch with a
CPU wheel.

**Under Jupyter the kernel's working directory is the notebook's own directory**, one level below
the repo root that `python -m ...train` runs from — so notebook and CLI runs had been writing to
two different `results/` trees. `runtime.chdir_to_repo()` resolves it, best-effort: a container
with the working tree bind-mounted somewhere other than `/workspace/code` degrades to the `local`
platform, which relocates nothing.

`train.main()` also lost its private copy of the `runtime_env_vars` export loop; both it and the
notebook now call `runtime.apply_env_vars()`.

See [18_configuration.md](18_configuration.md) §8 and
[10_testing.md](10_testing.md) §6.3 (23 tests).

---

## 14. Checkpointing became recoverable

A run's checkpoint used to be a single directory. `algo.save(checkpoint_dir)` wrote every save to
`results/chkpt`, so the run had exactly one recoverable state — no way back from a league that
collapsed at iteration 12, and a save interrupted partway through destroyed the only copy. That is
the event checkpointing exists to survive, and on Colab (§13) it is the expected way for a session
to end.

**Each save is now its own directory**, `results/chkpt/iter_00008`, staged as `iter_00008.tmp` and
renamed into place; the newest `chkpt_keep` (default 3) are retained and the rest pruned. An
interrupted save leaves a `.tmp` directory the scanner skips rather than a half-written one that
looks complete, and a restore that cannot read the newest checkpoint falls back to the one before
it — verified against a real truncated checkpoint
([16 §16.8.1](16_verification_log.md), probe 8). Rolling back is now just deleting the newest
directory. A checkpoint in the old layout is still found and restored from, and is never pruned.

**A restore no longer silently discards config edits.** `Algorithm.from_checkpoint` rebuilds
everything from the config stored *in the checkpoint* and drops the `PPOConfig` just built from
`train_config.json`. Since resuming is documented as "edit `train_config.json`, set `is_restore`",
that is the same file holding `lr`, the reward coefficients and `num_agents` — an edit made in the
same pass had no effect and said nothing. A structural change (`num_agents`, `n_hist`, the policy
set) now raises, because the restored weights do not fit the requested problem; everything else
prints as ignored, with both values.

**`num_iters` became a target rather than an amount.** The driver loop counted from zero, so 16
configured iterations after a restore meant 16 *more*, and the length of a run depended on how many
times it was interrupted. It now reads `algo.iteration` — RLlib restores `training_iteration` with
the weights — and trains through `num_iters`, printing true iteration numbers. `num_iters_is_delta`
opts back into the old reading for extending a finished run.

**Champion metadata got a readable copy.** `champion_history`, `champion_id_counter` and
`available_modules` reached the next run only via cloudpickle of `SelfPlayCallback`; a rename, an
`__init__` change or a Ray upgrade would bring the champion modules back without the league that
indexes them, restarting the counter and re-minting `champion_1` over a champion still in play.
`league_state.json` is now written beside every checkpoint and reconciled on restore against the
modules that actually came back. See [08 §8.1](08_self_play_league.md).

**`build_algo` returns the algorithm's own callback on the restore path** (S3-8), not the fresh,
empty one from `build_config`. Training never used the returned object, which is why the bug
survived — the damage was to anything that inspected the league.

**Which checkpoint to resume from became selectable.** `restore_path` (`--from-checkpoint`) pins
one save; `null`, the default, takes the newest, which is what a disconnect wants. It requires
`is_restore` — set without it the run would silently start from scratch, so it raises — and a
pinned checkpoint never falls back to its neighbour, since training from a checkpoint other than
the named one is exactly what pinning exists to prevent. Rolling a run back past a collapsed
league no longer means deleting directories.

40 tests in `test_checkpointing.py` ([10 §6.1.1](10_testing.md)), plus eleven probes against real
checkpoints in [16 §16.8.1](16_verification_log.md).

See [18_configuration.md](18_configuration.md) §5.1–5.2 and [20_colab.md](20_colab.md) §20.5.

---

### Logging and the conservation invariant

**`logging` replaces `print`** (S2-8). There was no logging framework at all: ~86 `print()` calls
across `envs/` and `train/`, 42 in the self-play callback alone, and with `num_env_runners > 0`
every remote worker wrote all of them into one stream with no level filter, no attribution and no
way to turn them off short of editing the source.

Everything now reports through
[`logging_setup.get_logger`](../gym_continuousDoubleAuction/logging_setup.py), at levels: `DEBUG`
for per-step detail (the env render, account and LOB tables), `INFO` for per-episode and
per-iteration events, `WARNING` and `ERROR` for the rest. The format carries the pid, so
interleaved worker output is separable. `cda_log_level` in `train_config.json` sets the level and
is exported as `$CDA_LOG_LEVEL`, which is how it reaches Ray's worker processes — they are
separate interpreters that never run `main()`. It is kept distinct from Ray's own `log_level`.

Two consequences worth knowing: the env's per-step render is now gated on DEBUG as well as
`is_render`, so a bare env no longer dumps the whole book on every step at the default level (the
random runner's `--render` raises the level itself); and entry points name their loggers
explicitly, because `python -m` sets `__name__` to `"__main__"`, which is not under the package
logger and would have dropped every INFO line.

**A NAV conservation violation raises.** The check compares the sum of every agent's NAV against
the cash the system started with — a hard ledger invariant — and reported a break by printing
`FAILED` into a stream nobody read. It now emits `nav_conservation_error` through
`metrics_logger` whether or not the invariant held, logs at ERROR when it did not, and raises
unless `strict_nav_check` is off. The tolerance is configurable (`nav_tolerance`) for a future
change that legitimately removes cash from the system, such as fees.

**The `g_store` trio was deleted** (S4-1): `train/storage/store_handler.py`,
`train/logger/log_handler.py` and `train/plotter/plot_handler.py`, ~270 LOC depending on a
detached Ray actor that was never created anywhere, so every entry point into them would have
raised at call time. The orphaned `plot_defaults` config group went with them.

`test_logging_setup.py` (10 tests) covers level resolution and export, handler setup, and fails
the build if a `print` reappears in `envs/` or `train/`; `test_nav_callback.py` grew from 2 tests
that asserted nothing to 6 that assert the behaviour above. See
[11_logging_and_observability.md](11_logging_and_observability.md).

---

## 16. The iteration that trained on nothing

A GPU Colab run of 16 iterations finished in 19 minutes having done **zero gradient steps**, and
said so only in a warning that reads like a performance hint:

```
WARNING rollout_ops.py:122 -- No samples returned from remote workers...
```

`sample_timeout_s` was left at RLlib's default of 60s. The batch is
`max_step × num_episodes_per_iter` = 16,384 env steps, and the Python order book delivers roughly
60 env-steps/sec per runner with 8 agents, so two runners need about two minutes. Every iteration
timed out, and a timed-out iteration does not return a short batch — it **discards** the partial
rollouts. The learner got nothing, while the loop counted the iteration, logged it, and wrote
checkpoints of the initial random weights. The only visible symptom downstream was a `KeyError:
'env_runners'` in the notebook cell that reads the league table, since a result with no samples has
no `env_runners` block at all.

- **`sample_timeout_s` is now a `TrainConfig` field** (`rollouts` group, `--sample-timeout`),
  defaulting to 600s rather than inheriting RLlib's 60.
- **`_log_iteration` names the failure**: an iteration whose result has no `env_runners` block logs
  a WARNING quoting the batch size, the timeout it missed, and the two knobs that fix it.
- **`train()` returns `(algo, last_result)`.** It returned only the Algorithm, so inspecting the
  league meant calling `algo.train()` again — a second full iteration of sampling and learning, run
  for its return value, outside this function's checkpointing. `CDA_NSP.ipynb` now reads the result
  it was handed.

See [18 §5.1](18_configuration.md#51-sample_timeout_s-and-the-run-that-trains-on-nothing) and
[09 §5.1](09_distributed_training.md).

---

## 17. What the first two GPU runs that trained showed

With `sample_timeout_s` fixed (§16), two full 16-iteration runs completed on 2026-08-15 doing real
gradient steps: one on a Colab T4 at 186s/iter, one in an RTX 4060 docker container at 58s/iter.
The docker run is recorded in `CDA_NSP.ipynb`; the Colab notebook was not committed, so the figures
below come from that run's own output rather than from a file in this repository. Both reached
262,144 lifetime env steps, kept NAV conserved in every episode check, and finished with 2 healthy
workers and 0 restarts.

Both also hit the same two silent failures, on different machines with different seeds.

### 17.1 Each fresh checkpoint was deleted the moment it was written

The log says it plainly, once you look for it:

```
pruned old checkpoint: .../results/chkpt/iter_00002
checkpoint at iter 2:  .../results/chkpt/iter_00002
```

Same path, prune first. Repeated at iterations 4, 6, 8 and 10, then stopping — which is the tell:
`chkpt_keep` is 3, and the directory already held `iter_00012/14/16` from an earlier run.
`_prune_checkpoints` ranked by iteration number, so the save just written was the "oldest" of four.

Retention now ranks by **mtime**, with the iteration number as tiebreaker. mtime says what the
iteration number cannot: which of these did *this* run write. A run starting from scratch in a
directory holding checkpoints it did not write also warns and names them, newest first —
`warn_about_foreign_checkpoints`. Nothing is deleted; the directory belongs to the operator.

The reason this matters beyond disk hygiene is restore selection, which still ranks by iteration
number (correctly — a resumed run's saves genuinely are the higher-numbered ones). For the first
eleven iterations of both runs, `--restore` would have loaded the *previous* run: in this case the
one from §16 that trained on nothing. See [15 S3-17](15_findings_and_recommendations.md).

### 17.2 Champion promotion died two-thirds of the way through

`iteration N league stats: mean=nan std=nan threshold=nan` — from iteration 12 of 16 on Colab,
iteration 10 in docker, and every iteration after.

`on_train_result` filtered `None` out of `module_episode_returns_mean` but not `NaN`, which is what
RLlib reports for a module the mapping fn did not draw that iteration. One NaN makes the mean, the
std and the threshold NaN, and every `best_return > threshold` False. Both runs froze at 4
champions. It is self-reinforcing: each champion in the pool makes an undrawn baseline likelier,
so the failure becomes more certain the longer the run goes.

NaN is now filtered alongside `None`, and the modules that played no episodes are named at INFO
rather than silently distorting the league. See [15 S3-16](15_findings_and_recommendations.md).

### 17.3 What both runs did not do is learn

Unchanged and already documented as S1-1: `vf_loss` pinned at the `vf_clip_param` bound of 10.0,
`vf_loss_unclipped` between 1.4e11 and 6.6e11, `vf_explained_var` at 0.0 to 1.8e-07. The critic
receives no gradient, PPO degenerates to REINFORCE, and `best_trainable` across the 16 iterations
of either run is noise with no trend. The infrastructure now works end to end; the learning
problem is untouched.

---

## 18. A run leaves a record behind

The two GPU runs in §17 could only be diagnosed after the fact, from scrollback, because
`algo.train()` returns a full metrics dict every iteration and the driver loop read two keys out
of it — `num_env_steps_sampled` and `module_episode_returns_mean` — for a log line and dropped the
rest. The loop calls `algo.train()` directly rather than through `tune.Tuner`, so nothing wrote
`progress.csv` or TensorBoard events either. A finished run left checkpoints and no history.

**Every iteration now appends its whole result dict to `<log_base_dir>/progress.jsonl`.** Not a
chosen subset: the loss terms, KL, entropy, timers and learner stats are all in there, because
deciding in advance which of them a future question needs is what produced this gap. A
`_json_safe` pass runs first, since RLlib results carry numpy scalars and arrays, the occasional
object with no JSON form, and NaNs — numbers stay numbers rather than being stringified by a bare
`default=str`, non-finite floats become `null` because `NaN` is not valid JSON, and anything left
over is stringified. The file is opened and closed per iteration so a killed run keeps the
iterations it finished, and every failure inside the writer is swallowed with a warning:
instrumentation must not be what takes down a run that is otherwise training fine.

**`vf_explained_var` is now in the per-iteration log line**, per trainable module, beside the
returns. This is the metric §17.3 identifies as the one that exposes S1-1, and nothing surfaced
it — which is why a critic pinned at 0.0 survived two full runs. It is read from
`result["learners"][<module_id>]`, keyed on `trainable_policy_ids`: only the modules in
`policies_to_train` appear there, so the frozen champions and the random baselines are absent by
construction. A module missing from the result is omitted rather than reported as 0.0, since
"absent" and "the critic explains nothing" are different states and telling them apart is the
whole point.

**CI asserts on it.** `test/integration/test_progress_and_vf.py` trains a real PPO for three
iterations at the existing tiny test size and checks that the file has one line per iteration,
that a real result survives the JSON round trip, and that every trainable module reports a finite
`vf_explained_var`.

The obvious next assertion — `!= 0.0`, the value a critic that never received a gradient reports —
was written, run, and thrown away, because it **passes on this repository today**. A run of the
suite reports values around 1e-5, matching the "0.0 to 1.8e-07" that §17.3 records from the two
GPU runs, and all of it is nonzero: floating-point noise is not evidence of learning, so the
assertion would have guarded nothing while looking like it guarded the defect. What is there
instead is `test_the_critic_actually_explains_something`, asserting `|vf_explained_var| >= 1e-3`
under a **strict xfail**. It fails today because S1-1 is open. When S1-1 is fixed it XPASSes and
fails the build, at which point the marker comes off and it becomes the live regression guard it
cannot be while the defect is still there.

`test_progress_log.py` (19 tests) covers the writer itself against hand-built results — the
append-across-a-restart case, numpy and NaN handling, and a write failure that must not stop the
loop.

See [11_logging_and_observability.md](11_logging_and_observability.md) §1.6.

---

## 19. A step leaves a record behind

§18 gave the *run* a history. The *step* still had almost none: `Info_Helper.set_info` reported
`reward`, `NAV` and `num_trades`, and everything else a step knew about itself was computed,
consumed and dropped inside the same function call. The position was in the account, the drawdown
was calculated in `set_reward` and thrown away the moment the penalty was charged, the spread was
derived in `state_helper` as `log1p(spread_ticks)` for the observation and the raw number
discarded, and the five reward components existed only as terms in one expression. Every question
in [11](11_logging_and_observability.md) §2.2–2.4 was unanswerable not because the data was hard
to get, but because nothing kept it.

**The per-step `info` dict now carries account state, market state, the reward decomposition and
the submitted action** — see [11 §1.7](11_logging_and_observability.md) for the field list. The
original three fields are untouched in name, type and order, and `NAV` remains the exact `str()`
of a `Decimal` so the conservation check (§1.5) and `visualize_nav.py` both keep working.

Four decisions in that change were not obvious, and one of them was a trap.

**The reward terms sum to the reward, and the sum is the reward.** `set_reward` builds a dict of
signed contributions and accumulates it, rather than keeping the old expression and computing a
parallel breakdown beside it. A decomposition that can drift from the number the agent was trained
on is worse than no decomposition, because it looks authoritative.

**The trap: `sum()` would have changed the reward.** The obvious way to write that accumulation is
`sum(terms.values())`. On Python 3.12+ the builtin applies Neumaier compensated summation to
floats — it is *more* accurate than the original left-to-right expression, and it disagrees with
it on ~44% of random inputs, by ~1e-13 relative. `math.fsum` likewise. Adding instrumentation must
not perturb what is being instrumented, so the reward is accumulated with an explicit loop, which
reproduces the previous arithmetic bit for bit — verified over 200,000 random inputs. Iterating
the dict rather than naming the five keys also means a sixth term added later cannot be logged but
left out of the reward.

**`net_position` is reported as a float.** `account.py` initialises it to `int` 0 and then
rebuilds it as a `Decimal` on the first fill, so its type changes partway through every episode.
That is a latent inconsistency in the account, not something this change fixes; reporting one type
throughout at least keeps it from reaching consumers.

**`spread` is `None`, not `0.0`, when the book is one-sided.** The observation needs a finite
sentinel and uses `0.0`. A log does not, and `0.0` there could not be told apart from a book whose
touch is one tick wide — the collision [15](15_findings_and_recommendations.md) S3-14 describes.

`test_info_dict.py` (18 tests) covers the back-compat of the original three fields, the terms
summing exactly, penalties equalling coefficient × counter, `spread` on a one-sided book, and the
whole dict surviving `json.dumps` — a numpy `int64` in `info` would break the progress log, and
unlike `np.float64` it does not subclass its Python counterpart. One of those tests was checked by
mutation: moving the per-step counter reset to before `set_info` makes it fail, which is the point
— the counters would otherwise log a valid, healthy-looking, permanent 0.

See [11 §1.7](11_logging_and_observability.md) and [07 §6.4](07_reward_function.md).

---

## 20. Money in Decimal, sizes in int

The account was `Decimal` where it mattered, but four of its fields did not hold one type for a
whole episode. Measured over a real run: `net_position` was `int` until the first fill and
`Decimal` after; `VWAP` was `Decimal` until a position went flat and `int` after, from a bare `0`
at `account.py:136`; `reward` was `int` until the first `set_reward`; `drawdown` was `Decimal`
until the first step, introduced by §19, the change that documented the pattern.

The policy is now explicit — money and prices `Decimal`, sizes `int`, `reward` and `drawdown`
`float` — and enforced by `test_type_policy.py` (15 tests) rather than left to convention. See
[11 §1.8](11_logging_and_observability.md).

**This is not tidiness.** `Decimal * float` raises `TypeError`; `Decimal * int` does not. The
orderbook already carries two workarounds for that exact error, each commented with the traceback
it came from, and `cash_processor.py:78` computes `Decimal(str(price)) * qoute['quantity']`, which
would raise on the modify path with a float size. Making sizes `int` removes the failure mode
instead of adding a third workaround.

**The orderbook is untouched**, per `ec1f5ea`. It stores sizes as `Decimal` — `order.py:12`
coerces on the way in — so a fill reports whichever type its branch held: `quantity_to_trade`
(int) on a partial or exact fill, `head_order.quantity` (Decimal) when the incoming order is the
larger one, 84 against 10 on one tape. Rather than change the book, the mixing is absorbed at the
one point every trade passes through on its way into env code, `trader._normalise_trade_sizes`.
That coercion is lossless by construction and not by luck: ints go in, the book only subtracts
whole sizes from whole sizes, and a fractional size raises rather than truncating silently.

Sizes are also `int` at ingress. The old `act["size"] = (size + self.min_size) * 1.0`, commented
*"\*1 for float"*, was the single character that made every downstream size a float.

**A mutation test earned its keep here.** Restoring that `* 1.0` left all thirteen type tests
green, because the egress normalisation absorbs float sizes so completely that the account never
sees the difference. The tests could not distinguish a working ingress from a broken one. Two
ingress tests were added for that reason, and the same mutation now fails both — which matters
because `cash_processor`'s modify path is reached by orders, not by the trades the egress tests
inspect.

Two deliberate exceptions. `reward` and `drawdown` stay `float`: RLlib requires float rewards and
the drawdown feeds the reward, so they are learning signals rather than money. `last_price` stays
`float` because it never reaches the ledger — `mark_to_mkt` hands the account the tape's `Decimal`,
while `last_price` is a separate anchor consumed only by `_set_price`'s NumPy arithmetic and by
`state_helper`, which already wraps it in `float()`.

`info` is unaffected as a format, being a serialisation boundary where JSON has no `Decimal` —
except that `net_position` is now a plain `int` rather than a `float()` cast that existed only to
hide the account changing type underneath it.

---

## 21. The log outlives the terminal

§18 gave the run a machine-readable history and §19 gave the step one. The log itself was still
written only to stdout, so a finished run left its numbers on disk and its narrative in scrollback:
the per-episode NAV tables, the league statistics, and the ERROR that immediately precedes a
`strict_nav_check` raise. §17 records two GPU runs diagnosed exactly that way — after the fact,
from a terminal buffer. There was one `addHandler` call in the package and it attached a
`StreamHandler`.

**Every process now writes a rotating log file under `log_base_dir`, beside `progress.jsonl`** —
`run.log` from the driver, `run.<pid>.log` from each env runner. Bounded by `file_max_bytes` and
`file_backup_count`, so it does not re-create the unbounded-growth problem [11 §3] lists for the
episode pickles. A failure to open it warns rather than raising: instrumentation must not take
down a run that is otherwise training, the same rule `_append_progress` follows.

**One file per process is not a detail, and measuring it changed the design.** The first version
wrote from the driver only, on the reasoning that `RotatingFileHandler` is unsafe across processes
— two of them crossing the size threshold together rename and truncate the same file — and that
Ray captures worker stdout anyway. A real two-runner run showed what that costs: the driver file
held 7 lines and **not one NAV table**. The episode callbacks run on the env runners, so with
`num_env_runners > 0` the NAV tables and the conservation ERROR are emitted in a worker and reach
no file at all. Since the shipped runtime profiles use `num_env_runners=2`, driver-only logging
would have missed precisely the lines that motivated the change. Per-process files keep them and
sidestep the rotation race, since no two processes share an inode. `log_base_dir` reaches the
workers through `$CDA_LOG_DIR`, the same channel the level already takes.

**Timestamps carry the date.** `datefmt` was `"%H:%M:%S"`. A training run outlasts a day, so a
time-only stamp cannot be ordered across midnight or joined to anything dated.

**Log lines carry the training iteration.** `progress.jsonl` is keyed by iteration and the log was
keyed by nothing, so relating the two meant matching on wall-clock order. Lines are now stamped
`iter=<n>`, tracked in a `ContextVar` — per-thread, not a module global, since the driver loop may
not be the only thread — and injected by a filter on the *handlers* rather than the logger, because
a filter on the package logger never sees records propagating up from a child module. It reads `-`
where the iteration is unknown, which is deliberate: `0` is a real iteration number.

Being honest about the limit: with remote runners a worker's NAV table is dated, attributed and
durable but reads `iter=-`. The worker does not know which iteration its episode belongs to.
Recovering that means passing the iteration to the runners, which is a change to what RLlib hands
the callbacks rather than a logging change.

`test_logging_setup.py` grows from 10 tests to 29. Two isolation hazards the new ones introduced
are handled in the fixture rather than left to luck: file handles are closed before pytest removes
the `tmp_path` they point into, and `$CDA_LOG_DIR` is restored, since `configure` now exports it
and a leaked value would make the next test write into a directory that no longer exists.

See [11 §1.9](11_logging_and_observability.md).

---

## 22. Two behaviours a return series cannot tell apart

An agent that stops trading looks the same in its returns whether it *chose* to pass or whether
every order it sent was refused for want of cash. Both produce a flat, unremarkable line, and
nothing recorded could separate them.

The first case is **S1-1's companion, S1-3**. `entropy_coeff` is 0.0, so policies can collapse to
always-pass, and a do-nothing policy still clears the champion promotion threshold because 0 beats
a negative league mean. The pool then fills with snapshots of the do-nothing policy while the
returns series looks ordinary. [11 §2.2](11_logging_and_observability.md) has listed the
`category=0` count as "**directly detects** the passivity collapse predicted by S1-3" since the
audit; it was still not counted.

The second is a policy quoting past its cash. `order_step_placed` cannot express it: that flag is
`0` both for an agent that never tried and for one whose order was refused, which are opposite
behaviours.

**Both are now metrics** — `pass_action_fraction` and `order_rejection_fraction`, per episode,
`window=10` (§1.2). The custom-metric count goes from four to six.

Two details worth recording.

**The pass flag is set where the encoding lives.** `is_pass_action` is written in `set_actions`,
beside `_CATEGORY_MAP`, rather than derived by a consumer from `category == 0` — a reader of `info`
should not have to know the action encoding to ask whether an agent passed. `test_info_dict.py`
cross-checks that the flag and the encoding agree, over every agent-step of a real episode; they
did, 200 of 200.

**A counter that never fires is indistinguishable from a broken one.** The first run of the
rejection counter reported 0 across 200 agent-steps, which proves nothing — at `init_cash=1e6`
every order is affordable. Re-run at `init_cash=500` it reported 151 of 200, and that case is now
a test, so the counter is known to be able to fire rather than assumed to be.

The tally is a plain dict keyed by episode ID, not a `defaultdict` with a lambda factory: this
callback is cloudpickled into every checkpoint, and a lambda default_factory is exactly the kind of
thing that passes every local test and fails on a restore path nobody exercised. There is a test
that pickles the callback mid-episode. It is also counted independently of the per-episode pickle
store, since `episode_data_dir=None` is a supported configuration and these metrics must not
depend on that dump being switched on.

**[verified]** on a real 2-iteration run: `pass_action_fraction` reported `0.122` and `0.130`,
consistent with 1 of 9 action categories being the pass code for near-uniform untrained policies.

This also makes [11 §4](11_logging_and_observability.md)'s recommendation list accurate again.
Item 3 is done; items 1, 2 and 4 turn out to be half done in the same way — the reward
sub-components, the per-agent account state and the market price and spread are all captured in
`info` but none is reduced into a metric. That is the shape of what remains: capture is good,
aggregation is six metrics.

---

## 23. Logging: concurrency, run isolation, and the traceback that was never logged

A review of the logging *functionality* rather than its coverage — what happens when more than one
thread or process writes at once, and what a run leaves behind when it dies. Six changes, in
descending order of how much they can cost.

See [11_logging_and_observability.md](11_logging_and_observability.md) §1.10–§1.14.

### 23.1 Two runs shared one `run.log` and one `progress.jsonl`

The per-worker file names (§1.9) kept the processes of *one* run apart, and the reasoning was
explicit: `RotatingFileHandler` is not safe across processes, so two of them crossing the size
threshold together rename and truncate the same file. But the driver's own file carries no pid, and
`log_base_dir` defaulted to a fixed `results`. So two concurrent runs — or a notebook session
alongside a CLI run — hit exactly the race the worker naming exists to avoid, on the driver's file.

`progress.jsonl` was the worse of the two, because the failure is not rotation but line integrity.
`json.dump` writes incrementally: 61 `write()` calls for a trivial dict. `TextIOWrapper` coalesces
them into ~8 KiB chunks, so a small record is one atomic `O_APPEND` write — but a real RLlib result
dict is bigger than the buffer and splits (measured: 31 KB → 4 syscalls, 314 KB → 39). Two drivers
appending interleave *inside* a JSON line, and the record is then unparseable.

Each run now gets `<log_base_dir>/<run_id>/`, `run_id` generated from the date, time and four random
hex digits. The random suffix is not decoration: two runs launched by one script in the same second
would collide on a timestamp alone.

**The checkpoint tree deliberately stays outside it.** Restoring from a disconnect means finding the
newest `iter_*` an *earlier* run wrote; a per-run checkpoint tree would hide it and every resumed
run would silently start from nothing. So what must be shared is, and what cannot tolerate sharing
is not. `--run-id` re-enters an existing directory, which is how a restored run extends its own
`progress.jsonl`.

### 23.2 A run that died did not say why in its log

`main()` was `try: train(cfg) / finally: ray.shutdown()`, with no `except`. Python's default hook
writes the traceback to `sys.stderr`, outside logging — so `run.log` ended mid-sentence and the
reason lived in scrollback. That is precisely the failure §1.9 was written to fix, still present
for the single most valuable line in a failed run, and it applied to the `strict_nav_check`
`AssertionError` whose whole purpose is to stop a run loudly enough to be diagnosed later.

Now: `main()` logs it where it happens, so it carries the `iter=` that failed; `sys.excepthook`
catches whatever gets past that, including in *worker* processes that no driver-side try/except
could reach; and `threading.excepthook` catches a thread dying, which Python handles separately
again. Previous hooks are chained, so stderr still gets what it always did. `KeyboardInterrupt` is
one INFO line with no stack — these runs normally end by being killed.

### 23.3 The log level and directory did not reach a pre-existing cluster

`configure()` exports `$CDA_LOG_LEVEL` and `$CDA_LOG_DIR`, which workers inherit because the raylet
inherits the driver's environment. That holds only when this process *starts* the cluster. Against
`ray.init(address=...)` the raylet was started long before, so neither variable arrives: workers
come up at the config default and write no run log — and since the episode callbacks run on the
runners, the NAV tables and the conservation ERROR would reach no file anywhere. They are now also
passed as a `runtime_env`, which Ray applies to the workers it starts for the job regardless of who
started the cluster.

### 23.4 A pid is not a unique file name

`run.<pid>.log` is unique per *node*. On a multi-node run with `log_base_dir` on a shared mount —
NFS, or the Drive mount Colab uses — two workers on different nodes can hold the same pid and open
the same file, reintroducing the rotation race through the naming meant to prevent it. The name now
carries Ray's cluster-unique worker id behind the pid, which is kept because it is what the `pid=`
field of every line matches. Ray is read from `sys.modules` rather than imported: `apply_env_vars()`
must run before ray is first imported, and `configure()` runs before that.

### 23.5 Configuration was racy; nothing tested concurrency at all

The write path was always safe — `Handler.handle` takes the handler's lock around `emit`. The setup
path was not: `get_logger` checks `_configured` then acts on it, and `configure` closes and removes
handlers before adding replacements, so two threads inside that sequence produce duplicate handlers
or a handler closed mid-emit. It is now under one lock.

The reason this survived is that `test_logging_setup.py` had no thread or process test in it at all;
every safety property was asserted in prose. It now has both, including real subprocesses, which is
the one thing threads cannot stand in for.

The `iter=` tag also stopped being a `ContextVar`. It was chosen to be per-thread, but a new thread
starts from an empty context, so the driver's own lines read `iter=-` whenever they came from
anywhere but the loop thread — and a value set inside a Ray actor task is not guaranteed to survive
into the next task, which is what §23.6 depends on. One training loop per process makes the
iteration a property of the process, so it is a module global.

### 23.6 `iter=` now reaches the env runners

§1.9 recorded the worker's `iter=-` as needing "a change to what RLlib hands the callbacks". It did
not: the driver knows the number and `foreach_env_runner` already reaches every runner, so it only
had to be sent, once per iteration, before sampling starts. Best-effort — a restarting runner costs
`iter=-` on its lines, never the run. This is what makes a worker's NAV table joinable to its
`progress.jsonl` row under `num_env_runners > 0`, which is the configuration where those lines are
emitted nowhere else.

### 23.7 Two smaller corrections

**Output went to stderr, not stdout.** `logging.StreamHandler()` defaults to stderr, while §1.3,
§1.9 and `tunable_constants.json` all described stdout — so `train ... > run.txt` captured nothing.
Now explicitly `sys.stdout`.

**`warnings.warn` went nowhere.** A `DeprecationWarning` from Ray or gymnasium is the earliest
signal that an upgrade is about to break this repository, and it was going to stderr unrecorded and
unrotated. `logging.captureWarnings(True)` alone would not have been enough — it logs to
`py.warnings`, outside this package's namespace, which inherits none of its handlers and falls
through to stderr anyway; the handlers are mirrored onto it.

---

## 24. Logging under multiple env runners

§23 made the logging correct within a process and between two runs. It did not ask what happens
once sampling moves off the driver — which is what `runtime_profiles.json`'s GPU profile does at
`num_env_runners=2`, and what CI, at `num_env_runners=0`, never exercises.
[21_logging_review.md](21_logging_review.md) is that audit. Three of its findings were defects
rather than gaps, and all eight of its recommendations are implemented.

### 24.1 The stop signal stopped nothing

`strict_nav_check` exists to end a run whose ledger is corrupt. It did that by raising inside
`on_episode_end` — a hook that runs **on the env runner**. So the raise arrived as a `RayTaskError`
from `sample()`, and `restart_failed_env_runners` (True by default) made `EnvRunnerGroup` log it
through Ray's own logger and restart the actor. `algo.train()` returned normally, and the run kept
training on the ledger the check had just condemned. It stopped the run only at
`num_env_runners=0`, which is the default and what CI runs, which is why nobody had seen it.

The raise also destroyed the evidence: `synchronous_parallel_sample` asks each runner for
`(sample(), get_metrics())` in one call, so a throwing `sample()` means that runner's metrics —
including any record of the violation — are discarded with the error.

The hook now reports and returns: the ERROR, `nav_conservation_error`, and a
`nav_conservation_violations` count emitted on conserved episodes too, so the key always exists.
`train._check_nav_conservation` reads it after `algo.train()` and raises `NavConservationError` on
the driver, after the progress row is written and before the checkpoint. At `num_env_runners=0` the
stop is one iteration later than it used to be; that is the price of one code path that behaves the
same at every runner count.

### 24.2 The off switch turned off the write, not the work

`--no-episode-data` disabled the `pickle.dump` and left `on_episode_step` appending every step to an
in-memory store regardless. At 8,314 pickled bytes per step and `max_step=4096` that is ~34 MB per
episode of memory bought for nothing — `runtime_profiles.json` had estimated ~10 MB for the files,
which was wrong by 3.4× as well.

### 24.3 The episode record was the one path with no protection

The run log had been made absolute and run-scoped in §23; `episode_data_dir` had not. It was a bare
relative string, pickled into every env runner and resolved there against whatever working
directory that worker inherited — today usually the driver's, by accident rather than by guarantee
— and shared by every concurrent run.

### 24.4 What replaced the pickles

A Parquet record: one row per (episode, step, agent), a declared schema, and `run_id`, `iteration`,
`wall_time` and `module_id` columns. That closes three separate entries from
[11 §3](11_logging_and_observability.md) at once — arbitrary code execution on load, no timestamp or
iteration metadata, and no bound on growth — and makes champion matchups a group-by rather than
missing instrumentation. Writing happens on a background thread per process, every failure in it is
a warning, and `episode_sample_every` (default 10) plus `episode_max_bytes` (default 2 GiB per
writer) bound it.

It is written with `pyarrow.parquet`, not `ray.data`, deliberately. Starting a Ray Data execution
inside an env runner is the same objection [21 §5](21_logging_review.md) raises against RLlib's own
offline recording: it clamps to `num_cpus_per_env_runner` and competes with sampling on a two-core
profile. `ray.data.read_parquet` reads the output natively, so nothing downstream is lost.

**RLlib's Offline Dataset Logging cannot be used at all**, which is what prompted the review.
Setting `output` selects a recording env runner whose class selection opens with
`raise ValueError("Multi-agent recording is not supported, yet.")`, and this environment is
multi-agent by construction. Past that, the columnar format writes no `info` — which is most of what
this repository's per-step record exists to keep.

### 24.5 Six metrics became 27

The gap across [11 §2](11_logging_and_observability.md) was never capture; it was aggregation. The
per-step `info` already held the reward decomposition and the account state, and the callback
already computed the league's timing and pool. None of it was reduced into anything a run could
watch. Now: `reward_term_mean_*` and `reward_term_var_share_*` for all five contributions,
`episode_nav_mean`/`_min`/`_max`, `mean_agent_drawdown`, `mean_abs_net_position`, `mean_num_trades`,
`maker_fill_ratio`, `champions_promoted`, `iterations_since_champion`, `available_modules` and
`idle_modules`.

On a real 2-iteration run the variance split reads `nav_term` 0.95, `drawdown_penalty` 0.05, the
other three below 1e-8 — the [07 §6.4](07_reward_function.md) split, live, from a run rather than
from a post mortem.

### 24.6 Ray's own logging, and three things found while building this

`ray.init(logging_config=ray.LoggingConfig(...))` is the only lever that reaches a worker's Ray-side
output — the restart notices and the traceback §24.1 describes being swallowed. `ray_log_encoding`
selects it, feature-detected so an older Ray degrades to its own formatting, and setting it turns
propagation off on this package's logger since `LoggingConfig` configures root.

Three things the review had not predicted:

* **A 30-second hang at process exit.** The recorder's first design stopped its writer thread with a
  sentinel on the queue — and the one moment `close()` runs under load is the one moment the queue
  is full, so the put failed, the thread never stopped, and the join sat out its whole timeout. Two
  tests taking exactly 30.00s is what made it visible. It is a `threading.Event` now.
* **`on_train_result` metrics are one iteration late.** The hook is handed an already-compiled
  `result`, so `champions_promoted` reads 1.0 in the row *after* the promotion. Always true of
  `league_size` and the return statistics; the new champion metrics simply made it visible against a
  known event. Documented, not corrected — the lag is uniform.
* **Live state should never have been pickled.** The callback ships to every env runner and every
  checkpoint, carrying its in-flight episode tallies along. The unpickling side is a different
  process; a tally for an episode it never ran is not bookkeeping it should continue.

---

## 25. Three defects at the edges of a working simulator

A code review of the tree at `7e6e8fb` (see [15](15_findings_and_recommendations.md) S1-4, S3-6,
S3-18, S3-19). The finding worth recording is not any one of these individually but what they had
in common: the parts of this codebase that are *hard* to get right — Decimal accounting, price/time
priority, position flips, league checkpointing — were correct and defended by tests, while three of
the parts that are *easy* to get right were broken in ways that made both documented entry points
fail immediately. A 487-test suite exercised the env's parts thoroughly and never the shape of one
whole default episode.

### 25.1 The default env could not trade

`env_defaults.json` shipped `init_cash: 0`, and `_order_approved` gates on `nav <= 0`. A bare
`continuousDoubleAuctionEnv({})` placed no order ever and terminated after one step. Its
`max_step: 64` had never been reachable.

The reason this survived is worth more than the fix: CI's only bare-env job is the `CDA_rand.py`
smoke run, which supplies its own `init_cash` from `cli_defaults.json` — so the one job covering
the default env overrode the value that broke it. The new tests read the checked-in file on
purpose, because a fixture with its own cash would rebuild the same blind spot.

### 25.2 An episode ran `max_step + 1` steps

`set_all_done` tested `t_step > max_step - 1` while `step()` increments `t_step` afterwards.
`train_batch_size` is `max_step * num_episodes_per_iter`, so the env had been quietly delivering
four more steps per iteration than the batch it was sized for. Now written as
`t_step + 1 >= max_step` — in terms of steps taken, which is the quantity the caller counts.

### 25.3 An installed package had no config and could not import

Two independent defects behind one symptom, and the "Resolved since" table in
[15](15_findings_and_recommendations.md) had already claimed `setup.py` fixed for non-editable
installs on the strength of an earlier pass that addressed neither.

`install_requires` did not name `ray[rllib]` (the env subclasses `MultiAgentEnv`), `scikit-learn`
(`action_helper` imports `shuffle` at module scope) or `six` (`envs/orderbook/`, which is
off-limits, and which had been resolving by accident as a transitive dependency of pandas).
Separately, `config/` sits at the repo root outside the package with no `package_data`, so a wheel
carried zero JSON files — and because the config reads are default arguments evaluated at
class-definition time, that failed at *import*, not at first use.

A `build_py` subclass now stages `config/*.json` into the package at build time, which is exactly
the second location `config_dir()` already searched and never found. Nothing moved and no
documented path changed. Verified the way it should have been all along: build a wheel, install it
into a clean environment, construct an env.

The prior entry's remediation note was also wrong in a way that would have preserved the bug —
it said `import ray` in the env was "entirely unused". There were two ray imports, and the one
that mattered was the base class.

---

## 26. Reproducible episodes, and one deletion

Two follow-ups to §25, from the same review (see [15](15_findings_and_recommendations.md) S3-5,
S3-6, S3-20).

### 26.1 `reset(seed=...)` now seeds the episode

The env had three sources of randomness — the price anchor in `reset`, order sizes in
`_set_size`, and the queueing order in `rand_exec_seq` — and all three drew from the *global*
`np.random`. The `seed` argument reached `gymnasium.Env`, which set `self._np_random`, which
nothing read. All three now use `self.np_random`.

Worth recording because it changes how the old behaviour should be understood: **training runs
were already reproducible**, by accident. RLlib seeds global `random` and `np.random` per
EnvRunner from `config.seed + worker_index`, which happened to cover all three sources. What was
broken was reproducibility for anything that is *not* RLlib — the probes in
[16](16_verification_log.md), the generated-LOB figures, and any test that wants to pin what a
specific episode does rather than an invariant that holds for every episode. That last absence
is visible in the shape of the suite: it tests conservation and structure, and had nothing
pinning a trajectory.

Three things also made the accidental version unreliable: `run.seed` is `null` by default, the
seeding happens once per worker rather than per episode, and a runner restarted by
`restart_failed_env_runners` re-seeds from the same value and rewinds its stream mid-run.

`rand_exec_seq` had accepted a `seed` parameter since it was written that nothing ever passed.
It is honoured now, and the shuffle is `Generator.permutation` rather than
`sklearn.utils.shuffle` — so `scikit-learn`, a ~30 MB dependency in every EnvRunner used to
reorder at most `num_agents` dicts, is out of the requirements entirely. Fixing the seeding and
removing the dependency turned out to be the same edit.

### 26.2 `modify_cash_transfer` deleted

The one function in the accounting layer that computed the escrow delta of a size change
directly, with no call sites. It is gone rather than wired up because it is only correct where
the live cancel-and-reprocess path already is: when a modify does not match, the two are
algebraically the same expression, which is why NAV conservation never distinguished them. When
a modify *does* match — which `modify_order` fully supports, since it re-runs the quote through
`process_limit_order` — the escrow-delta form has no term for the fill and holds cash against
quantity that is no longer resting. Measured divergence and the full table are in
[15](15_findings_and_recommendations.md) S3-20.

The lesson is the one §25 opened with. This is the third piece of code found in this review that
was plausible, documented, and unreachable; a reader extending modify handling would reasonably
have changed it and seen no effect.

---

## 27. The documentation caught up with the code, and learned to draw

A review pass over every markdown file in `doc/` (`README_v1.md` deliberately untouched, as the
preserved 2020 README) against the source tree.

### 27.1 Line-anchored links had all rotted

Sixty-three code references carried a line range in both the link text and the anchor, in the
form `` `file.py:154-186` `` linking to `...#L154-L186`. Almost none
of them still pointed at the thing they named — `process_limit_order` had moved from 154 to 162,
`process_market_order` from 136 to 144, `on_train_result` from 265 to 757 — and several landed
inside an unrelated function or in a block comment. A line number is a reference that rots on the
next edit and rots *silently*, since nothing checks it.

All of them now point at the file, with the function or class named in the prose beside the link.
That is one indirection worse to follow and does not go stale. Ray-internal citations in
[21](21_logging_review.md) keep their line numbers: they cite a pinned version of somebody else's
source, which is exactly the case where a line number is the right reference.

### 27.2 What the docs said that the code no longer did

The specific corrections, each verified against the tree:

| Doc | Said | Actually |
|---|---|---|
| 02 §2.3 | `train/logger/`, `plotter/`, `storage/` exist as dead code; `test/` has 90 tests | Those three packages are deleted. 474 unit + 36 integration. `config/`, `config_loader.py`, `logging_setup.py`, `episode_record.py` and the eight `visualize/` scripts were missing from the map entirely |
| 02 §2.7, 05 §3.2, 15 S3-4 | `reset()` hardcodes `OrderBook(1, ...)`; the env never stores `self.tick_size`; `min_tick` is a second independent hardcoded tick | `min_tick` *is* the `tick_size` config key and `reset()` uses `self.tick_size`. Only the book's own copy is still inert |
| 02 §2.6 | `initial_price_min` / `initial_price_max` are unreachable from training | Both are `TrainConfig` fields, forwarded by `env_config` |
| 06 §6, 12 §5.5, 10 §8 | No episode is reproducible even with a seed set | S3-5 is fixed; `test_seeding.py` pins it eleven ways |
| 07 §2, 12 §3.6 | The five reward coefficients are function-local literals | They are `env_config` keys — the same document already said so two paragraphs earlier |
| 08 §7 | "Six metrics is the entirety of what reaches RLlib's structured logger" | 27. [21 §8](21_logging_review.md) had already corrected the same sentence in doc 11 and missed the copy here |
| 08 §9 | The NAV check raises `AssertionError` from the episode hook | The hook counts; the driver raises. That split is the whole point of [21 §2.1](21_logging_review.md) |
| 08, 04 §1, 07 §3 | Three per-step counters | Four, plus `reward_terms` and `drawdown` |
| 04 §3, 12 §5.6, 15 S4-14 | Rejections are silent and the dead-action fraction is unmeasurable | `num_rejected_step` and `is_pass_action` reach `info` and become metrics. The `modify` / `cancel`-with-no-target case is still uncounted |
| 05 §10, 11 §1.1, 14, 15 S4-9 | Episode data is `pickle`; two `.pkl` fixtures are committed | Parquet, and the files are gone from the repository |
| 02 §2.1, 10 §7 | CI is a 3.11 / 3.12 matrix of three jobs | Python 3.12 only, plus a second `packaging` job that installs the built wheel into a clean venv outside the checkout |
| 10 §0, §4.2, 01 §1.6 | 349 / 458 / 176 tests, depending on which line you read | 510: `509 passed, 1 xfailed`. `test_env_lifecycle.py` and `test_seeding.py` were missing from the inventory, and two tests listed under `test_observation_history.py` had moved |
| 08 §1 | The callback is 633 LOC | ~1,340 |

[16](16_verification_log.md) is a log rather than a status page, so its entries are kept as
recorded, with dated re-measurements added beside the two that read differently today.

### 27.3 Diagrams

Twenty-three Mermaid diagrams, because several things in this system are graphs that were being
described in prose or in ASCII art that had drifted from the code. Flow diagrams for the step
lifecycle, order routing, modify handling, action decoding, observation construction, reward
accumulation, champion promotion, config precedence, the logging channels, and the Docker and
Colab paths; a class diagram for the mixin chain; a state diagram for the position machine; a
sequence diagram for one `env.step`; and mind maps for the documentation set, the observation
defects, the findings register, the config tree and test coverage.

Two of them replaced ASCII art that had gone stale — [02](02_architecture.md) §2.9's data-flow
picture predated the Parquet record and the metrics path, and [09](09_distributed_training.md)
§2.2's topology box predated the per-runner `EpisodeRecorder`.

Every diagram is parsed by Mermaid 11 in CI-less form during authoring: the four that failed —
`Box(-inf, inf)` and `(1 xfail = S1-1)` inside mind-map nodes, where a parenthesis is shape
syntax, and a `-v "$PWD"` shell quote inside an edge label — were caught that way rather than by
rendering wrong on GitHub.

---

## 28. The observation encoder became selectable

The trainable modules' network was RLlib's stock MLP, and the only way to change it was to edit
`model_handler`. The `encoder` group in [`train_config.json`](../config/train_config.json) now
selects it, so an LSTM or a transformer becomes a config change and a new file rather than a
rewrite of the module wiring. See [18](18_configuration.md) §5.4.

### 28.1 The catalog was already the seam

`DefaultPPOTorchRLModule.setup` builds three things from its catalog — the actor/critic encoder,
the pi head, the vf head — and `Catalog._determine_components_hook` reads `latent_dims` off
whatever `_get_encoder_config` returns. Overriding that one classmethod therefore replaces the
network without touching PPO, the heads, or the league.

Two consequences that kept this small. `PPOCatalog.__init__` wraps the result in an
`ActorCriticEncoderConfig`, which is what supplies the `ENCODER_OUT/{ACTOR, CRITIC}` contract, the
`.critic_encoder` attribute `compute_values` reaches for, `inference_only` handling, and the
stateful wrapper a recurrent config gets — none of which has to be written per encoder. And
`Catalog.__init__` converts a dataclass `model_config` with `dataclasses.asdict`, so a
`DefaultModelConfig` subclass carrying two extra fields survives into `_model_config_dict` where
the catalog can dispatch on it. An encoder is consequently just a `ModelConfig` and an `Encoder`;
`DefaultPPOTorchRLModule` needs no subclass.

`RLModuleSpec.from_module` already clones the module class, catalog and model config, so champion
snapshots inherit the encoder with no change to `SelfPlayCallback`.

### 28.2 `mlp` is a pass-through, and is tested as one

The default resolves to the same stock `DefaultModelConfig` spec as before, with no
`catalog_class`, so a default run and every checkpoint written by one are unaffected. That is
pinned by a test comparing the spec against `default_model_config()`.

The cost of that guarantee is that `mlp` exercises none of the new code — it can pass while the
whole custom path is broken. `_passthrough`, a registered test fixture too simple to be the cause
of a failure, is what travels the full route instead. It is buildable but refused from a config
file, which is the distinction between `known_encoder_type` and `validate_encoder_type`:
config is validated once at the `TrainConfig` boundary, and everything downstream takes the
encoder as a parameter.

### 28.3 The restore guard had to learn a second shape

`encoder_type` and `encoder_spec` joined `STRUCTURAL_CONFIG_KEYS`, for the reason `n_hist` is
there: `Algorithm.from_checkpoint` discards the freshly built config, so changing the architecture
in the same pass as `is_restore` would otherwise be a silent no-op.

Writing that check surfaced a live bug in it. The encoder is not an `AlgorithmConfig` attribute —
it sits on each trainable module spec's `model_config` — and reading it with `getattr` worked only
until the first champion, because `add_module` normalises every spec's `model_config` to a plain
dict. From that point the fingerprint reported the `mlp` default whatever was actually running,
which disabled the structural check for the rest of the run. Every real run creates champions, so
this was the normal path, not an edge case. `_model_config_get` reads both shapes;
`test_the_fingerprint_survives_a_champion_snapshot` pins it.

### 28.4 `transformer`

Self-attention over the order-book grid, and the first encoder to use the seam.

The flat observation is a `(time, level, field)` grid that the MLP was
discarding. `ObsLayout` recovers it and `tokenize` slices it three ways — `time`
(one token per snapshot), `level` (one per book level), `both` (one per cell,
the default). Under `level` and `both` a token is one level's four fields, and
the two market-level scalars, which are per-snapshot rather than per-level, ride
on an extra global token per snapshot — so `both` is `n_hist * (k_rows + 1)`
tokens, 44 at the shipped settings.

Positions are two learned embeddings, time and level, summed. A single flat
embedding over 44 indices would have to learn the factorisation from scratch
before it could tell "level 3 at t=0" from "level 0 at t=3". Learned rather than
sinusoidal on both axes: the level axis is 11 long and ordered by book depth,
where the touch is qualitatively unlike level 9 rather than merely earlier, so
translation-invariance buys nothing.

Blocks are hand-written rather than `nn.TransformerEncoderLayer`, because the
MoE encoder is this stack with each block's feed-forward replaced and a factory
parameter makes that substitution one line. Pre-norm, since nothing in this
project's PPO config does learning-rate warmup and a post-norm stack without one
fails in a way that reads as "the architecture doesn't work".

**The input LayerNorm is not a knob.** Measured over 40 real steps, the four
channels of a token have standard deviations `[1.27, 8.17, 0.046, 9.52]` —
`sqrt(volume)` runs some 200× the ask-price channel, and all four sit inside the
same 4-wide token. Through an untrained projection that puts a mean 47% of the
attention mass on one token (entropy 1.62 of a possible 3.78); with the norm,
9.5% and 2.76. Removing it does not degrade the transformer, it stops it
attending.

`dropout` ships at 0 and should stay there. PPO's ratio compares a log-prob
recorded during rollout against one recomputed on the learner; dropout is live
for the second and not the first, so a non-zero value feeds mask noise straight
into the policy gradient. `test_eval_forward_is_deterministic` pins the
consequence for every encoder.

### 28.5 A parametrised architecture suite

`test_encoder_architectures.py` runs the shared contract over every registered
encoder automatically — usable pi/vf outputs, a state dict that round trips,
`vf_share_layers` honoured both ways, the `get_non_inference_attributes`
naming contract, a deterministic eval forward, and gradients actually reaching
the encoder. A new encoder is covered when it is registered, not when someone
remembers to write its tests. Two further checks close the loop between code and
config: every selectable encoder must have an `encoder_specs` block, and that
block's keys must be exactly what its builder accepts.

### 28.6 `lstm`, and the bug it found in the info dict

The structured recurrent encoder: a `TokenEmbedConfig` tokenizer embeds one
observation's book grid per step, and an LSTM recurs over the *rollout* axis on
top of that. The alternative — RLlib's `use_lstm=True` — feeds the raw 168-float
observation to a stock MLP tokenizer and discards the structure exactly as `mlp`
does, which would have made the recurrent run an ablation of the MLP rather than
of the transformer.

It needs no custom `Encoder` class. `RecurrentEncoderConfig` already takes a
`tokenizer_config`, and `TorchLSTMEncoder` already does the fold / tokenize /
unfold / recur sequence, `get_initial_state`, and the batch-first to
layers-first state transposition. So the encoder is a stock
`RecurrentEncoderConfig` holding our tokenizer — the same shape RLlib's own
`use_lstm` path builds. Being an instance of `RecurrentEncoderConfig` is also
load-bearing twice over, both by `isinstance`: `DefaultPPORLModule.setup` forces
`inference_only=False` so the critic's states are collected, and
`ActorCriticEncoderConfig.build` returns the stateful wrapper.

`max_seq_len` is the one knob that could not live on the encoder config, because
RLlib's connectors read it to cut batches into sequences before any encoder
exists. It is declared in the `lstm` spec block and lifted onto the top-level
model config, which is what `model_config_overrides` is for.

**The env broke before the model did.** Selecting `lstm` made every env step
fail with `'int' object is not iterable`, from `info_helper._plain` — which
assumed a numpy array is at least 1-D, when `tolist()` on a 0-d array returns a
bare scalar. No stateless module had ever produced a 0-d array; the
time-dimension connectors hand back the Discrete action components that way. The
bug was pre-existing and latent, reachable only by making a module stateful.

Registering an encoder now also declares its full spec schema, so
`encoder_settings` does the merge and the unknown-key check once instead of each
builder repeating it, and `model_config_overrides` sees a default the config
file omitted rather than silently inheriting an unrelated one from
`DefaultModelConfig`.

The parametrised suite learned about statefulness at the same time: it builds
`(B, T, obs)` batches with a `STATE_IN` tree for a recurrent module, and expects
one value per timestep rather than per row. Without that it could not have
covered a recurrent encoder at all — it would just have failed on shape.

### 28.7 `moe_transformer`

The transformer with each block's feed-forward replaced by a top-k gated
mixture of experts. Everything else — tokenisation, positional encoding,
pooling, the mandatory input LayerNorm — is inherited, which is what
`TransformerBlock`'s feed-forward factory was for.

The interesting part is not the mixture, it is getting its auxiliary loss to the
optimiser. `ActorCriticEncoder._forward` returns only `ENCODER_OUT` and discards
every other key its inner encoders produced, so an encoder cannot simply return
a second term. The chain is: `MoEFeedForward` returns `(output, stats)`, the
block passes the tuple through, the encoder stages it, `CDAPPOTorchRLModule`
moves it into `fwd_out` — the one channel from a forward pass to the loss — and
`CDAPPOTorchLearner` adds `aux_loss_coeff * aux` to PPO's total.

The staging is taken, not read: `take_moe_stats` clears as it returns. A stale
auxiliary loss silently added to a later batch's gradient would be invisible;
getting `None` because a link broke is not.

Both the module and the learner are wired unconditionally rather than only for
this encoder. They are exactly their base classes when no stats exist, which is
every other encoder, so this is one code path instead of a branch.

Per-expert routing fractions are logged as `moe_max_expert_share` and
`moe_min_expert_share`. This is not decoration: a collapsed mixture and a
healthy one produce identical losses and identical throughput, and differ only
in those numbers. Given a 168-float observation and a small league, the honest
prior is that the experts specialise weakly — the metric is what makes that
finding falsifiable rather than assumed either way.

One test-harness bug surfaced here and is worth recording, because it was the
kind that makes a test pass while testing nothing: both suites' `build_module`
helpers overwrote `module_class` with the stock `DefaultPPOTorchRLModule`, which
had been correct when every spec left it `None`. Once custom encoders set their
own it silently swapped `CDAPPOTorchRLModule` back out, taking the auxiliary
loss with it. They now only fill it in when the spec left it unset.

### 28.8 Making the comparison mean something

Three additions aimed at the failure where a run compares architectures and
actually measures something else.

**Per-encoder `lr` and `vf_share_layers`.** Both `ppo` defaults were chosen for
the MLP. `lr = 5e-05` was tuned for a 2x256 tanh net, and holding an attention
stack to it measures the learning rate; `vf_share_layers: false` costs an MLP
little and doubles a transformer. Either may now be set in any encoder's spec
block, overriding the group for that encoder only. They are accepted everywhere
and consumed centrally, so no encoder has to know about them, and absent means
inherit — a null would be indistinguishable from a value nobody chose.

**Parameter counts at startup.** Each trainable module logs its own. At the
shipped settings the alternatives run 3-6.5x the MLP (225k, 672k, 799k, 1.46M),
which is the difference between "this architecture is better" and "this
architecture had six times the parameters". RLlib already reports sampling
throughput per iteration, which is the other half.

**A comparison protocol**, written down in [18](18_configuration.md) §5.5: fix
the seed and use several, one run per architecture rather than a resume, re-tune
the learning rate or say you didn't, and read the parameter counts.

### 28.9 Checkpoint round-trip for a custom encoder

`Algorithm.from_checkpoint` rebuilds from the config stored in the checkpoint,
so a custom encoder's module class, catalog class and spec all have to survive
serialisation and re-import. The unit suite's `get_state` / `set_state` cannot
show that — it never leaves the process and both ends were built by the same
code path — so there is now an integration test that saves and restores for
real.

Writing it surfaced a wrong assumption worth recording. The first version
compared every parameter on the EnvRunner and failed on
`encoder.critic_encoder`. That is correct behaviour, not a bug:
`get_non_inference_attributes` marks `vf` and `encoder.critic_encoder` as
training-only, so they are never synced out and each runner's copy keeps its own
random initialisation. The authoritative weights are the Learner's, which is
what the checkpoint persists and what the test now compares; the EnvRunner is
checked for the actor-side tensors only, which is what actually acts in the
environment.

### 28.10 Review pass

Three findings from a review of the five commits above, all of the same shape:
something silently doing the wrong thing where this codebase's rule is that a
bad configuration raises.

**A token is now `max(book_rows, extra_dim)` channels wide**, not `book_rows`.
The global token carrying the market-level scalars was right-padded to
`book_rows` and truncated to fit, so a scalar past the fourth was dropped with
no error. Unreachable at the shipped layout — 4 book fields against 2 scalars —
but `extra_dim` is a `tunable_constants.json` knob whose own note anticipates
more market features being added. The failure it would have produced is the
nastiest kind for this particular change: the dropped feature would still reach
`mlp`, which does not tokenise, so the architectures would have been compared on
different observations with nothing anywhere to say so.

**An `mlp` block in `encoder_specs` is validated rather than ignored.** `mlp`
returned from `build_trainable_module_spec` before any spec validation, so a
block written for it was accepted and had no effect. Validation now happens
before the branch, which also means `mlp` honours the two common keys (`lr`,
`vf_share_layers`) like every other encoder instead of dropping them.

**`model_config_get` has one definition.** Reading a spec's `model_config` with
`getattr` is wrong once `add_module` has normalised it to a dict — that was the
bug in 28.3 — and `policy_handler`'s log line still had the same pattern. It was
not reachable there (the spec is a dataclass at that point, and it is only a log
line), but the helper now lives in the encoders package with both callers
sharing it, so the pattern cannot be reintroduced by copying a call site.

Also worth recording, since 28.2 claimed more than it should have: the `mlp`
*module* is byte-for-byte what it was, but 28.7 set `learner_class` for every
run, `mlp` included. `CDAPPOTorchLearner` is exactly `PPOTorchLearner` when no
auxiliary loss exists, so the loss is unchanged — but "bit-identical" was true
of the module spec, not of every field of the algorithm config.

### 28.11 The MoE auxiliary loss is averaged, not summed

`aux_loss_coeff` did not mean a fixed thing. The load-balancing term was summed
over every MoE block, and both the actor's and the critic's blocks route
independently, so at `num_layers: 2` with the shipped `vf_share_layers: false`
four feed-forwards contributed: the aux loss read ~8.6 where a single block's
floor is `top_k` = 2. Flipping `vf_share_layers` halved it to ~4.2; doubling
`num_layers` would have doubled it again.

Nothing about that is incorrect - summing per layer is what Switch Transformer
does - but it makes the coefficient depth-dependent. Two consequences, both
silent: a coefficient tuned at one depth applies different balancing pressure at
another, and comparing two MoE configs of different depths confounds depth with
how hard the gate is being pushed. That second one is the same confound the
per-encoder `lr` override was added to remove in 28.8, so it had no business
surviving in the encoder that override was written alongside.

`_collect` now averages. The floor is `top_k` in every configuration, and the
measured value sits at ~2.1 across `num_layers` 1, 2 and 4 with
`vf_share_layers` either way - pinned by
`test_aux_loss_does_not_scale_with_the_stack`, which is parametrised over all
six combinations.

This changes what a given `aux_loss_coeff` does. Nothing has been trained with
the old behaviour, so there is nothing to migrate; if there had been, the
equivalent old coefficient is this one divided by the block count.

### 28.12 The existing docs caught up

28.1-28.11 documented the *new* subsystem thoroughly and left the docs describing
the old world untouched. An audit found four places still describing a
single-architecture codebase.

**[10](10_testing.md) was wrong by 172 tests and three files.** It claimed "510
tests: 474 unit + 36 integration" in both the run command and its mind map, when
the suite is 682 (623 + 59). Worse, its stated purpose is "every test file, what
each case pins down", and the three encoder suites were absent entirely. They now
have a §6.4 in the same per-file, per-class style, and every count in the file
inventory was re-verified against `--collect-only` rather than trusted.

Two of those tests were worth describing rather than just counting, because they
exist for bugs a unit test could not have reached:
`test_the_fingerprint_survives_a_champion_snapshot` (the `add_module`
dict-normalisation that silently disabled the restore check from the first
champion onward) and the recurrent class (selecting `lstm` broke the *info dict*,
not the model).

**[02](02_architecture.md) still said the trainable modules use the default PPO
module "with `fcnet_hiddens=[256,256]`, `tanh`".** True only for `mlp` now. The
package tree had been updated in 28.1 and this sentence four hundred lines away
had not - the usual way a doc goes stale.

**[12](12_perspective_rl_researcher.md)'s "unnormalised observations into a `tanh`
MLP" finding is now partially mitigated**, and says so. It stands unchanged for
`mlp`, which is still the default and still has nothing in front of it; every
other encoder LayerNorms after its input projection. The finding's own table
(sqrt size to 47.01 against normalised price 0.40) and the measurement taken while
building the transformer (channel stds `[1.27, 8.17, 0.046, 9.52]`; 47% of
attention mass on one token) are two independent measurements of one problem, and
the note says the source fix that finding asks for would still be better than
every encoder compensating for it.

A new gap is recorded in [10](10_testing.md) §8: the suite proves every encoder
builds, trains for an iteration and checkpoints - mechanics, not merit. Nothing
runs long enough to say whether any of them beats the MLP, which is the question
the whole group exists to answer.

---

## 29. The reward stops fighting the learner

Three of the four blocking findings were one arithmetic problem wearing three hats: the reward was
denominated in dollars of NAV. See [07 §2.1 and §4](07_reward_function.md).

### 29.1 Rewards are a fraction of starting capital (S1-1)

`set_reward` divides every NAV-derived quantity by `trader.acc.init_nav`. Value targets are now
O(1), so PPO's `vf_clip_param` — RLlib's default 10.0, set nowhere in this repo — stops binding.
It had been clamping a value loss of ~1.3e7 to a flat constant, which has zero derivative: the
critic received **no gradient at all** and `vf_explained_var` sat at ~9e-05 while `total_loss`
looked small and stable because 10.0 of it never moved.

`acc.init_nav` rather than the configured `init_cash`: the account already records what the trader
actually started with, so the scale cannot drift from the ledger it normalises. A second copy of
that number is how S1-4 happened.

`integration/test_progress_and_vf.py` had pinned this as a **strict xfail**, with a note saying
that fixing S1-1 would make it XPASS and that the marker should then be deleted. That is exactly
what happened, on the first real run after the change. It is now a live regression guard.

### 29.2 Drawdown is charged on the signed change, not the level (S2-1)

`max_nav` never decreases within an episode, so charging the level billed one early loss on every
one of the remaining ~4,000 steps — even to an agent that never traded again — and the total scaled
with episode length, making `max_step` a hidden risk-aversion knob.

The fix is the *signed* change, and the sign is the interesting part. Charging only newly opened
drawdown — `max(0, Δ)`, which is what doc/15 and doc/12 had both recommended — bills `nav_term` a
second time on every losing step below the peak and refunds nothing on recovery, so a round trip
costs `drawdown_penalty × X`. That is an asymmetric loss multiplier by another name, and it would
have left S1-3 half-open while looking like a fix for S2-1. Signed, the charges telescope to
`-drawdown_penalty × final_drawdown` over an episode regardless of path.

`trader.acc.drawdown` is now load-bearing twice — the recorded diagnostic *and* the next step's
`previous_drawdown` — and carries a comment saying so, because dropping it would silently restore
the level penalty.

### 29.3 The market is zero-sum again (S1-3)

`loss_multiplier` 1.5 → **1.0**. Total NAV is conserved exactly, so any multiplier above 1 makes
the summed reward negative even though the summed NAV change is zero — which made passing dominant
for every agent and predicted empty-market collapse.

| 4 agents × 300 steps | before | after |
|---|---|---|
| all agents pass | `0.0` | `0.0` |
| random trading | **−591,027** | **−0.0104** |

Measured over 1,000 steps, `nav_term` now sums to **exactly 0.000000** across agents: the zero-sum
property is visible in the reward, not only in the ledger.

### 29.4 The micro-penalties mean something again (S2-3)

They were 0.1 and 0.05 against per-step NAV moves of ±10⁴ — five orders of magnitude too small to
express any of the three economic objectives they encoded. Now in the same units as everything
else, and calibrated against measurement rather than chosen: over 8,000 random-agent steps, 37% of
steps move NAV at all and one that does moves it by a median 1.9e-03 of starting capital, so the
penalties sit at 0.5–1% of that. `passive_bonus` equals `trade_penalty`, making a passive fill
net-free while an aggressive one costs 0.2 bps — "capture spread" expressed as a price.

Charging real maker/taker fees through NAV rather than through the reward remains open.

### 29.5 What this does not fix

Passing still scores exactly zero, and that is correct: in a zero-sum market no reward can make
trading positive-sum on average. What changed is that the residual friction is ~0.5% of a typical
NAV move rather than dominating it, so trading is no longer dominated for an agent with an edge.
S1-2 — no private state in the observation — is untouched and is the next blocker.

---

## 30. The observation stops hiding the agent from itself

S1-2: every agent received the byte-identical public book vector, while the reward is
`f(nav, prev_nav, max_nav, ...)`. An agent long 100 lots and one short 100 lots saw the same input
and needed opposite actions — which a policy, being a function of its observation, cannot do. See
[05 §1.0](05_observation_space.md).

### 30.1 A per-agent private block

The observation is now `[ n_hist x snapshot | private ]`, 4x42 + 9 = **177 floats**. The book
prefix is still shared and computed once per step; only the tail differs.
`State_Helper.PRIVATE_FIELDS` names its nine entries in order and is the single definition of the
layout — `__init__` checks its length against `private_dim` from `tunable_constants.json`, on the
same rule `book_rows` already followed.

Every field is normalised by the trader's own `init_nav` or is already a ratio. That is not
cosmetic: the block shares a vector, and a `tanh` MLP, with the normalised book, so an unbounded
private field would saturate it exactly as the raw sizes do (S2-2).

`drawdown` is the entry that could not have been supplied any other way. The reward's drawdown
term depends on `max_nav`, a path functional over the whole episode, so no amount of recurrence
could have recovered it from a stream that never showed it.

### 30.2 The private block is not tokenised with the book

`tokenize` builds tokens `max(book_rows, extra_dim)` channels wide. Folding `private_dim` into that
width would take every book token from 4 channels to 9 and right-pad each with five zeros —
attention over padding on every level of every snapshot, to carry nine numbers belonging to none of
them.

So `split_private` splits before tokenisation, `tokenize` never sees the tail, and
`blocks.PrivateToken` projects it into a single extra token. Every tokenising encoder uses that one
class rather than its own copy: two architectures reading private state through differently-shaped
heads would differ by the head as much as by the architecture. The token deliberately receives no
positional embedding — the two axes are time and book level, and the agent's own state belongs to
neither.

`mlp` needed no change at all; it sees a wider flat vector.

### 30.3 `obs[-SNAPSHOT_DIM:]` is now wrong everywhere

The newest book frame no longer ends where the vector does. Slicing off the end returns the private
block plus a truncated snapshot — an array of exactly the right *shape* with every field
misaligned, which is the same failure `[-40:]` produced before `EXTRA_DIM` existed.

`ObsLayout.book_flat_dim` and `split_private` exist so the correct slice has a name. Four test
files and the probe harness held the old assumption; `from_obs_space` refusing a width that is not
`private_dim` plus a whole number of snapshots is what surfaced all of them at once, rather than
letting them reshape into garbage.

### 30.4 What is still missing

Own resting orders and agent identity are not in the block. Resting orders are the larger gap:
`modify` and `cancel` remain partly blind, because an agent can see its escrowed cash but not which
orders that cash is committed to.

---

## 31. A JEPA encoder, added without touching any of the others

`encoder_type: "jepa"` is a transformer that also trains a self-supervised objective: mask part of
the book, predict the masked part's *representation* from the rest, and score that against a
slowly-updated copy of the encoder itself. Nothing reconstructs the input. See
[22 4.2](22_jepa_integration.md) and [18 5.4](18_configuration.md).

### 31.1 Why latent prediction rather than reconstruction

The measured per-channel standard deviations of a `both` token
`[bid_price, bid_size, ask_price, ask_size]` are `[1.27, 8.17, 0.046, 9.52]`. The size channels are
`sqrt(volume)` and run some 200x the ask-price channel, so a squared-error loss in *input* space is
dominated by queue-size jitter - the least predictable and least economically meaningful quantity
in the observation. Predicting in representation space removes that structurally: the target comes
from an encoder that is itself being trained, so anything genuinely unpredictable is free to drop
out of the representation and the loss stops paying attention to it.

### 31.2 Added without editing a single existing encoder

The requirement was that `mlp`, `transformer`, `lstm` and `moe_transformer` keep behaving exactly
as they did. Two design choices follow from it, and both differ from what doc/22 4.2 originally
proposed:

- **The aux-loss seam was not generalised.** Renaming `moe_learner` into a shared seam is the
  better design in the abstract - two consumers is usually when that pays - but it edits code on
  every custom encoder's path. `JEPARLModule` and `CDAJEPALearner` *subclass* the MoE ones instead,
  so `CDAJEPALearner` still adds the MoE term and a league mixing the two works.
- **The encoder composes rather than subclasses.** Subclassing `TorchTransformerEncoder` would have
  needed an `_encode_tokens()` hook extracted from the class `moe_transformer` inherits. Instead
  `jepa.py` imports `tokenize`, `positional_index`, `TransformerBlock`, `AttentionPool` and
  `PrivateToken` as they stand and duplicates ~15 lines of the forward sequence. That duplication
  is the price of the isolation, paid deliberately.

`@register` gained optional `module_class_path` and `learner_class_path`, resolved lazily because
those classes live in `train/model/`, which imports the encoder package. Nothing else declares
either, so every previously registered encoder resolves to exactly the classes it did before.

Eight files were required to stay untouched and did:
`transformer.py`, `moe_transformer.py`, `lstm.py`, `token_embed.py`, `moe.py`, `blocks.py`,
`tokenize.py`, `moe_learner.py`. `TestOtherEncodersAreUnaffectedByJEPA` asserts the same claim from
the registry side.

Exactly one existing test changed. `test_non_inference_attributes_contract` asserted the literal
list `["vf", "encoder.critic_encoder"]` for every encoder; it now asserts that list as a *prefix*
and requires every encoder except `jepa` to add nothing to it. A fixed list would make adding any
encoder with training-only submodules look like a regression in all the others.

### 31.3 The policy never sees a mask

The policy latent is computed from the **unmasked** observation - the agent acts on everything it
was given - and the objective runs in train mode only. Inference therefore costs one trunk pass,
the same as `transformer`; a training step costs two plus the target's. That matters beyond
throughput: mask sampling is stochastic, and PPO's ratio compares a log-prob recorded during
rollout against one recomputed on the learner, so anything stochastic on the inference path becomes
noise in the ratio rather than an error.

### 31.4 Watch `jepa_latent_std`

This is the `moe_max_expert_share` trap, and worse. A collapsed JEPA maps every observation to the
same latent, which makes the prediction *perfect*: its loss goes to **zero**, which reads as
success, and throughput is unchanged. `jepa_latent_std` goes to zero at the same moment and is the
only thing separating the two; it should sit near 1.0, the scale LayerNormed targets already have.
`jepa_offdiag_cov` catches the slower variant where variance holds up but the dimensions become
redundant, and `variance_coeff` weights a VICReg-style hinge that pushes back once either starts.

Anti-collapse rests on the asymmetry: the target trunk moves only by EMA, never by gradient, so the
predictor is chasing a target that keeps moving - which a constant encoder cannot satisfy.

### 31.5 What the probe says, and what it does not

Scored against `mlp` and `transformer` on the reward-free targets, `jepa` is competitive and wins
nothing decisively. That is the expected reading rather than a disappointment: the probe scores
encoders **untrained**, so it measures JEPA's *architecture* - essentially the transformer's - and
not its *objective*, which has had no chance to train. Scoring the objective needs `--checkpoint`
after a real run, or the offline pretraining of doc/22 4.4.

---

## 32. An encoder can be taught before a policy exists

`train/pretrain/` trains a JEPA encoder's self-supervised objective on observations alone - no
reward, no policy, no opponents - and writes weights a training run starts from. See
[24_pretraining.md](24_pretraining.md).

### 32.1 Almost entirely reuse

Nothing in it reads a Parquet file or steps an env. `train/probe/corpus.py` already reads both
sources, deduplicates the per-agent copies, marks episode boundaries and validates widths;
`probe.probe.split_masks` already splits by episode; `probe.features.build_module` already builds
the module *training* would build. What was added is the optimiser, the checkpoint format and the
guard on it.

Building the whole `RLModuleSpec` and training the encoder inside it - rather than instantiating a
`TorchJEPAEncoder` directly - is what makes the pretrained architecture provably the one training
will use. The pi and vf heads are built and never touched.

### 32.2 The fingerprint, and one definition of it

A checkpoint holds `encoder.pt`, `encoder_fingerprint.json` and `rl_module/`. The fingerprint is
the point of the format: `train.py` already refuses a restore whose `encoder_type` or
`encoder_spec` differs from the checkpoint's, because the weights are that architecture's weights,
and pretrained weights need the same guard.

`encoders.encoder_fingerprint` is now the single definition, called by both
`train._encoder_fingerprint` and the pretrainer, so the two cannot drift. That function exists at
all because a `getattr`-only read once reported the `mlp` default from the first champion onward,
silently disabling the structural check for a whole run.

The check runs at *spec-build* time, before the path reaches any encoder, so a mismatch names the
architectures rather than surfacing as a shape error on some env runner.

### 32.3 Not `RLModuleSpec.load_state_path`

There is a field that looks made for carrying a pretrained path. In RLlib 2.56 it is stored, merged
and copied, and never read back - setting it would have silently done nothing, which is the same
dead-config-key shape as `OrderBook`'s `tick_size`.

The path rides on the model config instead, and `TorchJEPAEncoder.__init__` loads its own weights,
so every process that builds an encoder loads them itself with no state to synchronise. The load is
last in `__init__`, so anything explicit afterwards wins - which is what makes it safe on the two
paths that would otherwise surprise: a champion snapshot constructs the encoder and then
`set_state`s trained weights over it, and a restored run does the same with its checkpoint.

`mlp` refuses a pretrained encoder outright, having no objective that could have produced one.

### 32.4 Watch latent_std, not the loss

The report carries the training loss, a validation loss split by episode, and `latent_std`. Only the
last is load-bearing: a collapsed JEPA maps every observation to one vector, which makes its
prediction *perfect* - the loss goes to zero and reads as success. `PretrainReport.collapsed`
detects it and the CLI exits non-zero rather than leaving a flattering number beside unusable
weights.

### 32.5 The first measurement

`--pretrained` was added to the probe so the same architecture appears twice in one report, on
identical rows with an identical split. On a 150-step run over 4 random-agent episodes the result is
directional rather than uniform:

| target | untrained | pretrained |
|---|---|---|
| `spread_change` h=1 | -0.0094 | **+0.0165** |
| `imbalance_change` h=20 | -0.3529 | **+0.1090** |
| `realized_vol` h=5 | +0.1292 | **-0.4961** |

It won on the structural targets and lost on the temporal one, which is what `mask_axis: level`
should do - level masking only ever asks what depth is consistent with the rest of the book, so
nothing in the objective preserves temporal structure in the latent. The obvious next experiment is
`mask_axis: time`. This is a smoke-sized budget and establishes that the mechanism works and its
effect is legible, not that pretraining pays at scale.

---

## 33. An action-conditioned world model

`world_model: true` in the `jepa` spec block adds a second self-supervised term:
`z_hat_t+1 = P(z_t, a_t)`, the next observation's latent predicted from this one's plus the action
taken, scored against the EMA target encoder's view of `o_t+1`. See
[22 4.3](22_jepa_integration.md) and [18 5.4](18_configuration.md).

What it learns is the **latent market impact of an order** - how the book responds to a market
order versus a passive quote versus a cancel. That is a first-class microstructure quantity, and
this environment generates it endogenously, which is exactly the setting [01](01_overview.md) 1.3
describes.

### 33.1 The connector is attached only for it

PPO's train batch carries no `Columns.NEXT_OBS`. RLlib ships
`AddNextObservationsFromEpisodesToTrainBatch`, and `train.py` attaches it through
`encoders.needs_next_obs` - true only for a `jepa` encoder with `world_model` on. Attaching it
unconditionally would put an observation-sized tensor per row into every other architecture's train
batch, for a column none of them reads.

The connector fills each episode's next observations from that episode, so the boundary needs no
masking: the last step of an episode takes that episode's final observation, never the next
episode's reset.

### 33.2 Absent is not an error

The encoder reads `NEXT_OBS` and `ACTIONS` off the batch it is already handed, and returns no
world-model term when either is missing. That is every path except the connector-fed training one -
`compute_values`, a manual forward, a test that built a batch by hand - and raising on a key PPO
never promised would have broken all of them.

### 33.3 Two economies in the implementation

The prediction reuses the trunk output already computed for the policy latent, so the term costs
one extra *target* pass rather than two more.

Its target is mean-pooled rather than run through `self.pool`. The pool is trained by the policy
gradient, so putting it inside the target path would make the world model's target move for reasons
that have nothing to do with the market.

### 33.4 The floor is not underfitting

`z_t+1` depends on every agent's action and the predictor conditions on one of them, so it is
fitting a conditional expectation over the opponents. Its loss has a non-zero floor. That is
interesting rather than wrong - it is an opponent model - and tuning the floor away would mean
overfitting to noise. Both the config note and the code say so, because a loss that will not reach
zero invites exactly that.

### 33.5 Still not included: the intrinsic reward

The predictor's error would make a curiosity signal, and RLlib ships the connector pattern for it.
It stays out, for the reasons doc/22 4.3 records - chiefly that it would destroy Phase 1's control
(you could no longer tell whether the reward fix worked or curiosity was papering over it) and that
it would invert champion selection, since an agent with a *better* world model earns *less*
intrinsic reward.

---

## 34. Review of sections 29-33, and what it found

Seven defects, all of which built, trained and reported plausible numbers.

### 34.1 An inference-only `jepa` module could not be built

Champions are inference-only copies, so a `jepa` league failed at its first
snapshot. Two causes stacked:

`JEPARLModule.get_non_inference_attributes` read `self.encoder` unguarded, and
RLlib calls that method from `TorchRLModule.__init__` - *before* `setup()` has
created the encoder. `RLModuleSpec.build` catches `AttributeError` in order to
fall back to a deprecated constructor, so the real error was swallowed and
resurfaced as a confusing complaint about `RLModuleConfig`.

Underneath it, RLlib's own stripping loop mishandles a dotted path whose target
actually exists: it traverses to the leaf and then calls `delattr` on the
**module** rather than on the leaf's parent. PPO's own `encoder.critic_encoder`
escapes only because inference-only setup never creates it, so the loop's
"absent, skip" branch runs first. `JEPARLModule.setup` now deletes the
training-only submodules itself, which makes them absent by that same route; the
dotted paths stay in `get_non_inference_attributes`, where `get_state` still
needs them to filter the state dict and handles dots correctly.

An inference-only `jepa` module is now 339K parameters against 1.42M.

### 34.2 A `time` mask could hide the whole sequence

The clamp was against `n_hist - 1`, which bounds *snapshots* rather than tokens.
At `n_hist: 1` - a value the `lstm` block explicitly recommends - it masked
every token, leaving the context encoder no input while the objective went on
reporting a loss. Both structural branches now check the token count, and a
tokenisation that yields a single token is refused at construction, since one
token cannot be both hidden and visible.

### 34.3 `time_left` was off by one step

`step()` increments `t_step` *after* `set_step_outputs` builds the observations,
so reading it raw made the reset observation and the one after the first step
both report 1.0, and the terminal observation report `1/max_step` remaining
rather than 0. `set_private_state` now takes the completed-step count, and
`reset` passes 0.

### 34.4 The critic ran the objective and it was thrown away

`vf_share_layers` is false by default, so the critic gets its own encoder - and
`_jepa_sub_encoder` only ever collects the actor's stats, to avoid
double-counting the term. The critic's copy therefore ran a mask pass, a target
pass, the predictor and the world model on every training forward, had all of it
discarded, and retained the autograd graph in `_jepa_stats` until the next
forward overwrote it. `JEPARLModule.setup` now switches `objective_enabled` off
on the branch whose stats are not collected.

### 34.5 The Parquet reader's premise had been invalidated by section 30

`from_parquet` deduplicated on `(episode_id, step)` because every agent received
the byte-identical observation - which is precisely what the private block
removed. The deduplication kept working and silently discarded N-1 agents'
private state.

One row per step is still the right default, for a reason that outlived the
original: every target is a public book quantity, so N agents at one step carry
N identical targets over a shared book prefix, and keeping them all would put
near-identical rows across the held-out split. But that is now a *choice* rather
than a lossless collapse, the docstring says so, and `per_agent=True` keeps
every row for pretraining, where the private block is part of what the objective
encodes.

### 34.6 Validation EMA-stepped the target encoder

The objective only exists in train mode, so the pretrainer evaluates it in train
mode under `no_grad`. The EMA update fired there too, moving the target with no
corresponding update to the online trunk - making the saved weights a function
of `log_every` and the validation split size. The update is now gated on
`torch.is_grad_enabled()`.

### 34.7 `world_model` was not declared training-only

It computes an auxiliary loss and is never read on the inference path, so an
inference-only copy carried it. Added to `_TRAINING_ONLY` - and declared only
when it exists, since it is an attribute set to None when off and `hasattr`
alone would have declared a submodule that `setup` would then try to delete.

### 34.8 One thing the review got wrong

It attributed 34.1 solely to the nested-`delattr` mechanism. That is real and is
the *second* failure, but the first is the unguarded `self.encoder` read, and
fixing only the mechanism the review named would have left the module still
unbuildable. Worth recording because the finding was correct while its stated
cause was not - the reproduction is what separated them.


---

## 35. An audit of the plan's own checklist

The review in §34 read the code. This one read the *plan* against the repository
and asked which of its stated gates were actually discharged. Every finding is a
documentation defect rather than a code defect, which is exactly the category a
code review does not catch.

### 35.1 Four test counts in `10` were wrong

`test_encoder_registry.py` (38, now 45), `test_probe.py` (43, actually 45),
`integration/test_probe_harness.py` (25, actually 28), and the JEPA section (30,
actually 42 across three classes). The per-file table's rows summed to 751 and
109 against stated totals of 752 and 112, which is what made them findable: the
totals had been updated and the rows they are a sum of had not.

`TestJEPAReviewRegressions` - the 18 tests §34 added - was not documented at all.
It is now `10` §6.4.4.

### 35.2 `10` still described the critic guard as an xfail

Three places: the §6.2.2 heading, its table row, and the §8 gaps table. §29.1
records that the marker was deleted when S1-1 was fixed and the assertion went
live; the testing document was never brought along, so it described a suite that
records a frozen critic rather than one that catches it.

The §8 row on encoder learning was stale in a subtler way. It said the strong
question "still needs S1-1 and S1-3 fixed". Both are fixed. What actually
remains is that **no multi-seed training comparison has been run** - the protocol
in `18` §5.5 is unexecuted for every architecture, `jepa` included. The gap did
not close; its reason changed, and the row now says which.

### 35.3 `23` still called the deduplication load-bearing

The same defect §34.5 found in the code, left behind in the document. Its section
argued from "every agent receives the byte-identical public book vector", which
§30 made false. Rewritten to say what the row selection now does, why the default
is still right for public-book targets, and what `per_agent=True` buys and does
not buy.

### 35.4 The `private_dim` guard was relied on and never confirmed

The plan flagged it as a risk: `n_hist` is in `STRUCTURAL_CONFIG_KEYS` and
`private_dim` is not, so the only thing between a changed value and a silently
misread checkpoint is `ObsLayout.from_obs_space` failing to divide. Confirmed by
measurement, and now pinned by `TestPrivateDimIsGuardedByArithmeticAlone`:

| `private_dim` against a saved 177-float space | Result |
|---|---|
| 9 (unchanged) | builds, `n_hist=4` |
| 6, 8, 10, 12 | **raises** - remainder against a 42-float snapshot |
| 51 | **builds silently as `n_hist=3`** |

The guard holds for every change anyone would make by hand. Its blind spot is a
change of exactly `snapshot_dim`, which leaves no remainder and is read as one
fewer snapshot plus a larger tail. Pinned as a known property rather than fixed:
closing it means adding `private_dim` to `STRUCTURAL_CONFIG_KEYS`, and the case
is off by 42.

### 35.5 What is genuinely still open

Not defects - work the plan scoped and this branch did not do:

| Item | State |
|---|---|
| Multi-seed encoder comparison (`18` §5.5) | **Unexecuted.** The largest gap. No claim that any encoder trades better than another is supported by anything here |
| World-model loss curve | Mechanics are tested; §33.4 argues the floor from first principles. No measured curve is recorded |
| JEPA pretraining at scale | §32.5 is a 150-step smoke measurement, explicitly not evidence that pretraining pays |
| Own resting orders in the private block | §30.4. The larger half of what S1-2 left |
| Maker/taker fees through NAV | §29.4 |
| `12` §9 items 5-10, 12-14 | Untouched by this branch |

---

## 36. Documents that had started arguing with themselves

§35 audited the plan against the repository. This pass audited the *documents*
against the code, and found one real bug and a set of claims that had gone
false when the code beneath them changed. The pattern worth naming: none of
these were in the sections describing the new work, which were written last and
are correct. They were in the older sections that the new work invalidated
without touching.

### 36.1 `visualize_orderbook` plotted private state as ask sizes

The one code defect. It read the newest book snapshot as
`np.asarray(obs)[-SNAPSHOT_DIM:]`, which was right until §30 appended a 9-float
private block and moved the end of the vector:

```
obs width: 177   SNAPSHOT_DIM: 42   n_hist: 4
correct newest snapshot at [126:168]
buggy slice at            [135:177]        offset: 9 floats

plotted as "ask sizes":
   correct : [-0. -0. -0. -0. -0. -0. -0. -0. -0. -0.]
   buggy   : [-0. -4.554 -0. -0. -0. -1. -0. -1. -0. -0.]
```

That `-4.554` is a private float - a position or a cash balance - charted as
depth. Nothing raises: every index resolves, every sum is a float, the plot
renders. `05` §1 warns about this exact slice in prose and §9 even lists this
file as a consumer that reads from the end; the env, the tests and the probe
were all updated for the new layout and this file was missed.

It survived because **nothing in `visualize/` had a single test**. The fix is a
`_newest_snapshot` helper that slices against `n_hist * SNAPSHOT_DIM`, derives
`n_hist` from the vector rather than assuming it, and raises on a width it
cannot decompose - the same contract `ObsLayout.from_obs_space` holds on the
model side. `test_visualize_orderbook.py` (12 tests) pins it, including a
sentinel test that fails if the old slice is restored.

### 36.2 `--per-agent` was documented and unreachable

§34.5 added `per_agent` to `from_parquet` and both `10` and `23` presented it as
the remedy for the dropped private state. It was on no command line, so the
remedy could not be taken. Now a probe flag.

### 36.3 Two documents contradicted themselves

`07` §2.1 said "**The reward is zero-sum when NAV is**". Twenty lines later a
blockquote said "**The reward is not zero-sum.**" Both were written honestly -
the second predates §29 - and together they say nothing. Rewritten to the
distinction that actually holds: `nav_term` sums to exactly zero, the four
shaping terms do not, and the comparability caveat survives at ~0.5-1% of a NAV
move rather than 2.4x it. The flowchart below it was pre-§29 in three separate
ways: `x loss_multiplier (1.5)`, a drawdown term fed the *level*, and no
`init_nav` division anywhere - which is to say it drew the formula §29 replaced.

`05` §1 documented the private block as shipped while §7's mindmap and §7.7
still called "no private state" the single biggest flaw, and §8 said time
remaining "is missing and cheap... the agent cannot currently condition on it" -
`time_left` is `PRIVATE_FIELDS[8]`.

### 36.4 `12` was six sections of present-tense description of fixed defects

§2, §3.1, §3.3, §3.4, §3.5 and §4 all described live blockers, while §9's agenda
table in the same document marked those same items **done**. The analysis is
kept - it is the record of *why* each mattered, and it is correct as history -
under a status banner in the convention §3.6 and §5.6 already used.

§3.4 needed more than a banner. Its recommended patch is
`max(0.0, new_dd - prev_dd)`, the clipped form §29.2 rejected on the evidence
that it is an asymmetric loss multiplier in disguise. A reader following that
advice would reintroduce the bias §3.1 is about, so the correction sits with the
code block rather than only in the banner.

### 36.5 The rest

`02` §2.6 listed the reward coefficients as `0.1 / 0.05 / 0.2 / 0.1 / 1.5` -
the pre-§29 values, including the `1.5` that made passivity dominant, in the
table a reader tunes from. `15`'s mindmap and sequencing list still showed
S1-1/S1-2/S1-3/S2-1/S2-3 and items 1/3/5 as open though its own body marked each
fixed; item 2 was split, because the `vf_explained_var` half is done and
`grad_clip` is genuinely still unset. S4-16 described a test that no longer
exists. `01` cited `02` §6 where every other reference uses §2.x. Four documents
still gave the observation as 168 floats.

`22` §3 - the "read this before §4" gate - still named S1-1, S1-2 and S1-3 as
prerequisites for the JEPA proposals, all three of which are fixed. Its two
blocking caveats now carry status banners: §3.1's gate is open and unwalked (the
multi-seed comparison is what would walk it), and §3.2 is collected except for
resting orders. `15`'s S1-1/S1-2/S1-3/S2-1/S2-3 headings said `[verified]` while
their bodies said Fixed; they now say `[verified, fixed]` in the convention S1-4
already used.

`16` was deliberately left alone. It carries a banner saying it is a log and not
a status page, and its `(168,)` readings are correct as dated measurements. The
one transcript in `05` §6 is labelled rather than rewritten, for the same
reason.

---

## 37. The 2026-08-30 review pass

A review that re-audited every open item in [15](15_findings_and_recommendations.md) against the
code as it stood, and searched the two areas the register did not cover: the risk layer of the
accounting, and everything added since it was written. It found one blocking defect and four major
ones the register did not contain, each confirmed by running the code. Every S2 in the register is
now closed.

### 37.1 An agent's position was not bounded by its capital (S1-5)

`Trader._order_approved` waived the cash check for the portion of an order reducing the *current*
net position, and nothing netted an order against the trader's **other resting orders** — so N
individually-"closing" orders were each approved against the same lots. Executed: a trader long 10
with `cash = 0` rested ten 10-lot asks across ten price levels, every one approved, and filled into
a **90-lot short with no refusal**. The approval is what bounds risk, so this was the absence of a
position limit rather than a rounding error.

It now nets against the position not already claimed by this trader's own resting orders, excluding
the order an upsert or a modify is about to replace. Nine of the ten are refused and the position
goes flat.

This contradicted the register's own summary, which called the buying-power logic "subtle and
right". That line is amended rather than deleted: the design is sound and the defect was one missing
term in it.

### 37.2 Bankrupt agents kept trading (S2-4)

`set_done` recorded bankruptcy and `set_all_done` then rebuilt the dictionary as all-`False`, so
`terminateds[agent]` was `False` for every agent on every step: the agent kept emitting transitions,
kept accruing reward, and kept resting executable orders in a book it had no capital behind. Its
module return — what champion promotion reads — was then dominated by a constant unrelated to its
policy.

Termination is decided and applied in the same call, which also settles the monotone-`done_set`
worry: an agent goes at the moment its NAV is non-positive, so no later step can terminate a
recovered one.

**The consequence worth recording**, because it was one edit away from being a silent regression:
the NAV conservation check read only the *final* step's `info`, so a terminated agent's NAV vanished
from the total and any episode containing a bankruptcy would have read as a violation — halting a
strict run over an intact ledger. `on_episode_step` carries each agent's last reported NAV forward,
and a test pins that a genuine breach is still caught when an agent terminated.

### 37.3 One participant could set the price everyone was marked at (S2-5)

Self-matching printed to the tape and `mark_to_mkt` marked every account off the last print, so one
self-traded contract re-priced the whole market: a 1-lot self-print moved **1,000 NAV**. It was also
free — `_process_trades` sends a self-trade down a branch that never calls `process_acc`, so neither
trade counter incremented and `trade_penalty` never charged for it.

Both halves were needed. `Trader._prevent_self_match` withdraws the trader's own crossing orders
before they reach the matcher (in `Trader`, not `process_order_list`, because `envs/orderbook/` is
off-limits). But the *resting leg* of a prevented self-cross survives, and with the mark falling
back to a one-sided quote that lone order simply became the mark — the same 1,000 NAV, with no trade
at all. So `mark_price` uses the midpoint only when the book is genuinely two-sided and falls back
to the last trade otherwise. Moving the mark now means posting a better quote somebody else can
lift.

### 37.4 The observation (S2-2, S2-6, S2-7, S2-11)

Four changes, and the vector grows from 177 floats to **193**, so no earlier checkpoint loads.

- **Scales.** Level volumes are `sqrt(V / limit_max_size)`; `log_mid` is centred on the log of the
  geometric mean of the anchor range; `position` divides by a new `position_scale` key rather than
  by `limit_max_size`, which is not a maximum of anything. The size/price standard-deviation ratio
  falls from **220× to 3.7×** and inventory saturates its scale on **0.0%** of agent-steps
  against 13.2%.
- **One normaliser per stack.** The deque holds raw frames and the whole stack is normalised once,
  at emission, by `M_t`. A bid resting at 90 while the midpoint moved 100 → 96 read 0.100 then
  0.063; it now reads 0.0625 in both, with `mid_return` recording the move as −0.04.
- **Trade flow.** The tape loop that iterated, counted and discarded is now `_trade_flow`, and
  `signed_volume` / `log1p_trade_count` / `trade_direction` join the snapshot. `extra_dim` is
  checked against a new `EXTRA_FIELDS` tuple; it was documentation before, so setting it was a
  silent no-op.
- **A cost basis that is still a price.** `_size_decrease` rolls realised P&L into the remaining
  lot's basis — load-bearing on the short side, so it stays — which let `VWAP` go negative and made
  `vwap_vs_mid` report `0.0`, the encoding for *flat*, on **5.0%** of open-position steps.
  `entry_vwap` is the price actually paid; the rolled basis stays as `carrying_vwap`.

### 37.5 The learning stack (S2-9, S2-10, S3-22)

- **The JEPA anti-collapse hinge carried no gradient.** It was computed from `target`, built under
  `torch.no_grad()` by a trunk with `requires_grad_(False)`, so `loss + coeff * penalty` was the
  prediction loss plus a *constant*. Nothing raised, because adding a constant to a tensor that does
  carry a `grad_fn` is legal. The encoder had collapse detection and no collapse prevention, and
  `variance_coeff` was a dead knob that still invalidated checkpoints. The statistics now come from
  the online side.
- **The `lstm` encoder ignored the grid.** Its tokenizer was `tokenize → Linear → LayerNorm → mean`,
  a linear function of the token sum: permuting book levels moved the latent by 1.8e-07. Positional
  embeddings alone do not fix that — under a linear projection and a mean they are an
  input-independent constant, verified at 0.000000 — so a token-wise nonlinearity goes with them.
  The guard is in the every-encoder contract.
- **The encoder fingerprint did not identify the encoder.** It hashed the raw spec, giving both
  false mismatches (a stated default vs an omitted one) and false matches (an omitted key surviving
  an edit to `*_DEFAULTS`). It hashes the merged settings now, and `pretrain`, `save` and
  `verify_fingerprint` share one definition of what `encoder_spec=None` means.

### 37.6 Two documented entry points that did not work (S2-12, S3-21)

`gymnasium.make("continuousDoubleAuction-v0")` — documented in `setup.py`'s own docstring — raised
`TypeError` because only the plural spaces were set. `visualize/` had no `__init__.py`, so no wheel
carried it, while [01](01_overview.md) documents it as an entry point. Both were invisible to every
CI job, because each job constructs what it needs directly.

Both are covered by `test/test_entry_points.py`, and both were additionally verified against a real
wheel installed into a clean venv outside the checkout. **The matching change to the CI packaging
job is not in this branch**: the credential this work was pushed with has no `workflow` scope, so
GitHub refused the update to `.github/workflows/tests.yml`. The job should build the wheel, call
`gymnasium.make`, import `gym_continuousDoubleAuction.visualize`, and fail if
`visualize/run_all.py` is absent from the archive — importing the *package* rather than `run_all`,
which needs matplotlib and, through `visualize_modules → policy_handler`, torch. Until that lands,
these two entry points are guarded by the unit test and by nothing in CI, which is the same blind
spot that let them break.

### 37.7 Documents that had gone stale again

Test counts (`681 passed, 1 xfailed`, `36`, `59`) against the real 863 + 112; the S1-1 xfail still
described as live in two documents, contradicting a third that correctly records its deletion;
[14](14_perspective_ai_engineer.md) §5.1 and §5.3 measuring a tree a quarter the current size, now
carrying the same "original audit" banner §5.4 already had; `168 floats` in five places; "episode
pickles ~10 MB" for what is 34 MB of Parquet; and a `1/num_experts` target for a metric that sums
to `top_k`, stated identically in two notes that would have read a healthy mixture as collapsed.

Dependencies: `pyarrow` is imported directly and was declared nowhere — the exact reasoning that
produced S3-6 — while `scipy` and `tensorboardX` were declared as direct dependencies and are
imported nowhere. `six` was in `install_requires` but missing from `requirements.txt`. The lock file
still carried the removed scikit-learn stack and lacked `GPUtil`; the Docker image still installed
scikit-learn and pinned a numpy floor `requirements.txt` does not use. `setup.py` said `0.1.0` while
`CITATION.cff` and the README said `2.0.0`. The duplicate `CODEOWNER` file, which GitHub never read,
is deleted.

### 37.8 What this pass did not close

`S1-5`'s escrow half: a resting order is escrowed at full notional whether it opens or closes, so a
cash-poor trader closing a position drives `cash` negative while `cash_on_hold` rises by the same
amount. NAV is untouched — it is a reclassification, not a loss — and it is asserted rather than
fixed, because changing it means tracking escrow per order and every partial-fill path in
`Cash_Processor` assumes escrow equals full notional.

Everything in S3 and S4 that was open remains open, including `sys.exit()` in the matching engine
(S3-7), the two degenerate size dimensions (S3-1, S3-2), the level index as a non-stationary
coordinate (S3-15), the league ranking a signal not comparable across roles (S3-12), and the absence
of `entropy_coeff`, `grad_clip`, `gamma` and `lambda_` from the PPO configuration (S3-11, S3-13).
`envs/orderbook/` remains off-limits, which is why S2-5's fix lives in `Trader`.

---

## 38. A pre-existing flake that the merge surfaced

CI on `master` failed immediately after §37 landed:

```
TestMoETransformer::test_aux_loss_does_not_scale_with_the_stack[False-1]
assert 2.5662789344787598 == 2.0 ± 0.5
```

### 38.1 It was not a regression

The obvious reading — the observation layout grew from 177 floats to 193, token
width from 4 to 6, so the input distribution to an untrained MoE gate changed — is
wrong, and it is worth recording *why*, because the measurement points the other
way.

The MoE auxiliary term is a load-balancing loss whose floor is `top_k` at perfectly
uniform routing. Its value on an untrained gate depends on the gate's **random
initialisation**, which nothing in the test seeds. Sampled 1,500 times with the RNG
walking forward exactly as it does inside a pytest process:

| | `1a6996a` (PR #81's base, 177 floats) | after §37 (193 floats) |
|---|---|---|
| pooled mean | 2.149 | 2.142 |
| max observed | **2.694** | 2.541 |
| draws past the 2.5 bound | 4 of 600 | 1 of 1,500 |

So the flake existed at the base, with a maximum *higher* than the value CI actually
failed on. §37 did not introduce it and did not measurably worsen it; CI happened to
draw a tail on the first run after the merge. The rate is worst at `num_layers=1`,
where there are fewest blocks to average over.

### 38.2 The band was the wrong instrument

The test asserted `approx(2.0, abs=0.5)` independently in each of six
(depth, sharing) parametrisations. But its own docstring states the claim as
*invariance*: the term is averaged over MoE blocks rather than summed, so
`aux_loss_coeff` means the same thing at every depth. An absolute band around the
floor is a proxy for that, and a leaky one — under a summed implementation the
`(1, True)` configuration comes out at 2.26, comfortably **inside** the band it was
supposed to police.

It now builds all six configurations from one seed and compares them with each
other: the floor (`>= top_k`), proximity to it (`< 1.5 x top_k`), and the ratio
across the stack (`< 1.25`, against a measured spread of 1.03–1.06). Summing gives a
ratio near 8 and a deepest-configuration value of 17.6, so the replacement is a much
sharper test than the band — and being seeded, it is deterministic. Verified by
swapping `torch.stack(aux_terms).mean()` for `.sum()` in `moe_learner.py`: it fails
and names every configuration's value.

The seeding is done under `torch.random.fork_rng`, so the suite's global stream is
left where it was found — other tests rely on it varying, and silently pinning it
would mask their own nondeterminism rather than fix it.

### 38.3 Scope

Only this one test had the defect. The two neighbouring assertions on the same
quantity are deterministic by construction: one sums the routing fractions, which
equal `top_k` whatever the routing does, and the other zeroes the gate's weights to
force exactly uniform load. No suite-wide seeding fixture was added for that reason.

The unit count moves from 863 to 858: six parametrisations became one test.

---

## 39. A research note on Continual Backprop

[25_continual_backprop.md](25_continual_backprop.md), in the same genre as
[22](22_jepa_integration.md): a design exploration, not a change. No code was added, no
configuration key was introduced, and no run behaves differently.

It asks whether Continual Backprop — backprop plus the continual, utility-ranked reinitialisation
of low-utility hidden units — has anything to offer a league-based self-play trainer, and reaches a
qualified yes with the qualification in a different place than JEPA's. JEPA suited *this
observation* and not *this reward*. Continual Backprop suits *this training regime* — the champion
pool turning over under `max_champions: 8` and `min_iterations_between_champions: 2` makes the
learning problem non-stationary by construction, which is the regime loss of plasticity is a
phenomenon of — and is aimed at a failure **nobody has yet confirmed this system has**. Before the
note, grepping `doc/` for *plasticity*, *dormant* or *dead unit* returned nothing at all.

### 39.1 The structural finding

Every previous extension to the learning stack went through the encoder registry. Continual
Backprop must not, for three reasons the note develops in §2.5:

- `encoder_type: "mlp"` is a deliberate pass-through that never reaches `CDACatalog`, so a
  registry-based mechanism would be unavailable for the shipped default — which is a 2×256 **tanh**
  MLP, the configuration most susceptible to the saturation CBP targets.
- `learner_class_for` fills RLlib's single algorithm-wide Learner slot from the *configured
  encoder*, so a CBP learner registered against an `encoder_type` would be mutually exclusive with
  `jepa` rather than composable with it.
- Resetting Adam's moment estimates for replaced units is part of the algorithm, and only the
  Learner can see the optimiser.

The shape the note proposes instead is a `CBPLearnerMixin` composed over whatever
`learner_class_for` returned, with its per-unit state held on the Learner rather than on the module
— which also keeps it out of champion snapshots by construction, rather than by remembering to
declare it the way `jepa` must via `get_non_inference_attributes`.

### 39.2 What was measured

Two feasibility probes, logged in [16](16_verification_log.md) §16.13. The mixin composes over both
`CDAPPOTorchLearner` and `CDAJEPALearner` with every existing loss term intact, and
`Learner.update` calls `after_gradient_based_update` exactly once per update — which is what lets a
replacement event avoid invalidating PPO's `exp(logp_new - logp_old)` ratio mid-update.

The second probe corrected the note's own first draft. It had repeated the usual claim that zeroing
a replaced unit's outgoing weights makes the replacement *function-preserving*. Measured on
`blocks.feedforward`, only half of that is true: the fresh random incoming weights reach the output
**not at all** (exactly `0.0`), but dropping the old unit's contribution moves the layer by `0.098`
even for the lowest-utility units. Nothing makes that half zero; it is bounded only by selecting
the minimum-utility unit, and on a freshly initialised network that bound is weak because the
utility spread is barely 2×.

### 39.3 What it recommends

Not the algorithm. §4.1 first — plasticity *instrumentation* only: dormant and saturated unit
fractions, effective rank, weight norm, and the CBP utility statistic computed and logged but
**not acted on**. It cannot change a run's trajectory, it is most of the implementation of the real
thing, and it answers the question everything else is blocked on, which is whether this system
loses plasticity at all.

The note is also explicit that CBP must be scored on the [23](23_probe_harness.md) probe rather
than on episode return until S1-3 is fixed: under a reward where passivity is the joint optimum,
preserved plasticity preserves the capacity to learn nothing, and a returns-based comparison would
measure which variant reaches passivity faster.

---

## 40. Continual Backprop, implemented

[25_continual_backprop.md](25_continual_backprop.md) §39 proposed this and recommended measuring
before building. Both halves are now built, off by default; the measurement is still outstanding
and is now the blocking step rather than the code.

Two modules, splitting algorithm from wiring the way `encoders/` splits architecture from
`moe_learner.py`:

- `train/model/cbp.py` — layer discovery, the three utility measures, the replacement rule, the
  plasticity metrics. Imports no RLlib, so the formulas are testable against hand-computed values
  without building an `Algorithm`.
- `train/model/cbp_learner.py` — forward hooks, the generate-and-test step, metrics, checkpoint
  state, and the composition helpers.

Plus two config groups, `optimizer` and `continual_backprop`, and 67 tests.

### 40.1 Reading the papers changed three things

The §39 note was written from general knowledge of the method. Against the sources it was wrong in
two places and understated in a third.

**It is the same network, not a similar one.** §39 said the shipped default is "very close to" the
configuration loss of plasticity was demonstrated on. arXiv Appendix D specifies "Policy Network:
(256, tanh, 256, tanh, Linear)", "Value Network (256, tanh, 256, tanh, linear)" and "separate
networks for policy and value function". That is `fcnet_hiddens: [256, 256]`, `fcnet_activation:
"tanh"`, `vf_share_layers: false` — exactly, trunks included. The mechanism can be validated
against a known-good reference instead of invented.

That turned up the structural trap: the **second hidden layer's outgoing weights are in the `pi`/`vf`
head, not the encoder**, so a layer walker that stops at the encoder boundary finds one replaceable
layer per network where there are two and silently leaves half the units alone. Discovery joins
across the boundary and a test names `pi.net.mlp.0` to keep it joined.

**Replacement fires per minibatch, not per iteration.** §39 reasoned that it must run once per
iteration to protect PPO's `exp(logp_new - logp_old)` ratio. arXiv Algorithm 3 runs generate-and-test
after *every* Adam step, inside the minibatch loop, and that is the configuration that produced the
paper's 100M-step RL results. Three things bound the disturbance: outgoing weights are zeroed so the
function is unchanged at the instant of replacement, Nature Algorithm 1 caps it at one unit per
layer per step (`If c > 1`, not `while` — the first implementation here used `while` and was
corrected), and at the shipped rate it happens about once per 39 steps. `cbp_fire_on: "iteration"`
keeps the conservative placement available.

**The recipe includes the optimiser.** Neither paper runs CBP alone in RL: it is CBP with L2 at
weight decay `1e-4` and "tuned Adam" at `β₁ = β₂ = 0.99`, the last because the usual `(0.9, 0.999)`
mismatch is itself identified as a cause of plasticity loss. This repo runs stock Adam with no
weight decay. Both are now configurable — in a **separate** group, so that enabling CBP and
retuning Adam cannot be done accidentally in one step and measured as one effect.

### 40.2 The finding that decides how to read any result

CBP's replacement rate and maturity threshold are counted in **optimiser steps**, and this project
takes far fewer of them than the papers do: 4 per iteration at the defaults against Continual PPO's
320. Transplanting the Nature paper's PPO values makes the maturity threshold 2,500 iterations
against a default run of 16 — **continual backprop would never fire once**.

A mechanism that never fires logs exactly what a working one logs. So `cbp_replacements` and
`cbp_mature_unit_frac` are required metrics, the maturity default is the arXiv value of 100 rather
than the Nature PPO value of 1e4, and both the config note and [18 §5.6.4](18_configuration.md) say
to read those two counters before believing anything else.

### 40.3 Isolation

Continual backprop is an update rule, not an architecture, so it is composed *over* whatever
`learner_class_for` returned rather than registered as another candidate to come back from it — the
argument in [25](25_continual_backprop.md) §2.5. Registering it in the encoder registry would have
made it mutually exclusive with `jepa` and unavailable for `mlp`, which never reaches the catalog.

With both switches off, `_learner_class` returns the base class object itself, and
`test_off_resolves_to_exactly_the_base_learner` asserts identity rather than behaviour. Nothing
that existed before regressed: the suite moves from 970 to **1,042 tests**, all passing, the 72 new
ones being 42 in `test_cbp.py` and 30 in `integration/test_cbp_wiring.py`.

### 40.4 Three bugs the tests found

None was hypothetical, and the third was found only by a real save and restore.

`find_replaceable_layers` originally returned the `jepa` encoder's EMA `target_trunk`, which is
structurally identical to the trunk it mirrors. Replacing a unit there would break the EMA
relationship the objective rests on, and nothing would undo it, because nothing updates that trunk
by gradient descent. Layers whose weights do not require gradients are now skipped.

`CBPLayerState.get_state` used `.detach().cpu()`, which returns *the same object* for a tensor
already on the CPU. The returned state therefore aliased the live tensors: a checkpoint would have
serialised whatever the values had drifted to rather than what they were when taken. Found by a
round-trip test that zeroed the live state and watched its own saved copy go to zero with it.

Third, and the one that mattered most: **continual backprop attached itself to league champions.**
A champion is a snapshot of a past policy, kept fixed so the opponent it represents does not drift,
and it shares the `MultiRLModule` with the trainable policies. Replacing a unit in one would have
silently mutated an opponent that is supposed to be constant, with no gradient to undo it. It did
not show up on a fresh run, where the league is empty when the learner is built; it showed up on a
restore, where the champions come back with the checkpoint and are present from `build()`. The fix
is `should_module_be_updated` - the same rule, one level up, that keeps replacement off the `jepa`
encoder's EMA target trunk: continual backprop replaces units gradient descent maintains, and
nothing else.

---

## 41. Four bugs a code review found in section 40

All four were at boundaries the test suite does not cross. None was in the algorithm: the utility
formulas, the accumulator, the one-replacement-per-step cap and the optimiser resets were correct
against the papers and covered. The suite runs **CPU-only, at `num_learners: 0`, and only ever
restores an unchanged config** - which is exactly the envelope the bugs lived outside of.

### 41.1 Two that would have crashed every GPU run

`CBPLayerState.zeros(layer.num_units)` omitted the device. `TorchLearner.build` sets `self._device`
and moves the module to CUDA *before* the mixin's setup runs, so the state sat on the CPU while the
activations arrived on the GPU, and `activation_stats`'s `h - f_hat` raised on the first forward
pass. The shipped `gpu` runtime profile is a supported configuration, so this was not an exotic
path. The state is now allocated from `layer.incoming.weight.device`.

`torch.Generator()` is a CPU generator, and `_reinitialise` hands it to `uniform_` on a tensor that
lives wherever the parameter does. Worse than the first because it is *delayed*: it does not raise
at build time but the first time the accumulator crosses 1.0, some tens of optimiser steps in. Now
built on the learner's device.

### 41.2 One that silently halved the mechanism

`_trunk_head_layers` reads `encoder`, `pi` and `vf` by attribute. At `num_learners > 1` RLlib wraps
each module in a `TorchDDPRLModule`, which subclasses `DistributedDataParallel`, keeps the real
module as a submodule named `module`, and defines no attribute forwarding - so all three lookups
returned None, the trunk-to-head join found nothing, and the default network came back with 2
replaceable layers instead of 4. No error, and metrics that look perfectly healthy. Precisely the
layers [25 §2.2](25_continual_backprop.md) identifies as easy to miss.

Unwrapping fixes a second thing that had not been noticed: `named_modules()` on the wrapper prefixes
every name with `module.`, and those names are the checkpoint keys, so a checkpoint could not have
moved between a distributed run and a single-learner one.

### 41.3 One that made a documented operation a no-op

`Algorithm.from_checkpoint` rebuilds from the config stored in the checkpoint, so the
`learner_class` and `learner_config_dict` assembled for the new run were used only for comparison
and never took effect. And `_config_fingerprint` carried neither group, so the existing "these
values will NOT take effect" warning could not fire either. Turning continual backprop on alongside
a resume therefore did nothing at all and looked identical to a run honouring it.

The note in `train_config.json` said the opposite - that a restore "may legitimately turn continual
backprop on, off, or up" - which made this the worst of the four: a documented operation that
silently did nothing.

Changing one of these keys alongside `is_restore` is now a hard error. They are
`UNRESTORABLE_CONFIG_KEYS`, a third category beside the structural ones and the merely ignorable,
with their own message: the weights fit perfectly, only the settings cannot apply, and a reader who
took "cannot restore" to mean the checkpoint was dead would throw away a good one.

Two softenings keep it from being noise. A tuning knob edited while continual backprop is off on
both sides is allowed, since it describes something that was not going to happen either way. And a
checkpoint predating the groups is compared against what such a run actually did - CBP off, torch's
own Adam - rather than skipped, which matters because every checkpoint in existence predates the
feature; comparing only the intersection of the two fingerprints would have made the fix hollow on
exactly the checkpoints most likely to be resumed.

### 41.4 What the tests can and cannot now pin

The suite goes from 1,042 to **1,058**. The device and DDP tests assert the *property* - state
allocated from the weight's device, the RNG from the learner's, a wrapper unwrapped before
discovery - rather than executing it, because a CPU-only box cannot do the latter: a `meta`-device
tensor stands in for CUDA and a stub with DDP's two relevant behaviours stands in for the wrapper.
That is weaker than running on the real hardware and is stated as such in
[10 §6.5](10_testing.md) and [25 §3.7](25_continual_backprop.md).

One test was also found to be flaky rather than wrong: `TestCBPSurvivesARealSaveAndRestore` asserted
that the restored league carries a champion, which depends on league statistics that are not
reproducible across test orderings. It now creates one explicitly, the same manoeuvre
`test_checkpoint_roundtrip.py` uses, so the class cannot pass vacuously on an empty league.

---

## 42. The plasticity measurement, and the metric that got it wrong

[25](25_continual_backprop.md) §7 made one thing the blocking step after §40 and §41: actually
run `cbp_metrics_only` and find out whether this system loses plasticity. It has now been run.
**The answer at this scale is no — and the instrument §39 proposed said yes.**

### 42.1 The result

Numbers in [16](16_verification_log.md) §16.16. The network is the shipped default untouched;
the environment is scaled down and the update schedule up to buy optimiser steps, those being the
clock plasticity runs on.

| | optimiser steps | effective rank |
|---|---|---|
| On the training minibatch | 17,875 | 97.1 → 73.2, **−24.6%**, both policies |
| On a fixed corpus, 8 layers | 19,500 | **+2.5% to −1.9%** |

Two further readings agree with the second. The training-batch rank is **not monotone** — it fell
to 68.2 by iteration 178 and recovered to 73.2 by 275 as the league turned over, ρ weakening from
−0.90 to −0.71 — and capacity loss does not come back. And dead and saturated units sat at
**exactly zero** on every layer, where arXiv Appendix G reports ~90% of features saturated under
plain backprop.

### 42.2 Why the two disagree, and what it says about the metric

The rank of an activation matrix has two parents: the network and the inputs. Both papers measure
it in supervised settings where the inputs are a fixed dataset, so only the network can move it.
In reinforcement learning the policy chooses its own inputs, and under S1-3 — where passivity is
the joint optimum — a converging agent visits an ever narrower set of book states. The rank of
what it sees falls with the network unchanged.

So `cbp_effective_rank` as shipped in §40 was confounded, and on this system it produced a 24.6%
false positive. A reader following [18](18_configuration.md) §5.6.4, reading the correlates, and
seeing that number would reasonably have switched continual backprop on to treat a patient who
was not ill.

§40 argued instrumentation is safe because it cannot change a run's trajectory. That is true of
the run and false of the conclusion: a metric that cannot break training can still be believed.

### 42.3 The fix

`train/probe/rank.py`. The probe harness already exists to answer questions about an encoder
without going through the reward, and it already holds a corpus fixed while the encoder varies —
which is exactly the property the metric was missing. It reports each feature set's effective
rank beside its width, flags any set whose rank is bounded by the corpus rather than the encoder,
and prints as its own table under the score matrix rather than as a column on it, since rank is a
property of a feature set while every row of that matrix is a (feature set, target) pair.

The Learner-side version is **kept and renamed** `cbp_batch_effective_rank`. "What the network is
doing on the data it is actually training on" is a real thing to want; what was wrong was a name
that did not say what it was measured on.

There are now two implementations of effective rank — torch in `cbp.py`, which must not import
RLlib or the probe package, and numpy in `probe/rank.py`, which is what the harness works in.
`test_it_agrees_with_the_torch_definition` is the only thing keeping them the same measurement.

Two notes on the other correlates, both of which read zero throughout and neither of which is
confounded this way (weights do not depend on the batch, and a unit dead on one input
distribution is generally dead on others):

- `cbp_dead_unit_frac` is ReLU-shaped — a tanh unit does not die toward zero, so it cannot fire
  on the shipped network whatever happens to it.
- `cbp_saturated_unit_frac` uses the per-unit batch mean |h| > 0.9, i.e. "saturated on
  essentially every input", which is stricter than the papers' per-output definition.

### 42.4 What is still open

A null at 2×10⁴ optimiser steps on a scaled-down environment at one seed does not rule out loss
of plasticity at the 10⁶–10⁸ the project needs. [25](25_continual_backprop.md) §7 step 5 is the
re-run at scale, on real hardware, multi-seed, reading the fixed-corpus rank rather than the batch
one. Step 7 — continual backprop in the offline pretrainer — is worth promoting if that stays
null, since the pretrainer has no policy and so cannot have this confound at all.

Also fixed here: §40 appended its testing section as `## 6.5 Continual Backprop` *after* section 7
of [10](10_testing.md), where `### 6.5 The probe harness` already existed. Renumbered to 6.6 and
moved into section 6 where it belongs.

---

## 43. A code review, and the documents §37 left behind

A review pass over the working tree. The code findings are small; the documentation ones are not,
and they are all the same finding.

### 43.1 The observation reference was a version behind the observation

§37.4 widened the observation from **177 floats to 193** — `extra_dim` 2 → 6, snapshot 42 → 46,
book block 168 → 184 — and rescaled two of the existing features. It updated
[15](15_findings_and_recommendations.md), [16](16_verification_log.md) and this changelog. It did
not update [05](05_observation_space.md), which is the *reference* for the thing it changed, and
the stale numbers had spread from there into eight more documents.

What [05](05_observation_space.md) still said, and now does not:

- the snapshot is 42 floats and the observation 177;
- `extra_dim` is 2, and there are two market scalars;
- volumes are `sqrt(V)` and `log_mid` is `ln(M)`;
- the deque holds already-normalised frames, so §7.1 — frames cannot be compared — is a live
  defect;
- §7.3 — the tape loop is dead code, there is no trade-flow information at all — is a live defect;
- §7.5 — the size block is 80–250× the price block — is a live defect;
- every agent receives the same array, `distinct obs vectors across agents: 1`.

The last one had been fixed two passes earlier, in §30. Three of the six are §37.4's own subject.
§7.1, §7.3 and §7.5 are marked fixed rather than deleted, because the fix only reads as a fix
against what it replaced, and §6 now carries the before-and-after measurements side by side.

Sections 3.3–3.5 are new: `mid_return` and the three trade-flow scalars had no reference entry
anywhere, only a line in this changelog.

The same numbers were corrected in [README](../README.md), [01](01_overview.md),
[02](02_architecture.md) §2.5 and §2.9, [09](09_distributed_training.md),
[12](12_perspective_rl_researcher.md), [18](18_configuration.md), [21](21_logging_review.md),
[22](22_jepa_integration.md), [23](23_probe_harness.md) and [25](25_continual_backprop.md). Two of
those were not just a width:

- [18](18_configuration.md) §5.4 said a token is 4 channels wide because `max(book_rows,
  extra_dim)` is `max(4, 2)`. It is `max(4, 6)` now, so tokens are **6** wide and it is the
  per-level tokens that are zero-padded, not the global one. That paragraph had predicted exactly
  this ("the `max` matters if you add market features") and then went stale on its own prediction.
- The [README](../README.md) summary named the per-frame normalizer and the missing trade-flow
  features as what remained wrong with the observation pipeline. Both are §37.4.

### 43.2 A verification-log entry recorded numbers from a tree it did not run on

[16](16_verification_log.md) §16.14 enumerated the default network as `Linear 177->256` and
checked the initialisation bound against `1/sqrt(177) = 0.075165`. The tree those probes ran on
already emitted 193; re-measured, it is `Linear 193->256` and `1/sqrt(193) = 0.071982`, with a
measured max |w| of 0.07198. Corrected in place with a note, since a verification log that quietly
changes its numbers is worse than one that says it got them wrong. Nothing the entry exists to
support depends on the input width, so the conclusion stands.

### 43.3 §2.5 of the Continual Backprop note argued for a hook the code does not use

[25](25_continual_backprop.md) §2.5 was written before §3.1 was, and still said
`after_gradient_based_update` "is the correct hook", pointing at §3.1 for the argument — where
§3.1 in fact reverses it and the shipped default is `apply_gradients`. Its two code sketches had
drifted too: a mixin method that no longer exists and a `cfg.cbp["enabled"]` config shape that
never did. Rewritten to make the ordering explicit — §3.1 settles the hook, §2.5 only claims it is
*on the Learner* — and the sketches now match `cbp_learner.py`.

Also in that note: §5's instrument table named `dormant_unit_frac` and `effective_rank`, neither
of which is emitted, and asked for the rank metric §3.8 had just established is confounded. §6
still said the disease was "unmeasured" after §3.3 measured it.

### 43.4 Four smaller ones

- `CBPLearnerMixin._cbp_log`'s docstring described reductions the method does not perform — it
  says the correlates are averaged and two utility statistics take extremes, where in fact
  `dead_unit_frac` and `saturated_unit_frac` take the max, `utility_min` the min, and
  `utility_median` the mean. [11](11_logging_and_observability.md) had the table right, so the
  code comment was the one arguing with the reader.
- `train_config.json`'s `_note_metrics_only` still said whether this system loses plasticity "is
  currently unknown" after §42 answered it, and `_note_restore` said every key in the group is a
  hard error alongside `is_restore` when nine of the eleven are only checked while the mechanism
  is running.
- `cbp.effective_rank` and `probe.rank.effective_rank` disagree on a matrix with fewer than two
  rows — NaN and 0 respectively — while three docstrings and a test claimed one definition. The
  divergence is right (a metric series wants NaN where a report column wants 0) and is now stated
  in both docstrings and pinned by a test of its own.
- The rank table's `used` column was formatted one character narrower than its header.

### 43.5 What the review did not find

No correctness defect in the Continual Backprop implementation, the probe harness or the
observation pipeline. 914 unit tests and 153 integration tests pass. The utility formulas, the
accumulator, the one-per-step cap, the optimiser resets, the device and DDP handling and the
checkpoint round trip were all checked against the papers and against §41's four boundary bugs,
and nothing further turned up.

Two tests are new — the deliberate torch/numpy divergence in `effective_rank`, and the
fingerprint-collision guard — and one latent hazard was closed rather than merely noted:
`_config_fingerprint` flattens `learner_config_dict`'s groups into the same namespace as the
AlgorithmConfig attributes, so a future group with a bare `num_epochs` would have shadowed the
real one and made a genuine divergence invisible to the restore check. It raises now.

### 43.6 The test inventory, re-counted

[10](10_testing.md) §"File inventory" was itself a version behind: it reported `858 passed` and a
unit total of 770 against a real 914, was missing nine files outright — including both continual
backprop suites, and `test_self_match`, `test_resting_exposure`, `test_entry_vwap`,
`test_obs_pipeline` and `test_obs_feature_scales`, which are §37's own tests — and thirty-eight of
its per-file counts were wrong. Re-measured with `--collect-only`: **914 unit, 153 integration,
1,067 total**. The coverage mindmap's per-area counts were regenerated from the same numbers, and
the four other documents quoting a total — [01](01_overview.md), [02](02_architecture.md),
[14](14_perspective_ai_engineer.md) and [15](15_findings_and_recommendations.md) — were brought to
it. [16](16_verification_log.md) §16.2 keeps its `90 passed`: it is a dated record of the original
audit's run, not a claim about now.

This is the third pass to re-count these (§36, §37.7, here), which suggests the counts want a
generator rather than a reviewer.


## 44. The 2026-09-18 review pass: a cancel that could not cancel, and a grid that was not one

A code review of the merged tree, in the same shape as §37 and §43: read everything, run
everything, probe what the tests do not reach. The suite was green before (914 + 153) and is green
after (935 + 153). Two defects in the simulator's action path were found by asking what happens at
the edges the tests do not visit — a trader with nothing left to spend, and a tick that is not 1 —
and both turned out to be the rule at those edges rather than the exception.

### 44.1 A cancel was cash-checked, so an over-committed trader could not cancel (S2-13)

`Trader._order_approved` applied the same predicate to every order type. For a `cancel` that meant
"is `size × price` affordable from `cash`", where `size` and `price` are the cancel's own,
irrelevant, decoded values. A trader with all its cash escrowed in resting orders — the one state
in which cancelling is the thing to do — was therefore refused the cancel, silently, with
`num_rejected_step` incremented as if it had quoted past its means. A `modify` that shrank an
order, or re-priced it at the same notional, was refused the same way, because the check compared
against `cash` before `cancel_cash_transfer` had returned the old order's escrow.

A cancel is now approved unconditionally once the `nav > 0` gate passes. A `modify` or a
`limit` upsert may spend the escrow the order it replaces gives back, so only a real increase in
notional beyond `cash + released` is refused. `_replaced_order` returns the order alongside its id
so the exclusion S1-5 introduced and the release this needs come from one lookup. Seven tests in
`test_cash_check.py`. [15](15_findings_and_recommendations.md) S2-13, [16](16_verification_log.md)
§16.17.

### 44.2 The action layer put off-grid prices in the book on any non-integer tick (S3-4)

[15](15_findings_and_recommendations.md) S3-4 said `_set_price` emits on-grid prices "by
construction" and measured the drift as one combination in sixty. That measured the anchor path.
The level path — taken whenever the targeted book level is occupied — read the resting price out
of `agg_LOB_raw`, a **float32** array, so 100.1 came back as `100.0999984741211`, and the offset
was then added in float. The book keys its price map on `Decimal(str(price))` and rounds nothing,
so every re-quote at an occupied level opened a new level one ulp away, and `_get_order_ID`,
comparing the book's `Decimal` with the action's `float`, never found the trader's own order:
cancels were no-ops and a same-price limit rested a second order instead of upserting. At default
`tick_size` 1 none of this fires, which is why nothing noticed.

Three changes: `agg_LOB_raw` is float64 (the observation is still float32 at emission),
`_set_price` snaps its result to the tick grid in `Decimal`, and `_get_order_ID` compares as
`Decimal(str(price))` — the book's own conversion. `test_tick_grid.py` (14 tests) covers seven
ticks including 0.3 and 0.0001, the upsert, the cancel and NAV conservation under random play at
0.1. The dead `OrderBook.tick_size` parameter is the only part of S3-4 left, and it stays for the
reason it always did: `envs/orderbook/` is off-limits.

### 44.3 Smaller

- Two unused locals (`counter_party` in `_process_trades`, `best_bid` / `best_ask` in
  `_set_price`) and one placeholder-less f-string in `test_logging_setup.py`, all flagged by
  pyflakes, which otherwise reports only unused imports across the package.
- `tunable_constants.json`'s `observation_layout` note still listed two market scalars; there
  have been six since §37.4.
- [10](10_testing.md) §8 still carried `test_insufficient_funds` as an empty `pass`; it has
  asserted the behaviour since §37, and S4-5 in [15](15_findings_and_recommendations.md) now
  says so.

### 44.4 A runbook

[26](26_runbook.md) is new: the install, the checks, the train / restore / inspect loop, the
reward-free tools, what to watch while a run is going, and a troubleshooting table — each command
verified against `--help` and, for the training loop, against a two-iteration run whose output
tree is reproduced there. The information existed across [18](18_configuration.md),
[19](19_docker.md), [20](20_colab.md), [11](11_logging_and_observability.md) and the module
docstrings; there was no single page an operator could follow top to bottom.

### 44.5 Recommendations carried forward

Recorded in [15](15_findings_and_recommendations.md) and the closing message of the review rather
than acted on here, because each is a scope decision: the dead `OrderBook.tick_size` parameter and
`from decimal import *` in `order.py` (both blocked on the `envs/orderbook/` policy); a counter for
a `modify` / `cancel` that finds nothing to target (S4-14, the remaining half); the escrow that
still charges closing orders (S1-5's open tail); a lint step in CI, which this pass could not add
because the push credential has no workflow scope (§37 hit the same wall); and the multi-seed
encoder comparison [10](10_testing.md) §8 has called the largest gap for three passes running.


## 45. The recommendations of §44, carried out

§44.5 listed six things a review pass should not decide on its own. Asked to proceed, this pass
did all six. The suite grows from 935 to 979 unit tests; the first run of the new property suite
found two defects of its own, which is the best argument for it.

### 45.1 The `envs/orderbook/` freeze is lifted (S3-4, S3-7, S4-3, S4-4)

The package had been off-limits since the first review, on the grounds that nothing tested its
invariants well enough to change it safely. §45.4 changed that, and with the invariant suite in
place the deferred items went through: `OrderBook` takes no `tick_size` (it stored one and never
read it - `OrderBook(0.0001, 10)` is now a `TypeError`, and the `inert_tick_size_copy`
documentation block is gone); all six `sys.exit` calls raise `ValueError` naming the method and the
refused value; `from decimal import *` is `from decimal import Decimal`; `six.moves.cStringIO` is
`io.StringIO`, so `six` leaves `install_requires` and `requirements.txt`; and ~150 lines of
commented-out and superseded code (`__str__0` twice, `to_str`, the old `modify_order`, the shadowed
`Order.next_order`/`prev_order` methods) are deleted. `test_config_sources` no longer asserts the
book carries the tick, because nothing does but the action layer.

### 45.2 The third silent no-op is counted (S4-14)

`num_unmatched_step` on the account, incremented when a `modify` or `cancel` names no resting
order, reset per step with the other counters, reported in `info`, given a column in the episode
record, and aggregated into `unmatched_action_fraction` beside the pass and rejection fractions.
Ten tests in `test_unmatched_actions.py` and three in `test_activity_metrics.py`.

### 45.3 Lint is enforced without a workflow change (S4-6)

The push credential cannot edit `.github/workflows/` (§37.6), so `test_lint.py` runs pyflakes over
the package and fails on any message, and CI enforces it through the test step it already runs.
Getting there meant removing 69 unused imports and declaring `__all__` in the five `__init__`
files that re-export (`envs`, `orderbook`, `probe`, `pretrain`, and the encoder registry, whose
side-effect imports are now named as `REGISTERED_ENCODER_MODULES`). `pyflakes` and `hypothesis`
join the `dev` extra.

### 45.4 Property-based tests, and what they found (S4-13, S3-23)

`test_orderbook_properties.py` drives Hypothesis-generated order sequences through `Trader` and
`OrderBook`, and Hypothesis-chosen seeds through the whole env at three ticks, asserting the
invariants [10](10_testing.md) §8 had listed for three passes: tree caches against a walk, time
priority within a level, no locked or crossed book, escrow equal to own resting notional,
positions netting to zero, NAV conservation, `cash + cash_on_hold >= 0`, prices on the grid.

Its first run failed twice. A size-reducing `modify` kept an order's queue position but stamped it
with the modify time, so `_get_order_ID`'s "oldest order" rule could pick the wrong one next time;
`Order.update_quantity` now moves the timestamp only when it moves the order. And NAV conservation
is exact only to about `1e-22`: the VWAP quotient rounds at the Decimal context and
`mark_to_mkt` multiplies it back in two independently rounded products. That is not a regression -
17.6% of steps carried the residual on the tree before this pass - but [16](16_verification_log.md)
§16.10 had recorded conservation as exact, and the `nav_tolerance` note says the expected error
is zero. Both are corrected; the finding is S3-23, with the cost-basis-as-sum fix that would make
it exact.

### 45.5 The encoder comparison protocol, as a command (doc/18 §5.5)

`python -m gym_continuousDoubleAuction.train.compare` runs every (encoder, seed) as a separate
training run with the seed pinned and its own checkpoint tree, scores each final checkpoint on
the probe harness against one shared corpus, and writes per-run JSON plus a Markdown table of
means and standard deviations across seeds. It reports two encoders as *separated* on a metric
only when the gap exceeds both standard deviations and each side has at least three seeds; below
that the footer calls the table a smoke test. Run once at smoke scale ([16](16_verification_log.md)
§16.18) to prove the path; the run at scale remains the open item in [10](10_testing.md) §8.
Twelve tests cover the aggregation; the `cda_compare` group in `cli_defaults.json` holds its
defaults.

### 45.6 The S1-5 tail, measured and closed

Escrow against a resting order that would only close the position was treated as spent by the
cash check. Measured first: at `init_cash` 100,000 under random play, 84% of refusals happened
while such escrow existed and 67% would have passed had it counted. Then fixed in the approval
predicate alone - `Trader._closing_escrow`, capped at the quantity that actually closes, oldest
order first - leaving the ledger and every partial-fill path untouched. `cash` may now sit below
zero by at most that amount while both orders rest; the property suite asserts `cash +
cash_on_hold >= 0` and NAV is unaffected. Refusals at 100,000 fell from 607 to 340.

### 45.7 Still open after this pass

The run of §45.5 at scale; the cost-basis fix of S3-23; a formatter, coverage and type hints in
`envs/` (the rest of S4-6); the remaining dead code in `continuousDoubleAuction_env.py` and
`action_helper.py` (S4-3, S4-4); and whether a dead action should cost the agent anything, which
is a reward question rather than an accounting one.


## 46. Conservation exact, and a plan for aimable order management

### 46.1 S3-23 closed the day it was opened

§45.4 found that NAV conservation held only to about `1e-22`, because the ledger stored the
position's basis as a VWAP quotient and rebuilt it by multiplication. The basis is now stored as
what it always was in substance: `Account.cost_basis`, the exact `Decimal` sum of the trade values
that built the position, which every path reads and writes directly. `VWAP` is a derived property
over it, kept for display and for the tests that construct positions by hand. `mark_to_mkt` forms
`position_val` from the basis with one product, so for a long it is `|pos| × mark` exactly and for
a short `2 × cost_basis − |pos| × mark`. Re-measured over the same 12,000 steps: zero residual, at
`tick_size` 1 and 0.1. The property suite asserts `==` again; the `nav_tolerance` note is true
again and now says why. [15](15_findings_and_recommendations.md) S3-23,
[16](16_verification_log.md) §16.19, [04](04_accounting.md) §1 and §5.

### 46.2 A plan for making `modify` and `cancel` usable (S3-24)

Measured first: under random play a `cancel` hits one of the agent's own orders **7%** of the time
it is issued and a `modify` 48%, with agents holding 1.6 orders on average. The three causes -
the agent cannot see its own orders, a cancel is aimed by exact price out of thirty codes, a modify
is aimed by FIFO - and the four-phase plan that follows (own-book observation block; aim by
`order_slot`; make a miss visible in the next observation; prove it learned with `train.compare`)
are written up as [15](15_findings_and_recommendations.md) S3-24, with effort and the structural
consequence: both layout changes should land as one checkpoint generation, and that is the moment
to record a layout version (S4-19).


## 47. Order management made aimable (S3-24, phases 1–4; S1-2 and S4-19 closed)

The plan of §46.2, carried out as one checkpoint generation. The observation is 216 floats (from
193), the action Dict has six heads (from five), and every checkpoint now says which layout it was
trained against.

### 47.1 Phase 1 — the own-book block

The private block is `[9 base | own bid sizes (k_rows) | own ask sizes (k_rows) | own counts (2) |
unmatched_last_step]`, built by `State_Helper.private_fields(k_rows)` so a config tree with a
different depth gets the block for its depth. Own size at level k is this agent's resting quantity
at the price of public level k, read from the live book after the step's orders and put on the
public book's scale and sign. `tokenize` writes the two own sizes into channels 4 and 5 of the
newest snapshot's level tokens — the channels the six market scalars had left as zero padding on
level tokens — so every tokenising encoder sees them per level at no extra width, and `ObsLayout`
learns where the block sits from the env's own definition rather than a second constant.

### 47.2 Phase 2 — `order_slot`

A sixth action head, `Discrete(max_own_orders + 1)` with `max_own_orders` 4, the measured p90 of
resting orders. Slot k names the agent's k-th own order from the touch (best price first, oldest
first within a level, the order the own-book block lists them in); 0 is "all on this side" for a
cancel and the oldest order for a modify, which is the pre-slot FIFO rule so a policy that ignores
the head loses nothing. A cancel no longer reads `price`.

**One departure from the plan, forced by measurement.** The plan had a slot past the agent's count
miss. Under random play that made modify worse than FIFO — 48% → 23% of issued modifies landed —
while cancel rose only from 7% to 19%, because a uniform policy spends a fifth of its order
management on each slot and the upper ones name orders it does not have. A learned policy gains
nothing from dead slots: it can read its own-order counts and aim exactly. So a slot past the count
now clamps to the deepest own order, the only miss left is a side with nothing resting on it, and
under random play 35–36% of issued cancels and modifies land, 58–62% of those with anything
resting. [16](16_verification_log.md) §16.20 has the four-row table.

### 47.3 Phase 3 — feedback

`unmatched_last_step` in the private block, 1.0 on the observation after a dead modify or cancel.
And a sixth reward term, `dead_action_penalty`, shipped at 0.0 with the S1-3 warning on the knob:
`x + (-0.0) == x`, so the reward is bit for bit what it was, and the term is in
`info["reward_terms"]`, the record and the variance-share metrics like the other five.

### 47.4 Phase 4 — proving it, as far as this session can

`train.compare` collects `order_rejection_fraction`, `unmatched_action_fraction` and
`maker_fill_ratio_max` beside returns, and was run before and after at three seeds × 8 iterations
of the scaled-down protocol. The dead-action share fell 0.315 → 0.289 with pass and maker
fractions unchanged; nothing is separated by the driver's rule and nothing at that scale is
learning, so this proves plumbing and direction, not the claim. The Hypothesis suite drives
slot-aimed modifies and cancels through every book, escrow and ledger invariant.

### 47.5 S4-19 — the layout stamp

`envs/layout_version.py` writes the observation and action layout versions, the private-field list
and the action-key list into every checkpoint's `league_state.json`, and `build_algo` compares
before restoring. A pre-stamp sidecar is layout 1 by definition, so every checkpoint written before
today is refused by name rather than by tensor shape.

### 47.6 What else moved

`test_cbp` pins the policy head at 31 outputs (was 26). `test_config_sources` sets `private_dim`
alongside `k_rows` when it swaps a depth in. The tokeniser test that said the private block never
reaches a token now says everything but the own-book block never does. Fourteen documents that
stated 193 state 216. Suite: 1,019 unit + 153 integration.


## 48. The hygiene group

The S4 rows that needed no design decision, done in one pass. Two of the group turned out not to
be hygiene and are marked as such rather than done.

- **S4-1, S4-2, S4-3, S4-4 — dead code.** `train/helper/helper.py` and `envs/agent/random_agent.py`
  are deleted, `Trader` no longer inherits from the legacy random agent, the last dead methods
  (`state_diff`, `_set_side`, `_set_type`, `_higher`, `_lower`) and the last ~200 lines of
  commented-out code (the old `step` and space getters, the old `Tuple` action space) are gone.
- **S4-6 — tooling.** `pyproject.toml` with a `ruff` selection matching the pyflakes rules
  `test_lint.py` enforces, a `pytest` block and `coverage` tables; `pytest-cov` in the `dev` extra;
  the unit suite measured at **79.1%** line-and-branch ([16](16_verification_log.md) §16.21); type
  hints on the public API of every `envs/` module. No formatter pass - that is one deliberate
  commit of churn, not a side effect of a hygiene pass - and no coverage threshold yet, because at
  79% it would ratchet the CLI mains first.
- **S4-7 — rendering.** `is_render` defaults to `false`, and `_render` no longer mutates the
  state it prints, so a rendered run and a silent one evolve identically.
- **S4-8 — Docker.** The image installs from `requirements.txt` on its own cached layer.
- **S4-10 — defensive reads.** Every `getattr(self, ..., default)` in `envs/` is gone; the
  attributes are initialised where their mixin is built and read directly. The mixin architecture
  itself stands - unwinding it is a redesign, and the row says so.
- **S4-11 — two hot-path claims, measured.** The counter-party scan cost 0.2 µs and is O(1)
  anyway; the pre-action snapshot cost 5.9% of a step and is now rebuilt only when the book
  changed since the last one, which is exactly after a bankruptcy cancels orders.
- **S4-12 — `train.evaluate`.** The repository can now *use* a checkpoint: restore it, roll
  episodes with its own mapping function and modules through `forward_inference` (unsquashing the
  normalised Box heads the way the env runner does - without that, half the sampled
  `size_sigma`s are negative and the env refuses them), and report per module what the policies
  did. Seven tests, three of them against a real one-iteration checkpoint.
- **S4-18** was already fixed; the row was stale.
- **S4-15 and S4-17 are not done**, and the register now says why: both change the observation's
  representation - its bounds, or the sign convention every encoder is fed - which is a layout
  version bump and a learning-problem change, to be made with `train.compare` in hand rather than
  in a hygiene pass.

Suite: 1,023 unit + 156 integration.

## 49. Positive asks and a finite observation Box (S4-17, S4-15; layout version 3)

The two S4 rows the hygiene pass declined, done as a measured pass ([16](16_verification_log.md)
§16.22). Same 216-float width; different meaning, so `OBSERVATION_LAYOUT_VERSION` is 3 and a
version-2 checkpoint is refused by name (S4-19) rather than silently reading every ask as a bid.

- **S4-17 — the ask sign is gone.** `set_agg_LOB` stores ask prices and sizes as they are;
  `_normalise_frame` emits `(P_ask − M) / M ≥ 0` and `+sqrt(V / limit_max_size)`; `_l1_prices` and
  `own_book` follow; `_set_price` reads the positive row; the probe's `depth_imbalance` is
  `(bids − asks) / (bids + asks)` and the order-book visualizer no longer un-negates. Side is the
  block, which is what lets an encoder share weights between the two halves. Seven tests that
  pinned the old sign now pin the new one.
- **S4-15 — the Box is finite.** `observation_bounds` in `tunable_constants.json` gives one
  `[low, high]` per feature family, exact where the range is an identity and measured with
  headroom where it is not ([18](18_configuration.md) §4.1.1, [05](05_observation_space.md) §1.2);
  `State_Helper.observation_bounds` tiles them over the vector and the env declares the `Box` with
  them. A field without a bound fails construction by name.
- **Every clip is counted.** `set_next_state` clips to the bounds and writes the count to
  `num_obs_clipped_step`: in `info`, in the episode record (`INFO_COLUMNS`), aggregated into the
  `obs_clip_fraction` metric ([11](11_logging_and_observability.md) §1.2) and reported by
  `train.compare`. It reads 0 on every one of the 112,000 agent-steps measured, and it caught the
  first candidate bounds being wrong — older frames' price rows go negative against the newest
  midpoint — before any training run did.
- **A measurement against S3-14.** Deriving the bounds put numbers on the one-sided-book fallback:
  under random play the midpoint falls to a lone quote at the tick floor and the price ratios reach
  20× and more. The row in [15](15_findings_and_recommendations.md) carries them now.
- **Tests.** `test_observation_bounds.py` (12) and two `obs_clip_fraction` tests in
  `test_activity_metrics.py`. `integration/test_evaluate_checkpoint.py` now accepts a promoted
  champion among the checkpoint's opponents - whether the one training iteration promotes one
  depends on the returns drawn, and the first full run on this layout did. Suite: **1,037 unit +
  156 integration**.

## 50. Zero means one thing: occupancy rows and the last-trade reference (S3-14; layout version 4)

The first of the pre-existing S3 rows taken through the measure-first pass
([16](16_verification_log.md) §16.23).

- **Measured first.** Under random play at the shipped config 7.8% of steps had a one-sided book,
  and on every one of them the best quote read exactly `0.0` - the same value as an absent level;
  1.2% of occupied price cells in all, and 22% at a thin-book stress config where 77% of steps
  were one-sided or empty. No other source of ambiguous zeros exists in the newest frame.
- **Two occupancy rows per snapshot** (`bid_occupied`, `ask_occupied`, 0/1), built in
  `set_agg_LOB` beside the price and size rows so every frame in the stack keeps its own, passed
  through normalisation unchanged, bounded on `[0, 1]`. `book_rows` is 6, a snapshot 66 floats,
  the observation 296. The tokenising encoders carry them as two more channels of each level token.
- **The reference price of a one-sided book is the last trade**, not the lone quote
  (`State_Helper.mid_price`; [05](05_observation_space.md) §2.1). The quote then reads its distance
  from the print. This is the chain `Exchg_Helper.mark_price` has used since S2-5, so the price the
  agent sees and the price it is marked at now agree whenever the book is not two-sided.
- **After:** the row equals `size > 0` on every cell of every step; the zeros that remain (0.66%
  shipped, 11.2% stress) are quotes resting exactly at the last print and are labelled occupied.
- **A correction to §49's story.** The extreme price tails found while deriving the S4-15 bounds
  were traced cell by cell: every one sat in a book whose midpoint had random-walked down to one to
  three ticks, mostly two-sided. They are S3-15's additive-tick coordinate, not the one-sided
  fallback; §16.22, [05](05_observation_space.md) §1.2 and the S3-14 row now say so.
- **Layout version 4.** A version-3 checkpoint is refused by name (S4-19).
- **Tests.** `test_occupancy_channel.py` (11); one more branch of the reference chain in
  `test_obs_market_features.py`; the width literals in five test files follow the layout. Suite:
  **1,049 unit + 156 integration**.

## 51. The book as a fixed tick-offset grid (S3-15; layout version 5)

The second pre-existing S3 row taken through the measure-first pass
([16](16_verification_log.md) §16.24).

- **Measured first.** In the `levels` layout the best occupied level sat 3.8 ± 2.5 ticks from the
  reference under random play, its price changed on 35–54% of steps, and the action's price code
  *j* landed anywhere from 0 to 20 ticks out with codes 1–6 indistinguishable. A ±10-tick window
  around the reference held 72.5% of resting volume.
- **`book_mode: "grid"`, the new default** ([05](05_observation_space.md) §1.4). Two size rows over
  `2 k_rows + 1` tick offsets from the reference price `R` (the §2.1 chain snapped to the tick);
  cell *c* is the price `R + (c − k_rows) × tick`; every frame in the stack is re-gridded against
  the newest `R_t`, so a resting order sits in the same cell of every frame. 48 floats per snapshot,
  224 in all. The raw six-row frame is unchanged underneath, which is what makes the re-gridding
  possible and keeps `agg_LOB_raw` and the L1 reads as they were.
- **The action shares the grid** ([06](06_action_space.md) §2.1.1). Price code *j* quotes exactly
  *j* ticks from `R` on the passive side; the offset head still shades by a tick; ghost pricing is
  a `levels`-mode path. After: code *j* lands at *j* ± 0.9 ticks, and the window now holds 93% of
  resting volume because the agents quote on it (99.5% at ±16).
- **`levels` is kept** as the other value of the key, per env instance, so `train.compare --set
  book_mode=levels` runs the comparison. `TrainConfig.book_mode`, the env config and the layout
  stamp carry it; a checkpoint from the other mode is refused by name, which matters because the
  two widths coincide at one `n_hist`.
- **Consumers follow the mode by name.** `ObsLayout` infers the mode from the space (default
  first) and exposes `row_slice`; the tokeniser puts own sizes on the cell their tick offset names;
  the probe's `depth_imbalance`, the visualizer and `print_table` address rows by name.
- **`train.compare --set FIELD=VALUE`** overrides any `TrainConfig` field for every run, coerced to
  the field's type - the switch the remaining S3 comparisons need.
- **Tests.** `test_grid_book.py` (14), two more in `test_layout_version.py`; the `levels`-mode
  tests build that mode explicitly. Suite: **1,065 unit + 156 integration**.

## 52. Episode horizons: fixed, or drawn from a range

`episode_length_mode` in the env config ([18](18_configuration.md) §3.4): `"fixed"` is the
behaviour to date, every episode truncated at `max_step`; `"random"` draws each episode's horizon
uniformly from `[max_step_min, max_step_max]` with the env's seeded generator, reports it once as
`episode_horizon` in the reset infos, and keeps it out of the observation - `time_left` counts
against the latest possible end, so the policy sees a bound but not the draw. Truncation lands on
the draw; bankruptcy termination is unchanged; `TrainConfig.train_batch_size` is sized by the mean
of the range. `test_episode_horizon.py` (14). Suite: **1,079 unit + 156 integration**.

## 53. Action masking: what is impossible is never chosen

The recommendation of the last review, done as asked: mask what is impossible, let the policy
learn what is merely unwise ([06](06_action_space.md) §7, [16](16_verification_log.md) §16.25).

- **The observation carries the mask.** Nine `can_<category>` entries close each agent's private
  block (41 fields; 233 floats in grid mode), set by `Action_Helper.action_mask_for`: a modify or
  cancel needs a resting order on that side, a market or limit order needs to pass the same cash
  check that judges the order, for the minimum size at the reference price. Pass is always
  possible. Layout version 6.
- **The modules honour it.** `CDAPPOTorchRLModule` adds −10⁹ to a masked category's logit on every
  forward pass, and is now the module for the `mlp` path too (stock encoder and catalog, so nothing
  else changes); `RandomRLModule` redraws a masked category among the possible ones. Where the mask
  and the logits sit is derived from the spaces (`train/model/action_mask.py`).
- **Measured.** Unmatched actions under random play: 29.6% → 0.2% of agent-steps (the residue is
  an order filled earlier in the same step's shuffle). Rejections at the thin-cash stress config:
  33.9% → 33.2% - size-driven, out of a category mask's reach, and a pointer at S3-1 to S3-3.
- **`action_mask: false`** makes the env emit all ones, same layout, for the unmasked baseline in
  `train.compare`.
- **Tests.** `test_action_mask.py` (16). Suite: **1,095 unit + 156 integration**.

## 54. Pluggable matching, and fair clearing within a step (S3-25)

As asked: fifo stays the default, the allocation rule and the step's clearing are pluggable, and
orders that cross within the same instant can be cleared without the shuffle deciding
([06](06_action_space.md) §8, [16](16_verification_log.md) §16.26).

- **`matching_rule`** on `OrderBook` (keyword-only): `fifo` or `pro_rata`. `allocate` is the one
  place a level is shared out; `process_order_list` executes its answer. Pro-rata floors to whole
  contracts and hands the residue out in time order, so totals are exact.
- **`step_clearing: "batch"`**: `OrderBook.begin_batch` queues the step's new market and limit
  orders and a modify's re-entered quote; `clear_batch` clears them against the resting book at one
  uniform price - volume-maximising, then least imbalance, then nearest the reference, which is a
  candidate - with resting orders first at the margin and the batch rationed under
  `matching_rule`; leftovers rest or lapse as before. `Exchg_Helper.do_actions` runs it and settles
  each trader through `Trader.settle_batch`, which books a same-batch counter party without an
  escrow release (`counter_party['resting']` on the record). The per-action trade lists stay
  aligned with the shuffled actions for the render path.
- **Measured.** Sequential: the first agent in the shuffle fills 58.1% of its fresh orders, the
  last 49.1%, monotonically; 1.58 prices per trading step. Batch: 57.7% to 57.1%, one price, 43
  contracts a step against 51. NAV conserved exactly under all four combinations.
- **Both are env-config keys and `TrainConfig` fields**, for `train.compare --set`.
- **A settlement bug the clip counter found.** The first batch compare showed `obs_clip_fraction`
  0.02–0.03: `cash_on_hold` a few contracts negative, because a resting order filled at a better
  price than its limit released escrow at the trade price while it had posted it at the limit.
  `settle_batch` re-bases the escrow first; NAV conservation alone had not caught it, S4-15's
  counter did.
- **Tests.** `test_matching_regimes.py` (19) at the book, `test_clearing_env.py` (13) through the
  env. Suite: **1,127 unit + 156 integration**.

## 55. Taking a trained policy out of a checkpoint (`train.export`)

[14](14_perspective_ai_engineer.md) §5.9 listed "no inference/serving path" as a production gap.
`evaluate.py` closed half of it — a checkpoint can be *run*. This closes the other half: a
checkpoint's weights can be taken *out*, and the module to take is chosen for you.

- **`python -m gym_continuousDoubleAuction.train.export --checkpoint <iter_n> --out champion.pt`**
  writes a `torch.save` of one module's `state_dict`, plus what makes those tensors mean anything:
  the module id and class, the checkpoint and iteration, the promotion record, and the
  observation/action layout stamp (§47.5). `--list` prints the checkpoint's modules and its
  champion table without exporting; `--module-id` names a module directly.
- **The default is the league's winner.** With no `--module-id` it reads `champion_history` from
  the `league_state.json` the checkpoint already carries and takes the champion with the best
  recorded return — no unpickling, no `Algorithm` restore.
- **And it says that this is a guess.** A champion's `return` is its score relative to the league
  of the iteration it was promoted in, so two champions' returns are not comparable; `--list` says
  so in its own output and points at `train.evaluate --seed`, whose per-module table settles it on
  shared seeds and names a module id to pass back.
- **A foreign layout warns rather than refuses**, unlike `evaluate`. Nothing here drives the env,
  reading old weights is a reasonable thing to want, and the stamp travels in the file either way.
- **No second path resolution.** The module directory inside a checkpoint is resolved by
  `probe.features.load_module`, which already knew where one lives and already had the error that
  names the modules actually present; `_available_modules` became public as `available_modules` for
  the `--list` output rather than being reimplemented.
- **Deliberately not TorchScript or ONNX.** The architecture is rebuilt from the checkpoint's own
  spec, so reloading needs `ray[rllib]` and this package. A frozen graph would be a second
  definition of the network to keep in step with the first, and §5.9 still names it as open.
- **Tests.** `test_export.py` (17) for the choice and the record, integration
  `test_export_checkpoint.py` (7) for a real train → promote → save → export → reload round trip,
  which asserts the exported tensors equal the source policy's rather than a fresh initialisation.
  Suite: **1,144 unit + 163 integration**.
