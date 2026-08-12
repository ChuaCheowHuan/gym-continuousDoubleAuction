# 2. How It Is Implemented

## 2.1 Technology stack

| Layer | Choice | Version | Notes |
|---|---|---|---|
| Language | Python | 3.10–3.14 declared; 3.12 in dev, 3.11/3.12 in CI | `setup.py:31`, `.github/workflows/tests.yml:19` |
| RL framework | Ray RLlib **new API stack** | 2.56.1 | `RLModule` / `Learner` / `EnvRunner`, not `Policy`/`Trainer` |
| Env API | Gymnasium `MultiAgentEnv` | 1.2.2 (hard-pinned by Ray) | `requirements.txt:13-17` documents the pin rationale |
| DL backend | PyTorch | ≥2.13, <3 | `framework("torch")`, `train.py:177` |
| Book data structure | `sortedcontainers.SortedDict` | ≥2.4 | price→`OrderList` map |
| Numeric type for money | `decimal.Decimal` | stdlib | exact cash/quantity arithmetic |
| Rendering | `tabulate`, `pandas` | | `env.render()` prints ASCII tables |
| Plotting | `matplotlib` | ≥3.11 | offline scripts in `visualize/` |
| Packaging | setuptools | | `install_requires` + `[rllib]`/`[plot]`/`[dev]` extras |
| CI | GitHub Actions | matrix 3.11 / 3.12 | unit tests → random smoke run → RLlib integration |
| Containers | Docker | CUDA 12.8 + cu128 torch wheels | `docker/ml/dockerfile_ray_torch` |

## 2.2 Package map

```
gym_continuousDoubleAuction/
├── __init__.py                       gymnasium register("continuousDoubleAuction-v0")
├── CDA_env_rand.py                   random-agent smoke driver (CI step 2)
├── envs/
│   ├── continuousDoubleAuction_env.py   MultiAgentEnv: reset/step/render
│   ├── exchg/                           the "exchange" mixin family
│   │   ├── exchg_helper.py                composition root + printing + MTM
│   │   ├── state_helper.py                observation construction + history
│   │   ├── action_helper.py               action space + action decoding
│   │   ├── reward_helper.py               reward function
│   │   ├── done_helper.py                 termination / truncation
│   │   └── info_helper.py                 per-agent info dict
│   ├── orderbook/                       matching engine
│   │   ├── orderbook.py                   OrderBook: process/cancel/modify + tape
│   │   ├── ordertree.py                   price→OrderList SortedDict
│   │   ├── orderlist.py                   FIFO doubly-linked list per price
│   │   └── order.py                       single order record
│   ├── account/                         clearing / risk
│   │   ├── account.py                     position state machine
│   │   ├── cash_processor.py              cash ↔ cash_on_hold transfers
│   │   └── calculate.py                   NAV, P&L, mark-to-market
│   └── agent/
│       ├── trader.py                      order lifecycle + trade settlement
│       └── random_agent.py                (legacy) random action sampler
├── train/
│   ├── train.py                        TrainConfig dataclass, build_algo, CLI
│   ├── policy/policy_handler.py        MultiRLModuleSpec, module ID conventions
│   ├── model/model_handler.py          RandomRLModule + DefaultModelConfig
│   ├── callbk/…_self_play_callback.py  league: champions, matchmaking, logging
│   ├── logger/, plotter/, storage/     legacy Ray-actor telemetry (dead code)
│   └── helper/helper.py                order-imbalance / mid-price utilities
├── visualize/                          offline plots from episode pickles
└── test/                               90 unit tests + integration/
```

## 2.3 Class composition — the mixin chain

The environment is assembled by **multiple inheritance**, not composition:

```
continuousDoubleAuctionEnv
├── Exchg_Helper
│   ├── State_Helper     (obs construction, obs_history deque)
│   ├── Action_Helper    (action space, action decoding, price/size mapping)
│   ├── Reward_Helper    (set_reward)
│   ├── Done_Helper      (set_done, set_all_done)
│   └── Info_Helper      (set_info)
└── ray.rllib.env.multi_agent_env.MultiAgentEnv
```

Declared at
[`continuousDoubleAuction_env.py:17-19`](../gym_continuousDoubleAuction/envs/continuousDoubleAuction_env.py#L17-L19)
and
[`exchg_helper.py:15`](../gym_continuousDoubleAuction/envs/exchg/exchg_helper.py#L15).

Each mixin cooperates via `super().__init__(**kwargs)`
([`state_helper.py:17-20`](../gym_continuousDoubleAuction/envs/exchg/state_helper.py#L17-L20),
[`action_helper.py:8-21`](../gym_continuousDoubleAuction/envs/exchg/action_helper.py#L8-L21)),
so the MRO chain initialises cleanly. The pattern works, but it means the
mixins are not independently testable or reusable — they all assume the presence
of `self.LOB`, `self.traders`, `self.agents`, `self.last_price`. See
[05_perspective_ai_engineer.md](05_perspective_ai_engineer.md#52-architecture-mixins-vs-composition).

The trader side uses the same idiom:

```
Trader(Random_agent)         →  owns  Account(Calculate, Cash_Processor)
```

## 2.4 The step lifecycle

`step(actions)` at
[`continuousDoubleAuction_env.py:210-254`](../gym_continuousDoubleAuction/envs/continuousDoubleAuction_env.py#L210-L254):

```
 1. self.agg_LOB = set_agg_LOB()                 # pre-action book snapshot (display only)
 2. actions = set_actions(actions)               # Dict-action  →  LOB order dicts
 3. actions = rand_exec_seq(actions, None)       # random arrival order this step
 4. seq_trades, seq_order_in_book = do_actions() # apply to book, settle fills
 5. mark_to_mkt()                                # prev_nav ← nav; re-mark all accounts
 6. state_input = prep_next_state()              # post-action snapshot, push into history
 7. set_step_outputs(state_input)                # obs / reward / terminated / truncated / info
 8. render()                                     # optional ASCII dump
 9. t_step += 1
```

### Step 2 — action decoding

`_set_action_mkt_depth`
([`action_helper.py:138-182`](../gym_continuousDoubleAuction/envs/exchg/action_helper.py#L138-L182))
turns the neural-network `Dict` output into an order dict:

| Field | Meaning |
|---|---|
| `category ∈ [0,8]` | `0`=pass; `1-4`=bid {market, limit, modify, cancel}; `5-8`=ask {…} |
| `size_mean ∈ [-1,1]`, `size_sigma ∈ [0,1]` | parameters of a Gaussian the **environment** samples the size from |
| `price ∈ [0,9]` | book depth level 1–10 to quote at |
| `price_offset ∈ {0,1,2}` | passive (−1 tick) / join / aggressive (+1 tick) |

Size is drawn as `rint(abs(N(mean_mul · size_mean, size_sigma)))` where
`mean_mul` is 49.5 for market orders and 499.5 for limit orders
([`action_helper.py:206-226`](../gym_continuousDoubleAuction/envs/exchg/action_helper.py#L206-L226)).

Price is resolved against the **raw, unnormalised** book
(`agg_LOB_raw`), falling back to "ghost" levels stepped off `last_price` when
the requested depth level is empty
([`action_helper.py:228-277`](../gym_continuousDoubleAuction/envs/exchg/action_helper.py#L228-L277)).
This raw/normalised split is deliberate and correct: observations are
normalised for the network, actions are priced in absolute currency.

Actions with `side is None` (category 0) are dropped before reaching the book
([`action_helper.py:80-86`](../gym_continuousDoubleAuction/envs/exchg/action_helper.py#L80-L86)).

### Step 4 — order handling and settlement

`Trader.place_order`
([`trader.py:15-66`](../gym_continuousDoubleAuction/envs/agent/trader.py#L15-L66)):

```
_order_approved()  ── reject if NAV ≤ 0, or if the *opening* portion of the
                      order exceeds free cash (closing/covering is always free)
       │
       ├─ market → LOB.process_order
       ├─ limit  → _place_limit_order   (upsert: modifies an existing same-price order)
       ├─ modify → _modify_limit_order  (oldest resting order on that side, FIFO)
       └─ cancel → _cancel_limit_order  (+ release cash_on_hold)
       │
       ├─ _process_trades(trades, agents)      settle both sides of each fill
       └─ order_in_book_passive_party(...)     reserve cash for any resting residue
```

`_process_trades`
([`trader.py:263-288`](../gym_continuousDoubleAuction/envs/agent/trader.py#L263-L288))
walks each fill and updates **both** parties: the aggressor via
`process_acc(trade, 'init_party')` and the resting side via
`process_acc(trade, 'counter_party')`, found by ID scan across all agents.

### Step 4b — position state machine

`Account.process_acc`
([`account.py:183-199`](../gym_continuousDoubleAuction/envs/account/account.py#L183-L199))
dispatches on current inventory sign to a five-case transition table:

| Current | Fill direction | Handler | Effect |
|---|---|---|---|
| flat | any | `_neutral` | open position at trade price |
| long | bid | `_size_increase` | update VWAP, add value |
| long | ask, size ≤ position | `_size_decrease` | realise part, re-derive VWAP |
| long | ask, size > position | `_covered_side_chg` | close out, then open the short remainder |
| short | mirror of the above | `_net_short` | |

Cash movements are isolated in `Cash_Processor`
([`cash_processor.py`](../gym_continuousDoubleAuction/envs/account/cash_processor.py)),
which enforces the invariant that placing an order moves cash into
`cash_on_hold` rather than out of the account, so **NAV = cash + cash_on_hold +
position_val** is unaffected by order placement.

### Step 5 — mark to market

`Exchg_Helper.mark_to_mkt`
([`exchg_helper.py:42-52`](../gym_continuousDoubleAuction/envs/exchg/exchg_helper.py#L42-L52))
takes the **last trade price on the tape** as the mark, updates
`self.last_price` (which is also the action-space price anchor), and re-marks
every account. Per account
([`calculate.py:35-55`](../gym_continuousDoubleAuction/envs/account/calculate.py#L35-L55)):

```
profit       = |net_position| · (mkt − VWAP)   signed by position side
position_val = |net_position| · VWAP + profit
prev_nav     = nav
nav          = cash + cash_on_hold + position_val
max_nav      = max(max_nav, nav)          # high-water mark, monotone within an episode
```

Note the ordering: `prev_nav ← nav` happens **inside** `mark_to_mkt`, so
`nav − prev_nav` in the reward is a genuine one-step delta — but only on steps
where the tape is non-empty. Before the first ever trade in an episode, NAV is
never re-derived and rewards are exactly 0.

### Step 6 — observation construction

`set_agg_LOB`
([`state_helper.py:70-171`](../gym_continuousDoubleAuction/envs/exchg/state_helper.py#L70-L171))
builds one 42-float snapshot:

```
 [ 0:10]  normalised bid prices   (M − P_bid)/M          ≥ 0
 [10:20]  sqrt bid sizes                                 ≥ 0
 [20:30]  normalised ask prices  −(P_ask − M)/M          ≤ 0
 [30:40]  −sqrt ask sizes                                ≤ 0
 [40]     log(M)                     price-level anchor
 [41]     log1p(spread / min_tick)   0.0 ⇒ no two-sided market
```

`M` is the L1 midpoint, with a documented fallback chain (one-sided book → that
side's best; empty book → `last_price`; degenerate → 100.0) so `log(M)` is always
defined. The sign convention (bids positive, asks negative) is what lets the
renderer and the visualisation scripts split the vector back into sides.

The final observation is `n_hist` snapshots concatenated
([`state_helper.py:37-49`](../gym_continuousDoubleAuction/envs/exchg/state_helper.py#L37-L49)),
default 4 → **168 floats**. On reset the deque is pre-filled with `n_hist`
copies of the initial snapshot so the shape is constant from step 0
([`state_helper.py:23-35`](../gym_continuousDoubleAuction/envs/exchg/state_helper.py#L23-L35)).

**The history deque is a single shared object on the environment**, and the same
stacked vector is handed to every agent — there is no per-agent view. See
[03](03_perspective_rl_researcher.md#32-the-observation-contains-no-private-state)
for why this matters.

### Step 7 — outputs

`set_step_outputs`
([`exchg_helper.py:54-79`](../gym_continuousDoubleAuction/envs/exchg/exchg_helper.py#L54-L79))
loops over traders building obs/reward/done/info, then **resets the per-step
counters** (`num_trades_step`, `num_passive_fills_step`, `order_step_placed`)
after the reward has consumed them. That ordering is correct and easy to break.

## 2.5 Reward function

[`reward_helper.py:24-47`](../gym_continuousDoubleAuction/envs/exchg/reward_helper.py#L24-L47):

```python
nav_change = nav − prev_nav
nav_term   = nav_change × (1.5 if nav_change < 0 else 1.0)     # loss aversion
drawdown   = max(0, max_nav − nav)                             # distance from peak

reward = nav_term
       − 0.10 × order_step_placed        # 1 if a market/limit order was submitted
       − 0.05 × num_trades_step          # per fill
       − 0.20 × drawdown                 # LEVEL, charged every step
       + 0.10 × num_passive_fills_step   # maker rebate proxy
```

Coefficients are hard-coded module constants, not configuration. The five terms
span roughly five orders of magnitude in practice; see the measured
decomposition in [07_verification_log.md](07_verification_log.md#73-reward-decomposition).

## 2.6 Training architecture

### Module layout

For `n` agents with `k` trainable
([`policy_handler.py:1-32`](../gym_continuousDoubleAuction/train/policy/policy_handler.py#L1-L32)):

```
policy_0 … policy_{k-1}     trainable PPO modules      ← fixed 1:1 to agent_0…agent_{k-1}
policy_k … policy_{n-1}     frozen RandomRLModule      ┐
champion_1, champion_2, …   frozen PPO snapshots       ┘ ← opponent pool, sampled per episode
```

Default: `n=8`, `k=2` → 2 learners against 6 pool slots.

Critically, module **classes** are declared through `MultiRLModuleSpec`
([`policy_handler.py:95-109`](../gym_continuousDoubleAuction/train/policy/policy_handler.py#L95-L109)),
because on the new API stack `multi_agent(policies={...})` reads only the dict
*keys*; a `PolicySpec(policy_class=...)` is silently discarded. The file's
migration note documents exactly this trap, and
`test_baseline_opponents_are_random_modules` guards it.

`RandomRLModule`
([`model_handler.py:36-72`](../gym_continuousDoubleAuction/train/model/model_handler.py#L36-L72))
emits `Columns.ACTIONS` directly from `action_space.sample()`, so it is a *true*
uniform sampler rather than a frozen randomly-initialised network — which for a
`Dict` action space with `Box` components is a materially different distribution.

Trainable modules use RLlib's default PPO torch module with
`fcnet_hiddens=[256,256]`, `tanh`, and `vf_share_layers=False`
([`model_handler.py:78-95`](../gym_continuousDoubleAuction/train/model/model_handler.py#L78-L95)).

### Matchmaking

`SelfPlayCallback.get_mapping_fn`
([`league_based_self_play_callback.py:574-633`](../gym_continuousDoubleAuction/train/callbk/league_based_self_play_callback.py#L574-L633))
returns a closure that:

- maps `agent_i → policy_i` for `i < k` (always the learners);
- for `i ≥ k`, draws from the pool with weights `original_opponent_weight=1.0`
  for `policy_*` baselines and `champion_weight=3.0` for `champion_*` snapshots;
- seeds the RNG from `zlib.crc32(episode_id) + agent_index`, **not** `hash()`,
  so selection is reproducible across processes (`hash()` on `str` is salted by
  `PYTHONHASHSEED`).

### Champion promotion

`on_train_result`
([`league_based_self_play_callback.py:265-354`](../gym_continuousDoubleAuction/train/callbk/league_based_self_play_callback.py#L265-L354)):

```
returns = result[ENV_RUNNER_RESULTS]["module_episode_returns_mean"]   # keyed by real ModuleID
threshold = mean(returns) + std_dev_multiplier · std(returns)
best trainable module with return > threshold  →  snapshot
   subject to: ≥ min_iterations_between_champions since the last one
               evict the oldest if champion_count == max_champions
```

Using `module_episode_returns_mean` (rather than the old
`agent_episode_returns_mean` with an `agent_X → policy_X` remap) is the correct
choice, because opponent agents play *whichever* module the pool assigned them
that episode.

`_create_champion_snapshot_from_policy`
([`league_based_self_play_callback.py:383-531`](../gym_continuousDoubleAuction/train/callbk/league_based_self_play_callback.py#L383-L531))
is the most subtle code in the repository, and its four ordering constraints are
all load-bearing:

1. Read weights from `learner_group.get_state(...)`, **not**
   `algorithm.get_module()` (that returns the inference-only EnvRunner copy,
   without the value head) and **not** `learner_group._learner` (which is `None`
   whenever `num_learners > 0`).
2. Append the champion to `available_modules` **before** `add_module`, because
   `add_module` pickles the mapping closure — and with it a snapshot of the pool
   — to ship to the remote EnvRunners.
3. `set_state` the trained weights into the Learner-side champion.
4. **Force-push** the weights to the EnvRunners with
   `foreach_env_runner(lambda r: r.set_state({COMPONENT_RL_MODULE: {...}}))`,
   deliberately *not* `sync_weights()`, because `sync_weights` carries a
   `WEIGHTS_SEQ_NO` that the runner already has and would silently drop.

Each of those four has a dedicated integration test.

### Distributed execution

`TrainConfig` exposes `num_env_runners` (rollout parallelism) and `num_learners`
(gradient parallelism) with 0/0 as the CPU-friendly default
([`train.py:58-70`](../gym_continuousDoubleAuction/train/train.py#L58-L70)).
`resolved_gpus_per_learner()` forces GPU fraction to 0 when CUDA is absent
([`train.py:119-127`](../gym_continuousDoubleAuction/train/train.py#L119-L127)),
which is what makes the notebook's `0.75` default safe on a laptop.

The integration suite covers all three topologies: local, `num_env_runners=1`,
and `num_learners=1`.

## 2.7 Data flow diagram

```
                 ┌──────────────────────── RLlib driver ─────────────────────────┐
                 │  PPO Algorithm                                                │
                 │    ├─ LearnerGroup ── policy_0, policy_1 (+ frozen champions) │
                 │    └─ EnvRunnerGroup                                          │
                 └───────────────────────────────┬───────────────────────────────┘
                                                 │ agent_id → module_id (weighted draw)
                                                 ▼
   obs(168) ─► RLModule ─► Dict action ─► set_actions ─► shuffle ─► OrderBook
      ▲                                                                │
      │                                                        trades / residue
      │                                                                ▼
      │                                                     Trader._process_trades
      │                                                                │
      │                                                                ▼
      │                                     Account: cash / cash_on_hold / VWAP / position
      │                                                                │
      │                                                        mark_to_mkt(last tape price)
      │                                                                │
      │                                    ┌───────────────────────────┼─────────────┐
      │                                    ▼                           ▼             ▼
      └──────────── set_agg_LOB ◄──── obs_history deque            set_reward     set_info
                    (shared by all agents)                              │             │
                                                                        ▼             ▼
                                                                    reward dict   info dict
                                                                                      │
                                                        SelfPlayCallback.on_episode_* │
                                                          ├─ per-episode step pickle ◄┘
                                                          └─ NAV conservation check
```
