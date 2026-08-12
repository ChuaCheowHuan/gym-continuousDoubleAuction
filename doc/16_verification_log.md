# 16. Verification Log

Every **[verified]** claim in this documentation set traces to one of the probes below.

All probes were re-run against the working tree on branch `update_lib` during this merge, on
Python 3.12.1 / Ray 2.56.1 / torch 2.13.0+cpu / gymnasium 1.2.2 / NumPy 2.5.2. Where a probe had
also been run for the earlier `doc_new/` analysis (at commit `3dcfc53`), both readings are shown
— the absolute numbers differ because **the environment is not seedable** (finding S3-5), but
every qualitative conclusion and every order of magnitude reproduced.

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

`six` and `sklearn` are importable only because they are installed transitively / via
`requirements.txt`; neither is in `setup.py::install_requires` (finding S3-6).

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

The narrower real defect is that `build_algo` returns the *fresh, empty* callback from
`build_config` rather than the restored one — confirmed by reading
[`train.py:215-227`](../gym_continuousDoubleAuction/train/train.py#L215-L227).

**Supports:** S3-8, S3-11.

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

- `g_store` is referenced only inside `log_handler.py` and `plot_handler.py`, both as
  `ray.util.get_actor("g_store")` lookups. The detached actor in `store_handler.py` is **never
  instantiated** anywhere.
- `train/helper/helper.py` is imported by nothing — the only reference is a commented-out import
  in `store_handler.py`.
- `state_diff` is defined in `state_helper.py` and called nowhere.
- `random_agent.Random_agent` is referenced only by `trader.py`'s `import` and class declaration;
  `select_random_action` is never called.
- `sklearn` appears exactly once, at `action_helper.py:5`, for `shuffle(actions, random_state=...)`.
- `six` appears at `orderbook.py:10` and `orderlist.py:101`, both for `cStringIO`.
- `import ray` at `continuousDoubleAuction_env.py:6` is unused — the only `ray.`-prefixed
  reference in the file is the `from ray.rllib...` import on line 7.

Infrastructure confirmations:

- `.github/workflows/tests.yml` exists: `push` to `master`/`update_lib`, `pull_request`,
  `workflow_dispatch`; matrix Python 3.11 + 3.12; three staged jobs (unit tests → random-agent
  smoke run → RLlib integration).
- `.gitignore` contains both `episode_data` and `gym_continuousDoubleAuction/episode_data`, with
  an explanatory comment.
- `episode_data/` contains exactly two committed fixtures: `test_ep_failure.pkl`,
  `test_ep_success.pkl`.
- `CODEOWNER` and `CODEOWNERS` both exist at the repo root.

**Supports:** S2-8, S3-6, S3-7, S4-1, S4-2, S4-3, S4-9, S4-18, and the CI / `.gitignore`
corrections in [README.md](README.md).

---

## 16.10 Reproducing these probes

The rollout probes (16.3–16.6) are a single self-contained script that imports
`continuousDoubleAuctionEnv` directly. The training probe (16.7) builds a real `Algorithm`
through `build_config` and takes a few minutes. Neither writes into the repository when
`episode_data_dir=None` is passed; with the default the rollout probes will create
`episode_data/` in the working directory.

Because seeding is non-functional (S3-5), **re-running will not reproduce the exact numbers
above** — only the signs, ratios and orders of magnitude. That is itself a finding, and fixing it
is item 9 of Phase 2 in
[15_findings_and_recommendations.md](15_findings_and_recommendations.md#suggested-sequencing).
