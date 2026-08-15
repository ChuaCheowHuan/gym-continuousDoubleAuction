# 18. Configuration

Every value in the project lives in `config/`. No module holds a literal copy of one.

The `config/` folder at the repository root holds five JSON files, **all five of which are real
inputs**. Python code declares the *schema* — what each knob is called, what type it has, what it
does — and reads the *value* from these files through
[`config_loader.py`](../gym_continuousDoubleAuction/config_loader.py). There is no
`.get(key, some_default)` anywhere in the codebase, because a default written in Python is exactly
the second copy this arrangement exists to remove.

JSON has no comment syntax, so each file (and each group inside it) carries a `_source` key naming
the module that reads it, plus a `_description` and often a `_note`. The loader strips any key
beginning with `_`, at every level.

---

## 1. The five files

| File | Holds | Read by |
|---|---|---|
| [`config/train_config.json`](../config/train_config.json) | Every `TrainConfig` value, **including the env keys** | `TrainConfig`, `default_model_config`, `SelfPlayCallback` |
| [`config/env_defaults.json`](../config/env_defaults.json) | Fallbacks for an env built without a full config dict | `continuousDoubleAuctionEnv` and the env mixins |
| [`config/tunable_constants.json`](../config/tunable_constants.json) | Structural constants: space layout, ID prefixes, logging setup, path defaults | `state_helper`, `action_helper`, `policy_handler`, `logging_setup`, `visualize/` |
| [`config/cli_defaults.json`](../config/cli_defaults.json) | Flag defaults with no other config home | `CDA_env_rand` |
| [`config/runtime_profiles.json`](../config/runtime_profiles.json) | *Where* a run executes: the `gpu` / `cpu` hardware sets and per-platform paths | `train/runtime.py`, `CDA_NSP.ipynb` |

The split between the first file and the last is the one worth holding on to: `train_config.json`
is **what the run does** and is identical on every machine; `runtime_profiles.json` is **what the
machine is** and changes with it. Moving a run between hardware sets changes wall-clock time and
output paths, not the trained policy. See [§8](#8-runtime-profiles).

### 1.1 The loader

```python
from gym_continuousDoubleAuction.config_loader import constant, env_default, group, value

k_rows   = constant("observation_layout", "k_rows")     # tunable_constants.json
init_cash = env_default("init_cash")                    # env_defaults.json
ppo      = group("train_config.json", "ppo")
```

Three rules it enforces:

- **A missing key raises**, naming the file, the group, and the keys that *are* present. A key
  absent from the JSON is a configuration bug, not an invitation to fall back.
- **`_`-prefixed keys are documentation** and are stripped recursively.
- **Files are read once** and cached per directory. `reload()` clears the cache.

`$CDA_CONFIG_DIR` points the loader at a different config tree. That is how the tests in
[`test_config_sources.py`](../gym_continuousDoubleAuction/test/test_config_sources.py) prove there
are no literals left: they copy `config/`, change a value, and assert the change comes out the far
end of the env or of `TrainConfig`. A literal left behind in Python would keep the old value and
fail.

### 1.2 Derived values are not stored

`snapshot_dim` is `book_rows × k_rows + extra_dim`; `train_batch_size` is
`max_step × num_episodes_per_iter`; `limit_max_size` is `mkt_max_size × limit_size_multiple`. None
of these appear in any file. Writing a derived value down creates a second copy that can disagree
with the first — the same failure the files exist to prevent, one level up.

---

## 2. Running it

```bash
python -m gym_continuousDoubleAuction.train.train --iters 4
python -m gym_continuousDoubleAuction.train.train --config sweeps/wide_book.json
```

```python
cfg = TrainConfig()                      # values from config/train_config.json
env = continuousDoubleAuctionEnv(cfg.env_config)
```

Precedence is **`config/train_config.json` → `--config <other file>` → explicit flags**.

`train_config.json` is not something you opt into with a flag; it *is* the default. `TrainConfig()`
with no arguments reads it, so editing the file changes what a run does. `--config` is for running
against a *different* file — a sweep variant, or a config saved beside a past run — and keys that
file omits fall back to the checked-in one.

Every flag declares `argparse.SUPPRESS` as its default, so an unset flag is absent from the
namespace rather than carrying a value. That is what makes the precedence work, and it is also why
no flag has a default of its own: an argparse default would silently overwrite the config file for
any flag you did not pass.

Unknown keys raise rather than being ignored — a misspelled or renamed key would otherwise have no
symptom at all.

### 2.1 The one name change across the env boundary

The `environment` group of `train_config.json` is what `TrainConfig.env_config` forwards to the
env, so the env keys and the run settings live in one file. Two things to know:

- **One key changes name.** The field is `num_agents`; the env receives `num_of_agents`. Writing
  `num_of_agents` in `train_config.json` is rejected.
- **`num_trained_agents` sits in the `environment` group but is not forwarded** — it configures
  the policy/module wiring, not the env.

### 2.2 `env_defaults.json` and why it is separate

A training run supplies every env key from `train_config.json`, so it never reaches a fallback. A
bare `continuousDoubleAuctionEnv({})` — a test fixture, a notebook, an `env_config` you build by
hand — falls back to `env_defaults.json`.

Those standalone values deliberately differ from the training ones: `num_of_agents=5`,
`max_step=64`, `init_cash=0`, `is_render=true`. A bare env is small, cheap and prints what it is
doing; a training env is large and silent. Keeping them in a separate file is what lets both be
explicit instead of one being a literal buried in `__init__`.

---

## 3. Environment config

The `environment` group of `train_config.json`, forwarded as an `env_config` dict to
`continuousDoubleAuctionEnv` by `TrainConfig.env_config`. See
[02_architecture.md](02_architecture.md) §2.6 for the table of the original seven keys and their
`TrainConfig` counterparts.

### 3.1 Order sizing

| Key | Value | Meaning |
|---|---|---|
| `min_size` | 1 | Smallest order size. Also the offset added to every sampled size, since 0 is not a valid order |
| `mkt_max_size` | 100 | Upper bound on market order size |
| `limit_size_multiple` | 10 | Limit orders may be this many times larger than market orders |

`limit_max_size` and the two `*_size_mean_mul` values are **derived**, not configured.
`limit_size_multiple` was previously the single-letter attribute `Action_Helper.N`.

### 3.2 Reward coefficients

| Key | Value | Meaning |
|---|---|---|
| `order_penalty` | 0.1 | Per order placed this step |
| `trade_penalty` | 0.05 | Per trade filled this step |
| `drawdown_penalty` | 0.2 | Per unit of NAV below the running peak |
| `passive_bonus` | 0.1 | Per passive (liquidity-providing) fill this step |
| `loss_multiplier` | 1.5 | Extra weight on negative NAV changes |

These were literals inside `Reward_Helper.set_reward` until they were promoted to config — the
parameters most worth sweeping were the least reachable in the project. The formula they feed is
documented in [07_reward_function.md](07_reward_function.md) §2, including why
`drawdown_penalty` in particular dominates the reward at the current scale.

### 3.3 How the keys reach their consumers

The env is assembled from cooperative mixins
([02_architecture.md](02_architecture.md) §2.2), so the keys are forwarded along the MRO rather
than read directly by the classes that use them:

```
continuousDoubleAuctionEnv.__init__      self._cfg(key) -> env_config, else env_defaults.json
  └── Exchg_Helper.__init__              **kwargs  (consumes init_cash, tick_size,
        │                                           tape_display_length)
        └── State_Helper.__init__        **kwargs  (consumes n_hist; sets the
              │                                     observation layout on the instance)
              └── Action_Helper.__init__ consumes min_size, mkt_max_size,
                  │                      limit_size_multiple, tick_size
                  └── Reward_Helper.__init__ consumes the five coefficients
```

Every mixin consumes its own arguments and forwards the rest, so `kwargs` is empty by the time the
chain reaches `Done_Helper` / `Info_Helper`, which define no `__init__`. Each mixin's argument
defaults are `env_default(...)` calls, so a mixin constructed directly gets the same values the env
would have given it.

---

## 4. Structural constants

`config/tunable_constants.json`. These shape the observation and action spaces, the module-ID
naming contract, and the plot and path defaults.

### 4.1 Observation layout

| Key | Value | Meaning |
|---|---|---|
| `k_rows` | 10 | Book depth — price levels per side |
| `book_rows` | 4 | Rows in the book block: bid_price, bid_size, ask_price, ask_size |
| `extra_dim` | 2 | Market-level scalars appended: log_mid, log1p_spread_ticks |

`k_rows` is **one** definition with four consumers: the observation space, the action space's
`price` component, the reshape in `_set_price`, and the reshape in `print_table`. These were once
four independent literals that all happened to be 10, so changing depth raised `ValueError` or
silently made high levels unreachable.

Depth is now genuinely changeable: `State_Helper.__init__` reads the layout onto the instance as
`k_rows` / `book_rows` / `extra_dim` / `book_dim` / `snapshot_dim`, and the observation space is
built from `self.snapshot_dim`. Set `k_rows` to 6 and the observation, the action space and the
price logic all follow.

`book_rows` is checked against `BOOK_ROW_ORDER`, the tuple naming what `set_agg_LOB` actually
concatenates. A value the code cannot honour raises at env construction rather than being ignored.

The module-level `K_ROWS` / `BOOK_DIM` / `SNAPSHOT_DIM` names still exist in `state_helper`, read
from the same config at import. They are for consumers with no env instance to ask — the
visualizers, which read a pickled observation, and the tests.

### 4.2 Action space

| Key | Value | Meaning |
|---|---|---|
| `category_n` | 9 | Side/type codes: none, then bid and ask × {market, limit, modify, cancel} |
| `price_offset_n` | 3 | Passive / join / aggressive, in ticks |
| `size_mean_low` / `size_mean_high` | -1.0 / 1.0 | Bounds of the size-mean Box |
| `size_sigma_low` / `size_sigma_high` | 0.0 / 1.0 | Bounds of the size-sigma Box |

The price code's cardinality is not here — it is `observation_layout.k_rows`.

Both counts are **checked against the code that decodes them**, which is the change that made them
real config rather than documentation:

- `category_n` must equal the size of `_CATEGORY_MAP`, the side/type table in `action_helper`. The
  old `if`/`elif` chain hardwired 9, so changing the number did nothing.
- `price_offset_n` must be odd, so the neutral "join" code is the middle one. The offset is now
  `price_offset - price_offset_n // 2` rather than a hardcoded `- 1`, so widening it to 5 extends
  the range symmetrically to ±2 ticks and works.

### 4.3 The rest

**Price anchor fallbacks.** The price used before any trade has printed, previously the literal
`100.0` written twice — once in `Action_Helper.__init__`, once in the observation midpoint fallback
in `state_helper`. Both paths are dead in practice, since `reset()` overwrites `last_price` from
`initial_price_min` / `initial_price_max`, but they are read from one place now and cannot drift.

**Module ID prefixes.** `policy_` / `champion_` are a naming contract `SelfPlayCallback` parses,
not a knob — changing them invalidates existing checkpoints, whose module directories carry the old
prefix.

**Runtime env vars.** Set with `setdefault` before `ray.init`, so a value already exported in the
shell wins.

**Logging.** The default level, the format string, the date format, and the name of the
environment variable the level travels in (`CDA_LOG_LEVEL`). Read by
[`logging_setup.py`](../gym_continuousDoubleAuction/logging_setup.py), which applies them once per
process on the first `get_logger` call — including inside Ray's worker processes, which never run
`main()` and would otherwise come up unconfigured. The pid is in the format on purpose: with
`num_env_runners > 0` several processes log into one stream. See
[11 §1.3](11_logging_and_observability.md).

**Visualize defaults.** The paths the `visualize/` scripts read. (The `plot_defaults` group went
with `plot_handler.py` — see [11 §1.4](11_logging_and_observability.md).)

---

## 5. Training config

`TrainConfig` ([`train.py`](../gym_continuousDoubleAuction/train/train.py)) is the schema: it names
every knob, gives it a type, and documents what it does. It holds no values — each field's default
is `_default("key")`, which reads `config/train_config.json` when a `TrainConfig` is instantiated.

Two consequences worth knowing:

- **The dataclass and the file cannot disagree.** They used to. Before this change the dataclass
  said `num_cpus_per_env_runner = 1.0` and `num_gpus_per_learner = 0.75` while the file said `0.25`
  and `0.25`; a run without `--config` silently used the dataclass pair.
- **A key missing from the file raises**, rather than resolving to something written in Python.

Network shape is configured through `fcnet_hiddens`, `fcnet_activation` and `vf_share_layers`,
threaded to `default_model_config` via `create_multi_agent_config`. Called without arguments,
`default_model_config` reads the same `ppo` group directly, so both paths agree by construction.
`vf_share_layers` is `False` deliberately: the learners train against non-stationary league
opponents, where sharing a trunk between policy and value tends to destabilise the value estimate.

`SelfPlayCallback` does the same with the `league_self_play` group and the two agent counts. That
group also carries the two knobs on the episode-end NAV conservation check: `nav_tolerance`, the
absolute cash tolerance, and `strict_nav_check` (`--no-strict-nav-check`), which decides whether a
violation raises or only logs. It defaults to raising — a conservation break means the ledger is
corrupt — and the `nav_conservation_error` metric is emitted either way. See
[11 §1.5](11_logging_and_observability.md).

`num_learners`, the reward coefficients and the sizing knobs have no CLI flag, so the file is the
only way to set them outside the Python API.

### 5.1 `sample_timeout_s`, and the run that trains on nothing

In the `rollouts` group, with `--sample-timeout`. It is how long the driver waits for a remote env
runner to hand back its share of `train_batch_size` before giving up on it.

RLlib's default is **60 seconds**, and this environment cannot meet it at the shipped batch size.
`train_batch_size` is `max_step × num_episodes_per_iter` = 4096 × 4 = 16,384 env steps; the order
book matches in Python at roughly 60 env-steps/sec per runner with 8 agents, so two runners need
about two minutes. The failure is silent in the worst way: a timed-out iteration **discards the
partial rollouts**, hands the learner nothing, and then counts itself, logs, and checkpoints
exactly like a real one. A 16-iteration run finishes in 19 minutes having done zero gradient steps,
and its checkpoints hold the initial random weights.

What it looks like, once per iteration:

```
WARNING rollout_ops.py:122 -- No samples returned from remote workers...
iter 1/16 | env steps sampled: n/a | module returns: {}
iter 1 trained on no samples: the result has no 'env_runners' block...
```

The second warning is this repo's (`_log_iteration`), and it names the batch size and the timeout
it just missed. The consequence downstream is that `result` has no `env_runners` key at all, so
anything indexing `result[ENV_RUNNER_RESULTS]` raises `KeyError` rather than reading a zero.

Raise `sample_timeout_s` above what one iteration's sampling actually takes, or shrink the batch
with `max_step` / `num_episodes_per_iter`. The value is ignored when `num_env_runners` is 0, since
the driver then samples in-process with no timeout to miss.

### 5.2 The `run` group

These are the keys that still mean something on a **restored** run. Everything else in the file is
baked into the checkpoint — see §5.3.

| Key | Flag | What it does |
|---|---|---|
| `num_iters` | `--iters` | The iteration to train **through**, not a number of iterations to run |
| `num_iters_is_delta` | `--iters-is-delta` | Read `num_iters` as "this many more from wherever the restore landed" |
| `chkpt_freq` | `--chkpt-freq` | Save every N iterations (0 saves only at the end) |
| `chkpt_keep` | `--chkpt-keep` | How many saves to retain; `<= 0` keeps all |
| `is_restore` | `--restore` | Resume from a checkpoint rather than starting from scratch |
| `restore_path` | `--from-checkpoint` | Which checkpoint; `null` takes the newest readable one |
| `log_level` | `--log-level` | **Ray's** level, handed to `PPOConfig.debugging` |
| `cda_log_level` | — | **This package's** level; exported as `$CDA_LOG_LEVEL` so worker processes inherit it |

**Two log levels, deliberately.** Ray at `INFO` is noise; this package at `INFO` is the per-episode
NAV table, the per-iteration league statistics and the checkpoint lines — the output a run is meant
to produce. Set `cda_log_level` to `DEBUG` for the per-step render and account tables, `WARNING`
for a quiet run. See [11 §1.3](11_logging_and_observability.md).

**`num_iters` is a target.** A 16-iteration run resumed at iteration 9 does 7 more, so the length
of a run does not depend on how many times it was interrupted. It used to be a count on a driver
loop that restarted at zero, which made 16 configured iterations mean 16 *more* every time. The
iteration numbers are the algorithm's own — RLlib stores `training_iteration` in the checkpoint —
so they are the same numbers the checkpoint directories and the log lines carry.
`num_iters_is_delta` restores the old reading, for extending a run that already reached its target.

**Checkpoint layout.** Each save is its own directory:

```
results/chkpt/
├── iter_00004/          ← an RLlib checkpoint, plus league_state.json
├── iter_00006/
└── iter_00008/          ← the newest; what a restore picks
```

`chkpt_keep` prunes the oldest. Every save used to overwrite one directory, which left a run with
exactly one recoverable state: no way back from a league that collapsed at iteration 12, and a save
interrupted partway — the event checkpointing exists to survive — destroyed the only copy. Saves
are now staged as `iter_N.tmp` and renamed into place, so an interrupted save leaves a directory
the scanner skips rather than a half-written one that looks complete. A restore that cannot read
the newest checkpoint falls back to the one before it.

`league_state.json` beside each checkpoint records the champion pool in plain JSON. The champion
*modules* are in the checkpoint proper, but everything indexing them — history, the monotonic ID
counter, the matchmaking pool — lives on the cloudpickled callback, and survives only as long as
`SelfPlayCallback` stays unpickle-compatible. On restore the sidecar is reconciled against the
modules that actually came back, and any repair is printed. See
[08_self_play_league.md](08_self_play_league.md).

**Choosing a checkpoint.** `restore_path` null — the default — takes the newest readable
checkpoint, which is what a disconnect wants. Name one to go back further:

```bash
python -m gym_continuousDoubleAuction.train.train --from-checkpoint results/chkpt/iter_00008
```

```json
"run": {
  "is_restore": true,
  "restore_path": "results/chkpt/iter_00008"
}
```

It names **one save**, not the directory holding them; pointing at `results/chkpt` raises and
lists the checkpoints that are there, newest first. Two rules follow from what pinning is for:

- **`restore_path` requires `is_restore`.** Set without it, the run would start from scratch and
  ignore the path, so it raises instead. `--from-checkpoint` implies `--restore`, since naming a
  checkpoint on the command line is not ambiguous about intent; in the file, the two keys must
  agree. Validation happens before the env is built, so a typo fails in a second.
- **A pinned checkpoint never falls back.** An unreadable one raises rather than quietly training
  from its neighbour — the opposite of what the automatic path should do, and the point of having
  said which one.

Rolling back a run past a collapsed league is then: pick the checkpoint, restore from it, and let
training overwrite the iterations after it. `chkpt_keep` bounds how far back you can go.

The notebook has no separate knob for any of this — it is a thin driver that reads
`train_config.json`, and cell 4 prints the resolved `restore` line before the run starts.

### 5.3 What a restore ignores

`Algorithm.from_checkpoint` rebuilds everything from the config stored *in the checkpoint*. The
`PPOConfig` built from `train_config.json` is discarded. Since resuming means editing
`train_config.json` to set `is_restore`, that is the same file holding `lr`, the reward
coefficients and `num_agents` — so an edit made in the same pass as the restore flag had no effect
and said nothing.

It is now loud in both directions:

- **A structural change is fatal.** `num_agents`, `n_hist` or the policy set changing means the
  restored weights do not fit the requested problem, so the restore raises rather than training
  something other than what was asked for. Revert the key, or start a fresh run.
- **Everything else warns.** `lr`, reward coefficients, batch sizes and runner counts print as
  "will NOT take effect" with both values, and the run continues on the checkpoint's config.

To train with new values, start a fresh run — `is_restore` false, or a new `log_base_dir`.

---

## 6. `tick_size`

`tick_size` sets the price grid the action space quotes on. It reaches `Action_Helper.min_tick`,
which is the only thing that constructs prices — `_set_price` builds them as
`anchor ± k × min_tick`.

**This used to be two independent values.** `Action_Helper.min_tick` was a hardcoded `1` that
actually drove prices, while the configured `tick_size` was passed to an `OrderBook` argument that
was stored and never read. Setting `tick_size` therefore had no effect anywhere. Both values were
1, so wiring `min_tick` to the config key changed no behaviour at the current config.

**`reset()` no longer discards it.** It used to rebuild the book as `OrderBook(1, ...)` regardless
of configuration; it now uses `self.tick_size`. The change is inert — see below — but there is no
reason to keep a second value in the env.

**The book's copy is still there, and still inert.** `OrderBook` accepts a `tick_size`, stores it,
and never reads it; there is no rounding or tick validation anywhere in the matching path. Its
literal default of `0.0001` is **the one value in the project not read from `config/`**, recorded
in `tunable_constants.json` under `inert_tick_size_copy` as documentation.

**The recommendation is to delete the book's copy, not to enforce it** — the action layer should be
the single definition. There is exactly one price producer in the system: every price reaching
`process_order` comes from `_set_price` via `place_order`, and it emits on-grid prices by
construction, so validation in the book would re-derive a guarantee the producer already provides.
Deletion is nearly free — 9 of the 11 `OrderBook(...)` call sites already use the no-arg form.

**This is deferred**: the `envs/orderbook/` package is off-limits to changes, and deleting the
parameter means editing `orderbook.py`. Tracked as S3-4 in
[15_findings_and_recommendations.md](15_findings_and_recommendations.md).

Enforcement in `OrderBook.process_order` would be the right call instead of deletion only if a
second price source appears that the action layer does not control — scripted or human agents,
replayed order flow, an external feed.

### 6.1 Float-grid caveat

`_set_price` performs **no** quantization, so a tick that is not binary-exact can in principle
produce a price whose `Decimal(str(price))` key sits off the grid, splitting one book level into
two price-map entries.

This is rarer than it sounds. Over all anchors 10–100, ticks {0.01, 0.05, 0.1, 0.2, 0.25, 0.3} and
ten levels either side, exactly one combination drifts: `10 − 9 × 0.3` → `7.300000000000001`.
Ticks of `1`, `0.5` and `0.25` are exact in binary and cannot be affected. Worth adding a `Decimal`
quantize step if non-integer ticks are ever used in earnest; it is not by itself a reason to change
anything.

---

## 7. Adding a knob

1. Add the key to the right file, in the right group, with a `_note` if the reason is not obvious.
2. Read it through `config_loader` at the point of use. Do not give it a Python default.
3. If it is a `TrainConfig` field, declare it in the dataclass as `= _default("key")`.
   `test_config_loading.py` asserts the file and the dataclass name exactly the same set of fields,
   so a field without a key (or a key without a field) fails the suite.
4. If the code cannot honour every value the key could take — a cardinality wired to a mapping, a
   count that has to be odd — validate it and raise. A structural value that is silently ignored is
   worse than a literal, because the file claims it works.

---

## 8. Runtime profiles

[`config/runtime_profiles.json`](../config/runtime_profiles.json) answers a question the other four
files deliberately do not: *what machine is this?* It exists because `CDA_NSP.ipynb` has to run
unchanged on a [Colab VM](20_colab.md) and inside the
[docker/ml image](19_docker.md), which differ in core count, GPU presence and filesystem layout —
and in nothing else. Resolved by
[`train/runtime.py`](../gym_continuousDoubleAuction/train/runtime.py).

This document is the mechanism. For the step-by-step of actually running either target, see
[20_colab.md](20_colab.md) and [19_docker.md](19_docker.md).

### 8.1 The two hardware sets

Exactly two, chosen by `torch.cuda.is_available()` and the notebook's `USE_GPU` toggle. The stated
bounds are a ceiling of **2 CPUs + 1 GPU** and a floor of **1 CPU + 0 GPUs**;
[`test_runtime_profiles.py`](../gym_continuousDoubleAuction/test/test_runtime_profiles.py) asserts
both sets stay inside them.

| | `gpu` | `cpu` |
|---|---|---|
| `ray.init(num_cpus, num_gpus)` | 2, 1 | 1, 0 |
| `num_env_runners` | 2 | 0 |
| `num_cpus_per_env_runner` | 1.0 | 1.0 |
| `num_learners` | 0 | 0 |
| `num_gpus_per_learner` | 1.0 | 0.0 |

Two choices in there are worth stating outright:

- **`num_learners=0` in both.** The learner runs in the driver process and still gets the GPU —
  `num_gpus_per_learner` is only turned into a Ray *resource request* for remote learners
  (`learner_group.py`, the `is_remote` branch). A remote learner would cost one of the two CPUs and
  buy nothing at a 256×256 MLP.
- **`num_env_runners=2` under the gpu set.** Sampling is the bottleneck here, not the update — the
  environment matches orders in Python, measured at ~500 env-steps/sec on one core, against a PPO
  update the GPU finishes in seconds. This is the `num_env_runners=N, num_learners=0` shape
  [doc/09 §5](09_distributed_training.md) recommends for exactly this case. A test asserts
  `num_env_runners × num_cpus_per_env_runner ≤ num_cpus`, because runners are actors: ask for more
  CPUs than `ray.init()` was given and they stay pending forever rather than failing.

### 8.2 Platforms

`repo_path`, `results_root` and `episode_data_root` per platform; `null` means "leave it alone",
which is what a local checkout wants. The Colab entry splits the two output roots on purpose:
checkpoints go to the Drive-backed repo so a disconnected session is recoverable with
`is_restore`, while the per-episode pickles (~10MB per 4096-step episode) go to the VM's local disk
and never cross the Drive FUSE layer.

`platforms.colab.pip_packages` is the one entry read *without* the loader — the notebook's
bootstrap cell reads it with plain `json.load`, because it runs before the package is importable
and installing what makes it importable is the whole job of that cell. Its pins must track
`requirements.txt`; torch, numpy and pandas are absent from it deliberately, since installing this
repo's pins over Colab's preinstalled CUDA torch would replace it with a CPU wheel.

### 8.3 Overriding it

`$CDA_PLATFORM` and `$CDA_USE_GPU` pin what detection would otherwise guess, so a headless run can
be forced onto a given set without editing anything:

```bash
CDA_PLATFORM=docker CDA_USE_GPU=false python -m gym_continuousDoubleAuction.train.train
```

Note the asymmetry, which is intentional: `CDA_USE_GPU=true` does **not** force the gpu set onto a
machine without CUDA. It falls back to the cpu set and says so, because the alternative is RLlib
placing a learner on a device that is not there.
