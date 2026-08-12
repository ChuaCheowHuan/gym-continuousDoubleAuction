# 14. Perspective: AI Engineer

Scope: code quality, scalability, deployment readiness, dependency management, modularity,
observability, production-level considerations.

**Headline:** the `train/` package is modern, well-reasoned and genuinely well tested — the Ray
2.56 migration was done properly, with regression tests for the distributed failure modes. The
`envs/` package is older code carrying visible technical debt: no logging, `sys.exit` as error
handling, dead modules, and a packaging manifest that does not match the imports. Nothing here is
production-deployable as a service, but as a research codebase it is above average.

---

## 5.1 Overall code-quality snapshot

| Signal | Measurement |
|---|---|
| Python LOC | 7,478 across 63 files |
| Test LOC | ~2,430 |
| Unit tests | 90, **all passing** |
| Integration tests | 13 across 3 classes covering local / remote-EnvRunner / remote-Learner |
| CI | GitHub Actions, Python 3.11 + 3.12 matrix, three staged jobs |
| `logging` module usage | **0** — everything is `print()` |
| `print()` calls in `envs/` + `train/` | ~86, incl. **42 in the self-play callback** and 13 in the env |
| `sys.exit()` in library code | **6 live** (all in `orderbook.py`), 2 more commented out |
| Broad `except Exception` in the callback | 2 (one deliberate, one questionable) |
| Type hints | present in `train/`, essentially absent from `envs/` |
| Linter / formatter config | none (no `ruff`, `black`, `flake8`, `pyproject.toml`) |
| Pre-commit hooks | none |

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

**Costs:**

- **No enforced interface.** `State_Helper` reads `self.LOB`, `self.traders`, `self.last_price`,
  `self.min_tick` — none of which it owns or declares. `getattr(self, 'n_hist', 4)` and
  `getattr(self, 'last_price', 100.0)` are defensive workarounds for exactly this.
- **Not independently testable.** You cannot unit-test the reward without a full env;
  `test_reward_logic.py` works around it by instantiating a bare `Reward_Helper()` with a
  `MockTrader`, which happens to work only because `set_reward` touches nothing else.
- **Namespace collisions are silent.** Five mixins sharing one `self` means any attribute name
  reused across them overwrites without warning.
- **Fragile initialisation.** Whether `MultiAgentEnv.__init__` runs at all depends on which mixin
  happens to lack an `__init__`, and a stray kwarg reaching `object.__init__` raises `TypeError`
  — which is how a real bug once surfaced as
  `AttributeError: … has no attribute 'min_tick'`.

A composition refactor (`self.state = StateBuilder(book, cfg)`, `self.reward = RewardFn(cfg)`)
would be mechanical and would make reward/obs variants swappable — which is what a research
codebase most needs.

---

## 5.3 Dependency management

### The declared vs. actual import mismatch

`setup.py:32-41` declares:

```python
install_requires = ["gymnasium==1.2.2", "numpy>=2.5,<3", "pandas>=3.0,<4",
                    "sortedcontainers>=2.4", "tabulate>=0.10"]
```

with the comment *"Kept deliberately narrow: these are what the environment needs to import… so
the env stays usable without [RLlib]."*

That claim does not hold. **[verified]** — the environment package imports three undeclared
packages:

| Import | Location | Declared in `install_requires`? |
|---|---|---|
| `ray.rllib.env.multi_agent_env` | [`continuousDoubleAuction_env.py:6-7`](../gym_continuousDoubleAuction/envs/continuousDoubleAuction_env.py#L6-L7) | **No** — it is in the `[rllib]` extra |
| `sklearn.utils.shuffle` | [`action_helper.py:5`](../gym_continuousDoubleAuction/envs/exchg/action_helper.py#L5) | **No** — `scikit-learn` is in the `[plot]` extra |
| `six.moves.cStringIO` | [`orderbook.py:10`](../gym_continuousDoubleAuction/envs/orderbook/orderbook.py#L10), [`orderlist.py:101`](../gym_continuousDoubleAuction/envs/orderbook/orderlist.py#L101) | **No** — not in `requirements.txt` either |

`pip install gym_continuousDoubleAuction` without the extras produces an `ImportError` on the
first `import`. CI never catches this because it always installs the full `requirements.txt`.

Three of these are trivially removable:

- **`import ray`** on line 6 of the env is entirely unused — only the `MultiAgentEnv` import on
  line 7 is needed. (Even that could be made optional with a lazy import, delivering the "env
  usable without RLlib" property the comment promises.)
- **`six`** is a Python-2 compatibility shim. `from io import StringIO` is the stdlib equivalent;
  `six` is only present transitively via `python-dateutil` and could vanish on any dependency
  bump.
- **`sklearn.utils.shuffle`** pulls scikit-learn (~30 MB plus SciPy) into every EnvRunner process
  to shuffle a list of ≤8 dicts. `random.shuffle` or `np.random.permutation` is a drop-in
  replacement — and would also let the shuffle be seeded from the env's RNG, fixing the
  reproducibility gap in [12](12_perspective_rl_researcher.md) §5.5.

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

This is the weakest engineering area. Full audit in
[11_logging_and_observability.md](11_logging_and_observability.md); the summary:

- **No logging framework at all.** **[verified]** zero `import logging` in the repository.
- **~86 `print()` calls** in `envs/` + `train/`, 42 of them in `SelfPlayCallback` — including a
  3+-line banner per episode start listing the full policy map, five `DEBUG:`-prefixed lines and
  a full NAV table per episode end.
- With `num_env_runners > 0`, **every remote worker prints this independently**, with no level
  filtering, no worker attribution, and no way to turn it off short of editing the source.
- `env.render()` defaults to **`is_render=True`** on the env, so any direct instantiation dumps
  the book, tape and every account per step through pandas.
- **Only three custom values reach TensorBoard** (`league_size`, `league_mean_return`,
  `league_std_return`). Everything a practitioner would actually watch — NAV distribution,
  drawdown, trade counts, maker/taker ratio, champion promotions, `vf_explained_var` — is printed
  to stdout and then lost.
- The **NAV conservation check** is a good idea implemented as a `print("… FAILED …")`. A
  conservation violation is a hard ledger-invariant break; it should raise or emit a counter
  metric.

---

## 5.5 Error handling

**`sys.exit()` in library code** — six live occurrences, all in `orderbook.py`:

```python
if quote['quantity'] <= 0:
    sys.exit('process_order() given order of quantity <= 0')
```

`sys.exit` raises `SystemExit`, which derives from `BaseException`, not `Exception`. Inside a Ray
EnvRunner actor this will not be caught by ordinary handlers and will kill the worker; RLlib will
mark it unhealthy and the training run degrades (or hangs) rather than failing with a usable
traceback. These should all be `raise ValueError(...)`.

Currently unreachable in practice — decoded size is `rint(abs(N(...))) + min_size ≥ 1` — but it
is one action-space change away from being reachable.

**The broad `except Exception` in champion creation** is *deliberate and defensible*: it rolls
back the pool entry so matchmaking can never select a half-created module, and prints a
traceback. The commit history shows this exact handler once masked the
`learner_group._learner is None` bug for an entire training run — swallowing the error and
leaving the league permanently empty while printing one line per iteration. The rollback is
right; the response to a *repeated* failure should escalate (raise after N consecutive failures,
or emit a metric) rather than continuing silently for hours.

**Silent no-ops in the env** are a third category: rejected orders and unmatched modify/cancel
requests return `([], [])` with nothing recorded. See
[12](12_perspective_rl_researcher.md) §5.6.

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
printed warning — so the notebook's `0.75` default does not hard-fail on a laptop. Good defensive
default.

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
| **Per-episode pickles** | `episode_data_dir` writes one file per episode containing every step's obs (168 floats), action, reward and info. At `max_step=4096` that is ~4,096 dicts × 8 agents held in memory then serialised, per episode, per worker. It is configurable to `None` (`--no-episode-data`) and the docstring warns about it, but the default in both `TrainConfig` and the notebook is **on**. |
| **`_process_counter_party` linear scan** | [`trader.py:290-305`](../gym_continuousDoubleAuction/envs/agent/trader.py#L290-L305) scans all agents per fill → O(fills × agents). Fine at 8 agents; a dict lookup is the obvious fix. |
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

**Gaps**

| Gap | Risk |
|---|---|
| **No learning-signal assertion** | Nothing checks `vf_explained_var`, `vf_loss` saturation, or that returns improve. This is exactly how the frozen critic went unnoticed. |
| **No coverage measurement** | No `pytest-cov`, no threshold. |
| **`test_accounting.py::test_insufficient_funds` is an empty `pass`** with a 15-line comment debating what the behaviour should be — a TODO shipped as a test. |
| **`test_probabilistic_mapping.py` is a bare function with asserts**, not a `unittest.TestCase`; it collects under pytest but does not run under the notebook's `%run` path the same way. |
| **No property-based tests** | The order book is an ideal Hypothesis target: "tree volume == Σ level volumes", "no crossed book", "Σ NAV == Σ initial cash" hold for *any* order sequence. |
| **No performance regression test** | Nothing catches a 10× slowdown in the matching engine. |

---

## 5.8 Dead and vestigial code

| Item | Status |
|---|---|
| `train/storage/store_handler.py` (90 LOC) | Ray detached actor `g_store`, **never created anywhere** **[verified]** |
| `train/logger/log_handler.py` (~89 LOC) | `ray.util.get_actor("g_store")` → would raise at call time |
| `train/plotter/plot_handler.py` (90 LOC) | same dependency on `g_store` |
| `train/helper/helper.py` | `ord_imb` / `mid_price` utilities, imported by nothing (only a commented-out import) **[verified]** |
| `envs/agent/random_agent.py` | `select_random_action` returns the **old 5-tuple** action format; superseded by `RandomRLModule`; nothing calls it, but `Trader` still inherits from `Random_agent` **[verified]** |
| `State_Helper.state_diff` | never called **[verified]** |
| `Action_Helper._set_side` / `_set_type` / `_higher` / `_lower` | never called (superseded by the category mapping) |
| `Action_Helper.max_price` | passed into `_set_price` and never used in its body |
| `OrderBook.__str__0`, `Order.__str__0`, `OrderList.to_str` | superseded |
| `OrderBook.get_volume_at_price` | commented out |
| `envs/orderbook/test/example.py`, `genOrders.py` (353 LOC) | standalone scripts, not collected by pytest |
| `analyze_unused.py` | a dead-code detector, itself unreferenced (except from a commented-out notebook cell) |
| ~200 LOC of commented-out code | e.g. `continuousDoubleAuction_env.py:100-133, 178-207`, `orderbook.py:260-318`, `action_helper.py:23-36` |
| `CODEOWNER` **and** `CODEOWNERS` | duplicate files at the repo root |

Roughly **270 LOC of unreachable telemetry** in `train/` alone, plus the rest. The most
misleading part is that the three `g_store` modules look like a working telemetry pipeline; they
are a broken one. If the intent is to revive them, they need a
`storage.options(name="g_store", lifetime="detached").remote(n)` call somewhere; otherwise they
should be deleted, with `helper.py`'s order-imbalance functions salvaged into the observation
(see [13](13_perspective_financial_trader.md) §6).

---

## 5.9 Deployment readiness

### What exists

- **A GPU training image** — `docker/ml/dockerfile_ray_torch`, CUDA 12.8 runtime matched to cu128
  torch wheels, with a comment explaining the CUDA/wheel-index coupling and a `--shm-size=2g`
  note about Ray's object store using `/dev/shm`. Both are real operational lessons.
- **Checkpointing** — `algo.save()` every `chkpt_freq` iterations plus a final save, with
  `--restore` and an Adam-`betas` deserialisation workaround
  ([`train.py:230-242`](../gym_continuousDoubleAuction/train/train.py#L230-L242)).
- **A clean CLI** — `python -m gym_continuousDoubleAuction.train.train --help`.
- **`.gitignore` covers the artefact paths**, including a comment explaining that `episode_data`
  is written relative to the *working directory* so it can land at the repo root. No build
  artefacts are tracked in git.

### What is missing for production

| Gap | Impact |
|---|---|
| **`build_algo` returns a detached callback on the restore path** | See §5.9.1 — a latent bug, narrow but real. |
| **The Docker image `pip install`s a hardcoded dependency list** | Duplicates `requirements.txt` rather than `COPY`ing it. Two places to update; already at risk of drift. |
| **No inference/serving path** | Nothing loads a checkpoint and runs a policy. There is no `evaluate.py`, no Ray Serve deployment, no exported TorchScript/ONNX. |
| **No config validation** | `TrainConfig` accepts `num_trained_agents > num_agents` (caught later, in `build_multi_rl_module_spec`), negative `max_step`, etc. |
| **No experiment tracking** | No MLflow / W&B; results are TensorBoard + stdout. |
| **No Ray Tune integration** | `train()` is a hand-rolled loop; using `tune.Tuner` would bring scheduling, fault tolerance and sweeps essentially for free. |
| **No env versioning** | Changing the observation layout silently invalidates old checkpoints. `SNAPSHOT_DIM` is a good constant but is not recorded in the checkpoint. |
| **No resource requests / limits** | Not documented for a cluster deployment. |

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

The defect is narrower: `build_algo`
([`train.py:215-227`](../gym_continuousDoubleAuction/train/train.py#L215-L227)) calls
`build_config(cfg)` unconditionally, then on the restore branch discards the freshly-built `ppo`
config and returns the **fresh, empty** `callback_instance` alongside the restored algorithm:

```python
ppo, callback_instance = build_config(cfg)          # builds a NEW callback
if cfg.is_restore and os.path.exists(...):
    algo = Algorithm.from_checkpoint(...)           # uses the RESTORED callback
else:
    algo = ppo.build_algo()
return algo, callback_instance                      # ...but returns the new one
```

`train()` ignores the returned callback, so training is unaffected. But any caller that *uses* it
— the notebook, or the integration tests' `cls.callback._create_champion_snapshot_from_policy(
cls.algo, ...)` pattern — would be driving a detached object whose `available_modules` disagrees
with the mapping function the algorithm is actually using. Champions promoted through the
detached instance would be added as modules but never selected.

**Fix:** on the restore branch, recover the algorithm's live callback (or skip `build_config`
entirely and read it back off the restored config) rather than returning the throwaway one.

---

## 5.10 Security and safety

Low risk overall (a self-contained simulator), but two notes:

1. **`pickle` for episode data** and the `visualize/inspect_latest_episode*.py` loaders. Pickle
   executes arbitrary code on load. Fine for self-produced files; unsafe if episode data is ever
   shared between users. Two `.pkl` fixtures are committed under `episode_data/`. Prefer
   `npz` / `parquet` / `jsonl`.
2. **`sys.exit` in a worker process** (§5.5) — a denial-of-availability path for a long training
   run, not a security issue as such.

---

## 5.11 Prioritised engineering agenda

| # | Change | Effort | Why |
|---|---|---|---|
| 1 | Return the algorithm's live callback from `build_algo` on the restore path (§5.9.1) | S | Callers currently get a detached, empty league object |
| 2 | Replace all `print()` with `logging`; route callback diagnostics through `metrics_logger` | M | Multi-worker runs are currently unobservable |
| 3 | Fix `install_requires` (add `ray` / `scikit-learn` / `six`, or remove those imports) | S | The package does not install correctly as declared |
| 4 | Drop `six` → stdlib `io.StringIO`; drop `sklearn.utils.shuffle` → `random.shuffle` (seeded); drop the unused `import ray` | S | Removes a Py2 shim and a ~30 MB dependency; fixes reproducibility |
| 5 | `sys.exit` → `raise ValueError` in `orderbook.py` | S | Prevents worker kills |
| 6 | Raise (or emit a metric) on a NAV conservation violation instead of printing `FAILED` | S | A corrupt ledger should not be a log line |
| 7 | Add `vf_explained_var` / learning-signal assertions to CI | S | Would have caught the frozen critic |
| 8 | Delete the `g_store` trio + other dead code | S | Removes a misleading "working" telemetry path |
| 9 | Add `ruff` + `black` + pre-commit; add `pytest-cov` with a threshold | S | Baseline hygiene |
| 10 | Make the Docker image `COPY requirements.txt` instead of duplicating it | S | Removes drift |
| 11 | Add an `evaluate.py` that loads a checkpoint and runs deterministic episodes | M | There is currently no way to *use* a trained policy |
| 12 | Move `TrainConfig` under `tune.Tuner` | M | Free scheduling, fault tolerance, sweeps |
| 13 | Property-based tests (Hypothesis) for book invariants | M | The invariants are already known and stated |
| 14 | Record `SNAPSHOT_DIM` / an env version in the checkpoint | S | Turns a silent checkpoint mismatch into a clear error |
| 15 | Refactor mixins → composition | L | Makes reward/obs variants swappable |
