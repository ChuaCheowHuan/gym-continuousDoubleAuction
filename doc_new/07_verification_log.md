# 7. Verification Log

Every **[verified]** claim in this analysis traces to one of the probes below.
All were run against the working tree on branch `update_lib` at commit `3dcfc53`,
on Python 3.12.1 / Ray 2.56.1 / torch 2.13.0+cpu / gymnasium 1.2.2 / NumPy 2.5.2.

---

## 7.1 Environment and dependency versions

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

Note `six` and `sklearn` are importable only because they are installed
transitively / via `requirements.txt`; neither is in `setup.py::install_requires`
(finding S3-5).

---

## 7.2 Test suite

```
$ python -m pytest gym_continuousDoubleAuction/test -q \
      --ignore=gym_continuousDoubleAuction/test/integration
........................................................................ [ 80%]
..................                                                       [100%]
90 passed in 8.75s
```

---

## 7.3 Observation scale, reward scale, NAV conservation

4 agents, `init_cash=1,000,000`, 300 steps, uniformly random actions, seed 0.

```
obs identical across agents at reset: True
obs identical across agents at step t: True

--- observation feature scale (last snapshot block) ---
bid_price norm  min/max: 0.0000  0.2117
bid_size  sqrt  min/max: 0.0000  51.1859
ask_price norm  min/max: -0.2593 0.0000
ask_size  sqrt  min/max: -44.0114 0.0000
log_mid         min/max: 4.1589  4.2836
log1p_spread    min/max: 0.0000  2.5649

--- reward scale (random policy) ---
per-step reward min/mean/max: -15779.0 / -736.5 / 8744.1
episode return per agent: [-149059.7 -174899.3 -197819.4 -362007.7]
sum of all agents' returns: -883786.1

  final NAVs: [1001311. 1004094. 1001105. 993490.]
  total: 4000000.0   expected: 4000000
```

**Supports:** S1-2 (identical observations), S2-2 (250× feature-scale spread),
S1-3 / S2-3 (reward magnitude), and NAV conservation to the cent.

---

## 7.4 Reward decomposition and no-op dominance

Same setup, seed 1. Reward components re-derived per step from account state.

```
--- reward decomposition, summed over 4 agents x 300 steps ---
  nav           -264,587.5
  dd            -519,142.8
  order                0.0     (counters are zeroed inside step(); O(0.1)/step anyway)
  trade                0.0
  passive              0.0

--- all-agents-pass policy: total return over 300 steps x 4 agents = 0.0
```

The drawdown penalty is ~2× the asymmetric NAV term. Passing every step yields
**exactly zero**, versus −883,786 for random trading.

**Supports:** S1-3, S2-1.

---

## 7.5 Action-space pathologies

```
--- size sampling: mean=+0.5 -> [250.0, 250.0, 250.0, 250.0, 250.0]
                   mean=-0.5 -> [250.0, 250.0, 250.0, 250.0, 250.0]   identical: True
    sigma=0.0 -> [250.0, 250.0, 250.0];  sigma=1.0 -> [251.0, 249.0, 250.0]
    limit_size_mean_mul=499.5, mkt_size_mean_mul=49.5

--- tick_size: config=0.25 | LOB.tick_size before reset=0.25
             | after reset=1 | action-space min_tick=1
```

**Supports:** S3-1 (`abs()` folds the range), S3-2 (`sigma` is absolute and
therefore inert), S3-4 (`tick_size` discarded by `reset()`).

---

## 7.6 Market-mechanics probes

```
1. self-trade executed: True | tape len: 1 | same ID both sides: True

2. after forcing agent_0 NAV<0 -> terminateds: {'agent_0': False,
                                                'agent_1': False,
                                                'agent_2': False,
                                                '__all__': False}
   done_set: {'agent_0'}
   per-agent terminated flag for agent_0: False

3. obs dim per agent: (168,) | distinct obs vectors across 3 agents: 1

4. same-trader orders resting at price 90: 1 | level volume: 7
```

Probe 4: two limit bids for 5 and 7 lots at price 90 from the same trader leave a
single order of 7 — the second replaced the first.

**Supports:** S2-5 (self-matching), S2-4 (no per-agent termination), S1-2,
S3-9 (one order per price level per trader).

---

## 7.7 One real PPO training iteration

Built through the shipped `build_config` path
(`num_agents=4, num_trained_agents=2, max_step=64, num_episodes_per_iter=4,
num_epochs=1, minibatch_size=64`).

```
== policy_0 ==
   curr_entropy_coeff       0.0
   curr_kl_coeff            0.100
   entropy                  8.274
   mean_kl_loss             0.00278
   policy_loss              -0.5707
   total_loss               9.4299
   vf_explained_var         -0.000165
   vf_loss                  10.0
   vf_loss_unclipped        3,847,340.5

== policy_1 ==
   entropy                  8.454
   policy_loss              1.0516
   total_loss               11.0536
   vf_explained_var         -0.000135
   vf_loss                  10.0
   vf_loss_unclipped        31,965,536.0

module returns: {'policy_0': -7155.0, 'policy_1': -6590.8,
                 'policy_2': -9884.9, 'policy_3': -6014.3}
```

`policy_2` / `policy_3` are `RandomRLModule`s and produce no losses, as expected.

Corroborating source: `ray/rllib/algorithms/ppo/torch/ppo_torch_learner.py:99-101`

```python
vf_loss         = torch.pow(value_fn_out - batch[Postprocessing.VALUE_TARGETS], 2.0)
vf_loss_clipped = torch.clamp(vf_loss, 0, config.vf_clip_param)
```

and RLlib PPO defaults (never overridden by `TrainConfig`):

```
vf_clip_param    10.0        gamma        0.99
lambda_          1.0         grad_clip    None
entropy_coeff    0.0         minibatch_size 128
```

Advantages **are** standardised per module by
`ray/rllib/connectors/learner/general_advantage_estimation.py`:

```python
module_advantages = (module_advantages - module_advantages.mean()) / max(1e-4, module_advantages.std())
```

which is why the update does not diverge despite the reward scale — the damage is
confined to the critic.

**Supports:** S1-1, S3-10 (`entropy_coeff = 0`), S3-11 (γ, λ defaults).

---

## 7.8 Checkpoint / restore of league state

Train one iteration, promote champions, save, restore.

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

This probe **corrected an earlier hypothesis**: league state *does* survive
checkpointing, because `.callbacks(lambda: callback_instance)` closes over the
instance and RLlib cloudpickles it. The restored algorithm's own callback, its
modules, and its mapping function are all correct.

The narrower real defect is that `build_algo` returns the *fresh, empty* callback
from `build_config` rather than the restored one.

Incidentally: `champion_1` was promoted automatically during the single
`algo.train()` call — with `std_dev_multiplier=0.1` and an empty
`champion_history` (so no cooldown), promotion fires on the first eligible
iteration.

**Supports:** S3-7, S3-10.

---

## 7.9 Static measurements

```
sys.exit in library code:            8  (all in envs/orderbook/orderbook.py)
broad `except Exception`:            2 in the callback (+3 in scripts)
print() in library code:            88  (42 in the self-play callback, 13 in the env)
`import logging` anywhere:           0
type-annotated defs in train/:       9
type-annotated defs in envs/:        1
tracked build artefacts in git:      none
```

Dead-code confirmations (`grep`, `.py` files only):

- `g_store` is referenced only inside `log_handler.py` and `plot_handler.py`;
  the detached actor in `store_handler.py` is **never instantiated** anywhere.
- `sklearn` appears exactly once, at `action_helper.py:5`, for
  `shuffle(actions, random_state=None)`.
- `six` appears at `orderbook.py:10` and `orderlist.py:101`, both for
  `cStringIO`.
- `import ray` at `continuousDoubleAuction_env.py:6` is unused; only the
  `MultiAgentEnv` import on line 7 is needed.
