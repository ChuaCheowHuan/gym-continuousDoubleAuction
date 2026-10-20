# 12. Perspective: Reinforcement Learning Researcher

Scope: algorithm choice, reward design, environment interaction, sample efficiency, exploration,
training stability.

**Headline:** the RLlib *plumbing* is correct and unusually well tested. The *learning problem*
has three defects that, together, mean the current configuration cannot learn trading behaviour:
the critic is mathematically frozen, the observation omits everything the reward depends on, and
the reward makes passivity a dominant strategy.

---

## 1. Algorithm choice — PPO in a competitive multi-agent game

**What is used.** Independent PPO (`PPOConfig`, `framework("torch")`,
[`train.py`](../gym_continuousDoubleAuction/train/train.py)) with `k=2`
independently-parameterised learners, plus league-based self-play against frozen baselines and
champion snapshots.

**Assessment: appropriate.** PPO is the right default for a partially observed, non-stationary,
competitive setting: it is robust to hyper-parameter error, its trust region tolerates the
distribution shift caused by opponents changing, and it is the algorithm the AlphaStar-style
league literature is built around. The league itself is the correct structural answer to
non-transitivity — a simple "train against your latest self" scheme cycles — and the champion
pool with weighted sampling (`champion_weight=3.0` vs `original_opponent_weight=1.0`) is a
reasonable prioritised-fictitious-play approximation.

**Design notes worth flagging:**

- **Independent learners, not parameter-shared.** `policy_0` and `policy_1` are separate
  networks. Given that both receive *identical* observations (§2), the only thing distinguishing
  them is initialisation and their own gradient history. This is a legitimate choice — it gives
  the league two distinct lineages — but it halves the data per network relative to a shared
  policy.
- **No centralised critic.** With `vf_share_layers=False` each learner has its own decentralised
  value head over the shared public observation. In a competitive zero-sum game a decentralised
  critic is defensible; but combined with the missing private state (§2) the value function is
  being asked to predict a return that depends on unobserved variables — its Bayes-optimal error
  is irreducibly large.
- **Frozen baselines are genuinely uniform.** `RandomRLModule._forward` samples the action space
  directly. The docstring's point is correct and non-obvious: a *frozen randomly-initialised* PPO
  network is not the same opponent distribution — it draws `Box` components from a clipped
  Gaussian (so `size` piles up on the ends of its range) and carries a fixed bias in the discrete heads for the
  whole run.

---

## 2. The observation and the agent's private state

Every agent receives a private tail after the shared book (`State_Helper.private_fields`, 41
floats at defaults): its position, exposure, cash, escrow, NAV, drawdown, entry price relative to
mid, realised P&L and time remaining, then its own resting orders on the book grid, its order
counts, whether its last order-management action landed, and the action mask
([05_observation_space.md](05_observation_space.md) §1). The reward is a function of exactly these
quantities, so the learning problem is well-posed in the agent's observation: two states with
identical books and opposite inventory are now different observations.

What is still absent is **agent identity**. Two agents in the same private state cannot tell
which role they are playing, which matters only if roles should be learned as distinct policies
from one shared module; with one module per trainable agent it is moot.

Until this block existed every agent saw the byte-identical public vector, which made the reward
a function of unobserved state. The analysis of why that was ill-posed, and the fix proposed for
it, is in [29](29_fixed_issues.md#12-2--the-observation-contained-no-private-state); the register
entry is [S1-2](29_fixed_issues.md#s1-2--observation-contains-no-private-state-verified-fixed).

---

## 3. Reward design

Full specification in [07_reward_function.md](07_reward_function.md).

### 3.1 The reward is zero-sum in its NAV term

NAV is conserved exactly ([verified], 4 agents × 1,000,000 → final total NAV 4,000,000.00), so
`Σ_agents nav_change = 0` at every step, and the reward's NAV term inherits that: with
`loss_multiplier` 1.0 and the drawdown charged as a signed change, `nav_term` sums to exactly
`0.000000` across agents over 1,000 steps, and 4 random agents over 300 steps score **−0.0104** in
total ([07_reward_function.md](07_reward_function.md) §2.1). The remaining negative-sum part is the
friction of the micro-terms, which is small by design.

It used to be strongly negative-sum (−591,027 over the same 300 steps) through a loss-aversion
multiplier and a drawdown level: [S1-3](29_fixed_issues.md#s1-3--doing-nothing-is-a-dominant-strategy-verified-fixed) and [S2-1](29_fixed_issues.md#s2-1--drawdown-is-penalised-as-a-level-not-an-increment-verified-fixed).

### 3.2 The league ranks a signal that is not comparable across roles

Because the four shaping terms are not zero-sum, returns are not comparable across policies
playing different roles — and the league callback, by default, ranks trainable modules against a
pooled `mean + k·std` computed over *all* modules, including the frozen random baselines.

A policy can therefore clear the default promotion threshold by **trading less**, not by trading
*better*. Two things now stand against that: `min_champion_trades` refuses a champion that has
stopped trading (S3-11), and `league_self_play.promotion_reference: "excluding_baselines"`
computes the threshold over the trainable modules and champions only. The second is an option,
off by default, so the pooled ranking is still what a default run does ([S3-12](29_fixed_issues.md#s3-12--the-league-ranks-a-signal-that-is-not-comparable-across-roles-fixed---as-an-option)).

### 3.3 Doing nothing is not dominant, and cannot be beaten on average

Passing every step scores exactly `0.0`, and always will: in a market where NAV is conserved, no
reward can make trading positive-sum *on average*. What matters is that passing is no longer
**dominant**: random trading scores −0.0104 over 4 agents × 300 steps, so the residual friction is
~0.5% of a typical NAV move rather than dwarfing it, and an agent with an edge is not taxed out of
using it. That passing *was* dominant, a Nash equilibrium and the joint optimum, is
[S1-3](29_fixed_issues.md#s1-3--doing-nothing-is-a-dominant-strategy-verified-fixed).

### 3.4 The drawdown term charges a change, not a level

The term charges the **signed** change in drawdown, `(current_drawdown − previous_drawdown) /
init_nav`, which telescopes over an episode to `−drawdown_penalty × final_drawdown` whatever path
was taken. A round trip down and back to the peak is free, ending in drawdown is penalised, and the
term cannot be farmed; its magnitude no longer scales with `max_step`. The clipped
`max(0, Δ)` form this document once proposed would have been an asymmetric loss multiplier by
another name: why it was rejected, and the level form it replaced, are [S2-1](29_fixed_issues.md#s2-1--drawdown-is-penalised-as-a-level-not-an-increment-verified-fixed);
[07_reward_function.md](07_reward_function.md) §2.1 works through the arithmetic.

### 3.5 The micro-terms are scaled to the NAV term

Every NAV-derived quantity is divided by `acc.init_nav`, and the coefficients are calibrated
against the measured move distribution: `order_penalty` 1e-05, `trade_penalty` 2e-05,
`passive_bonus` 2e-05, ~0.5–1% of the median step that moves NAV at all. `passive_bonus ==
trade_penalty` makes a passive fill net-free while an aggressive one costs 0.2 bps. Real
maker/taker fees charged through NAV exist as an option (`maker_fee_bps`, `taker_fee_bps`, both 0
by default; [13_perspective_financial_trader.md](13_perspective_financial_trader.md) §4). When the
coefficients were 5–6 orders of magnitude too small to matter: [S2-3](29_fixed_issues.md#s2-3--transaction-cost-proxies-are-10⁵-too-small-verified-fixed).

### 3.6 Coefficients are configurable

All reward coefficients are `env_config` keys, read from the `environment` group of
`config/train_config.json` (falling back to `config/env_defaults.json` for a bare env), so they are
captured in the checkpoint's config and sweepable by Tune. For a research repository, reward
shaping is the primary experimental axis, and it is the axis the config file exposes. They used to
be function-local literals ([29](29_fixed_issues.md#12-36--the-reward-coefficients-were-function-local-literals)).

---

## 4. The critic

The critic learns. `set_reward` divides every NAV-derived quantity by `acc.init_nav`, so value
targets are O(1) and RLlib's default `vf_clip_param` of 10.0 does not bind.
`integration/test_progress_and_vf.py` asserts `|vf_explained_var| >= 1e-3` on a real short run,
so a regression is caught rather than hidden behind a flat `total_loss`. `vf_explained_var` is the
metric to watch for this; `total_loss` is not.

`grad_clip` is still unset ([15](15_findings_and_recommendations.md)). With O(1) targets this is a
precaution rather than a defect.

How the critic used to receive zero gradient (value targets in the 10⁴–10⁷ range against a clip of
10), what that did to GAE and PPO, and the fixes considered, is
[29](29_fixed_issues.md#12-4--the-critic-could-not-learn-vf_clip_param-saturation); the register
entry is [S1-1](29_fixed_issues.md#s1-1--ppos-critic-receives-zero-gradient-verified-fixed).

---

## 5. Environment interaction and the action space

Full specification in [06_action_space.md](06_action_space.md).

### 5.1 Size is one action head

The policy emits the order size directly as one `size` head on `Box(0, 1)`, sampled by the policy
distribution, so `log π(a|s)` covers it and PPO's own exploration schedule controls the spread.
The environment draws nothing. Three earlier defects led here, each in the register: half the old
`size_mean` range was a mirror image of the other ([S3-1](29_fixed_issues.md#s3-1--half-the-size_mean-action-range-is-a-no-op-verified-fixed)), the `size_sigma` head was a null
control ([S3-2](29_fixed_issues.md#s3-2--the-size_sigma-head-is-inert-verified-fixed)), and the environment sampled the size outside the policy's log-probability
([S3-3](29_fixed_issues.md#s3-3--size-is-sampled-by-the-environment-outside-the-policys-log-prob-verified-fixed)).

### 5.4 Action-space geometry is otherwise good

The `category × price-level × price-offset` factorisation is a thoughtful design: quoting
*relative to book depth* rather than in absolute price makes the policy invariant to the
episode's random price anchor, and the passive/join/aggressive offset is exactly the decision a
market maker faces. The "ghost level" fallback keeps the action well-defined in a thin book,
which matters a lot early in an episode when the book is empty.

Observation and action share one stationary coordinate: price code *j* is a fixed tick offset
from the reference price, the same grid the observation's book uses
([05_observation_space.md](05_observation_space.md) §1.4). It used to be the *k*-th occupied
price, which moved every step ([S3-15](29_fixed_issues.md#s3-15--level-index-is-a-non-stationary-coordinate-verified-fixed)).

### 5.5 Simultaneous-move semantics and reproducibility

All agents act on the same observation, and arrival order is randomised per step. This makes the
step a simultaneous-move stage game with a random tie-break — clean and defensible.

**Reproducibility.** An episode is reproducible from its seed: one `Generator` on the env,
gymnasium's own `self.np_random`, is threaded through the price anchor and the arrival shuffle,
and `test_seeding.py` pins it, seeding the *global* stream to two different values while asserting
the seeded episode is unchanged. Seeding used to do nothing at all ([S3-5](29_fixed_issues.md#s3-5--seeding-is-entirely-non-functional-verified-fixed)).

One limitation to keep in view: this makes an *episode* reproducible from its seed. A whole
distributed training run is not, because RLlib seeds each worker from `config.seed + worker_index`
once at construction and a restarted runner re-seeds from the same value, rewinding its stream
mid-run.

### 5.6 Silent no-ops are measured, masked and unpenalised

Rejected orders (insufficient cash, NAV ≤ 0) and a `modify` / `cancel` with nothing to target are
counted: `num_rejected_step`, `is_pass_action` and `num_unmatched_step` reach `info` and become
the `order_rejection_fraction`, `pass_action_fraction` and `unmatched_action_fraction` metrics, so
a policy collapsing to always-pass is visible while it happens. The impossible order-management
categories are masked, taking the unmatched fraction from 29.6% to 0.2% under random play, and the
agent sees whether its last order-management action landed (`unmatched_last_step`)
([S4-14](29_fixed_issues.md#s4--minor), [S3-24](29_fixed_issues.md#s3-24--modify-and-cancel-cannot-be-aimed-so-they-are-mostly-dead-actions-verified-fixed)).

**Still open: the learning signal.** A refused or dead action is not penalised by default.
`dead_action_penalty` exists and ships at `0.0` deliberately, because any positive value makes the
reward negative-sum across agents again (S1-3). The cash-driven refusals are size-driven and a
category mask cannot reach them. Whether either kind should be shaped is a reward-design decision.

---

## 6. Exploration

| Mechanism | Status |
|---|---|
| Policy entropy | `entropy_coeff` 0.01 falling to 0.001 on a schedule in global env steps |
| Entropy at init | **[verified]** 7.95 / 8.84 nats — near-uniform over the `Dict` space |
| Env-side size noise | None: the size is a policy action (§5.1) |
| Opponent diversity | **The real exploration driver** — the league |
| Episode randomisation | Price anchor `randint(10,100)`, arrival-order shuffle |

The entropy bonus resists premature collapse of the categorical heads, and the league keeps the
opponent distribution wide. The league only refreshes when a champion is promoted, so what it is
fed matters: `std_dev_multiplier` is 1.5 (2.5 would never promote at the default league size) and
`min_champion_trades` refuses to promote a snapshot that has stopped trading, so a league cannot
fill with do-nothing champions. When the entropy coefficient was 0 and the multiplier 0.1, so that
a champion was promoted on the first eligible iteration: [S3-11](29_fixed_issues.md#s3-11--no-entropy-bonus-and-champion-promotion-cannot-detect-passivity-verified-fixed).

---

## 7. Sample efficiency

| Quantity | Value | Source |
|---|---|---|
| `train_batch_size_per_learner` | `max_step × num_episodes_per_iter` = 4096 × 4 = **16,384** env steps | [`train.py`](../gym_continuousDoubleAuction/train/train.py) |
| `num_epochs` | 4 | [`train.py`](../gym_continuousDoubleAuction/train/train.py) |
| `minibatch_size` | `None` → RLlib default 128 | [`train.py`](../gym_continuousDoubleAuction/train/train.py) |
| Gradient steps / iteration | ≈ 16384/128 × 4 = **512** | derived |
| `lr` | 5e-5, constant | [`train.py`](../gym_continuousDoubleAuction/train/train.py) |
| `gamma` | 0.999 (`ppo` config key) → effective horizon ~1,000 steps | config |
| `lambda_` | 0.95 (`ppo` config key) | config |
| Default run length | 16 iterations ≈ **262k env steps** | [`train.py`](../gym_continuousDoubleAuction/train/train.py) |

Observations:

- **Only 4 episodes per iteration.** Each episode has one random price anchor and one opponent
  draw per agent slot. Four samples of that joint randomness is a very small effective batch for
  estimating the league gradient, even though the *step* count is respectable.
- **γ=0.999 against a 4096-step episode.** The effective horizon is about 1,000 steps, a quarter
  of the episode, and λ=0.95 restores GAE's variance reduction. Both are the usual choices for a
  long episode, not tuned on this env; they were 0.99 and 1.0 (RLlib's defaults) until
  [S3-13](29_fixed_issues.md#s3-13--γ099-against-4096-step-episodes-verified-fixed), and results trained at those
  values are not comparable.
- **262k steps is a smoke-test budget**, not a training budget, for an 8-agent competitive game.
  Realistically this needs 10⁷–10⁸ steps, which is why `num_env_runners` matters — see
  [09_distributed_training.md](09_distributed_training.md).

---

## 8. Training stability

**Working well:**

- `vf_share_layers=False` with a documented rationale — correct for non-stationary opponents.
- Champion cooldown + rolling eviction prevents league churn.
- Cross-process-deterministic matchmaking via `crc32`.
- KL penalty at RLlib defaults (`kl_coeff=0.2`, `kl_target=0.01`).
- Advantage standardisation per module keeps the update well-conditioned.

**At risk:**

1. **The default encoder has no normalisation in front of it.** The observation is scaled at the
   source (sizes as `sqrt(V / limit_max_size)`, `log_mid` centred), so the book features land
   within ±1.2 and the size/price spread is 3.7×; `encoder_type: mlp` relies on that and has no
   `MeanStdFilter` or normalisation connector. The other encoders LayerNorm after their input
   projection ([18](18_configuration.md) §5.4). The ~80–250× spread this used to be is
   [S2-2](29_fixed_issues.md#s2-2--unnormalised-observation-scales-saturate-the-tanh-mlp-verified-fixed).

2. **`grad_clip=None`** (RLlib default). With O(1) value targets (§4) the critic gradient is
   bounded by the reward scale, so this is a precaution, recorded as open in
   [15](15_findings_and_recommendations.md).

3. **The relative tick varies 10× across episodes by default.** The configured `tick_size`
   reaches the book (it used to be dropped:
   [S3-4](29_fixed_issues.md#s3-4--the-order-books-tick_size-is-inert-verified-fixed)), but with the price anchor
   drawn from `randint(10, 100)` the tick is 10% of price at anchor 10 and 1% at anchor 100: a
   large source of episode-to-episode non-stationarity. `log_mid` lets the agent *detect* the
   regime, but it must still learn very different regimes from 4 episodes per iteration.
   `initial_price_min` / `initial_price_max` are `TrainConfig` fields forwarded to the env, so
   narrowing the range is a one-line config edit; the checked-in config ships the wide range, so
   this is an experiment to run rather than a limitation.

Bankrupt agents terminate individually and stop emitting transitions; that they used to linger as
zombies charged a drawdown every step is
[S2-4](29_fixed_issues.md#s2-4--bankrupt-agents-are-never-terminated-verified-fixed).

---

## 9. Prioritised research agenda

Every item on the agenda this document set out is done: reward scaling, private state, the
drawdown change, cost scaling, the size head, feature scaling, bankrupt termination, entropy and
passivity guards, the stack normaliser and trade flow, γ, seeding, and dead-action counts. The
table, with what closed each item, is in
[29](29_fixed_issues.md#12-9--the-prioritised-research-agenda-as-completed).

What this perspective would do next is in §6–§8: the relative-tick swing of the default price range
(§8, a config choice), agent identity (§2), and whether dead actions should be shaped (§5.6).
All three are tracked in [15](15_findings_and_recommendations.md).