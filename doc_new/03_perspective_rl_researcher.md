# 3. Perspective: Reinforcement Learning Researcher

Scope: algorithm choice, reward design, environment interaction, sample
efficiency, exploration, training stability.

**Headline:** the RLlib *plumbing* is correct and unusually well tested. The
*learning problem* has three defects that, together, mean the current
configuration cannot learn trading behaviour: the critic is mathematically
frozen, the observation omits everything the reward depends on, and the reward
makes passivity a dominant strategy.

---

## 3.1 Algorithm choice — PPO in a competitive multi-agent game

**What is used.** Independent PPO (`PPOConfig`, `framework("torch")`,
[`train.py:174-210`](../gym_continuousDoubleAuction/train/train.py#L174-L210))
with `k=2` independently-parameterised learners, plus league-based self-play
against frozen baselines and champion snapshots.

**Assessment: appropriate.** PPO is the right default for a partially observed,
non-stationary, competitive setting: it is robust to hyper-parameter error, its
trust region tolerates the distribution shift caused by opponents changing, and
it is the algorithm the AlphaStar-style league literature is built around. The
league itself is the correct structural answer to non-transitivity — a simple
"train against your latest self" scheme cycles, and the champion pool with
weighted sampling (`champion_weight=3.0` vs `original_opponent_weight=1.0`,
[`train.py:86-87`](../gym_continuousDoubleAuction/train/train.py#L86-L87))
is a reasonable prioritised-fictitious-play approximation.

**Design notes worth flagging:**

- **Independent learners, not parameter-shared.** `policy_0` and `policy_1` are
  separate networks. Given that both receive *identical* observations (§3.2),
  the only thing distinguishing them is initialisation and their own gradient
  history. This is a legitimate choice (it gives the league two distinct
  lineages) but it halves the data per network relative to a shared policy.
- **No centralised critic.** With `vf_share_layers=False` each learner has its
  own decentralised value head over the shared public observation. In a
  competitive zero-sum game a decentralised critic is defensible; but combined
  with the missing private state (§3.2) the value function is being asked to
  predict a return that depends on unobserved variables — its Bayes-optimal
  error is irreducibly large.
- **Frozen baselines are genuinely uniform.**
  `RandomRLModule._forward` samples the action space directly
  ([`model_handler.py:56-65`](../gym_continuousDoubleAuction/train/model/model_handler.py#L56-L65)).
  The docstring's point is correct and non-obvious: a *frozen randomly-initialised*
  PPO network is not the same opponent distribution — it draws `Box` components
  from a clipped Gaussian (so `size_sigma` piles up at 0) and carries a fixed
  bias in the discrete heads for the whole run.

---

## 3.2 The observation contains no private state

**[verified]** All agents receive the byte-identical 168-float vector, at reset
and at every step:

```
obs dim per agent: (168,) | distinct obs vectors across 3 agents: 1
```

The observation is built once per step from the public book
([`state_helper.py:37-49`](../gym_continuousDoubleAuction/envs/exchg/state_helper.py#L37-L49))
and broadcast:

```python
states = {f'agent_{i}': stacked_obs for i in range(len(self.traders))}
```

Nothing in the vector encodes:

| Missing | Where it lives | Why the agent needs it |
|---|---|---|
| `net_position` | `account.py:20` | Sign and size of inventory determine whether a fill opens or closes risk |
| `VWAP` | `account.py:21` | Entry price ⇒ unrealised P&L direction |
| `nav`, `prev_nav` | `account.py:17-18` | **The reward is literally `nav − prev_nav`** |
| `max_nav` | `account.py:28` | The drawdown penalty is `0.2·(max_nav − nav)` |
| `cash`, `cash_on_hold` | `account.py:11-13` | Determines which orders `_order_approved` will reject |
| own resting orders | `LOB.bids/asks.order_map` | Modify/cancel actions are meaningless without knowing what is resting |
| agent identity | — | Two agents in the same state cannot differentiate roles |
| `t_step` / time remaining | `continuousDoubleAuction_env.py:54` | End-of-episode inventory liquidation is a different problem than mid-episode trading |

**Consequence.** The reward is a deterministic function of state variables the
policy cannot see. This is not ordinary partial observability that a recurrent
network could paper over — the drawdown term depends on `max_nav`, a *path
functional* over the entire episode. Formally the process is not an MDP in the
agent's observation, and the residual variance is not reducible by any policy
over these observations.

Two secondary effects:

- The `modify` and `cancel` action categories (4 of the 9 category values,
  [`action_helper.py:165-172`](../gym_continuousDoubleAuction/envs/exchg/action_helper.py#L165-L172))
  are effectively blind. `_get_order_ID`
  ([`trader.py:214-247`](../gym_continuousDoubleAuction/envs/agent/trader.py#L214-L247))
  silently no-ops if nothing matches. ~44% of the discrete action mass is
  unlearnable.
- Frame stacking (`n_hist=4`) adds *public* temporal context, which is genuinely
  useful for order-flow inference, but it cannot substitute for the private
  state.

**Fix.** Append a per-agent feature block to the snapshot, normalised against
`init_cash`, and stop broadcasting a single vector:

```python
private = np.array([
    net_position / max_position_scale,
    (nav - init_cash) / init_cash,
    (max_nav - nav) / init_cash,          # current drawdown
    cash / init_cash,
    cash_on_hold / init_cash,
    (VWAP - M) / M if net_position else 0.0,
    resting_bid_notional / init_cash,
    resting_ask_notional / init_cash,
    1.0 - t_step / max_step,              # time remaining
], dtype=np.float32)
```

This is a ~9-float addition per snapshot and the single highest-value change in
the repository.

---

## 3.3 Reward design

### 3.3.1 The reward is strictly negative-sum over a zero-sum market

NAV is conserved exactly — **[verified]**, 4 agents × 1,000,000 → final total
NAV 4,000,000.00. So `Σ_agents nav_change = 0` at every step.

But the reward adds a loss-aversion multiplier and a persistent drawdown level.
Over 300 steps with 4 random agents — **[verified]**:

| Term | Summed value |
|---|---|
| asymmetric NAV term | −264,587 |
| drawdown penalty | −519,143 |
| **total return, all agents** | **−883,786** |

against a market where the NAV pot did not move at all. The drawdown penalty
alone is roughly **twice** the entire (already negative) NAV term.

### 3.3.2 Doing nothing is a dominant strategy

**[verified]** A policy where every agent plays `category=0` every step:

```
all-agents-pass policy: total return over 300 steps × 4 agents = 0.0
```

Exactly zero — versus −883,786 for random trading. Reason: with no position, no
mark-to-market change; no orders, no `order_penalty`; no fills, no
`trade_penalty`; NAV never falls below `max_nav`, so no drawdown.

Trading is therefore **strictly dominated unless the agent can extract more than
its penalty budget from other agents**, and because the market is zero-sum the
population as a whole never can. `(pass, pass, …, pass)` is a Nash equilibrium
that is also the *joint-optimal* outcome under this reward. Worse, it is an
attractor reachable by pure gradient descent from a random start: the fastest
way to raise return early in training is to stop trading. Empty-market collapse
is the most likely training outcome as configured.

This is not hypothetical — it is exactly what the numbers above predict.

### 3.3.3 The drawdown term is a level, not a delta

[`reward_helper.py:37,43`](../gym_continuousDoubleAuction/envs/exchg/reward_helper.py#L37-L43):

```python
current_drawdown = max(0, trader.acc.max_nav - trader.acc.nav)
reward = ... - (drawdown_penalty * current_drawdown)
```

`max_nav` is monotone non-decreasing within an episode
([`calculate.py:12-13`](../gym_continuousDoubleAuction/envs/account/calculate.py#L12-L13)),
so a drawdown opened at step 50 is charged **every step until NAV recovers past
the old peak**. At `max_step=4096`, a 1,000-unit drawdown incurred early costs
`0.2 × 1000 × ~4000 ≈ 800,000` — three orders of magnitude more than the NAV
move that caused it.

Three problems: (a) it is not potential-based, so it changes the optimal policy
rather than only shaping it; (b) its magnitude scales with episode length, so
`max_step` silently becomes a risk-aversion hyper-parameter; (c) it is
non-Markov in the agent's observation.

**Fix.** Charge the *increment*, which is potential-based and telescoping:

```python
new_dd = max(0, max_nav - nav)
reward += -drawdown_penalty * max(0.0, new_dd - prev_dd)   # penalise deepening only
```

### 3.3.4 The micro-terms are numerically irrelevant

`order_penalty=0.1`, `trade_penalty=0.05`, `passive_bonus=0.1` sit against a NAV
term whose per-step magnitude is **[verified]** in the range −15,779 … +8,744.
They are 5–6 orders of magnitude too small to influence behaviour. Whatever
economic intent they encode (discourage over-trading, reward providing
liquidity) is not being expressed. Either scale them to the reward's natural
units or express them as basis-point costs on notional — see
[04_perspective_financial_trader.md](04_perspective_financial_trader.md#44-there-are-no-transaction-costs).

### 3.3.5 Coefficients are not configurable

All five constants are function-local literals
([`reward_helper.py:27-31`](../gym_continuousDoubleAuction/envs/exchg/reward_helper.py#L27-L31)),
with the code comment "Internal defaults, can be moved to config". For a
research repository, reward-shaping coefficients are the primary experimental
axis and should be in `env_config` so they are captured in checkpoints and
sweepable by Tune.

---

## 3.4 The critic cannot learn — `vf_clip_param` saturation

**This is the single most consequential finding.** RLlib's PPO clips the
value-function loss:

```python
vf_loss         = (value_fn_out - VALUE_TARGETS) ** 2
vf_loss_clipped = torch.clamp(vf_loss, 0, config.vf_clip_param)   # default 10.0
```
(`ray/rllib/algorithms/ppo/torch/ppo_torch_learner.py:99-101`)

The config never sets `vf_clip_param`
([`train.py:199-205`](../gym_continuousDoubleAuction/train/train.py#L199-L205)),
so it stays at **10.0**, while value targets are undiscounted-scale NAV sums in
the 10⁴–10⁶ range. `torch.clamp` is **flat** above the bound, so
`∂vf_loss_clipped/∂θ = 0` for every sample. The critic receives *zero gradient*.

**[verified]** — one real training iteration on the shipped config path:

```
== policy_0 ==
   vf_loss                 10.0            ← pinned at vf_clip_param
   vf_loss_unclipped       3,847,340.5
   vf_explained_var        -0.000165       ← critic explains 0% of return variance
   total_loss              9.43            ← 10.0 of which is the constant vf term
== policy_1 ==
   vf_loss                 10.0
   vf_loss_unclipped       31,965,536.0
   vf_explained_var        -0.000135
```

Downstream consequences:

1. **GAE degenerates.** RLlib's PPO default is `lambda_=1.0`, so the advantage is
   already the Monte-Carlo return minus `V(s)`. With `V` a constant-ish untrained
   function, the advantage is essentially the raw return.
2. **PPO becomes REINFORCE with a batch baseline.** Advantages *are* standardised
   per module in the new stack (`GeneralAdvantageEstimation` divides by the batch
   std), so the update does not explode — but the variance reduction a critic
   exists to provide is entirely absent. Sample efficiency collapses.
3. **The loss metric is a decoy.** `total_loss ≈ 9.4` looks small and stable; 10.0
   of it is a constant. Anyone monitoring `total_loss` sees a healthy-looking flat
   line while nothing is being learned. `vf_explained_var` is the metric that
   exposes it, and nothing in the code surfaces it.

**Fixes, in order of preference:**

- **Normalise the reward.** Divide `nav_change` by `init_cash` (or by a running
  return scale) so rewards are O(10⁻³) and returns are O(1). This fixes the
  critic, the drawdown scaling, and the micro-term irrelevance in one change.
- **Or** set `vf_clip_param` to something commensurate (e.g. `1e9`) — effectively
  disabling it — and add `grad_clip` to control the resulting large gradients.
- **Or** enable a reward-scaling connector / `PopArt`-style value normalisation.

Then **assert on `vf_explained_var`** in the integration suite so the regression
cannot recur silently. This is precisely the class of bug the existing
integration tests were written to catch — it just was not on the list.

---

## 3.5 Environment interaction and the action space

### 3.5.1 Half the size action range is a no-op

`_set_size`
([`action_helper.py:206-226`](../gym_continuousDoubleAuction/envs/exchg/action_helper.py#L206-L226)):

```python
sample = np.random.normal(mean_mul * mean, sigma, 1)
return np.rint(np.abs(sample)).item()
```

The `abs()` folds the distribution. **[verified]**, same RNG seed:

```
mean=+0.5 -> [250.0, 250.0, 250.0, 250.0, 250.0]
mean=-0.5 -> [250.0, 250.0, 250.0, 250.0, 250.0]   identical: True
```

`size_mean` is declared on `Box(-1, 1)`
([`action_helper.py:58`](../gym_continuousDoubleAuction/envs/exchg/action_helper.py#L58)),
so the policy's Gaussian head spends half its range on a mirror image. The
optimum is bimodal at `±m`, which fights the unimodal Gaussian policy: the head
is pushed toward mean 0 by symmetric gradients, and mean 0 means *minimum* size.
Declare the space as `Box(0, 1)` instead.

### 3.5.2 The `size_sigma` head is inert

`sigma` is passed straight to `np.random.normal` as an **absolute** standard
deviation, while means are 49.5·|m| (market) or 499.5·|m| (limit). **[verified]**:

```
sigma=0.0 -> [250.0, 250.0, 250.0];  sigma=1.0 -> [251.0, 249.0, 250.0]
```

Across `sigma ∈ [0,1]` the size varies by ±1 contract on a base of 250. The head
is a null control: the policy pays entropy cost for a parameter with no effect.
Either scale it (`sigma × mean_mul × k`) or delete it.

### 3.5.3 Environment-side sampling breaks the log-probability

Even setting scale aside, the *architecture* of size selection is unusual: the
policy emits distribution **parameters**, and the environment draws the sample.
The realised size is therefore not part of the action whose log-probability PPO
uses in the importance ratio. The policy is credited/blamed for an outcome
driven by an unrecorded random draw.

This shows up as extra advantage variance that no amount of data removes. The
standard formulation is to have the policy emit the size directly (a `Box`
action, with sampling handled by the policy distribution, so `log π(a|s)` covers
it), letting PPO's own exploration schedule control the spread.

### 3.5.4 Action-space geometry is otherwise good

The `category × price-level × price-offset` factorisation
([`action_helper.py:56-62`](../gym_continuousDoubleAuction/envs/exchg/action_helper.py#L56-L62))
is a thoughtful design: quoting *relative to book depth* rather than in absolute
price makes the policy invariant to the episode's random price anchor, and the
passive/join/aggressive offset is exactly the decision a market maker faces. The
"ghost level" fallback
([`action_helper.py:259-273`](../gym_continuousDoubleAuction/envs/exchg/action_helper.py#L259-L273))
keeps the action well-defined in a thin book, which matters a lot early in an
episode when the book is empty.

### 3.5.5 Simultaneous-move semantics

All agents act on the same observation, and arrival order is randomised
per step ([`action_helper.py:88-96`](../gym_continuousDoubleAuction/envs/exchg/action_helper.py#L88-L96)).
This makes the step a simultaneous-move stage game with a random tie-break —
clean and defensible. Note that `rand_exec_seq(actions, None)` passes
`random_state=None`, so the shuffle is **not** governed by RLlib's `seed`
([`train.py:97,209`](../gym_continuousDoubleAuction/train/train.py#L97-L209)):
runs are not bit-reproducible even with a seed set.

---

## 3.6 Exploration

| Mechanism | Status |
|---|---|
| Policy entropy | `entropy_coeff = 0.0` (RLlib default, never overridden) |
| Entropy at init | **[verified]** 8.27 / 8.45 nats — near-uniform over the `Dict` space |
| Env-side size noise | Present but inert (§3.5.2) |
| Opponent diversity | **The real exploration driver** — the league |
| Episode randomisation | Price anchor `randint(10,100)`, arrival-order shuffle |

With `entropy_coeff=0`, nothing resists premature collapse of the categorical
heads. In a competitive game that is often survivable because the league keeps
the opponent distribution wide — but here the league only refreshes when a
champion is promoted, which requires beating `mean + 0.1·std` of league returns
([`train.py:83`](../gym_continuousDoubleAuction/train/train.py#L83)). If the
learners converge to "always pass" (§3.3.2) they will still clear that threshold
(0 > a negative league mean), so the league will happily fill with champion
snapshots of the do-nothing policy. The mechanism is correct; the reward feeds
it the wrong signal.

**Recommendation:** set `entropy_coeff` to a small positive value with a decay
schedule, and add a guard that refuses to promote a champion whose trade count
is ~0.

---

## 3.7 Sample efficiency

| Quantity | Value | Source |
|---|---|---|
| `train_batch_size_per_learner` | `max_step × num_episodes_per_iter` = 4096 × 4 = **16,384** env steps | [`train.py:99-101`](../gym_continuousDoubleAuction/train/train.py#L99-L101) |
| `num_epochs` | 4 | [`train.py:74`](../gym_continuousDoubleAuction/train/train.py#L74) |
| `minibatch_size` | `None` → RLlib default 128 | [`train.py:80`](../gym_continuousDoubleAuction/train/train.py#L80) |
| Gradient steps / iteration | ≈ 16384/128 × 4 = **512** | derived |
| `lr` | 5e-5, constant | [`train.py:75`](../gym_continuousDoubleAuction/train/train.py#L75) |
| `gamma` | 0.99 (default) → effective horizon ~100 steps | RLlib default |
| `lambda_` | 1.0 (default) → Monte-Carlo advantages | RLlib default |
| Default run length | 16 iterations ≈ **262k env steps** | [`train.py:93`](../gym_continuousDoubleAuction/train/train.py#L93) |

Observations:

- **Only 4 episodes per iteration.** Each episode has one random price anchor and
  one opponent draw per agent slot. Four samples of that joint randomness is a
  very small effective batch for estimating the league gradient, even though the
  *step* count is respectable.
- **γ=0.99 vs a 4096-step episode.** The effective horizon (~100 steps) is 2.5%
  of the episode. Any strategy with a payoff horizon longer than ~100 steps
  (inventory accumulation, sustained market making) is invisible to the return.
  Either raise γ toward 0.999 or shorten episodes.
- **λ=1.0.** RLlib's PPO default is not the usual 0.95. With a working critic,
  λ=0.95 would meaningfully reduce variance; with the broken critic (§3.4) it
  makes no difference, which is itself a diagnostic.
- **262k steps is a smoke-test budget**, not a training budget, for an 8-agent
  competitive game. Realistically this needs 10⁷–10⁸ steps, which is why
  `num_env_runners` matters — see
  [05](05_perspective_ai_engineer.md#56-scalability).

---

## 3.8 Training stability

**Working well:**

- `vf_share_layers=False` with a documented rationale
  ([`model_handler.py:91-94`](../gym_continuousDoubleAuction/train/model/model_handler.py#L91-L94)) —
  correct for non-stationary opponents.
- Champion cooldown + rolling eviction prevents league churn
  ([`league_based_self_play_callback.py:355-381`](../gym_continuousDoubleAuction/train/callbk/league_based_self_play_callback.py#L355-L381)).
- Cross-process-deterministic matchmaking via `crc32`.
- KL penalty at RLlib defaults (`kl_coeff=0.2`, `kl_target=0.01`).

**At risk:**

1. **Unnormalised observations into a `tanh` MLP.** **[verified]** feature ranges
   in a live episode:

   | Block | min | max |
   |---|---|---|
   | normalised bid price | 0.0000 | 0.2117 |
   | sqrt bid size | 0.0000 | **51.19** |
   | normalised ask price | −0.2593 | 0.0000 |
   | sqrt ask size | **−44.01** | 0.0000 |
   | `log_mid` | 4.1589 | 4.2836 |
   | `log1p_spread` | 0.0000 | 2.5649 |

   That is a **~250×** spread between the price features (O(0.1)) and the size
   features (O(50)), feeding a `tanh` first layer
   ([`model_handler.py:88-90`](../gym_continuousDoubleAuction/train/model/model_handler.py#L88-L90)).
   The size units saturate `tanh` immediately and dominate the gradient; the
   price units contribute almost nothing. No `MeanStdFilter` or normalisation
   connector is configured. `sqrt` was the right instinct — it just is not
   enough. Divide sizes by a reference scale (e.g. `sqrt(size)/sqrt(typical)`),
   and centre `log_mid` on `log(55)`.

2. **`grad_clip=None`** (RLlib default). With the reward scale in §3.4 and no
   critic gradient, the policy gradient is the only path — but if the reward is
   normalised without also setting `grad_clip`, the restored critic gradient will
   be large. Set `grad_clip` when fixing the scale.

3. **No per-agent termination.** **[verified]** — forcing `agent_0.nav = −50`:

   ```
   terminateds: {'agent_0': False, 'agent_1': False, 'agent_2': False, '__all__': False}
   done_set: {'agent_0'}
   ```

   `set_done` records bankruptcy in `done_set`
   ([`done_helper.py:15-16`](../gym_continuousDoubleAuction/envs/exchg/done_helper.py#L15-L16)),
   but `set_all_done` then overwrites **every** per-agent flag with `False`
   ([`done_helper.py:32-33`](../gym_continuousDoubleAuction/envs/exchg/done_helper.py#L32-L33)).
   A bankrupt agent keeps generating transitions with a negative NAV for the rest
   of the episode. `_order_approved` blocks its new orders
   ([`trader.py:79-80`](../gym_continuousDoubleAuction/envs/agent/trader.py#L79-L80)),
   so it becomes a zombie emitting only pass-equivalent steps — and its
   accumulated drawdown penalty keeps charging every step, poisoning the
   module's episode return with a term unrelated to its policy.

4. **`tick_size` config is silently dropped.** **[verified]**:

   ```
   config=0.25 | LOB.tick_size before reset=0.25 | after reset=1 | action min_tick=1
   ```

   `reset()` hardcodes `OrderBook(1, ...)`
   ([`continuousDoubleAuction_env.py:141`](../gym_continuousDoubleAuction/envs/continuousDoubleAuction_env.py#L141)),
   discarding `self.tick_size`. Combined with a price anchor drawn from
   `randint(10, 100)`, the *relative* tick size varies **10×** across episodes
   (10% of price at anchor 10; 1% at anchor 100). That is a large, uncontrolled
   source of episode-to-episode non-stationarity. `log_mid` was added to the
   observation precisely so the agent can *detect* which regime it is in, which
   is the right mitigation — but the agent must then learn two very different
   regimes from 4 episodes per iteration.

5. **`initial_price_min/max` are unreachable from training.** They are read in
   `reset()` ([`continuousDoubleAuction_env.py:164-165`](../gym_continuousDoubleAuction/envs/continuousDoubleAuction_env.py#L164-L165))
   but omitted from `TrainConfig.env_config`
   ([`train.py:108-117`](../gym_continuousDoubleAuction/train/train.py#L108-L117)),
   so training always gets the wide `[10, 100]` range. Only the unit tests
   narrow it.

---

## 3.9 Prioritised research agenda

| # | Change | Effort | Expected impact |
|---|---|---|---|
| 1 | Scale rewards by `init_cash`; or raise `vf_clip_param` + set `grad_clip` | S | **Unblocks the critic.** Nothing else matters until this is done |
| 2 | Add private state to the observation (§3.2) | M | Makes the reward learnable at all |
| 3 | Make the drawdown penalty an increment, not a level (§3.3.3) | S | Removes the episode-length-dependent risk tax |
| 4 | Re-scale or remove the micro-penalties; express costs in bps | S | Restores the intended economic incentives |
| 5 | `size_mean → Box(0,1)`; scale or drop `size_sigma` | S | Recovers half the action range, removes a null control |
| 6 | Normalise observation feature scales | S | Removes `tanh` saturation |
| 7 | Terminate bankrupt agents individually | S | Stops zombie transitions polluting returns |
| 8 | `entropy_coeff > 0` with decay; refuse champions with ~0 trades | S | Guards against passivity collapse |
| 9 | Emit size directly as an action instead of distribution parameters | M | Removes unrecorded env-side stochasticity from the ratio |
| 10 | Assert `vf_explained_var > 0` in the integration suite | S | Prevents §3.4 from silently regressing |
| 11 | Raise γ toward 0.999 or shorten episodes | S | Makes long-horizon strategies expressible |
| 12 | Seed `rand_exec_seq` from the env seed | S | Reproducibility |
