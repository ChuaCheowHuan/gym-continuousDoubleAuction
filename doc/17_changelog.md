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

## 18. Logging: concurrency, run isolation, and the traceback that was never logged

A review of the logging *functionality* rather than its coverage — what happens when more than one
thread or process writes at once, and what a run leaves behind when it dies. Six changes, in
descending order of how much they can cost.

See [11_logging_and_observability.md](11_logging_and_observability.md) §1.10–§1.14.

### 18.1 Two runs shared one `run.log` and one `progress.jsonl`

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

### 18.2 A run that died did not say why in its log

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

### 18.3 The log level and directory did not reach a pre-existing cluster

`configure()` exports `$CDA_LOG_LEVEL` and `$CDA_LOG_DIR`, which workers inherit because the raylet
inherits the driver's environment. That holds only when this process *starts* the cluster. Against
`ray.init(address=...)` the raylet was started long before, so neither variable arrives: workers
come up at the config default and write no run log — and since the episode callbacks run on the
runners, the NAV tables and the conservation ERROR would reach no file anywhere. They are now also
passed as a `runtime_env`, which Ray applies to the workers it starts for the job regardless of who
started the cluster.

### 18.4 A pid is not a unique file name

`run.<pid>.log` is unique per *node*. On a multi-node run with `log_base_dir` on a shared mount —
NFS, or the Drive mount Colab uses — two workers on different nodes can hold the same pid and open
the same file, reintroducing the rotation race through the naming meant to prevent it. The name now
carries Ray's cluster-unique worker id behind the pid, which is kept because it is what the `pid=`
field of every line matches. Ray is read from `sys.modules` rather than imported: `apply_env_vars()`
must run before ray is first imported, and `configure()` runs before that.

### 18.5 Configuration was racy; nothing tested concurrency at all

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
into the next task, which is what §18.6 depends on. One training loop per process makes the
iteration a property of the process, so it is a module global.

### 18.6 `iter=` now reaches the env runners

§1.9 recorded the worker's `iter=-` as needing "a change to what RLlib hands the callbacks". It did
not: the driver knows the number and `foreach_env_runner` already reaches every runner, so it only
had to be sent, once per iteration, before sampling starts. Best-effort — a restarting runner costs
`iter=-` on its lines, never the run. This is what makes a worker's NAV table joinable to its
`progress.jsonl` row under `num_env_runners > 0`, which is the configuration where those lines are
emitted nowhere else.

### 18.7 Two smaller corrections

**Output went to stderr, not stdout.** `logging.StreamHandler()` defaults to stderr, while §1.3,
§1.9 and `tunable_constants.json` all described stdout — so `train ... > run.txt` captured nothing.
Now explicitly `sys.stdout`.

**`warnings.warn` went nowhere.** A `DeprecationWarning` from Ray or gymnasium is the earliest
signal that an upgrade is about to break this repository, and it was going to stderr unrecorded and
unrotated. `logging.captureWarnings(True)` alone would not have been enough — it logs to
`py.warnings`, outside this package's namespace, which inherits none of its handlers and falls
through to stderr anyway; the handlers are mirrored onto it.
