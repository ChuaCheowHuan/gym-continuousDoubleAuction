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

## 16.10 NAV conservation is exact to Decimal rounding; the `float()` round trip went blind above `init_cash` 1e10

> **Corrected 2026-09-18.** The heading used to say conservation is *exact*. It is exact to about
> one unit in the 22nd decimal place, not to zero - see §16.18 and [15](15_findings_and_recommendations.md) S3-23.
> The 300-step probe below saw the residuals cancel; a longer one does not. Nothing else in this
> section changes: the `float()` blindness it is about is real and fixed.

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
encoder.actor_encoder.net.mlp.0: Linear 193->256    encoder.critic_encoder.net.mlp.0: Linear 193->256
encoder.actor_encoder.net.mlp.1: Tanh               encoder.critic_encoder.net.mlp.1: Tanh
encoder.actor_encoder.net.mlp.2: Linear 256->256    encoder.critic_encoder.net.mlp.2: Linear 256->256
encoder.actor_encoder.net.mlp.3: Tanh               encoder.critic_encoder.net.mlp.3: Tanh
pi.net.mlp.0:  Linear 256->26                       vf.net.mlp.0:  Linear 256->1
```

**Corrected 2026-09-12.** The first version of this entry recorded the input width as `177` and the
init bound as `1/sqrt(177)`, which is the observation as it stood *before* §37.4 widened it. The
tree these probes ran on already emitted 193, so the two numbers were carried over from an older
document rather than read off the run. Re-enumerated above and re-measured below; only the input
width and the bound change, and the claim the entry exists to support — the papers' `(256, tanh,
256, tanh, Linear)` network, separate trunks, second hidden layer consumed by the head — is
untouched, since none of it depends on the input width.

The structural consequence is the one worth recording: the **second hidden layer's outgoing weights
are in the head, not the encoder**. A walker confined to `encoder` reports one replaceable layer
per network where there are two. `find_replaceable_layers` returns 4 on the default configuration
and 2 under `vf_share_layers: true`, where the trailing layer has two consumers (`pi` at 26 outputs
and `vf` at 1) rather than one.

RLlib leaves `nn.Linear`'s own initialiser in place, so "resample from `d_l`" is
`U(-1/sqrt(fan_in), +1/sqrt(fan_in))`: layer 0's weights were measured at max |w| = 0.07198 against
a bound of 1/sqrt(193) = 0.071982.

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

---

## 16.16 The plasticity measurement, and the metric that got it wrong (2026-09-12)

[25](25_continual_backprop.md) §3.3 said the effect continual backprop treats had
never been shown to occur here, and §7 made measuring it the blocking step. This is
that measurement. It ran with `cbp_metrics_only: true`, which computes every
correlate and replaces nothing, so the run's trajectory is identical to one with
continual backprop switched off entirely.

**The answer is no - and the shipped metric said yes.**

### Setup

The *network* is the shipped default untouched: `(256, tanh, 256, tanh, Linear)` for
the policy, the same for the value, separate trunks - which §2.2 establishes is the
papers' own Continual PPO network. The *environment* is scaled down and the *update
schedule* up, to buy optimiser steps per wall-clock second, optimiser steps being the
clock plasticity runs on (§3.6): 4 agents, 512-step episodes, 8 epochs over 8
minibatches = 65 optimiser steps per iteration against the default 4. Seed 11, one
seed, CPU.

### Result

| | optimiser steps | effective rank |
|---|---|---|
| On the **training minibatch** (`cbp_batch_effective_rank`) | 17,875 | 97.1 → 73.2, **−24.6%** (policy_0); 97.1 → 73.7, −24.1% (policy_1) |
| On a **fixed corpus** of real observations, 8 layers | 19,500 | **+2.5% to −1.9%**; actor layers rise (ρ ≈ 1.0), critic layers fall slightly |

The first is a textbook plasticity collapse. The second says the network's
representational capacity did not move. Two further readings agree with the second:

- **The training-batch rank is not monotone.** It fell to 68.2 by iteration 178, then
  recovered to 73.2 by 275 as the league turned over; Spearman ρ weakened from −0.90
  to −0.71. Capacity loss does not come back.
- **Dead and saturated units stayed at exactly zero** throughout, on every layer. A
  network actually losing plasticity does not look like that - arXiv Appendix G
  reports ~90% of features saturated under plain backprop.

Mean incoming |w| rose monotonically (ρ = 1.00) but by 1.6-2.1%, which is not the
weight growth the papers associate with the effect.

### What the difference was

The rank of an activation matrix depends on the inputs as much as on the network, and
here the policy chooses its own inputs. Under S1-3 the reward makes passivity the
joint optimum, so a converging agent visits an ever narrower set of book states and
the rank of what it sees falls - with the network unchanged. Holding the observations
fixed removes that term, and when it is removed nothing is left.

### Consequence for the code

`cbp_effective_rank` as first shipped measured the training minibatch and so carried
this confound. On this system it produced a 24.6% false positive: a reader following
[18](18_configuration.md) §5.6.4, reading the correlates, and seeing that number would
reasonably have switched continual backprop on for no reason. It is renamed
`cbp_batch_effective_rank` - the name now says what it is measured on - and the
comparable version lives in `train/probe/rank.py`, where the corpus is collected once
and does not change while the encoder does.

Two related notes on the other correlates, both of which read zero here:

- `cbp_dead_unit_frac` (mean |h| below 0.01) is ReLU-shaped. A tanh unit does not die
  toward zero, so this cannot fire on the shipped network whatever happens to it.
- `cbp_saturated_unit_frac` uses the per-unit *batch mean* |h| > 0.9, i.e. "saturated
  on essentially every input". The papers define saturation per output (arXiv App. G),
  so this is the stricter reading and fires later than their Figure 19a would.

### Reproducing it

Seeded throughout, so unlike 16.3-16.6 this one does reproduce. The measuring run is a
`TrainConfig` with `cbp_metrics_only=True`, `cbp_metrics_every_n_updates=1`, `num_agents=4`,
`num_trained_agents=2`, `max_step=512`, `num_episodes_per_iter=2`, `num_epochs=8`,
`minibatch_size=128`, `seed=11`, `episode_data_dir=None`, and the `ppo` group's network left
alone; the per-iteration `cbp_*` metrics come straight out of `result["learners"][<module>]`.

The fixed-corpus column is the same loop with one addition: a batch of 512 real observations
collected once before training, under uniformly random actions, and pushed through the module
every fifth iteration with temporary forward hooks on the layers `find_replaceable_layers` returns.
Do **not** draw that batch from `observation_space.sample()` - the space is `Box(-inf, inf)`, so
gymnasium returns a standard normal out to +/-3.2 while real observations sit near [0, 1], and the
measurement would be of a representation nobody uses. `train/probe/rank.py` now does this properly
against the harness's own corpus, and is what a re-run should use.

### What this does not establish

~20,000 optimiser steps against the papers' 10⁶-10⁸, on a scaled-down environment, one
seed. A null here does not rule out loss of plasticity at the scale the project
actually needs ([25](25_continual_backprop.md) §2.3), and it says nothing about whether
continual backprop would help if the effect did appear. What it does establish is that
the effect is not detectable at this scale, and that the metric which said otherwise
was measuring the agent's behaviour rather than its network.

**Supports:** §25 3.3, §25 3.8, §23, §11, §18 5.6.4.


## 16.17 A cancel that could not cancel, and a tick that split every level (2026-09-18)

Two probes from the review pass recorded in [17](17_changelog.md) §44, both against the tree as
merged in PR #84. Reproduce with the tests named at the end; the raw script is a dozen lines of
`Trader` / `OrderBook` calls and a bare env at `tick_size` 0.1.

### S2-13: the cancel

One trader, 1,000 cash, rests a bid for all of it, then tries to cancel it and, separately, to
shrink it.

```
=== before ===
after limit 10 @ 100: cash 0.0   on_hold 1000.0  rejected 0
after cancel        : cash 0.0   on_hold 1000.0  rejected 1  orders resting 1
after modify 5 @ 100: cash 0.0   on_hold 1000.0  rejected 1  resting qty 10

=== after ===
after cancel        : cash 1000.0  on_hold 0.0   rejected 0  orders resting 0
after modify 5 @ 100: cash 500.0   on_hold 500.0 rejected 0  resting qty 5
```

The "before" rows are the finding: the refusal is counted in `num_rejected_step` and the order
stays live. Nothing else in the ledger moves, so NAV conservation never noticed.

### S3-4: the tick grid

A bare env at `tick_size` 0.1, anchor pinned at 100, one agent posting a limit bid at level 0 with
the aggressive offset every step, the other passing. Each step should move the best bid up one
tick and leave one order at each level.

```
=== before ===
step 0 bid levels: [('100.0', '251')]
step 1 bid levels: [('100.0', '251'), ('100.0999984741211', '251')]
step 2 bid levels: [('100.0', '251'), ('100.0999984741211', '251'), ('100.19999694824219', '251')]
step 3 bid levels: [..., ('100.29999542236328', '251')]
LOB_actions last: [{... 'type': 'limit', 'size': 251, 'price': 100.29999542236328}]

=== after ===
step 1 bid levels: [('100.0', '251'), ('100.1', '251')]
step 2 bid levels: [('100.0', '251'), ('100.1', '251'), ('100.2', '251')]
step 3 bid levels: [('100.0', '251'), ('100.1', '251'), ('100.2', '251'), ('100.3', '251')]
LOB_actions last: [{... 'type': 'limit', 'size': 251, 'price': 100.3}]
```

`100.0999984741211` is `float32(100.1)`. It came out of `agg_LOB_raw`, and the book keyed a price
level on it. With the join offset instead of the aggressive one the same agent, before the fix,
rested a *new* order at a new one-ulp level every step rather than upserting — which is what
`test_tick_grid.py::TestFractionalTickBookStaysConsistent::test_requoting_the_same_level_upserts`
now pins.

### What this does not establish

Both probes are at default `init_cash` and small books. The cancel fix is a change to the approval
predicate only; whether agents *learn* to use cancels now that they work is a training question
this log does not answer. The grid fix is exact for any tick that `str()` round-trips, which is
every tick anyone writes in a JSON file; it does not make the book itself enforce a grid, and the
dead `OrderBook.tick_size` parameter is still there (S3-4).

**Tests:** `test_cash_check.py::TestCancelAndModifyNeverTrapCash` (7), `test_tick_grid.py` (14).
Suite after: 935 unit + 153 integration = 1,088, all passing.

**Supports:** §15 S2-13, §15 S3-4, §04 3, §06 1.5, §18 6.


## 16.18 The recommendations pass: closing-side escrow, a rounding residual, and a protocol run once (2026-09-18)

The six recommendations of [17](17_changelog.md) §44.5, executed in §45. Three of them produced
measurements; the rest produced code and tests and are recorded there.

### S1-5's tail: escrow held against closing orders

Six seeds x 400 steps x 6 agents of uniformly random play, at two starting balances. "Closing-side
escrow" is the notional escrowed against this trader's resting orders on the side that would
reduce its position. A refusal "would have passed" if `cash + closing escrow` covered the order.

```
init_cash 20,000  (before)
  agent-steps with closing-side escrow > 0:  4,898 / 14,400 (34.0%)
  closing-side share of total escrow:        59.8%
  refusals: 3,712; while closing escrow > 0: 1,602; would pass if it counted: 793
init_cash 100,000 (before)
  agent-steps with closing-side escrow > 0:  6,318 / 14,400 (43.9%)
  closing-side share of total escrow:        47.5%
  refusals: 607; while closing escrow > 0: 508; would pass if it counted: 409

after (Trader._closing_escrow counted as spendable)
  init_cash  20,000: refusals 3,241 (from 3,712)
  init_cash 100,000: refusals   340 (from 607)
```

At 1,000,000 - the shipped default - the check never binds under random play (0 refusals), so
the numbers above are the regime where it does. The "would pass" column is an estimate made with
the same price estimate `_order_approved` uses; the "after" rows are the real count.

### S3-23: conservation is exact to 1e-22, not to zero

Twenty seeds x 600 steps x 4 agents, `init_cash` 100,000, `sum(nav) - 4 x init_cash` at every
step, **on the tree before any ledger change in this pass** (`trader.py` at commit `cb348b6`):

```
steps: 12,000; steps with non-zero error: 2,116 (17.6%); worst |error|: 7E-22
```

Same measurement after the pass: 1,773 (14.8%), worst `8E-22`. The difference is the different
sequence of fills, not the change. §16.10's "exactly conserved 300/300" was a 300-step sequence
where the residuals happened to cancel; its heading is corrected below. Cause and fix are in
[15](15_findings_and_recommendations.md) S3-23.

### What the Hypothesis suite found on its first run

Two failures, both real, both now fixed or reclassified:

- **Time priority within a level was not reflected in timestamps.** At one ask level the stamps
  read `[16, 12]`: a size-reducing `modify` kept the order's head-of-queue position (correct) and
  overwrote its timestamp with the modify time (not correct - `_get_order_ID`'s FIFO rule for the
  next modify then picked the wrong order). `Order.update_quantity` now moves the timestamp only
  when it moves the order. Found at seed 15, six steps.
- **The conservation residual above**, at seed 161.

### The comparison driver, run once at smoke scale

`python -m gym_continuousDoubleAuction.train.compare --encoders mlp transformer --seeds 0 1
--iters 1 --agents 4 --trained-agents 2 --max-step 64 --episodes-per-iter 2 --probe-episodes 1
--probe-steps 128 --horizons 1 5`, from an empty directory, 11 seconds of wall time:

| encoder | seeds | params | return | vf_explained_var | pass_action_fraction | separated on |
|---|---|---|---|---|---|---|
| mlp | 2 | 237,851 | -0.00161 ± 0.0014 | -1 ± 0 | 0.0957 ± 0.0193 | nothing |
| transformer | 2 | 675,483 | -0.000987 ± 0.000112 | -0.338 ± 0.35 | 0.104 ± 0.0249 | nothing |

Plus eight `probe:<target>@<horizon>` columns (the `two_sided` target was dropped by the harness
because a 129-observation corpus had one class, which is the harness working as documented). The
table is reproduced to show the *shape* of the output; every number in it is one iteration of
training on 128 env steps and means nothing about either architecture, which is what the
"Fewer than three seeds" footer the driver appends says. The protocol run at scale - 16 iterations,
three seeds, every registered encoder - is the item still open in [10](10_testing.md) §8.

**Supports:** §15 S1-5, S3-4, S3-7, S3-23, S4-6, S4-13, S4-14; §04 3; §10 2.2, 2.5, 8; §18 5.5, 6.


## 16.19 Conservation made exact, and how often an order-management action lands (2026-09-18)

### S3-23 closed

`Account.cost_basis` replaces the stored VWAP quotient as the ledger's primary quantity, and
`mark_to_mkt` forms `position_val` with one product. The §16.18 measurement, re-run unchanged:

```
init_cash 100,000, tick 1  : steps 12,000; non-zero conservation error: 0 (was 2,116 / 17.6%); worst 0 (was 7E-22)
init_cash 100,000, tick 0.1: steps  3,600; non-zero conservation error: 0;                         worst 0
```

`test_orderbook_properties.py::TestEnvInvariants` asserts `sum(nav) == total` again, with a comment
that a tolerance there would now be the regression. Every ledger test that builds a position by
hand (`acc.net_position = ...; acc.VWAP = Decimal(100)`) still passes through the `VWAP` setter,
which writes the basis as `value × |net_position|`.

### S3-24 measured

Five seeds × 400 steps × 6 agents of uniformly random play, at the shipped `init_cash`. An action
"hit" if `num_unmatched_step` stayed 0 for that agent on that step.

```
modify: issued 2,659; agent had >=1 resting order 1,885 (71%); hit 1,269 (48% of issued, 67% of those with an order)
cancel: issued 2,738; agent had >=1 resting order 1,992 (73%); hit   196 ( 7% of issued, 10% of those with an order)
own resting orders per agent-step: mean 1.6, median 1, p90 4, max 7; none on 26% of agent-steps
```

The cancel number is the finding: with one order resting and thirty price codes, a cancel that
does not know where the order sits lands one time in thirty, and random play is the policy that
does not know. The modify number is the other half: it lands whenever *any* order is on that side,
because it cannot choose which. The plan that follows from both is
[15](15_findings_and_recommendations.md) S3-24.

**Supports:** §15 S3-23, S3-24; §04 5; §10 2.5.


## 16.20 Order management made aimable: the hit rates and the before/after run (2026-09-18)

[15](15_findings_and_recommendations.md) S3-24, phases 1-4. Every number here is uniformly
random play at the shipped config unless stated; "hit" means `num_unmatched_step` stayed 0 for
that agent on that step.

### The hit rate, through four designs

Five seeds x 400 steps x 6 agents, the §16.19 script re-run on each tree:

| aiming rule | cancel hits (of issued) | modify hits (of issued) | agents with >=1 order resting |
|---|---|---|---|
| by exact price (cancel) / FIFO (modify) - before | **7%** | 48% | 71-73% |
| `order_slot`, 9 codes, a slot past the count misses | 12% | 14% | 69-70% |
| `order_slot`, 5 codes, a slot past the count misses | 19% | 23% | 66-67% |
| `order_slot`, 5 codes, **clamped** to the deepest own order - shipped | **35%** | **36%** | 58-60% |

Of the times the agent had anything resting on either side, the shipped rule lands 58% of cancels
and 62% of modifies; the remainder are actions on the side with nothing on it, which is the only
miss the design leaves. Two things the table says that the plan did not predict: a slot head with
dead upper slots makes *modify* worse for a random policy than the FIFO rule it replaced, because
FIFO landed whenever any order existed; and the fourth column falls as cancels start to work -
agents that can cancel hold fewer orders, so "had an order" is no longer a fixed 70%.

### The before/after comparison run

`train.compare --encoders mlp --seeds 0 1 2 --iters 8 --agents 4 --trained-agents 2 --max-step
128 --episodes-per-iter 4 --no-probe`, once on the tree at `5462604` (before) and once on this
one (after). Three seeds each, means ± standard deviation across seeds:

| tree | params | return | vf_explained_var | pass_action_fraction | unmatched_action_fraction | maker_fill_ratio_max |
|---|---|---|---|---|---|---|
| before | 237,851 | -0.00207 ± 0.00157 | -0.46 ± 0.332 | 0.121 ± 0.0155 | 0.315 ± 0.00318 | 0.635 ± 0.028 |
| after | 250,912 | -0.000759 ± 0.00175 | -0.374 ± 0.411 | 0.105 ± 0.00522 | 0.289 ± 0.0273 | 0.629 ± 0.00948 |

Nothing is *separated* by the driver's rule, and nothing should be read as learning: 8 iterations
at `lr` 5e-05 leaves both policies near their initialisation, and two of the four agents are the
random baselines whose behaviour the aiming rule changes directly. What the table does show is
the plumbing end to end - the new heads and fields flow through RLlib, the recorder and the
metrics - and the direction of the mechanical effect: the league-wide dead-action share falls
(0.315 → 0.289) while the pass and maker fractions hold, with 13,061 more parameters for the
wider input and head. The learning claim of phase 4 - "agents that can aim cancels quote more and
hold fewer stale orders" - needs the run at scale ([10](10_testing.md) §8).

### Layout stamp

Every checkpoint written on this tree carries `"layout": {"observation_version": 2,
"action_version": 2, ...}` in its `league_state.json`; the checkpoints under
`cmp_before/` carry no stamp, and `check_layout_stamp` refuses them as layout 1
(`test_layout_version.py`).

**Supports:** §15 S1-2, S3-24, S4-19; §05 1.0.1, 7.7; §06 1.5; §07 1; §10 2.6.


## 16.21 The hygiene pass: two timings and a coverage number (2026-09-18)

**S4-11, measured before touching it.** 300 random-play steps, 8 agents, `is_render` off:

```
step               1.05 ms
set_agg_LOB        0.062 ms   (5.9% of a step)  <- the pre-action snapshot
8-agent ID scan    0.2 us     <- _process_counter_party's loop
```

The scan was never a cost and is O(1) now only because the change is one line. The snapshot was
worth gating: it is now rebuilt only when `set_done` pulled a bankrupt trader's orders after the
post-action snapshot (`_snapshot_stale`), or when the render asks for its "@ t-1" table. In every
other case the two snapshots were byte-identical - nothing touches the book between the end of one
step and the start of the next - so the observation, the action prices and every test are
unchanged.

**S4-6, coverage.** `pytest --cov` over the unit suite, scoped by `pyproject.toml` to `envs/` and
`train/` (tests, the orderbook example scripts and `visualize/` excluded):

```
TOTAL   5716 statements   1094 missed   1662 branches   186 partial   79.1%
```

Least covered, and why: `train/pretrain/__main__.py` and `train/probe/__main__.py` 0% (CLI entry
points run by hand and by the runbook, not by a test); `cbp_learner.py` 13.5% (its 41 tests are in
the integration suite, which this run excluded); `CDA_rand.py` 20% (the CI smoke run covers it);
`evaluate.py` 27% (the integration test covers the rest); `exchg_helper.py` 52% (the render path,
which the suite runs only at DEBUG).

**Supports:** §15 S4-6, S4-11; §10 7, 8.

## 16.22 Positive asks and a finite Box: the ranges, the clip the counter caught, and the before/after run (2026-09-18)

S4-17 (drop the negated-ask convention) and S4-15 (finite observation bounds) were left out of the
hygiene pass because each changes what every encoder is fed. This is the measured pass for both:
observation layout version 3.

**Protocol for the ranges.** `env.reset(seed)` and every agent's action space seeded, actions
sampled from the space, 20 episodes × 400 steps, the *unclipped* vector recorded (bounds widened to
±10¹² for the measurement), then the clip count against the shipped bounds. Two configs: the
shipped one (8 agents, 1,000,000 cash, seeds 100–119) and a stress one (6 agents, 20,000 cash,
anchors 5–500, tick 0.1, seeds 200–219). 64,000 and 48,000 agent-steps.

| field | shipped min | shipped max | stress min | stress max | bound |
|---|---|---|---|---|---|
| `bid_price` | **−18.00** | 0.966 | −3.00 | 0.968 | [−128, 1] |
| `bid_size` | 0 | 1.444 | 0 | 1.096 | [0, 8] |
| `ask_price` | −0.706 | **22.00** | −0.500 | 7.50 | [−1, 128] |
| `ask_size` | 0 | 1.343 | 0 | 1.044 | [0, 8] |
| `log_mid` | −3.454 | 1.664 | **−5.522** | 2.291 | [−8, 8] |
| `log1p_spread_ticks` | 0 | 3.689 | 0 | 3.497 | [0, 10] |
| `mid_return` | −0.944 | **13.00** | −0.750 | 1.750 | [−1, 64] |
| `signed_volume` | −0.526 | 0.411 | −0.495 | 0.379 | [−8, 8] |
| `log1p_trade_count` | 0 | 2.079 | 0 | 1.792 | [0, 8] |
| `trade_direction` | −1 | 1 | −1 | 1 | [−1, 1] |
| `position` | −0.866 | 0.851 | −0.667 | 0.827 | [−1, 1] |
| `position_val` | −0.039 | 0.206 | −0.078 | 1.035 | [−8, 8] |
| `cash` | 0.723 | 1.031 | −0.913 | 1.064 | [−8, 8] |
| `cash_on_hold` | 0 | 0.227 | 0 | 1.037 | [0, 8] |
| `nav` | 0.923 | 1.078 | 0.755 | 1.143 | [−8, 8] |
| `drawdown` | −0.090 | 0 | −0.273 | 0 | [−8, 0] |
| `vwap_vs_mid` | **−31.23** | 0.950 | −13.29 | 0.750 | [−128, 1] |
| `realised_pnl` | −0.077 | 0.078 | −0.245 | 0.143 | [−8, 8] |
| `time_left` | 0 | 0.998 | 0 | 0.998 | [0, 1] |
| own sizes | 0 | 0.961 | 0 | 0.812 | [0, 8] |
| own counts, `unmatched_last_step` | 0 | 1 | 0 | 1 | [0, 1] |

**Clipped under the shipped bounds: 0 of 64,000 agent-steps, 0 of 48,000.**

Three things the table says.

1. **The identities hold.** Every side that is mathematics — `bid_price < 1`, `ask_price > −1`,
   `mid_return > −1`, `drawdown ≤ 0`, `vwap_vs_mid < 1`, the tanh, the `[0, 1]` fields — is
   approached and never crossed. `log_mid` at the stress config sat at −5.52 against a floor of
   `log(min_tick) − log_mid_centre = log(0.1) − log(50) = −6.21`; an unseeded run before this one
   reached −6.21 exactly, which is the floor being touched, not noise.
2. **The bold numbers are the tick floor, not prices.** An ask at 23× the midpoint, a bid at 19×
   in an older frame, a midpoint that grew fourteenfold in one step, a cost basis at 32× the
   mark. This section first attributed them to the one-sided-book fallback; §16.23 traced them
   cell by cell and found every one in a book whose midpoint had random-walked down to one to
   three ticks — mostly two-sided books — where a level a dozen ticks away is a multiple of the
   price. Their extremes are set by `price / min_tick`, not by the sample, and vary run to run —
   three 20-episode runs gave `ask_price` maxima of 18, 21 and 22. The bounds on those four fields
   are therefore a choice of where the counter starts, at more than 4× the widest value seen,
   rather than a claim that the market cannot exceed them; and the numbers are the first
   measurement S3-15's coordinate problem has had against it.
3. **Everything else is well inside**, by 4× or more: the sizes peak near 1.4 against 8, the
   NAV-normalised ratios stay within −1 … 1.15 against ±8, `signed_volume` within ±0.6 against ±8.

**The clip the counter caught.** The first candidate bounds put `bid_price` on `[0, 1]` and
`ask_price` on `[0, 4]`, reasoning from the newest frame: `P_bid ≤ M ≤ P_ask`. The smoke test
clipped **192 elements in 50 steps of 4 agents**, every one in an *older* frame's price row. The
stack is normalised by the newest frame's midpoint (§16.12, S2-6), so a bid resting above `M_t`
three steps ago reads `(M_t − P) / M_t < 0` — by design. A `(−inf, inf)` Box would have said
nothing; a clipping Box without a counter would have silently flattened a fifth of the older
frames' L1 prices to zero. The second candidate (`bid_price ≥ −4`, `ask_price ≤ 4`, `mid_return ≤
4`, `vwap_vs_mid ≥ −8`) clipped 816 of 64,000 agent-steps (1.28%) at the shipped config, all in
the four fallback-tail fields; that is what led to the wide bounds above.

**Before/after with `train.compare`**, the S3-24 protocol of §16.20: `mlp` and `transformer`,
seeds 0 1 2, 8 iterations, 4 agents (2 trained), `max_step` 128, 4 episodes per iteration, no
probe. Before = commit `96bd34c` (layout 2, negated asks, infinite Box); after = this tree
(layout 3). Same command, same seeds.

**Before** (layout 2):

| encoder | seeds | params | return | vf_explained_var | pass_action_fraction | order_rejection_fraction | unmatched_action_fraction | maker_fill_ratio_max | separated on |
|---|---|---|---|---|---|---|---|---|---|
| mlp | 3 | 250,912 | −0.00147 ± 0.000765 | −0.392 ± 0.304 | 0.105 ± 0.00224 | 0 ± 0 | 0.293 ± 0.0159 | 0.67 ± 0.0235 | pass_action_fraction, maker_fill_ratio_max |
| transformer | 3 | 682,016 | −0.00332 ± 0.00346 | −0.5 ± 0.193 | 0.136 ± 0.0153 | 0 ± 0 | 0.289 ± 0.0198 | 0.62 ± 0.0222 | pass_action_fraction, maker_fill_ratio_max |

**After** (layout 3; the new `obs_clip_fraction` column):

| encoder | seeds | params | return | vf_explained_var | pass_action_fraction | order_rejection_fraction | unmatched_action_fraction | maker_fill_ratio_max | obs_clip_fraction | separated on |
|---|---|---|---|---|---|---|---|---|---|---|
| mlp | 3 | 250,912 | −0.00272 ± 0.00235 | −0.711 ± 0.105 | 0.111 ± 0.00674 | 0 ± 0 | 0.287 ± 0.0135 | 0.623 ± 0.0175 | 0 ± 0 | vf_explained_var, maker_fill_ratio_max |
| transformer | 3 | 682,016 | −0.000517 ± 0.000946 | −0.465 ± 0.134 | 0.119 ± 0.0127 | 0 ± 0 | 0.269 ± 0.0217 | 0.668 ± 0.00828 | 0 ± 0 | vf_explained_var, maker_fill_ratio_max |

How to read it, in the order the columns matter:

- **`obs_clip_fraction` is 0 ± 0 for both encoders across all three seeds.** Training play, not
  only random play, stayed inside the declared bounds. This is the one number this section
  exists to produce.
- **Nothing that separates the encoders before separates them after, and vice versa, at a
  level that means anything.** Every return is within noise of zero, `vf_explained_var` is
  negative on both trees (eight iterations of 512-step batches is far short of a critic), and the
  "separated on" column flipped from `pass_action_fraction` to `vf_explained_var` between two runs
  that differ only in the observation's sign convention and bounds - which is a statement about
  the scale of this protocol, not about the layout. The activity fractions (`pass` 0.10–0.14,
  `unmatched` 0.27–0.29, `rejection` 0) are the same on both trees to within a standard deviation:
  the layout change did not alter what near-random policies do, which is what one expects of a
  sign flip and a clip that never fires.
- **The parameter counts are identical**, as they must be: same width, same heads.

As with §16.20, this is a smoke-scale run. It proves the protocol runs on layout 3, that the
clip counter is 0 in training, and that the change did not move the near-random baseline. Whether
a positive-ask book lets an encoder learn faster is a question for the run at scale ([10](10_testing.md)
§8), which no tree has had yet.

**Supports:** §15 S4-15, S4-17, S3-14; §05 1.2, 2.2, 2.3, 7.6; §18 4.1.1; §10 (`test_observation_bounds.py`).

## 16.23 What zero meant, how often, and where the price tails really come from (S3-14) (2026-09-18)

The measured pass for S3-14. Same random-play protocol as §16.22: 20 seeded episodes × 400 steps at
the shipped config (8 agents, 1,000,000 cash) and 20 at the stress config (6 agents, 20,000 cash,
anchors 5–500, tick 0.1); `env.reset(seed)` and every action space seeded. Per step: which branch
of the reference-price chain `mid_price` took, and for every price cell of the newest frame whether
the level was occupied (raw size > 0) and whether the normalised price read exactly `0.0`.

**Before** (layout 3):

| | shipped | stress |
|---|---|---|
| steps two-sided | 7,363 (92.0%) | 1,883 (23.5%) |
| steps bid-only / ask-only | 343 / 284 (**7.8%**) | 1,297 / 1,259 (**32.0%**) |
| steps empty (→ `last_price`) | 10 (0.1%) | 3,561 (**44.5%**) |
| occupied price cells, newest frame | 53,604 | 11,663 |
| … reading exactly 0.0 | **627 (1.17%)** | **2,556 (21.9%)** |
| … of which the lone L1 of a one-sided book | 627 (all) | 2,556 (all) |
| … at L2+ or in a two-sided book | 0 | 0 |
| occupied cells in the older frames reading 0.0 | 2,273 of 159,960 | 5,880 of 34,800 |
| absent cells (the other meaning of 0.0) | 106,396 | 148,337 |

So the ambiguity was exactly the third meaning: on every one-sided step the best quote *was* the
reference price and read `0.0`, indistinguishable from the 106,396 absent cells around it. A price
resting exactly at a two-sided midpoint never happened in the newest frame (it cannot: the midpoint
sits strictly between the two best quotes), and in the older frames it is the same one-sided quote
carried forward while the book stayed one-sided.

**The tails, traced.** The six widest normalised price cells in each config, with the midpoint,
the last trade and the chain branch at that step:

```
shipped:  value 9.8  M 2.5  last 27.0  two_sided   (ask at 27 against a mid of 2.5, tick 1)
          value 9.8  M 2.5  last  4.0  two_sided   x5, same episode, consecutive steps
stress:   value 3.5  M 0.4  last  0.7  two_sided   (tick 0.1)
```

Every one is a **two-sided** book whose price level has walked down to a few ticks — `M = 2.5` on a
tick of 1 — so a resting level a dozen ticks away reads as a multiple of the price. Under random
play every ghost quote is `last_price ± a few ticks` and every trade moves `last_price`, so the
level random-walks; the median episode's lowest `M` was 0.60 of its anchor and the worst 0.017.
§16.22 had attributed these tails to the one-sided fallback; they are the additive-tick coordinate
of S3-15 instead, and §16.22 is corrected to say so.

**The fix**, both halves of the register's proposal: two occupancy rows in every snapshot
(`1.0` where the level holds an order, carried in the raw frame so each frame keeps the occupancy
it was taken with), and the last trade as the reference price of a one-sided book — the chain
`mark_price` has used since S2-5 — so the lone quote reads its distance from the print rather than
`0.0`. Observation layout 4, 296 floats.

**After** (layout 4), same seeds:

| | shipped | stress |
|---|---|---|
| chain branches | unchanged (the book is the book) | unchanged |
| occupancy row ≠ `size > 0`, any cell, any step | **0** | **0** |
| occupied price cells reading exactly 0.0 | **354 (0.66%)** | **1,304 (11.2%)** |
| … lone L1 of a one-sided book | 323 | 1,273 |
| … elsewhere | 31 | 31 |

The zeros that remain are quotes resting exactly at the last trade — the remainder of a partial
fill, on a one-sided book, or a fresh quote at the print — and every one is now `occupied = 1.0`,
so `0.0` means "at the reference price", not "nothing here". The widest cells after the change are
the same tick-floor episodes (`value 22, M 1.0, last 1.0, ask_only` at the shipped config): the
reference for a one-sided book is now the last trade, and when the last trade is at the tick floor
so is the reference. The bounds of §16.22 still hold with 0 clips.

**Before/after with `train.compare`**, the protocol of §16.20 and §16.22 (`mlp`, `transformer`,
seeds 0 1 2, 8 iterations, 4 agents, 2 trained, `max_step` 128). Before = commit `1bbb264`
(layout 3, the "after" table of §16.22); after = this tree (layout 4).

**Before** (layout 3, 216 floats):

| encoder | seeds | params | return | vf_explained_var | pass_action_fraction | order_rejection_fraction | unmatched_action_fraction | maker_fill_ratio_max | obs_clip_fraction | separated on |
|---|---|---|---|---|---|---|---|---|---|---|
| mlp | 3 | 250,912 | −0.00272 ± 0.00235 | −0.711 ± 0.105 | 0.111 ± 0.00674 | 0 ± 0 | 0.287 ± 0.0135 | 0.623 ± 0.0175 | 0 ± 0 | vf_explained_var, maker_fill_ratio_max |
| transformer | 3 | 682,016 | −0.000517 ± 0.000946 | −0.465 ± 0.134 | 0.119 ± 0.0127 | 0 ± 0 | 0.269 ± 0.0217 | 0.668 ± 0.00828 | 0 ± 0 | vf_explained_var, maker_fill_ratio_max |

**After** (layout 4, 296 floats):

| encoder | seeds | params | return | vf_explained_var | pass_action_fraction | order_rejection_fraction | unmatched_action_fraction | maker_fill_ratio_max | obs_clip_fraction | separated on |
|---|---|---|---|---|---|---|---|---|---|---|
| mlp | 3 | 291,872 | −0.00209 ± 0.00112 | −0.332 ± 0.592 | 0.107 ± 0.00611 | 0 ± 0 | 0.289 ± 0.0253 | 0.645 ± 0.0153 | 0 ± 0 | nothing |
| transformer | 3 | 682,528 | −0.00132 ± 0.001 | −0.189 ± 0.517 | 0.102 ± 0.00977 | 0 ± 0 | 0.298 ± 0.0208 | 0.639 ± 0.0406 | 0 ± 0 | nothing |

Reading it:

- **The parameter counts moved as the width did.** The `mlp` gained 40,960 parameters: its first
  layer is `296 × 512` rather than `216 × 512`. The transformer gained 512: its input projection
  is per token, and a level token went from 6 to 8 channels. That asymmetry is the tokenising
  encoder's whole argument, made concrete - a feature added per level costs it almost nothing.
- **`obs_clip_fraction` stays 0 ± 0**, so the occupancy rows and the new reference price sit
  inside the §16.22 bounds under training play as well.
- **Nothing separates, before or after, at a level that means anything.** The near-random
  baseline did not move: pass fractions 0.10–0.12, unmatched 0.27–0.30, rejections 0. The
  "separated on" column went from two metrics to none between two runs that differ only in this
  layout change, which is a statement about the scale of the protocol (eight iterations of 512
  steps), not about the layout. `vf_explained_var` is negative on both trees.

As in §16.20 and §16.22, this proves the protocol runs on layout 4 and that the change did not
move the near-random baseline. Whether a network that can see occupancy learns faster is the run
at scale's question ([10](10_testing.md) §8).

**Supports:** §15 S3-14, S3-15; §05 1.3, 2.1, 7.2; §18 4.1; §10 (`test_occupancy_channel.py`).

## 16.24 The level index measured, and the grid that replaces it (S3-15) (2026-09-18)

The measured pass for S3-15. Protocol as §16.22–16.23: 20 seeded episodes × 400 steps of random
play at the shipped config (8 agents, 1,000,000 cash, tick 1) and at the stress config (6 agents,
20,000 cash, anchors 5–500, tick 0.1). Three questions: how far does level *d* sit from the
reference price `R` (the §2.1 chain snapped to the tick) and how often does its price change; where
does the action's price code *j* actually land; and how much of the resting book a fixed window
of ±`k_rows` ticks around `R` would show.

**Before** (`levels` layout, commit `7353388`), shipped config:

| level d | ticks from R, mean ± sd | range | P(price changed between steps) |
|---|---|---|---|
| 0 | 3.8 ± 2.5 | −20 … +27 | 0.35 |
| 1 | 7.0 ± 3.8 | −14 … +37 | 0.47 |
| 2 | 9.5 ± 4.3 | −12 … +46 | 0.53 |
| 4 | 12.9 ± 4.8 | +3 … +43 | 0.52 |
| 7 | 17.3 ± 5.9 | +9 … +41 | 0.33 |

(bid side; the ask side is the same to within 0.5 tick.) The negative ranges are older-frame
effects on one-sided books. So "level 3" is a coordinate that wanders over some forty ticks and
moves on every second step.

| price code j | realised ticks from R, bids | asks |
|---|---|---|
| 0 | 3.6 ± 2.5 | 4.0 ± 2.7 |
| 1 | 6.5 ± 4.6 | 6.2 ± 4.4 |
| 3 | 6.8 ± 5.6 | 7.0 ± 5.8 |
| 6 | 7.2 ± 5.0 | 7.4 ± 4.9 |
| 9 | 9.4 ± 4.9 | 10.0 ± 4.5 |

The code carried almost no positional meaning: codes 1–6 indistinguishable, every code spanning
0 to 20 ticks. Stress config: the same shape at slightly smaller numbers (level 0 at 3.7 ± 3.5,
codes 0–9 from 2.0 to 9.8 with sd 2.3–3.5).

Window coverage in `levels` mode — resting volume within ±w ticks of `R`:

| | ±10 | ±16 | ±20 | ±32 |
|---|---|---|---|---|
| shipped | 72.5% | 93.9% | 97.5% | 99.8% |
| stress | 81.4% | 96.8% | 98.9% | 100% |

**The fix.** `book_mode: "grid"`: two size rows over `2 k_rows + 1` tick offsets from `R`, every
frame re-gridded against the newest `R_t`, price code *j* quoting *j* ticks from `R` on the passive
side ([05](05_observation_space.md) §1.4, [06](06_action_space.md) §2.1.1). The `levels` layout
stays as the other value of the key.

**After** (`grid`, this tree), same seeds:

| price code j | realised ticks from R, bids | asks |
|---|---|---|
| 0 | −0.2 ± 0.9 | 0.2 ± 0.9 |
| 1 | 0.7 ± 0.9 | 1.3 ± 0.9 |
| 3 | 2.8 ± 0.9 | 3.3 ± 0.9 |
| 6 | 5.7 ± 1.0 | 6.3 ± 0.9 |
| 9 | 8.7 ± 1.1 | 9.2 ± 0.9 |

Code *j* lands at *j* ± 0.9 ticks; the 0.9 is the `price_offset` head shading by one tick either
way, and the ±0.3 skew between sides is the half-tick between `M` and `R` on a two-sided book. Same
at the stress config (bids 1.0 → 8.9, asks 1.1 → 9.1, sd 0.8–0.9). The observation's cell for
code *j* is `k_rows ∓ j` by construction, so the two coordinates are one.

Coverage in `grid` mode, because the agents now quote on the grid:

| | ±10 | ±16 | ±20 | ±32 |
|---|---|---|---|---|
| shipped | 93.3% | 99.5% | 99.9% | 100% |
| stress | 93.9% | 99.8% | 100% | 100% |

The occupied best level still sits 2.2 ± 1.7 ticks from `R` and changes on 40% of steps — the
book is as dynamic as it was — but that is now something the observation *shows* (the cell that
is non-zero moves) rather than something the coordinate *hides*. Occupied cells in the window:
29% mean (shipped), 6.5% (stress). Every emitted vector stayed inside the §16.22 bounds with 0
clips.

**Before/after with `train.compare`**, the protocol of §16.20–16.23 (`mlp`, `transformer`, seeds
0 1 2, 8 iterations, 4 agents, 2 trained, `max_step` 128). Before = `levels` (the "after" table of
§16.23, which is this tree's `levels` mode byte for byte); after = `grid`.

**Before** (`levels`, 296 floats):

| encoder | seeds | params | return | vf_explained_var | pass_action_fraction | order_rejection_fraction | unmatched_action_fraction | maker_fill_ratio_max | obs_clip_fraction | separated on |
|---|---|---|---|---|---|---|---|---|---|---|
| mlp | 3 | 291,872 | −0.00209 ± 0.00112 | −0.332 ± 0.592 | 0.107 ± 0.00611 | 0 ± 0 | 0.289 ± 0.0253 | 0.645 ± 0.0153 | 0 ± 0 | nothing |
| transformer | 3 | 682,528 | −0.00132 ± 0.001 | −0.189 ± 0.517 | 0.102 ± 0.00977 | 0 ± 0 | 0.298 ± 0.0208 | 0.639 ± 0.0406 | 0 ± 0 | nothing |

**After** (`grid`, 224 floats):

| encoder | seeds | params | return | vf_explained_var | pass_action_fraction | order_rejection_fraction | unmatched_action_fraction | maker_fill_ratio_max | obs_clip_fraction | separated on |
|---|---|---|---|---|---|---|---|---|---|---|
| mlp | 3 | 255,008 | −0.00346 ± 0.00211 | −0.47 ± 0.306 | 0.119 ± 0.00466 | 0 ± 0 | 0.291 ± 0.00514 | 0.621 ± 0.0497 | 0 ± 0 | nothing |
| transformer | 3 | 684,832 | −0.00141 ± 0.00196 | −0.431 ± 0.489 | 0.119 ± 0.0138 | 0 ± 0 | 0.281 ± 0.0304 | 0.617 ± 0.0234 | 0 ± 0 | nothing |

Reading it:

- **The widths moved the way the layouts say.** The `mlp` lost 36,864 first-layer parameters
  (296 → 224 inputs × 512); the transformer gained 2,304, because its level tokens are now 21 per
  snapshot instead of 10 and its positional table grew with them, while the token width itself
  fell from 8 to 6 (two size channels, two own channels, padded to the six scalars).
- **`obs_clip_fraction` stays 0 ± 0**: the grid's cells sit inside the `bid_size` / `ask_size`
  bounds of §16.22 under training play.
- **The near-random baseline did not move**: pass fractions 0.10–0.12, unmatched 0.28–0.30,
  rejections 0, returns within noise of zero, `vf_explained_var` negative on both trees. Nothing
  separates the encoders under either layout at this scale.

As in §16.20–16.23, this is a smoke-scale run: it proves the protocol runs on the grid and that the
layout change did not alter what near-random policies do. Whether a stationary coordinate lets a
policy *learn* a quoting rule is the run at scale's question ([10](10_testing.md) §8), and the one
this row was raised to ask.

**Supports:** §15 S3-15; §05 1.4, 7.4; §06 2.1.1; §18 3.0, 5.5; §10 (`test_grid_book.py`).
