# 14. Perspective: AI Engineer

Scope: code quality, scalability, deployment readiness, dependency management, modularity,
observability, production-level considerations.

**Headline:** the `train/` package is modern, well-reasoned and genuinely well tested — the Ray
2.56 migration was done properly, with regression tests for the distributed failure modes. The
`envs/` package is older code, but the debt this audit first found there (no logging, `sys.exit`
as error handling, dead modules, a packaging manifest that did not match the imports) is paid
down; what that audit measured is in [29](29_fixed_issues.md#14-51--the-original-code-quality-snapshot).
Nothing here is production-deployable as a service, but as a research codebase it is above
average.

---

## 5.1 Overall code-quality snapshot

| Signal | Measurement |
|---|---|
| Python code | 54,863 lines across 207 Python files |
| Tests | 2,163 unit and 148 integration, all passing |
| CI | GitHub Actions on Python 3.12: a `test` job (unit → random smoke run → RLlib integration) and a `packaging` job that installs the built wheel into a clean venv |
| Logging | `logging_setup`: levelled, worker-attributed, a rotating run log; a test fails the build on a bare `print` in `envs/` or `train/` |
| `sys.exit()` in library code | **0** — the matching engine raises `ValueError` |
| Lint, format, types | pyflakes (`test_lint.py`, zero findings), `ruff format --check` and `mypy` over `envs/` at zero errors (`test_types.py`) |
| Coverage | `pytest --cov` fails below the floor in `pyproject.toml`; a local gate, not a CI one |
| Pre-commit hooks | none |

The snapshot this section first recorded (7,478 lines, 90 unit tests, ~86 `print()` calls, no
logging module) is in [29](29_fixed_issues.md#14-51--the-original-code-quality-snapshot).

The quality gradient across the repository is steep. `train/train.py`, `policy_handler.py` and
`model_handler.py` are written to a high standard — module docstrings that explain *why*,
dataclass configuration, explicit migration notes naming the trap each rewrite avoids.
`envs/orderbook/` and `envs/account/` read like 2019-era code with patches applied on top.

---

## 5.2 Architecture: mixins vs composition

The environment is built by inheriting five helper classes plus RLlib's `MultiAgentEnv` — see
[02_architecture.md](02_architecture.md) §2.4 for the chain.

**Works:** the cooperative `super().__init__(**kwargs)` chain is correct, and splitting obs /
action / reward / done / info into files makes each concern easy to find.

**Composition, where it was cheap.** Reward, done, info and liquidation are composed objects
(`RewardModel`, `EpisodeStatus`, `InfoBuilder`, `LiquidationEngine`), each taking its inputs
explicitly, so each can be unit-tested without a full env. The state/action pair still shares
one `self`: it shares the observation layout and the book snapshot on every call, and what it
shares is declared in `SharedState` and checked by `mypy` ([02_architecture.md](02_architecture.md)
§2.4). The costs of the six-mixin design (no enforced interface, silent namespace collisions,
fragile initialisation) are in [29](29_fixed_issues.md#14-52--the-costs-of-the-six-mixin-environment).

Finishing it for the state/action pair (`self.state = StateBuilder(book, cfg)`) would make
observation variants swappable the way reward variants now are — which is what a research
codebase most needs. Recorded as open in [15](15_findings_and_recommendations.md).

---

## 5.3 Dependency management

`install_requires` matches what the package imports: `ray[rllib]` (the env's base class is
RLlib's `MultiAgentEnv`) and `six` (imported by `envs/orderbook/`) are declared, `scikit-learn` is
gone because nothing imports it, and the `packaging` CI job installs the built wheel into a clean
venv and imports it, so a mismatch fails CI. The manifest used to declare five packages while the
env imported three more: [S3-6](29_fixed_issues.md#s3-6--install_requires-does-not-match-the-imports-verified-fixed), with the config tree missing from the wheel in
[S3-18](29_fixed_issues.md#s3-18--the-config-tree-was-not-in-the-built-distribution-verified-fixed).

### What is done well

- **A lock file exists.** `requirements-lock.txt` is a full `pip freeze` with a header recording
  the date and verification method, plus an explicit note on how to pick the CPU vs CUDA torch
  wheel.
- **Pins are explained.** `requirements.txt:13-15` documents *why* `gymnasium` must not be bumped
  independently of Ray. That kind of comment prevents a whole class of "helpful upgrade"
  incidents.
- **torch is deliberately unpinned to a local build**, so the same file works on a CPU dev box
  and a GPU trainer — and CI installs the CPU wheel explicitly first to stop the CUDA wheel being
  pulled transitively.
- **Extras are sensibly partitioned** (`[rllib]`, `[plot]`, `[dev]`), and packaging itself works:
  `find_packages()`, real `install_requires`, no bogus entry point, and the `__init__.py` files
  that once forced tests to run under `PYTHONPATH`.

---

## 5.4 Observability

Full audit in [11_logging_and_observability.md](11_logging_and_observability.md); the summary:

- **A logging framework** (`logging_setup`): levelled output, worker attribution, a rotating run
  log per process, and no `print()` left in `envs/` or `train/`.
- **The NAV conservation check raises** at the driver and emits `nav_conservation_error`.
- **Training metrics reach TensorBoard and `progress.jsonl`:** league state, desk metrics,
  `vf_explained_var`, per-module performance.
- `env.render()` is off by default (`is_render: false`).

This was the weakest engineering area when first audited: no `import logging` anywhere, ~86
`print()` calls, and three custom values reaching TensorBoard
([29](29_fixed_issues.md#14-54--observability-as-first-audited), [S2-8](29_fixed_issues.md#s2-8--no-logging-framework-the-callback-prints-42-diagnostics-per-episode--fixed)).

---

## 5.5 Error handling

**Malformed input to the matching engine raises `ValueError`** naming the method and the refused
value; `test_orderbook_new.py::TestMalformedInputRaisesInsteadOfExiting` asserts that nothing in
the engine raises `SystemExit`, which would kill a Ray worker instead of surfacing a traceback. It
used to `sys.exit`: [S3-7](29_fixed_issues.md#s3-7--sysexit-used-for-error-handling-in-the-matching-engine-fixed).

**The broad `except Exception` in champion creation** is *deliberate and defensible*: it rolls
back the pool entry so matchmaking can never select a half-created module, and prints a
traceback. The commit history shows this exact handler once masked the
`learner_group._learner is None` bug for an entire training run — swallowing the error and
leaving the league permanently empty while printing one line per iteration. The rollback is
right; the response to a *repeated* failure should escalate (raise after N consecutive failures,
or emit a metric) rather than continuing silently for hours.

**No-ops in the env** are a third category: rejected orders and unmatched modify/cancel requests
change nothing in the book, but are counted (`num_rejected_step`, `num_unmatched_step`) and
reported as metrics. See [12](12_perspective_rl_researcher.md) §5.6.

---

## 5.6 Scalability

### Rollout and learner parallelism

Both axes are exposed and, importantly, **tested**:

| Axis | Config | Test coverage |
|---|---|---|
| Rollout | `num_env_runners`, `num_envs_per_env_runner`, `num_cpus_per_env_runner` | `TestLeagueWiringRemoteEnvRunners` |
| Learner | `num_learners`, `num_gpus_per_learner` | `TestLeagueWiringRemoteLearner` |

Both remote test classes **guard their own premise** — `test_sampling_actually_happens_remotely`
asserts `num_healthy_remote_workers() == 1`, and `test_learner_group_is_actually_remote` asserts
`not learner_group.is_local`. Without those, a silently-degraded remote setup would make every
other assertion pass vacuously over an empty list. That is a level of test discipline you rarely
see.

`resolved_gpus_per_learner()` forces the GPU fraction to 0 when CUDA is unavailable, with a
printed warning — so a GPU config does not hard-fail on a laptop. Good defensive default, and
`runtime.detect_hardware()` now applies the same rule one layer up: `USE_GPU=True` on a machine
without CUDA selects the cpu parameter set and says so, rather than handing RLlib a device that is
not there.

Full mechanics in [09_distributed_training.md](09_distributed_training.md).

### Distributed-state correctness

The concurrency reasoning in the callback is the strongest code in the repo:

- **Per-episode step storage** is a `defaultdict(list)` keyed by `episode.id_`. The comment
  documents the previous bug precisely: a single shared list plus a single `self.ID` interleaved
  concurrent episodes under `num_envs_per_env_runner > 1`, and `on_episode_end` setting it to
  `None` produced an `AttributeError` on the next `on_episode_step`.
- **Remote callback copies are stale by design.** `on_episode_start` reads the mapping from
  `env_runner.config.policy_mapping_fn` rather than from `self`, because each remote worker holds
  a pickled copy of the callback frozen at construction.
- **Pool-before-`add_module` ordering** is load-bearing and documented.
- **`crc32` instead of `hash()`** for cross-process determinism.
- **The `WEIGHTS_SEQ_NO` force-push** with a five-line explanation of why `sync_weights()`
  silently drops the update.

### Throughput bottlenecks

| Bottleneck | Detail |
|---|---|
| **Episode record** | Parquet written by a background thread per process, bounded by `episode_sample_every` (one episode in 10) and `episode_max_bytes` (2 GiB per writer); `--no-episode-data` switches it off, buffering included. A writer failure is a warning, so a full disk cannot kill an env runner ([11](11_logging_and_observability.md) §1.1). It used to be a synchronous per-step pickle ([S4-9](29_fixed_issues.md#s4--minor)). |
| **Counter-party lookup** | O(1) in the env (trader IDs index the roster), after measuring ([S4-11](29_fixed_issues.md#s4--minor)). |
| **`set_agg_LOB` called twice per step** | Once pre-action (display only) and once post-action. The pre-action call is pure overhead when `is_render=False`. |
| **`Decimal` arithmetic** | Correct but roughly an order of magnitude slower than float. Acceptable for a ledger; it is in the hot matching path. |
| **`env.render()` string building** | Builds pandas DataFrames per step when enabled. Must stay off in training. |

None of these are structural — the design scales horizontally through Ray, which is what matters.

---

## 5.7 Testing

Full inventory in [10_testing.md](10_testing.md). Engineering-relevant summary:

**Strengths**

- **The integration suite targets silent misconfiguration**, not crashes. Its module docstring
  names the three real bugs it exists to prevent, and each has a dedicated test.
- **The remote probe is written with real care.** The nested closure in
  `TestLeagueWiringRemoteEnvRunners.setUpClass` carries a comment explaining both pickling traps
  — closing over `cls`, and module-level helpers being pickled by reference into a worker that
  cannot import `test_league_wiring`.
- **Premise guards** on both remote test classes.
- **CI runs three distinct stages** — unit tests, a random-agent smoke run, then the RLlib
  integration tests — so an env-level break and an RLlib-level break are distinguishable from the
  job name alone.

**Gaps.** The gaps this section first listed are closed: a live `vf_explained_var` assertion
(S1-1), a coverage floor (S4-6), a real `test_insufficient_funds` (S4-5), Hypothesis invariant
tests for the book (S4-13), and `test_speed_regression.py` against a matching-engine slowdown.
The original table is in [29](29_fixed_issues.md#14-57--the-testing-gaps-as-first-audited). What
remains is that the coverage floor is a local gate rather than a CI one
([10](10_testing.md) §7).

---

## 5.8 Dead and vestigial code

All the dead and vestigial code this section listed is deleted: the ~270 LOC `g_store`
telemetry trio, `train/helper/helper.py`, `envs/agent/random_agent.py`, the unused
`State_Helper` / `Action_Helper` methods, the dead order-book methods, the 353-LOC scratch
scripts in `envs/orderbook/test/`, ~200 LOC of commented-out code, and the duplicate `CODEOWNER`
file ([S4-1 to S4-4 and S4-18](29_fixed_issues.md#s4--minor)). The order-imbalance idea in the old `helper.py` reached
the observation as `signed_volume` ([13](13_perspective_financial_trader.md) §6).

---

## 5.9 Deployment readiness

### What exists

- **A GPU training image** — `docker/ml/dockerfile_ray_torch`, CUDA 12.8 runtime matched to cu128
  torch wheels, with a comment explaining the CUDA/wheel-index coupling and a `--shm-size=2g`
  note about Ray's object store using `/dev/shm`. Both are real operational lessons.
- **Checkpointing** — `algo.save()` every `chkpt_freq` iterations plus a final save, with
  `--restore` and an Adam-`betas` deserialisation workaround
  ([`train.py`](../gym_continuousDoubleAuction/train/train.py)).
- **A clean CLI** — `python -m gym_continuousDoubleAuction.train.train --help`.
- **`.gitignore` covers the artefact paths**, including a comment explaining that `episode_data`
  is written relative to the *working directory* so it can land at the repo root. No build
  artefacts are tracked in git.

### What is missing for production

| Gap | Impact |
|---|---|
| **No serving path** | `train/evaluate.py` rolls episodes with a checkpoint's policies and `train/export.py` writes one module's weights to a torch file (docs/26 §26.9.2). There is no Ray Serve deployment and no TorchScript/ONNX: the exported file still needs `ray[rllib]` and this package to rebuild the architecture. |
| **Partial config validation** | `TrainConfig` refuses invalid values at construction (γ, λ, entropy, the batch split across learners and others), but `num_trained_agents > num_agents` is still caught later, in `build_multi_rl_module_spec`. |
| **No experiment tracking** | No MLflow / W&B; results are TensorBoard, `progress.jsonl` and the run log. |
| **No Ray Tune integration** | `train()` is a hand-rolled loop; using `tune.Tuner` would bring scheduling, fault tolerance and sweeps essentially for free. |
| **No resource requests / limits** | Not documented for a cluster deployment beyond [00](00_getting_started.md) §0.2. |

The observation and action layout versions are recorded in every checkpoint, so a layout change
is refused by name at restore rather than by tensor shape. That, the Docker image installing from
`requirements.txt`, and `build_algo` returning the live callback are fixed gaps
([S4-19, S4-8](29_fixed_issues.md#s4--minor), [S3-8](29_fixed_issues.md#s3-8--build_algo-returns-a-detached-callback-on-the-restore-path-fixed)).

### 5.9.1 Checkpoint/restore: what actually happens

This was worth testing rather than assuming, because the league's state (`champion_history`,
`available_modules`) lives on a plain Python object held by the callback, not in any
RLlib-managed structure.

**[verified]** — save a run with two champions, then restore it:

```
BEFORE save    -> champion_history: ['champion_1', 'champion_2']
                  available_modules: [policy_0..policy_3, champion_1, champion_2]

AFTER restore  -> modules on env_runner:  [champion_1, champion_2, policy_0..policy_3]  ✅
               -> algo's own callback:    champions ['champion_1', 'champion_2']        ✅
               -> mapping fn draws:       {'policy_3', 'champion_1'}                    ✅
               -> callback returned by build_algo(): champion_history: []               ❌
                  available_modules: [policy_0, policy_1, policy_2, policy_3]
```

So **league state does survive a checkpoint round-trip** — `.callbacks(lambda:
callback_instance)` closes over the instance, RLlib cloudpickles it into the checkpoint, and the
restored `Algorithm` gets a callback with its history intact. That is better than the design
suggests, and worth knowing.

`build_algo` returns that instance on the restore path, `algo_callback(algo)`, and `None` with
a warning if the restored algorithm has no `SelfPlayCallback`: a caller that inspects a detached
league would get a wrong answer silently, where an attribute error on `None` does not. Checkpoints
are `chkpt/iter_N/`, staged and renamed with the newest `chkpt_keep` retained; a structural config
divergence on restore raises; `num_iters` is a target iteration; and `league_state.json` sits
beside each checkpoint. The probe's last line above is the defect it found, that `build_algo`
returned a fresh, empty callback, fixed with four adjacent checkpoint defects in [S3-8](29_fixed_issues.md#s3-8--build_algo-returns-a-detached-callback-on-the-restore-path-fixed).

The remaining gap is structural rather than a bug: `train()` is still a hand-rolled loop, so this
is a reimplementation of retention and fault tolerance that `tune.Tuner` would provide (§5.9).

---

## 5.10 Security and safety

Low risk overall (a self-contained simulator), but two notes:

1. **Episode data is Parquet**, read by `ray.data.read_parquet`, pandas or DuckDB without this
   package installed, so there is no arbitrary-code-execution-on-load surface. It used to be
   pickle ([S4-9](29_fixed_issues.md#s4--minor)).
2. **Nothing in the engine can end an env-runner process**: malformed input raises `ValueError`
   (§5.5).

---

## 5.11 Prioritised engineering agenda

Twelve of the fifteen items on the agenda this document first set are done; the table, with what
closed each, is in [29](29_fixed_issues.md#14-511--the-engineering-agenda-as-first-set). What is
left (`pre-commit` and the coverage gate, `tune.Tuner`, the state/action composition refactor of
§5.2) is in [15](15_findings_and_recommendations.md#open-from-the-perspective-reviews).
