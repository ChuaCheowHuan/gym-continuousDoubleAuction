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
fixed; the table now also lists §18 and §19.

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
