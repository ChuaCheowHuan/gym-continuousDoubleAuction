# 16. Verification Log

Every **[verified]** claim in this documentation set traces to one of the probes below.

All probes were re-run against the working tree on branch `update_lib` during that merge, on
Python 3.12.1 / Ray 2.56.1 / torch 2.13.0+cpu / gymnasium 1.2.2 / NumPy 2.5.2. Where a probe had
also been run for the earlier `doc_new/` analysis (at commit `3dcfc53`), both readings are shown
— the absolute numbers differed because **the environment was not seedable at the time** (finding
S3-5), but every qualitative conclusion and every order of magnitude reproduced.

> **This document is a log, not a status page.** Entries are kept as they were recorded, including
> the ones whose finding has since been fixed — S3-5 (seeding) and S3-6 (`install_requires`) are
> the two that most change how a probe would read if re-run today. For current status see
> [15_findings_and_recommendations.md](15_findings_and_recommendations.md); for what a probe
> measures *now*, the re-measurements below are dated.

---

## 16.1 Environment and dependency versions

```
Python 3.12.1
ray              2.56.1
torch            2.13.0+cpu
gymnasium        1.2.2
numpy            2.5.2
pandas           3.0.5
sklearn          1.9.0
sortedcontainers 2.4.0
tabulate         0.10.0
six              1.17.0
```

At the time: `six` and `sklearn` were importable only because they were installed transitively or
via `requirements.txt`; neither was in `setup.py::install_requires` (finding S3-6).

**Re-measured, Python 3.12.3, same pins otherwise** (`pyarrow 25.0.1` is now in play for the
Parquet record, via `ray[rllib]`):

```
$ python -c "import sys, gym_continuousDoubleAuction.envs.continuousDoubleAuction_env; \
             print('sklearn imported:', 'sklearn' in sys.modules)"
sklearn imported: False
```

`scikit-learn` is in neither `install_requires` nor `requirements.txt`, because nothing imports it
— `rand_exec_seq` shuffles with the env's own `Generator.permutation`. `six` *is* declared now, as
are `ray[rllib]`, `numpy`, `pandas`, `sortedcontainers` and `tabulate`. S3-6 is closed, and the
`packaging` CI job builds a wheel and constructs an env from it in a clean venv so the claim stays
true.

---

## 16.2 Test suite

```
$ python -m pytest gym_continuousDoubleAuction/test -q \
      --ignore=gym_continuousDoubleAuction/test/integration
........................................................................ [ 80%]
..................                                                       [100%]
90 passed
```

Per-file counts summing to 90:

```
test_accounting.py                  13    test_obs_market_features.py      17
test_cash_check.py                   7    test_obs_normalization.py        12
test_modify_order.py                 6    test_observation_history.py       5
test_nav_callback.py                 2    test_orderbook_crossed_book.py    1
test_new_action_space.py             8    test_orderbook_double_delete.py   1
test_probabilistic_mapping.py        1    test_orderbook_new.py            12
test_reward_logic.py                 4    test_orderbook_volume_sync.py     1
```

Integration: `integration/test_league_wiring.py` — 3 classes, 13 test methods.

`grep -rn "expectedFailure"` over the repository returns **nothing**, contradicting the older
documentation's description of `test_modify_order_price_change`.

**Re-measured on the current tree:**

```
$ python -m pytest gym_continuousDoubleAuction/test -q
509 passed, 1 xfailed, 7 warnings in 105.79s (0:01:45)

$ python -m pytest gym_continuousDoubleAuction/test -q --collect-only | tail -1
510 tests collected
```

474 unit and 36 integration. The one `xfail` is
`integration/test_progress_and_vf.py::test_the_critic_actually_explains_something`, a **strict**
xfail pinning S1-1: it will fail the build by XPASSing on the day the critic starts learning. The
current per-file inventory is in [10_testing.md](10_testing.md) §0.

**Supports:** the file inventory in [10_testing.md](10_testing.md), and the correction in
[03_matching_engine.md](03_matching_engine.md) §4.

---

## 16.3 Observation identity, feature scale, reward scale, NAV conservation

4 agents, `init_cash = 1,000,000`, 300 steps, uniformly random actions from the env's own action
spaces.

```
1. obs dim per agent: (168,)
   distinct obs vectors at reset:     1
   distinct obs vectors mid-episode:  1

--- observation feature scale (last snapshot block) ---
   bid_price norm   min/max:    0.0000    0.4048
   bid_size  sqrt   min/max:    0.0000   47.0106
   ask_price norm   min/max:   -0.5802    0.0000
   ask_size  sqrt   min/max:  -40.2865    0.0000
   log_mid          min/max:    3.6763    4.0431
   log1p_spread     min/max:    0.0000    2.7726

--- reward scale (random policy) ---
   per-step reward min/mean/max: -10948.8 / -492.5 / 6125.8
   episode return per agent: {'agent_0': -104682.9, 'agent_1': -81466.0,
                              'agent_2': -244468.0, 'agent_3': -160409.9}
   sum of all agents' returns: -591026.8

--- NAV conservation ---
   total NAV: 4,000,000.00   expected: 4,000,000.00
```

Earlier reading (commit `3dcfc53`, different unseeded draw): price features ±0.26, sqrt sizes
±51.19, per-step reward −15,779 … +8,744, summed return −883,786, total NAV 4,000,000.

The **ratio** is what matters and it is stable: the size block exceeds the price block by roughly
80–250× in both runs.

**Supports:** S1-2 (identical observations), S2-2 (feature-scale spread), S1-3 / S2-3 (reward
magnitude), and NAV conservation to the cent.

---

## 16.4 Reward decomposition and no-op dominance

Same setup; reward components re-derived per step from account state.

```
--- reward decomposition, summed over 4 agents x 300 steps ---
  nav_term      -174,502.0
  drawdown      -416,472.4
  order / trade / passive       0.0  (counters are zeroed inside step(); O(0.1)/step anyway)

--- all-agents-pass policy: total return over 300 steps x 4 agents = 0.0
```

Earlier reading: nav_term −264,587.5, drawdown −519,142.8, all-pass 0.0.

The drawdown penalty is **~2.4×** the asymmetric NAV term (earlier run: ~2.0×). Passing every
step yields **exactly zero** in both runs.

**Supports:** S1-3, S2-1.

---

## 16.5 Action-space pathologies

```
--- size sampling (same np.random seed before each list) ---
    mean=+0.5 -> [250.0, 250.0, 250.0, 250.0, 250.0]
    mean=-0.5 -> [250.0, 250.0, 250.0, 250.0, 250.0]   identical: True
    sigma=0.0 -> [250.0, 250.0, 250.0]
    sigma=1.0 -> [251.0, 249.0, 250.0]

    mkt_size_mean_mul=49.5, limit_size_mean_mul=499.5
    mkt_max_size=100,       limit_max_size=1000

--- tick_size ---
    config=0.25 | LOB.tick_size before reset=0.25 | after reset=1
                | action-space min_tick=1 | env has a self.tick_size attribute: False
```

Note `limit_max_size = mkt_max_size × N = 100 × 10 = 1000`, so a full-scale limit draw is ≈ 500
contracts. This corrects the "up to 5,000 contracts" figure in `doc_new/04`.

**Supports:** S3-1 (`abs()` folds the range), S3-2 (`sigma` is absolute and therefore inert),
S3-4 (`tick_size` discarded by `reset()`).

---

## 16.6 Market-mechanics probes

```
1. self-trade executed: True | tape len: 1 | same ID both sides: True

2. after forcing agent_0 NAV<0 ->
   terminateds: {'agent_0': False, 'agent_1': False,
                 'agent_2': False, 'agent_3': False, '__all__': False}
   done_set: {'agent_0'}

3. obs dim per agent: (168,) | distinct obs vectors across agents: 1

4. same-trader orders resting at price 90: 1 | level volume: 7.0
   after adding a bid at 89 too, distinct bid price levels: 2
```

Probe 1: trader 0 rests a bid of 5 @ 90, then sends a market ask of 5 — it crosses its own order
and prints.

Probe 4: two limit bids for 5 and 7 lots at price 90 from the same trader leave a single order of
7 — the second replaced the first. A bid at a *different* price does create a second level, so
the constraint is one order per (trader, side, price).

**Supports:** S2-5 (self-matching), S2-4 (no per-agent termination), S1-2, S3-10 (one order per
price level per trader).

---

## 16.7 One real PPO training iteration

Built through the shipped `build_config` path (`num_agents=4`, `num_trained_agents=2`,
`max_step=64`, `num_episodes_per_iter=4`, `num_epochs=1`, `minibatch_size=64`,
`episode_data_dir=None`), one `algo.train()` call.

```
== policy_0 ==
   vf_loss                 10.0
   vf_loss_unclipped       13,015,503.0
   vf_explained_var        8.910894393920898e-05
   total_loss              9.25406265258789
   policy_loss             -0.7470841407775879
   entropy                 8.844436645507812
   curr_entropy_coeff      0.0
== policy_1 ==
   vf_loss                 10.0
   vf_loss_unclipped       10,513,565.0
   vf_explained_var        5.418062210083008e-05
   total_loss              9.48421859741211
   policy_loss             -0.5171220302581787
   entropy                 7.949091911315938

module returns: {'policy_0': -8975.0, 'policy_1': -6777.3,
                 'policy_2': -6682.7, 'policy_3': -8783.5}
```

Earlier reading: `vf_loss` 10.0 / 10.0, `vf_loss_unclipped` 3,847,340.5 / 31,965,536.0,
`vf_explained_var` −0.000165 / −0.000135, `total_loss` 9.43 / 11.05, entropy 8.274 / 8.454.

`policy_2` / `policy_3` are `RandomRLModule`s and produce no losses, as expected.

The same run also promoted a champion on **iteration 1**:

```
Iteration 1 League Stats
Best Trainable: policy_1 (-6777.32)
🏆 CREATING CHAMPION SNAPSHOT 🏆  Champion ID: champion_1
✓ League size now: 5 (2 trainable + 2 random + 1 champions)
```

With `std_dev_multiplier=0.1` and an empty `champion_history` (so no cooldown applies), promotion
fires on the first eligible iteration.

### Corroborating source

`ray/rllib/algorithms/ppo/torch/ppo_torch_learner.py:99-100`:

```python
vf_loss         = torch.pow(value_fn_out - batch[Postprocessing.VALUE_TARGETS], 2.0)
vf_loss_clipped = torch.clamp(vf_loss, 0, config.vf_clip_param)
```

RLlib PPO defaults, read off a fresh `PPOConfig()` and never overridden by `TrainConfig`:

```
vf_clip_param    10.0        gamma           0.99
lambda_          1.0         grad_clip       None
entropy_coeff    0.0         minibatch_size  128
kl_coeff         0.2         kl_target       0.01
use_critic       True        use_gae         True
```

(`TrainConfig` does override `num_epochs` from RLlib's 30 to 4.)

Advantages **are** standardised per module by
`ray/rllib/connectors/learner/general_advantage_estimation.py`:

```python
module_advantages = (module_advantages - module_advantages.mean()) / max(1e-4, module_advantages.std())
```

which is why the update does not diverge despite the reward scale — the damage is confined to the
critic.

**Supports:** S1-1, S3-11 (`entropy_coeff = 0`, first-iteration promotion), S3-13 (γ, λ defaults).

---

## 16.8 Checkpoint / restore of league state

Train one iteration, promote champions, save, restore. (Run for the `doc_new/` analysis; not
re-run during this merge, and reported here as originally measured.)

```
BEFORE save -> champion_history: ['champion_1', 'champion_2']
               available_modules: ['policy_0','policy_1','policy_2','policy_3',
                                   'champion_1','champion_2']

[train] restoring from checkpoint: .../restore_probe/chkpt

AFTER restore -> returned cb.champion_history: []
                 available_modules: ['policy_0','policy_1','policy_2','policy_3']
AFTER restore -> modules present on env_runner: ['champion_1','champion_2',
                                                 'policy_0','policy_1',
                                                 'policy_2','policy_3']
AFTER restore -> algo's own callback obj: SelfPlayCallback
                 its champions: ['champion_1','champion_2']
AFTER restore -> mapping draws for opponents: {'policy_3', 'champion_1'}
```

This probe **corrected an earlier hypothesis**: league state *does* survive checkpointing,
because `.callbacks(lambda: callback_instance)` closes over the instance and RLlib cloudpickles
it. The restored algorithm's own callback, its modules, and its mapping function are all correct.

The narrower real defect was that `build_algo` returned the *fresh, empty* callback from
`build_config` rather than the restored one.

**Supports:** S3-8, S3-11.

### 16.8.1 After the fix

Re-run against the current code, 2 agents / 1 trainable / `max_step=32`, a fresh `log_base_dir`.
Each block is one `python -m gym_continuousDoubleAuction.train.train` invocation.

```
# 1. two iterations from scratch, chkpt_freq=2, chkpt_keep=2
[train] starting from scratch
[train] iter 2/2 | env steps sampled: 128 | ...
[train] checkpoint at iter 2: .../chkpt/iter_00002

# 2. --restore --iters 3: resumes, does ONE more iteration, not three
[train] restoring from checkpoint: .../chkpt/iter_00002
[train] league state verified: 1 champion(s)
[train] resuming at iteration 2, training through 3
[train] iter 3/3 | ...
[train] final checkpoint: .../chkpt/iter_00003

# 3. --restore --iters 3 again: already at the target
[train] resuming at iteration 3, training through 3
[train] checkpoint is already at iteration 3, at or past the target of 3 - nothing to do.

# 4. --restore --iters 2 --iters-is-delta: 3 -> 5, and retention prunes to 2
[train] iter 5/5 | ...
[train] pruned old checkpoint: .../chkpt/iter_00003

# 5. --restore --agents 3: structural change refused
ValueError: Cannot restore: the configuration changes the shape of the problem ...
  env_config.num_of_agents: checkpoint has 2, config asks for 3
  policies: checkpoint has ['policy_0', 'policy_1'], config asks for [..., 'policy_2']

# 6. --restore --envs-per-runner 2: non-structural change reported, run continues
[train] WARNING: restoring keeps the checkpoint's own config. These config values will NOT take effect:
  num_envs_per_env_runner: 1 (checkpoint, in effect) != 2 (config, ignored)

# 7. a champion added to league_state.json by hand, its module absent
[train] league state repaired against league_state.json:
  - champion history ['champion_1'] -> ['champion_1', 'champion_9'] (taken from the sidecar; ...)
  - dropped champion_9: the restored algorithm has no such module

# 8. algorithm_state.pkl of the newest checkpoint truncated to 64 bytes
[train] restoring from checkpoint: .../chkpt/iter_00008
[train] checkpoint unreadable (UnpicklingError: pickle data was truncated); falling back to the previous one
[train] restoring from checkpoint: .../chkpt/iter_00007
[train] resuming at iteration 7, training through 9

# 9. --from-checkpoint .../iter_00002 while iter_00003 exists: the older one wins,
#    and iteration 3 is retrained over the checkpoint that recorded it
[train] restoring from pinned checkpoint: .../chkpt/iter_00002
[train] league state verified: 1 champion(s)
[train] resuming at iteration 2, training through 4
[train] checkpoint at iter 3: .../chkpt/iter_00003

# 10. --from-checkpoint pointed at the tree rather than one save
ValueError: restore_path .../chkpt is not a checkpoint directory - it has no
rllib_checkpoint.json. Name one save, not the directory holding them. Available, newest first:
  .../chkpt/iter_00004
  .../chkpt/iter_00003
  .../chkpt/iter_00002

# 11. a config file with restore_path set and is_restore false
ValueError: restore_path is set to '.../chkpt/iter_00002' but is_restore is false, so the run
would start from scratch and ignore it. Set is_restore true to resume from that checkpoint, or
restore_path to null to start fresh.
```

Probes 10 and 11 raise before `build_config` runs — no `[PolicyHandler]` lines precede them — so a
mistyped path costs a second rather than an env build and a module spec.

Probe 8 is the one the old layout could not survive: a single overwritten directory means a
corrupt newest checkpoint is the *only* checkpoint. Note that a *partial* checkpoint does not
reliably raise — deleting `learner_group/` from a checkpoint still restored — which is why the
primary protection is the staged-then-renamed write, not the fallback.

`build_algo` returning the algorithm's own callback (probes 2, 4) and the reconciliation branches
(probe 7) are also covered by `test_checkpointing.py`, which stubs RLlib's loader so the cases run
in seconds rather than minutes.

---

## 16.9 Static measurements

```
sys.exit in library code:            6 live in envs/orderbook/orderbook.py
                                     (+2 commented out; +1 in CDA_env_rand.py's main guard)
print() in envs/ + train/:          ~86  (42 in the self-play callback, 13 in the env)
`import logging` anywhere:            0
Python files:                        63
Python LOC:                       7,478
test LOC:                         2,432
`expectedFailure` occurrences:        0
tracked build artefacts in git:    none
```

Dead-code confirmations (`grep`, `.py` files only):

- `g_store` was referenced only inside `log_handler.py` and `plot_handler.py`, both as
  `ray.util.get_actor("g_store")` lookups, and the detached actor in `store_handler.py` was
  **never instantiated** anywhere. All three modules have since been deleted — see
  [11 §1.4](11_logging_and_observability.md).
- `train/helper/helper.py` is imported by nothing — the only reference was a commented-out import
  in the since-deleted `store_handler.py`.
- `state_diff` is defined in `state_helper.py` and called nowhere.
- `random_agent.Random_agent` is referenced only by `trader.py`'s `import` and class declaration;
  `select_random_action` is never called.
- `sklearn` appears exactly once, in `action_helper.py`, for `shuffle(actions, random_state=...)`.
  **Since removed** — `rand_exec_seq` uses `Generator.permutation`, and `scikit-learn` is in
  neither `install_requires` nor `requirements.txt` (S3-5, S3-6).
- `six` appears in `orderbook.py` and `orderlist.py`, both for `cStringIO`. **Still there**, and
  now declared in `install_requires`: `envs/orderbook/` is off-limits to changes.
- The bare `import ray` in `continuousDoubleAuction_env.py` is unused — the only `ray.`-prefixed
  reference in the file is the `from ray.rllib...` import on the next line. **Since deleted**; the
  `MultiAgentEnv` import is the real dependency, which is why `ray[rllib]` is now declared.

Infrastructure confirmations:

- `.github/workflows/tests.yml` exists: `push` to `master`/`update_lib`, `pull_request`,
  `workflow_dispatch`; matrix Python 3.11 + 3.12; three staged jobs (unit tests → random-agent
  smoke run → RLlib integration). **Since changed**: Python 3.12 only — numpy stopped shipping
  3.11 wheels — and a second `packaging` job builds the wheel and constructs an env from it in a
  clean venv outside the checkout.
- `.gitignore` contains both `episode_data` and `gym_continuousDoubleAuction/episode_data`, with
  an explanatory comment.
- **Since removed**, along with `pickle` itself: `episode_data/` contained exactly two committed
  fixtures at the time of this probe: `test_ep_failure.pkl`,
  `test_ep_success.pkl`.
- `CODEOWNER` and `CODEOWNERS` both exist at the repo root.

**Supports:** S2-8, S3-6, S3-7, S4-1, S4-2, S4-3, S4-9, S4-18, and the CI / `.gitignore`
corrections in [README.md](../README.md).

---

## 16.10 NAV conservation is exact; the `float()` round trip went blind above `init_cash` 1e10

The episode-end check used to parse `info["NAV"]` — the exact `str()` of a `Decimal` — back with
`float()`. Three probes, run to decide whether that round trip was doing any harm and whether
`nav_tolerance` was absorbing it as the config note claimed.

**Probe A — 300-step rollout, 4 agents, `init_cash = 1,000,000`, uniformly random actions.**
Comparing, at every step, the sum of agent NAVs against `init_cash × 4`:

```
steps compared: 300
  exactly conserved under Decimal: 300/300
  exactly conserved under float  : 300/300
```

Conservation is exact under *both* readings. Individual NAVs do carry long fractional tails —
the Decimal residual prints as `0E-21`, i.e. an exact zero at 21 decimal places of scale — but
they cancel.

**Probe B — scale sweep, `init_cash` from `1e6` to `1e15`,** measuring how far the float reading
of the NAV sum falls from the Decimal one:

```
init_cash=1e6   reading differs by 2.8e-20    breaches 1e-6 = False
init_cash=1e7   reading differs by 4.0e-20    breaches 1e-6 = False
init_cash=1e8 … 1e15  reading differs by 0    breaches 1e-6 = False
```

The float error cancels because `total_nav` and `total_initial_cash` were computed at the same
magnitude, so the subtraction removes the common rounding. On these two probes alone the round
trip looks harmless — which is why the third probe matters.

**Probe C — detection, not representation.** Inject a *genuine* breach of `2e-6` (just over
`nav_tolerance`) and ask which reading still sees it:

```
init_cash=1e6   decimal_detects=True   float_detects=True   (float read 2.00002e-06)
init_cash=1e7   decimal_detects=True   float_detects=True   (float read 1.99676e-06)
init_cash=1e8   decimal_detects=True   float_detects=True   (float read 2.02656e-06)
init_cash=1e9   decimal_detects=True   float_detects=True   (float read 1.90735e-06)
init_cash=1e10  decimal_detects=True   float_detects=False  (float read 0)
init_cash=1e11  decimal_detects=True   float_detects=False  (float read 0)
init_cash=1e12  decimal_detects=True   float_detects=False  (float read 0)
```

**Conclusion.** Two things, and the second is the one that justifies the change.

1. At the default `init_cash = 1e6` the round trip was harmless, and `nav_tolerance` was **not**
   absorbing arithmetic noise — the justification given in `train_config.json` and
   [11 §1.5](11_logging_and_observability.md) was wrong on that point, and both are corrected.
2. **Above `init_cash ≈ 1e10` the float check could not resolve its own tolerance.** A real
   quarter-dollar of destroyed cash at `init_cash = 1e15` reads as exactly `0.0`; float's spacing
   there is `0.5`. The check would pass a corrupt ledger silently — the precise failure
   `strict_nav_check` exists to prevent. Note also that even where detection succeeds, the float
   *reading* is off (`1.90735e-06` for a true `2e-06`), so the `nav_conservation_error` metric was
   already imprecise at `1e9`.

The check is now `Decimal` end to end: exact by construction rather than by a cancellation that
happens to hold at one account size, with an expected error of `0` that `nav_tolerance` may be set
to `0` to enforce. `float()` survives only at the metrics boundary, which reduces with NumPy.
The default configuration was ~4 orders of magnitude from the cliff, so no existing run was
affected.

**Supports:** the correction to S3-9 in
[15_findings_and_recommendations.md](15_findings_and_recommendations.md), and
[11 §1.5](11_logging_and_observability.md).

---

## 16.11 Reproducing these probes

The rollout probes (16.3–16.6) are a single self-contained script that imports
`continuousDoubleAuctionEnv` directly. The training probe (16.7) builds a real `Algorithm`
through `build_config` and takes a few minutes. Neither writes into the repository when
`episode_data_dir=None` is passed; with the default the rollout probes will create
`episode_data/` in the working directory.

16.12 is reproducible: it seeds both the env and the action spaces. Everything before it is not.
When those were recorded, seeding was non-functional (S3-5), so **re-running would not reproduce
the exact numbers above** — only the signs, ratios and orders of magnitude. That was itself a
finding, and it is now fixed: all three of the env's random draws read `self.np_random`, so
`reset(seed=...)` pins an episode and a probe written to seed the env *is* reproducible. The
numbers recorded above were produced before that, from unseeded runs, and are left as they were —
re-running the same script today will not match them digit for digit unless it seeds.

---

## 16.12 After the 2026-08-30 fix pass

Re-measured on the fixed code, 4 agents × 400 steps at default config, `reset(seed=7)` **and** the
action spaces seeded — `Space.sample()` draws from a generator of its own, which `reset(seed=)` does
not touch, so a probe that seeds only the env is not reproducible. `CDA_rand.py` already seeded both;
three of the new tests did not, and were flaky until they did.

### Observation feature scales (S2-2)

| Block | min | max | std |
|---|---|---|---|
| `bid_price` | 0.0000 | 0.3385 | 0.0663 |
| `bid_size` | 0.0000 | 1.1136 | 0.2471 |
| `ask_price` | −0.5856 | 0.0000 | 0.0823 |
| `ask_size` | −0.9214 | 0.0000 | 0.2433 |

Size/price standard-deviation ratio **3.7×**, against **220×** before (sizes std 9.0 vs prices 0.04,
sizes reaching ±47). Every book feature is inside ±1.2 — a range a `tanh` first layer can use.

### The market scalars (S2-6, S2-7)

`extra_dim` 2 → 6. The last four did not exist; the tape loop that should have produced three of them
iterated, counted and discarded.

| Scalar | min | max | std | non-zero |
|---|---|---|---|---|
| `log_mid` | 0.3963 | 1.1612 | 0.1722 | 100.0% |
| `log1p_spread_ticks` | 0.0000 | 3.4012 | 0.8147 | 89.0% |
| `mid_return` | −0.1935 | 0.2308 | 0.0374 | 48.0% |
| `signed_volume` | −0.0800 | 0.1080 | 0.0255 | 57.5% |
| `log1p_trade_count` | 0.0000 | 1.6094 | 0.4480 | 57.8% |
| `trade_direction` | −1.0000 | 1.0000 | 0.7592 | 57.8% |

`log_mid` was 4.55–4.64 before centring: a standing +4.6 bias into a bounded activation while every
price feature beside it had a standard deviation of 0.04.

### The one-normaliser-per-stack property (S2-6)

Directly, rather than by correlation. A bid resting at 90 while the midpoint moves 100 → 96:

| | frame at mid 100 | frame at mid 96 |
|---|---|---|
| normalised bid L1, **before** | 0.100 | 0.063 |
| normalised bid L1, **after** | 0.0625 | 0.0625 |
| `log_mid`, after | 0.0000 | −0.0408 |

`mid_return` on the newest frame is −0.0400, i.e. 96/100 − 1. The order had not moved; its
denominator had. A correlation against `Δ log_mid` is *not* a good test of this — the best bid and
the midpoint are mechanically linked, so a genuine relationship exists either way, and the measured
correlation moved from +0.61 to −0.71 rather than to zero.

### Account and risk invariants (S1-5, S2-4, S2-11)

Over 1,600 agent-steps:

```
|position| > position_scale (1500)          : 0      (0.0%)   was 13.2% vs limit_max_size
open positions                              : 1582
  of which entry_vwap <= 0                  : 0      (0.0%)   was 5.0% on the rolled VWAP
agent-steps with negative cash              : 0
total NAV                                   : 4000000.000000000000000000000  (init 4,000,000)
```

The layered-closing-order exploit, re-run: a trader long 10 with `cash = 0` resting ten 10-lot asks
across ten price levels now has **nine of the ten refused**, and lifting what rested leaves it
**flat** rather than 90 lots short.

The self-cross, re-run: the tape does not grow, and neither trader's NAV moves — where before a
1-lot self-print at a chosen price moved **1,000 NAV** between them.

### Encoder order-sensitivity (S2-10)

Maximum absolute change in the `lstm` tokenizer's latent, real observation space:

| | before | positions only | positions + token-wise nonlinearity |
|---|---|---|---|
| book levels permuted | 1.8e-07 | 0.000000 | 0.070 |
| history reversed | 1.2e-07 | 0.000000 | 0.078 |

The middle column is the one worth keeping: positional embeddings alone change nothing under a
linear projection and a mean, because `mean(W·xᵢ + pᵢ)` is `W·mean(xᵢ) + mean(pᵢ)`.

**Supports:** S1-5, S2-2, S2-4, S2-5, S2-6, S2-7, S2-10, S2-11.

---

## 16.13 Continual Backprop feasibility probes (2026-09-11)

Two structural claims in [25_continual_backprop.md](25_continual_backprop.md), measured against the
working tree on Python 3.12.3 / Ray 2.56.1. Both are design claims about *seams*, not about
training outcomes — no run was performed, and nothing in §25 asserts a measured effect on learning.

### The learner mixin composes over the existing chain (§25 2.5)

`type(f"CBP{base.__name__}", (CBPLearnerMixin, base), {})`, for each learner the encoder registry
can select:

```
CDAPPOTorchLearner   -> CBPCDAPPOTorchLearner     jepa_in_chain=False
CDAJEPALearner       -> CBPCDAJEPALearner         jepa_in_chain=True
```

In both cases `compute_loss_for_module` still resolves to the base learner's — so the MoE
load-balancing term and, for `jepa`, the latent-prediction term both survive — while
`after_gradient_based_update` resolves to the mixin's. This is the property that makes Continual
Backprop orthogonal to `learner_class_for`'s single algorithm-wide slot rather than a competitor
for it.

`Learner.update` was also read directly: it calls `before_gradient_based_update`, runs the whole
minibatch/epoch loop, then calls `after_gradient_based_update` **once**. That is what lets a
replacement event avoid invalidating PPO's `exp(logp_new - logp_old)` ratio mid-update (§25 3.1).

### Outgoing-zeroing injects exactly zero perturbation (§25 1)

`blocks.feedforward(d_model=64, ff_dim=256)`, 256-row batch, replacing 3 units, with the
replacement split into its two stages:

| units replaced | drop old contribution | add new randomness |
|---|---|---|
| 3 lowest-utility | 0.097763 | 0.0000000000 |
| 3 highest-utility | 0.173780 | 0.0000000000 |

Utility is `mean|hᵢ| · Σⱼ|wᵢⱼ_out|`, the CBP contribution utility. The right-hand column is exactly
zero in both rows and is the half of the guarantee that is exact: once the outgoing weights are
zero, fresh random incoming weights are multiplied by zero and reach the output not at all. The
left-hand column is never zero — removing a unit's contribution changes the function by definition
— and is bounded only by *selecting* the minimum-utility unit, which on a freshly initialised
network is a weak bound because the utility spread is only ~2× (0.30 vs 0.67).

This is the measurement that corrected the note's first draft, which claimed the replacement was
"function-preserving at the instant it happens". It is not; only the new-randomness half is.

**Supports:** §25 1, §25 2.5, §25 3.1, §25 3.4.

---

## 16.14 Continual Backprop, against the papers (2026-09-11)

Measured on the working tree, Python 3.12.3 / Ray 2.56.1 / torch 2.13.0+cpu, while implementing
[25_continual_backprop.md](25_continual_backprop.md). Two findings shaped the design; the third
corrected a claim the note's first draft had made.

### The shipped default network is the papers' Continual PPO network (§25 2.2)

arXiv Appendix D specifies, for the reinforcement-learning experiments, "Policy Network: (256,
tanh, 256, tanh, Linear)", "Value Network (256, tanh, 256, tanh, linear)" and "separate networks
for policy and value function". Built from this repo's shipped defaults and enumerated:

```
encoder.actor_encoder.net.mlp.0: Linear 177->256    encoder.critic_encoder.net.mlp.0: Linear 177->256
encoder.actor_encoder.net.mlp.1: Tanh               encoder.critic_encoder.net.mlp.1: Tanh
encoder.actor_encoder.net.mlp.2: Linear 256->256    encoder.critic_encoder.net.mlp.2: Linear 256->256
encoder.actor_encoder.net.mlp.3: Tanh               encoder.critic_encoder.net.mlp.3: Tanh
pi.net.mlp.0:  Linear 256->26                       vf.net.mlp.0:  Linear 256->1
```

The structural consequence is the one worth recording: the **second hidden layer's outgoing weights
are in the head, not the encoder**. A walker confined to `encoder` reports one replaceable layer
per network where there are two. `find_replaceable_layers` returns 4 on the default configuration
and 2 under `vf_share_layers: true`, where the trailing layer has two consumers (`pi` at 26 outputs
and `vf` at 1) rather than one.

RLlib leaves `nn.Linear`'s own initialiser in place, so "resample from `d_l`" is
`U(-1/sqrt(fan_in), +1/sqrt(fan_in))`: layer 0's weights were measured at max |w| = 0.07516 against
a bound of 1/sqrt(177) = 0.075165.

### This repo performs ~320x fewer optimiser steps per env step than the papers (§25 3.6)

CBP's accumulator and maturity threshold are both counted in optimiser steps.

| | Adam steps / iteration | env steps / iteration | Adam steps per env step |
|---|---|---|---|
| Continual PPO (arXiv App. D: 10 epochs, 4096 batch, 128 minibatch) | 320 | 4,096 | 0.078 |
| This repo (4 epochs, 16,384 batch, `minibatch_size: null`) | 4 | 16,384 | 0.00024 |

With the Nature paper's PPO values (rate 1e-4, maturity 1e4, 256 units), the maturity threshold
alone is 2,500 iterations here against a default run of 16 - continual backprop would never fire
once. Hence `cbp_maturity_threshold: 100` and the `cbp_replacements` metric.

### `if c > 1`, not `while` - and the aliasing bug the tests found

Two corrections that came out of implementation rather than reading:

- The first implementation replaced units in a `while state.accumulator > 1` loop. Nature
  Algorithm 1 is explicit that it is an `If`, capping replacement at **one unit per layer per
  optimiser step** however high the rate is set. That cap is what bounds the per-step disturbance,
  and so is part of why the per-minibatch placement (§25 3.1) is safe. Measured through a real
  update: no layer's replacement count exceeds the optimiser-step count.
- `CBPLayerState.get_state` used `.detach().cpu()`, which on a CPU tensor **returns the same
  object**, so the state dict aliased the live tensors - a checkpoint would have serialised
  whatever the values had drifted to rather than what they were when taken. `.clone()` on both
  sides. Found by `test_state_round_trips_through_set_state`, which zeroed the live state and
  watched its own saved copy go to zero with it.

### End to end

A real one-iteration run with the rate forced high enough to fire (the shipped 1e-4 replaces
nothing in a test-length run, which is §25 3.6 restated): 4 layers discovered per trainable module,
the frozen `RandomRLModule` baselines correctly carrying none, units replaced, the correlates
logged per module, and NAV conservation still exact.

**Supports:** §25 1, §25 2.2, §25 3.1, §25 3.6, §25 4.2.

---

## 16.15 The four boundary bugs (2026-09-12)

Verified against RLlib 2.56.1's source while fixing what a code review of §16.14's implementation
found. Recorded because each is a claim about RLlib's behaviour rather than about this repo's, and
because none of them is reachable from this test suite.

### Device: the module is on the GPU before the mixin's setup runs

`TorchLearner.build` in order: sets `self._device` from `get_device(...)`, calls `super().build()`
(which builds each module and moves it to that device), then calls
`_make_modules_ddp_if_necessary()`. `CBPLearnerMixin.build` calls `super().build()` first, so by the
time it attaches, the module is both on its final device **and** already DDP-wrapped. State
allocated with a bare `torch.zeros(n)` therefore sat on the CPU against CUDA activations.

### DDP: no attribute forwarding, and a name prefix

`TorchDDPRLModule(RLModule, nn.parallel.DistributedDataParallel)` defines no `__getattr__`; the
wrapped module is a submodule named `module`. So `getattr(wrapper, "encoder", None)` is None, and
`named_modules()` yields `module.encoder...` rather than `encoder...`. `_make_modules_ddp_if_necessary`
applies this at `num_learners > 1` (the method's own docstring says `> 0`; the code says `> 1`).

`RLModule.unwrapped()` is defined on the base class and returns `self`, so calling it
unconditionally costs an undistributed run nothing.

### Restore: the rebuilt config wins

`build_algo` calls `Algorithm.from_checkpoint(path)`, which reconstructs from the config stored in
the checkpoint. The freshly built `ppo` config is passed only to `_check_restored_config`. Anything
consumed at Learner-construction or optimiser-construction time is therefore discarded on a restore,
which is what made `cbp_enabled: true` alongside `is_restore: true` a silent no-op.

`_check_restored_config` also returned early when the fingerprint intersection showed no divergence,
so a first attempt at the guard never ran for a checkpoint that predated the config groups. The
unrestorable check now runs before that return and compares against what a pre-feature run did
rather than against the intersection.

**Supports:** §25 3.5, §25 3.7, §18 5.6.3.
