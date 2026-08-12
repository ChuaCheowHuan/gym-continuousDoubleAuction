# 9. Distributed Training: `num_env_runners` and `num_learners`

What these two `TrainConfig` / `AlgorithmConfig` settings do, how they interact with league-based
self-play, and which bugs existed at non-default values before they were fixed.

Related: [08_self_play_league.md](08_self_play_league.md) (what runs in the callback these
settings distribute), [10_testing.md](10_testing.md) §6
(`TestLeagueWiringRemoteEnvRunners`, `TestLeagueWiringRemoteLearner`).

---

## 1. What each one controls

Both are
[`ray.rllib.algorithms.algorithm_config.AlgorithmConfig`](https://github.com/ray-project/ray/blob/master/rllib/algorithms/algorithm_config.py)
settings, exposed on this repo's [`TrainConfig`](../gym_continuousDoubleAuction/train/train.py).
They control two independent axes of parallelism:

| Setting | Controls | Default in `TrainConfig` |
|---|---|---|
| `num_env_runners` | How many separate processes **collect experience** (step the environment, produce batches) | `0` |
| `num_learners` | How many separate processes **compute gradients** (forward/backward pass, optimizer step) | `0` |

They compose independently. `num_env_runners=4, num_learners=1` — four processes sampling, one
GPU process training — is a normal production shape.

At `0`, there is no separate process for that role; the work happens inline in the driver (the
process that calls `algo.train()`). At `N > 0`, `N` Ray actors do that work instead, and the
driver only orchestrates.

**Why this matters more than it looks like it should:** at `num_env_runners=0` and
`num_learners=0`, the driver's
[`SelfPlayCallback`](../gym_continuousDoubleAuction/train/callbk/league_based_self_play_callback.py)
instance *is* the object doing the sampling, and the driver's `LearnerGroup` *is* local. The
moment either setting goes above `0`, that stops being true — and three separate bugs in this
codebase's history lived exactly in that gap. See §4.

---

## 2. `num_env_runners`

### 2.1 What gets created

`num_env_runners=N` creates `N` remote `MultiAgentEnvRunner` actors — each a separate OS process,
potentially on a separate machine in a Ray cluster. Each one holds:

- its own copy of `continuousDoubleAuctionEnv` (`num_envs_per_env_runner` copies, vectorized, if
  greater than 1),
- its own copy of every module's weights (`policy_0`, `policy_1`, the frozen `RandomRLModule`
  baselines, and any `champion_N` snapshots),
- its own **pickled copy** of `SelfPlayCallback`, frozen at the moment the actor was constructed
  and never automatically kept in sync afterwards.

A local `EnvRunner` always exists in the driver too (`algo.env_runner`). At `num_env_runners=0`
it is the *only* one and does all the sampling. At `N > 0` it still exists but is idle for
sampling purposes — the remote actors do the work. (It is still used for
`RLModuleSpec.from_module` when a champion is created; see
[08_self_play_league.md](08_self_play_league.md) §5.2.)

### 2.2 One training iteration, worked example

```python
cfg = TrainConfig(
    num_agents=8, num_trained_agents=2,
    num_env_runners=2,
    num_envs_per_env_runner=2,
)
```

This creates 2 actors, each running 2 environment copies — 4 CDA environments total, 8 agents
each, split across 2 processes plus the driver.

```
Driver process
  ├─ holds: Algorithm, LearnerGroup, the "real" SelfPlayCallback
  │
  ├─ EnvRunner actor #1 (separate process)
  │     env copy A (8 agents)
  │     env copy B (8 agents)
  │     + its OWN pickled SelfPlayCallback
  │     + its own copy of every module's weights
  │
  └─ EnvRunner actor #2 (separate process)
        env copy C (8 agents)
        env copy D (8 agents)
        + its own pickled SelfPlayCallback
        + its own copy of every module's weights
```

Per `algo.train()` call:

1. **Sampling is dispatched** to both actors over Ray RPC. The driver runs no environment steps
   itself.
2. **Each actor steps its envs independently, in parallel.** For every agent slot in every
   episode, `SelfPlayCallback.get_mapping_fn` (using *that actor's own*
   `config.policy_mapping_fn`) picks which module plays it; the chosen module runs inference
   locally on that actor, using weights already resident there — no round-trip to the driver per
   step.
3. **Each actor returns its batch** to the driver once episodes finish or hit `max_step`.
4. **The driver's `LearnerGroup` trains** on the combined batches (see §3).
5. **The driver's `SelfPlayCallback.on_train_result` runs** — see §2.3 for why this is the
   driver's job alone.
6. **If a champion was created**, the driver pushes its weights and a refreshed mapping function
   to both actors, so their *next* sampling round can select it.

A concrete trace, two episodes running at the same instant in two different processes:

```
EnvRunner #1, env copy A:                 EnvRunner #2, env copy C:
  agent_0 -> policy_0                       agent_0 -> policy_0
  agent_1 -> policy_1                       agent_1 -> policy_1
  agent_2 -> policy_7                       agent_2 -> champion_1
  agent_3 -> champion_1                     agent_3 -> policy_7
  agent_4 -> champion_1                     agent_4 -> policy_6
  agent_5 -> policy_6                       agent_5 -> champion_1
  agent_6 -> champion_1                     agent_6 -> policy_7
  agent_7 -> policy_7                       agent_7 -> champion_1
```

`policy_0` / `policy_1` are the same two trainable modules in both — that shared curriculum is
the point of self-play. The opponent draws (agents 2–7) differ because each slot is an
independent weighted random choice, made separately per episode per actor.

### 2.3 Champion creation never happens on an EnvRunner actor

`on_train_result` — the only method that creates champions — is dispatched from
`Algorithm.log_result`, using `self.callbacks`, a single object constructed once in the driver's
`__init__`. `MultiAgentEnvRunner` never calls it; the actors' pickled callback copies only ever
run `on_episode_start` / `on_episode_step` / `on_episode_end`, because those are the only hooks
it dispatches. Verified empirically: after training with `num_env_runners=2` and one champion
created, the driver's `champion_history` has one entry; both actors' own callback copies still
have `champion_history == []`.

So there is exactly **one** champion pool, with one counter and one history, owned by the driver.
The actors are consumers of that pool (told about new champions after the fact), never producers
of it. What can go stale is a remote actor's *copy* of the pool state — not the pool itself
splitting in two. See §4.1.

### 2.4 Per-episode state on the runners

`on_episode_step` accumulates step data into `self.store`, a `defaultdict(list)` **keyed by
`episode.id_`**. This used to be a single shared list plus a single `self.ID`, which is only safe
with one env per runner: with `num_envs_per_env_runner > 1`, episodes on the same runner
interleave, so steps from concurrent episodes were appended to one list and written into
whichever episode ended first — and the first `on_episode_step` after any episode ended hit
`None.append`, because `on_episode_end` reset the shared list to `None`.

---

## 3. `num_learners`

### 3.1 What gets created

`num_learners=N` creates `N` remote `Learner` actors — data-parallel replicas, each holding a
full copy of every trainable module (`policy_0`, `policy_1`), typically one actor per GPU
(`num_gpus_per_learner`).

At `num_learners=0`, the `LearnerGroup` is **local** (`learner_group.is_local == True`) and
`learner_group._learner` is a real object (`PPOTorchLearner` in this repo). At
`num_learners > 0`, the `LearnerGroup` is **remote**: `is_local` is `False` and `_learner` is
`None` — the driver only holds handles to the remote actors. This is the fact that mattered for
§4.2.

`TrainConfig.resolved_gpus_per_learner()` forces the GPU fraction to 0 when
`torch.cuda.is_available()` is `False`, with a printed warning, so the `0.75` default does not
hard-fail on a CPU box.

### 3.2 How a batch is split across Learners — by timestep, not by module

It is tempting to guess that with 2 Learners, one trains `policy_0` and the other trains
`policy_1`. **That is wrong.** Verified against RLlib's `ShardBatchIterator`
([`minibatch_utils.py`](https://github.com/ray-project/ray/blob/master/rllib/utils/minibatch_utils.py)):
the shard loop is `for pid, sub_batch in self._batch.policy_batches.items()` — it iterates *per
module*, and *within each module's own sub-batch* takes a contiguous `1/num_shards` slice.

Concretely, with `num_learners=2` and 256 timesteps of data for each of `policy_0` and `policy_1`
this iteration:

```
policy_0's 256 steps:                    policy_1's 256 steps:
    Learner A gets steps [0:128]             Learner A gets steps [0:128]
    Learner B gets steps [128:256]           Learner B gets steps [128:256]
```

Every Learner gets data from **both** modules — a horizontal slice of the whole batch — not one
Learner per module. This has to be true: `policy_0` and `policy_1` both need a gradient update
every iteration, so a Learner that only ever saw one module's data would never train the other on
that replica.

Both Learners then compute gradients for both modules on their own shard, RLlib synchronizes and
averages the gradients **per module** across replicas (via a `DistributedDataParallel`-style
wrapper), and every Learner ends up with identical, updated weights for both `policy_0` and
`policy_1`.

### 3.3 After the update: weights flow back out

`PPO.training_step` calls
`env_runner_group.sync_weights(from_worker_or_learner_group=learner_group, ...)`
([`ppo.py`](https://github.com/ray-project/ray/blob/master/rllib/algorithms/ppo/ppo.py)) — the
driver pulls the now-identical trained weights from the Learner(s) and pushes them to every
EnvRunner, local and remote, so the next sampling round uses the freshly-updated
`policy_0` / `policy_1`.

Note the argument RLlib passes: `policies=modules_to_update`, i.e. **only modules that produced
losses**. A frozen champion never does, which is precisely why champion weights need the separate
force-push described in [08_self_play_league.md](08_self_play_league.md) §5.2.

---

## 4. Bugs that only existed at non-default values

Both settings default to `0` in `TrainConfig`, which is the one configuration where everything
lives in a single process. Every bug below was invisible there and only appeared once a setting
went to `1` or more — because that is what created a second process with its own stale copy of
something the driver mutates.

### 4.1 `num_env_runners > 0`: champion pool published one snapshot late

Fixed in `9c1c6da`. `_create_champion_snapshot_from_policy` called
`algorithm.add_module(new_agent_to_module_mapping_fn=self.get_mapping_fn(self), ...)` to push a
refreshed mapping function to every actor. That callable closes over `self`, and `add_module`
pickles it to ship it — which snapshots `self.available_modules` at the moment of the call. The
code appended the new champion to `available_modules` *after* calling `add_module`, so every
remote actor's mapping function was permanently one champion behind. Measured over 800 draws: the
driver drew `{policy_2, policy_3, champion_1, champion_2}`; a remote actor drew only
`{policy_2, policy_3, champion_1}`.

Fix: append to `available_modules` **before** calling `add_module`, with a rollback in the
exception path so a failed snapshot can never be selected.

A second, related bug fixed in the same commit: the `on_episode_start` "Policy Map" printout read
`self.available_modules` directly, which — on a remote actor — never contains any champion at
all, since that actor's callback copy is never updated after construction. Fixed by reading
`env_runner.config.policy_mapping_fn` instead, which `add_module` *does* keep current.

Regression coverage: `TestLeagueWiringRemoteEnvRunners` in
[`test_league_wiring.py`](../gym_continuousDoubleAuction/test/integration/test_league_wiring.py),
added in `d53c9fd`. It probes the remote actor directly (module presence, weight equality, and
`config.policy_mapping_fn` draw distribution), with a premise-guard test
(`test_sampling_actually_happens_remotely`) asserting the actor really is remote — without it, a
broken probe silently degrades into iterating an empty list and every assertion passes vacuously.

### 4.2 `num_learners > 0`: champion snapshotting failed on every attempt

Fixed in `a446281`. `_create_champion_snapshot_from_policy` read the source module via
`algorithm.learner_group._learner.module[...]` — the private `_learner` attribute described in
§3.1, which is `None` whenever the `LearnerGroup` is remote. Every snapshot attempt raised
`'NoneType' object has no attribute 'module'`, and the broad `except` around the snapshot logic
swallowed it: one error line per iteration, league permanently empty, no crash. Measured before
the fix at `num_learners=1`: `champions created: []`.

Fix: read the module state through the public `learner_group.get_state(components=...)`, which
works whether the `LearnerGroup` is local or remote.

Regression coverage: `TestLeagueWiringRemoteLearner`, added in the same commit, with its own
premise guard (`test_learner_group_is_actually_remote`).

### 4.3 The pattern

All three bugs (this document's two, plus the `WEIGHTS_SEQ_NO` one found earlier in the
migration) trace to the same root cause: code written and tested only at
`num_env_runners=0, num_learners=0`, where the driver's objects and the "remote" objects are
literally the same object, so nothing about process boundaries could go wrong.

**Any new code touching `SelfPlayCallback` or champion snapshotting should be exercised against
both `TestLeagueWiringRemoteEnvRunners` and `TestLeagueWiringRemoteLearner`, not just the
default-config tests, before being considered correct.**

---

## 5. Practical guidance

- **`num_env_runners=0, num_learners=0`** — what most of the test suite runs against, and the
  simplest to debug. Fine for a single CPU box.
- **`num_env_runners=N, num_learners=0`** — parallelize sampling only. Reasonable when the
  environment step (not the PPO update) is the bottleneck, which is likely true here: this
  environment does non-trivial per-step order book matching in Python, with `Decimal` arithmetic.
- **`num_env_runners=N, num_learners=1, num_gpus_per_learner=1`** — the common single-GPU shape:
  CPU-bound sampling parallelized across several processes, one dedicated GPU process doing the
  PPO update.
- **`num_learners>1`** — multi-GPU data-parallel training. Only worth it once a single GPU is the
  bottleneck; it adds the distributed-systems surface described in §4.2 for a larger effective
  batch per iteration and faster wall-clock training.

`num_env_runners` and `num_learners` should be sized independently, against whichever of sampling
or learning is actually the bottleneck on the target machine — not moved in lockstep.

### Cost to watch: per-episode pickles

With `episode_data_dir` set (the default), **every** episode on **every** runner writes one file
containing every step's obs (168 floats), action, reward and info. At `max_step=4096` and 8
agents that is ~4,096 dicts per episode held in memory and then serialised, per episode, per
worker. Pass `--no-episode-data` (or `episode_data_dir=None`) for real training runs.
