# 15. Consolidated Findings and Recommendations

Severity-ranked across all three perspectives and both source documentation sets. **[verified]**
marks a finding confirmed by executing the code; raw output is in
[16_verification_log.md](16_verification_log.md).

---

## The register at a glance

```mermaid
mindmap
  root((Findings))
    S1 Blocking — all fixed
      S1-1 critic got zero gradient — fixed
        rewards are now a fraction of init_nav
      S1-2 no private state — fixed
        own resting orders still absent
      S1-3 doing nothing dominated — fixed
      S1-4 bare env could not trade — fixed
      S1-5 cash check bypassable — fixed
        escrow still charges closing orders
    S2 Major — all fixed
      S2-1 drawdown charged as a level — fixed
      S2-2 observation scales saturate tanh — fixed
      S2-3 cost proxies 10^5 too small — fixed
        real maker/taker fees still open
      S2-4 bankrupt agents never terminated — fixed
      S2-5 self-matching enables mark manipulation — fixed
      S2-6 per-frame normalizer — fixed
      S2-7 no trade-flow features — fixed
      S2-8 no logging framework — fixed
      S2-9 JEPA variance hinge had no gradient — fixed
      S2-10 lstm encoder ignored the grid order — fixed
      S2-11 VWAP negative, obs reported flat — fixed
      S2-12 gymnasium.make raised — fixed
    S3 Moderate
      action space
        S3-1 half of size_mean is a no-op
        S3-2 size_sigma is inert
        S3-3 env-side sampling breaks the log-prob
      simulator and config
        S3-4 the book's tick_size is inert
        S3-5 seeding — fixed
        S3-7 sys.exit in the engine
        S3-20 dead escrow path — fixed
      training and league
        S3-8 detached callback — fixed
        S3-11 promotion cannot detect passivity
        S3-12 returns not comparable across roles
        S3-16 idle opponent killed promotion — fixed
        S3-17 retention deleted fresh checkpoints — fixed
      packaging
        S3-6 install_requires — fixed
        S3-18 config not in the wheel — fixed
        S3-19 episodes ran one step long — fixed
        S3-21 visualize not in the wheel — fixed
        S3-22 fingerprint hashed the raw spec — fixed
    S4 Minor
      dead code, hygiene, tooling
      S4-9 pickle episode data — fixed
      S4-14 dead-action fraction — partly fixed
      S4-18 duplicate CODEOWNER files
```

---

## Severity legend

| Level | Meaning |
|---|---|
| **S1 — Blocking** | Prevents the system from doing what it is built to do |
| **S2 — Major** | Substantially degrades results or correctness |
| **S3 — Moderate** | Real defect with a bounded blast radius |
| **S4 — Minor** | Hygiene, maintainability, polish |

---

## S1 — Blocking

### S1-1 · PPO's critic receives zero gradient **[verified, fixed]**

`vf_clip_param` defaults to 10.0 and is never overridden, while value targets are NAV sums in the
10⁴–10⁷ range. `torch.clamp(vf_loss, 0, 10.0)` is flat there, so `∂L_vf/∂θ = 0` for every sample.

```
vf_loss            10.0             ← pinned at the clip bound
vf_loss_unclipped  13,015,503  /  10,513,565
vf_explained_var   8.91e-05    /  5.42e-05      ← critic explains ~0% of variance
total_loss         9.25        /  9.48          ← 10.0 of which is a constant
```

PPO degenerates to REINFORCE with a batch-standardised baseline. Silent: the reported
`total_loss` looks small and stable because 10.0 of it is a constant.

**Fixed.** Every NAV-derived quantity in `set_reward` is now divided by `trader.acc.init_nav` —
the account's own record of what the trader started with, rather than a second copy of `init_cash`
that could drift from it. Value targets are O(1), the clamp no longer binds, and the substantive
`vf_explained_var` assertion in `integration/test_progress_and_vf.py` — which was a *strict xfail*
pinning this finding — XPASSed on the first real run after the change and is now a live regression
guard. The same change also closed S2-3 and made S2-1's fix expressible.
→ [12 §4](12_perspective_rl_researcher.md#4-the-critic-cannot-learn--vf_clip_param-saturation),
[07 §2.1](07_reward_function.md)

### S1-2 · Observation contains no private state **[verified, fixed — except resting orders]**

Every agent received the byte-identical 168-float public book vector (`distinct obs vectors
across agents: 1`). Absent: `net_position`, `VWAP`, `nav`, `max_nav`, `cash`, own resting orders,
agent identity, time remaining.

The reward is literally `f(nav, prev_nav, max_nav, …)` — all unobserved. Two states with
identical books but opposite inventory require opposite optimal actions and were
indistinguishable. The drawdown term depends on `max_nav`, a path functional over the whole
episode, so this was not partial observability a recurrent net could recover. It also made the
`modify` and `cancel` categories (4 of 9) blind.

**Fixed.** The observation is now `[ n_hist × snapshot | private ]`, 177 floats: the book prefix
is still shared and computed once, and a 9-float per-agent block is appended.
`State_Helper.PRIVATE_FIELDS` is the single definition of its layout and `__init__` checks its
length against `private_dim`. Every field is normalised by the trader's own `init_nav` or is
already a ratio, so the block is O(1) and cannot saturate the `tanh` MLP the way raw sizes do
(S2-2).

`test_shared_history_multi_agent_uniformity` — which asserted the defect as a requirement — is
replaced by `test_agents_see_distinct_private_state`, plus a test that the book prefix is *still*
shared, since that half was never the bug.

Three consequences worth knowing:

- **The observation width is structural.** No checkpoint written before this loads.
- **`obs[-SNAPSHOT_DIM:]` is now wrong everywhere.** It returns the private block plus a truncated
  final snapshot. Slice against `n_hist * SNAPSHOT_DIM` — `ObsLayout.book_flat_dim` and
  `split_private` exist for this. Four test files and the probe harness held that assumption.
- **The private block is not tokenised with the book.** Token width is
  `max(book_rows, extra_dim)`, so folding it in would widen every book token to 9 channels and
  right-pad with zeros. It gets its own projection and joins as one token — `blocks.PrivateToken`,
  shared by every tokenising encoder so they stay comparable.

**Still open:** own resting orders and agent identity are not in the block. Resting orders are the
larger gap — `modify` and `cancel` remain partly blind, since an agent can see its escrowed cash
but not which orders that cash is committed to.
→ [12 §2](12_perspective_rl_researcher.md#2-the-observation-contains-no-private-state),
[05 §1.0](05_observation_space.md)

### S1-3 · Doing nothing is a dominant strategy **[verified, fixed]**

| Policy | Total return, 4 agents × 300 steps |
|---|---|
| All agents `category=0` (pass) | **0.0 exactly** |
| Random trading | **−591,027** |

NAV is conserved exactly (total 4,000,000.00 at both ends), so `Σ nav_change = 0`, but the
loss-aversion multiplier and the drawdown level make the reward strictly negative-sum.
`(pass, …, pass)` is both a Nash equilibrium and the joint optimum, and gradient descent finds it
early because the fastest way to raise return is to stop trading. Empty-market collapse is the
predicted outcome.

**Fixed.** `loss_multiplier` 1.5 → **1.0**, the drawdown level → a signed change (S2-1), and the
micro-penalties rescaled to reward units (S2-3). Re-measured on the same 4 agents × 300 steps:

| | before | after |
|---|---|---|
| all agents pass | `0.0` | `0.0` |
| random trading | **−591,027** | **−0.0104** |

Passing still scores exactly zero, which is correct rather than residual: in a zero-sum market no
reward can make trading positive-sum *on average*. What changed is that the friction is now ~0.5%
of a typical NAV move instead of dominating it, so trading is no longer dominated for an agent with
any edge. Measured over 1,000 steps, `nav_term` sums to **exactly 0.000000** across agents.
→ [12 §3.3](12_perspective_rl_researcher.md#33-doing-nothing-is-a-dominant-strategy),
[07 §4.3](07_reward_function.md)

### S1-4 · The default standalone env could not trade **[verified, fixed]**

`config/env_defaults.json` shipped `init_cash: 0`. `Trader._order_approved` refuses on
`nav <= 0` before it inspects anything else, so every trader in a bare env started bankrupt: no
order was ever placed on any side, `Done_Helper.set_done` put all five agents in `done_set` on
the first pass, and `terminateds["__all__"]` came back `True` after a single `step()`. The
configured `max_step: 64` was unreachable.

| `continuousDoubleAuctionEnv({})` | Before | After |
|---|---|---|
| Trades in 64 steps | **0** | 134 |
| Steps before `terminateds["__all__"]` | **1** | 64 (truncated) |
| Final NAVs | `['0','0','0','0','0']` | spread around 1,000,000 |

This is the form `gymnasium.make("continuousDoubleAuction-v0")` produces and the one
[01](01_overview.md) documents as "small, cheap and prints what it is doing". The value was
written down in three places and its consequence in none of them.

CI did not catch it: the only bare-env job is the `CDA_rand.py` smoke run, which builds its own
env config from `cli_defaults.json` — where `init_cash` is 1,000,000 — and so overrode the one
value that broke it.

**Fixed:** `init_cash` is 1,000,000 in `env_defaults.json`, matching `cli_defaults.json` and
`train_config.json` so all three agree. `test_env_lifecycle.py::TestBareEnvIsTradable` reads the
checked-in file deliberately — a fixture supplying its own cash would reproduce exactly the blind
spot the smoke run had.

### S1-5 · The cash check is bypassable; position is not bounded by capital **[verified, fixed]**

`Trader._order_approved` waived the cash check for the portion of an order that reduces the
*current* net position, and nothing netted an order against the trader's **other resting orders**.
So N individually-"closing" orders were each approved against the same lots.

Executed: a trader long 10 with `cash = 0` rested ten 10-lot asks across ten price levels — every
one approved, `cash` driven to −10,550 — and when they filled it held a **90-lot short built from a
10-lot long, without a single refusal**. Since the approval is what bounds risk, this is not a
rounding error in the ledger; it is the absence of a position limit.

This is the one finding that contradicts the register's own summary below, which praises the
buying-power logic as "subtle and right". It is right per order and wrong in aggregate.

**Fixed.** `_order_approved` computes the closable position as `abs(net_position)` minus this
trader's own resting quantity on that side, excluding the order an upsert or a modify is about to
replace (a `limit` at a price it already rests at, or a `modify`, releases the old order in the same
call that would otherwise be charged for it). The same sequence now refuses nine of the ten and the
position goes flat instead of flipping. Pinned by `test_resting_exposure.py`.

**Still open, and deliberately.** The escrow charges full notional for *any* resting order,
including one that only closes, so a cash-poor trader closing a position drives `cash` negative
while `cash_on_hold` rises by the same amount. That is a reclassification, not a loss — NAV is
untouched — and it is asserted rather than fixed, because changing it means tracking escrow per
order: every partial-fill path in `Cash_Processor` assumes escrow equals full notional.


---

## S2 — Major

### S2-1 · Drawdown is penalised as a level, not an increment **[verified, fixed]**

`max_nav` is monotone within an episode, so a drawdown is re-charged **every step** until NAV
exceeds the old peak. Measured over 300 steps × 4 random agents: drawdown = **−416,473**, roughly
**2.4×** the entire NAV term (−174,502). At `max_step=4096` a 1,000-unit early drawdown costs
~800,000.

Side effects: not potential-based (changes the optimum, not just the shaping); magnitude scales
with `max_step`, making episode length a hidden risk-aversion knob; non-Markov in the observation.

**Fixed — but not with the fix this entry used to propose.** `max(0, new_dd - prev_dd)` charges
`nav_term` a second time on every losing step below the peak and refunds nothing on the way back
up, so a round trip costs `drawdown_penalty × X`: an asymmetric loss multiplier by another name,
which would have left S1-3 half-open while looking like a fix for this. What shipped is the
**signed** change, `(current_drawdown - previous_drawdown) / init_nav`, whose per-step charges
telescope to `-drawdown_penalty × final_drawdown` over an episode regardless of path. A round trip
is free, ending in drawdown is still penalised, and the term cannot be farmed.
→ [12 §3.4](12_perspective_rl_researcher.md#34-the-drawdown-term-is-a-level-not-a-delta),
[07 §4.1](07_reward_function.md)

### S2-2 · Unnormalised observation scales saturate the `tanh` MLP **[verified, fixed]**

| Feature block | Range (one 300-step rollout) |
|---|---|
| normalised prices | ±0.58 |
| sqrt sizes | **±47** |
| `log_mid` | 3.68 … 4.04 |

An ~80–250× spread (book-dependent; a second run measured ±0.26 vs ±51) into a `tanh` first layer
with no `MeanStdFilter` or normalisation connector. Size features saturate and dominate; price
features contribute almost nothing.

**Fixed**, in three places. Level volumes are `sqrt(V / limit_max_size)` — `limit_max_size` is the
scale orders are drawn on, and over 9,565 populated levels that lands at a median of 0.52, a p99 of
0.94 and a maximum of 1.32. `log_mid` is centred on the log of the geometric mean of the price-anchor
range, a constant of the configuration rather than of the episode, so the information is unchanged
and the feature spans about ±1.15 instead of being a standing +4.6 bias. And the private `position`
field no longer divides by `limit_max_size`, which is not a maximum of anything — it scales the mean
of the Gaussian `_set_size` draws from and clamps nothing — while inventory accumulates across
fills; there is now a `position_scale` key, defaulted to the measured p95 of 1,500.

Re-measured: the size/price standard-deviation ratio falls from **220× to 3.7×**, every book feature
lands inside ±1.2, and inventory exceeds its scale on **0.0%** of agent-steps against 13.2%.
`test_obs_feature_scales.py` asserts the *property* — that the blocks are comparable and bounded —
rather than the formulas, which stay pinned where they were.
→ [05 §7.5](05_observation_space.md#75-feature-scales-differ-by-one-to-two-orders-of-magnitude-after-normalization)

### S2-3 · Transaction-cost proxies are ~10⁵× too small **[verified, fixed — real fees still open]**

`order_penalty=0.1`, `trade_penalty=0.05`, `passive_bonus=0.1` against per-step NAV moves of
−10,949 … +6,126. Three of the reward's five stated objectives — "reducing number of trades",
"selective order placement", "capturing spread" — therefore have no effect. There are no real
fees anywhere in the simulator, so market making has no revenue model and crossing the spread has
no cost.

**Half fixed.** The *scale* problem is closed: the coefficients now multiply quantities already
expressed as fractions of starting capital, so `1e-05` is one basis point of it, and they were
calibrated against measurement rather than chosen — over 8,000 random-agent steps, 37% of steps
move NAV at all and one that does moves it by a median 1.9e-03 of starting capital, so the
penalties sit at 0.5–1% of that. `passive_bonus` is set equal to `trade_penalty`, making a passive
fill net-free while an aggressive one costs 0.2 bps, which expresses "capture spread" as a price.

**Still open:** these remain *proxies charged against the reward*, not fees charged against NAV.
Real maker/taker fees in basis points of notional, applied inside settlement so they flow through
the ledger, would also require relaxing the NAV-conservation assertion to account for them. That
is a simulator change, not a reward change, and it is unaffected by this fix.
→ [13 §4](13_perspective_financial_trader.md#4-there-are-no-transaction-costs),
[07 §4.2](07_reward_function.md)

### S2-4 · Bankrupt agents are never terminated **[verified, fixed]**

Forcing `agent_0.nav = −50`:

```
terminateds: {'agent_0': False, 'agent_1': False, 'agent_2': False,
              'agent_3': False, '__all__': False}
done_set:    {'agent_0'}
```

`set_done` records bankruptcy, then `set_all_done` overwrites every per-agent flag with `False`.
The agent keeps emitting transitions, keeps accruing the per-step drawdown tax (S2-1), and its
resting orders stay live and executable. Its module return is then dominated by a constant
unrelated to its policy — and that return is what champion promotion reads.

**Fixed.** `set_done` decides and applies termination in the same call — which also settles the
`done_set`-is-monotone worry, since an agent goes at the moment its NAV is non-positive and no later
step can terminate a recovered one. It keeps the observation and reward of its terminal transition,
loses its resting orders, and drops out of `agents` (not `possible_agents`, which stays the fixed
roster).

One consequence was worth catching: the NAV conservation check read only the final step's `info`, so
a terminated agent's NAV vanished from the total and any episode containing a bankruptcy would have
read as a violation — halting a strict run over a ledger that was intact. `on_episode_step` now
carries each agent's last reported NAV forward, and a test pins that a *genuine* breach is still
caught when an agent terminated.

### S2-5 · Self-matching enables mark manipulation **[verified, fixed]**

An agent can cross its own resting order (`same ID both sides: True`). The accounting handles it
consistently, so NAV stays conserved — but `mark_to_mkt` uses the **last tape print** as the mark
for *everyone*. An agent holding inventory can self-trade one contract at a chosen price and
instantly re-mark the whole market, including its own reward. Every regulated venue mandates
self-match prevention for exactly this reason.

It was also **free**: `_process_trades` sends a self-trade down a branch that never calls
`process_acc`, so neither `num_trades` nor `num_trades_step` incremented and `trade_penalty` never
charged for it. Any "refuse to promote a champion that does not trade" guard would have been evadable
the same way.

**Fixed, and it took both halves.** `Trader._prevent_self_match` withdraws the trader's own resting
orders that an incoming order would cross, before it reaches the matcher — the "cancel resting order"
SMP mode. It lives in `Trader` rather than as a `trade_id` skip in `process_order_list`, where it
would naturally go, because `envs/orderbook/` is off-limits (S3-4).

Prevention alone was not enough, which is the part worth reading twice. The *resting leg* of a
prevented self-cross survives, and with the mark falling back to whichever side of the book was
populated, that lone order simply became the mark — the same 1,000 NAV moved with no trade at all. So
`mark_price` uses the midpoint only when the book is genuinely two-sided, and falls back to the last
trade rather than to a one-sided quote. Moving the mark now takes a real two-sided market, and moving
the mid in one means posting a better quote somebody else can lift — a price someone can take the
other side of, which is the whole difference. The source is a `mark_price_source` config key ("mid"
or "last") because the change moves NAV dynamics and a run should be able to reproduce the old
behaviour.
→ [13 §3.1](13_perspective_financial_trader.md#31-self-matching)

### S2-6 · Every frame in the observation stack has a different normalizer **[verified, fixed]**

`set_agg_LOB` computes `M` from the book at that moment; `prep_next_state` appends the
already-normalized frame to the deque. Frames *t−3 … t* each carry their own `M_{t−3} … M_t`, so
**they cannot be differenced meaningfully** — which is the entire purpose of stacking them. A
resting order at a fixed absolute price appears to move whenever the midpoint moves.

Partially mitigated by the per-frame `log_mid`, which lets the agent recover each frame's
normalizer, but the network must then learn to undo the rescaling itself.

**Fixed** exactly that way. The deque holds raw frames and `prep_next_state` normalises the whole
stack once, by `M_t`. Concretely: a bid resting at 90 while the midpoint moved 100 → 96 used to read
0.100 in one frame and 0.063 in the next — the order had not moved, its denominator had. It now reads
0.0625 in both, `log_mid` still differs across them (0.0 → −0.0408) because each frame keeps its own
midpoint, and a new `mid_return` scalar records the move as −0.04. Nothing is lost; it is no longer
smeared through every price in the book.
→ [05 §7.1](05_observation_space.md#71-each-frame-in-the-stack-is-normalized-by-a-different-denominator)

### S2-7 · No trade-flow information — the tape loop is dead code **[verified, fixed]**

`set_agg_LOB` iterates the tape, uses nothing, and increments a discarded counter. The body is a
commented-out `write` copy-pasted from `OrderBook.__str__`. The observation therefore contains
**zero information about executions**: no last traded price, no trade direction, no signed
volume, no trade count.

In a continuous double auction, aggressive order flow is the single most predictive public
signal — more so than the resting book, which is largely stale intentions. Order-imbalance
helpers already exist in `train/helper/helper.py`, unused.

**Fixed.** The loop is now `_trade_flow`, and three scalars join the snapshot: `signed_volume` —
each fill signed by its **initiator's** side, which is what makes it order flow rather than volume —
`log1p_trade_count` and `trade_direction`. Over a 400-step rollout each is non-zero on ~58% of steps.
`extra_dim` goes 2 → 6 and is now checked against a new `EXTRA_FIELDS` tuple, on the same rule as
`book_rows` and `private_dim`; it was documentation before, so setting it was a silent no-op. The
observation is 193 floats rather than 177, so no earlier checkpoint loads.

The flow cursor advances only in `prep_next_state`, never in `set_agg_LOB`, because the latter runs
twice per step and only one call commits a frame — a display-only snapshot must not eat the step's
trade flow.
→ [05 §7.3](05_observation_space.md#73-the-tape-loop-is-dead-code--there-is-no-trade-flow-information-at-all)

### S2-8 · No logging framework; the callback prints 42 diagnostics per episode — **fixed**

*Was:* zero `import logging`; ~86 `print()` calls in `envs/` + `train/`; every remote worker
printing independently with no level filter, no attribution and no off switch; the
NAV-conservation check — a **hard ledger invariant** — printing `FAILED` rather than raising.

*Now:* all of `envs/` and `train/` reports through `logging_setup.get_logger`, at levels, with the
pid in the format and the level exported to worker processes; a violation raises by default and
emits `nav_conservation_error` either way. `test_logging_setup.py` fails the build if a `print`
comes back.

Still open, tracked in [11 §4](11_logging_and_observability.md#4-recommended-additions): only
three custom values reach TensorBoard, and no per-iteration history is written to disk.

### S2-9 · The JEPA anti-collapse hinge contributes zero gradient **[verified, fixed]**

`_jepa_loss` derived `std`, the off-diagonal covariance and
`variance_penalty = relu(VARIANCE_TARGET − std)` from `target`, which is built inside
`torch.no_grad()` by a trunk whose parameters are additionally `requires_grad_(False)`. Confirmed at
runtime: `std.grad_fn is None`, `variance_penalty.requires_grad is False`.

Nothing raised, and nothing could — adding a constant to a tensor that *does* carry a `grad_fn` is
legal, and the sum still backpropagates, just not through the term meant to do the work. So the
mechanism `jepa.py`, `train_config.json`'s `_note_collapse` and `pretrain/__init__` all describe as
"the only thing actively pushing back once a collapse starts" did not exist. The encoder had
collapse *detection* and no collapse *prevention*; `variance_coeff` was a dead knob that still
entered `encoder_fingerprint`, so changing it invalidated every checkpoint while changing nothing;
and the constant was silently folded into the logged `jepa_aux_loss`, making it incomparable with
`predict_loss`.

**Fixed.** The statistics come from `predicted`, the online counterpart of `target` — same
positions, same count, gradients reaching the predictor and, through `context`, the trunk —
layer-normed exactly as the target is so `VARIANCE_TARGET` means the same on both sides. VICReg
applies its variance and covariance terms to the embeddings being *trained*; BYOL stops the gradient
on the target branch alone. Reading them off the target was a deviation from both.

Worth knowing for the test: "a gradient reaches the trunk" passes either way, because one arrives
from the prediction loss regardless. The guard runs the same batch and mask twice, differing only in
`variance_coeff`, and asserts the gradients differ — a constant's derivative is zero however large
the coefficient in front of it.

### S2-10 · The `lstm` encoder is invariant to the order of the grid it exists to preserve **[verified, fixed]**

`TokenEmbedConfig` — the tokenizer that is the entire difference between this project's LSTM and
RLlib's stock `use_lstm=True` — was `tokenize → Linear → LayerNorm → mean`. A mean of per-token
linear projections is a linear function of the token *sum*, hence permutation-invariant on both
axes.

Measured on the real observation space: permuting the book levels moved the latent by **1.8e-07**
and reversing the history by **1.2e-07**, float32 noise either way. Its 44 book tokens collapsed to
their per-field mean before anything nonlinear. Since the `encoder` group exists to ask which
architecture reads this market better, an lstm-vs-transformer comparison was measuring something
else.

**Fixed**, and the second half is the part that is easy to miss. Positional embeddings alone do not
help: `mean(W·xᵢ + pᵢ)` is `W·mean(xᵢ) + mean(pᵢ)`, so under a linear projection and a mean the
position is an input-independent constant — verified, the permutation delta stayed at 0.000000 with
the embeddings in place. A token-wise nonlinearity between the two is what makes position bear on
the result. With both, the deltas are 0.070 (levels) and 0.078 (time) under the shipped
`pool="mean"`.

The guard is in the **every-encoder contract**, not in the LSTM's own tests: an architecture that
cannot see where a level sits, or which snapshot came first, is not answering the question the group
exists to ask.

### S2-11 · `VWAP` goes negative on a partial close, and the observation then reports "flat" **[verified, fixed]**

`Account._size_decrease` rolls realised P&L into the remaining lot's basis. The roll is load-bearing
and must stay — on the short side `position_val` is `2·raw_val − mkt_val`, so removing it moves NAV
— but it leaves `VWAP` free to go negative: long 2 @ 100, sell 1 @ 250 gives **−50**.

`set_private_state` computed `vwap_vs_mid` under a `vwap > 0` guard and fell through to `0.0`, which
is the encoding for **flat**. An agent holding an open position was told it held none, on a measured
**5.0%** of open-position agent-steps. `info["VWAP"]` exported the same non-price into the episode
Parquet.

**Fixed.** `Account.entry_vwap` is the price actually paid for the lots still held, maintained by
the three methods that open or reset a position and untouched by `_size_decrease`, rolling from its
own previous value so an earlier partial close cannot leak into it. The observation and
`info["VWAP"]` read it; the ledger's rolled basis stays available as `carrying_vwap`. Re-measured:
0.0% of open positions report a non-positive basis, and the worked case reports `vwap_vs_mid` 0.6.

### S2-12 · `gymnasium.make(...)` raises **[verified, fixed]**

`setup.py`'s own docstring documents it. Run from a clean directory:

```
TypeError: action space does not inherit from `gymnasium.spaces.Space`,
actual type: <class 'NoneType'>
```

Only the plural `observation_spaces` / `action_spaces` were set — the pair RLlib's new API stack
reads — while `PassiveEnvChecker` reads the singular ones inherited from `MultiAgentEnv`. Nothing in
the test suite or the CI packaging job exercised `make`; both construct the class directly, so it
stayed broken while every job was green.

**Fixed.** The singular spaces are set to a single agent's, which is exactly what RLlib defines them
as (`@OldAPIStack`). `metadata` also moves from the pre-gymnasium `render.modes` to `render_modes`,
and the registration passes `disable_env_checker=True` — `PassiveEnvChecker` is a *single-agent*
checker and this env returns a dict keyed by agent id, which is a category error rather than a
finding. That flag is set only after fixing the spaces; doing it first would have hidden the
`TypeError` rather than fixed it. The CI packaging job now calls `make`.


---

## S3 — Moderate

### S3-1 · Half the `size_mean` action range is a no-op **[verified]**

`_set_size` applies `abs()` to the Gaussian sample, so `mean=+0.5` and `mean=−0.5` produce
identical sizes under the same seed. `size_mean` is declared on `Box(-1, 1)`; the optimum is
bimodal at `±m`, which a unimodal Gaussian head resolves by drifting toward 0 — i.e. minimum
size. The gradient kink sits exactly where the policy initializes.
**Fix:** declare `Box(0, 1)`.

### S3-2 · The `size_sigma` head is inert **[verified]**

`sigma ∈ [0,1]` is used as an *absolute* standard deviation while means are 49.5·|m| or 499.5·|m|.
Across its full range the size varies by ±1 contract on a base of 250. The policy pays entropy
cost for a control that does nothing.
**Fix:** scale it, or delete it.

### S3-3 · Size is sampled by the environment, outside the policy's log-prob

The policy emits distribution parameters and the env draws the sample, so the realised size is
not part of the action whose log-probability PPO uses in the importance ratio — and the agent
never observes the realisation. Irreducible advantage variance.
**Fix:** emit size directly as a `Box` action.

### S3-4 · The order book's `tick_size` is inert **[partly fixed]**

`tick_size` used to exist as two independent values: a hardcoded `min_tick = 1` in
`Action_Helper` that actually drove prices, and an `OrderBook` argument that was stored and never
read. Setting the config key therefore changed nothing anywhere.

**Fixed:** `Action_Helper.min_tick` now comes from the `tick_size` config key, so the key controls
the price grid agents quote on. Both defaults were 1, so behaviour at default config is unchanged.

**Also fixed:** `reset()` no longer rebuilds the book as `OrderBook(1, ...)`; it uses
`self.tick_size`, the same tick `Exchg_Helper` built the first book with. The change is inert
(the book never reads the value) but there is no reason to keep a second number in the env.

**Deliberately not fixed — the action layer should be the single definition, and `OrderBook`'s
copy should be deleted.** `OrderBook` still accepts a `tick_size`, stores it, and never reads it.
That argument makes it look as though the matching engine enforces a grid, which it does not —
there is no rounding or tick validation anywhere in the matching path.

The reason to delete rather than enforce: there is exactly **one** price producer in the system.
Every price reaching `process_order` comes from `_set_price` via `place_order`, and `_set_price`
builds prices as `anchor ± k × min_tick`, so output is on the grid by construction. A snapping or
validation step in the book would re-derive a guarantee the producer already provides. Deleting
the parameter is also nearly free: 9 of the 11 `OrderBook(...)` call sites already use the no-arg
form.

**This is deferred because the `envs/orderbook/` package is off-limits to changes.** It requires
editing `orderbook.py` plus the two call sites in `exchg_helper.py` and
`continuousDoubleAuction_env.py`. Until then `tick_size` is half-live: it governs the action
layer, not the book.

Enforcement in `OrderBook.process_order` would be the right call instead of deletion only if a
second price source appears that the action layer does not control — scripted or human agents,
replayed real order flow, an external feed.

**Float-grid caveat, for whoever picks this up.** `_set_price` performs no quantization, so a tick
that is not binary-exact can in principle produce a price whose `Decimal(str(price))` key sits off
the grid, splitting one book level into two price-map entries. This is rarer than it sounds: over
all anchors 10–100, ticks {0.01, 0.05, 0.1, 0.2, 0.25, 0.3} and 10 levels either side, exactly one
combination drifts (`10 − 9 × 0.3 → 7.300000000000001`). Worth a quantize step if non-integer
ticks are ever used in earnest, but it is not the reason to make the change.

Related, and still open as a *default*: the price anchor is drawn from `randint(10, 100)`, so with
a fixed tick the *relative* tick varies **10×** across episodes — a large uncontrolled
non-stationarity, only partly mitigated by exposing `log_mid`. What has changed is that this is
now a choice rather than a limitation: `initial_price_min` / `initial_price_max` are `TrainConfig`
fields and are forwarded by `env_config`, so a run can narrow the range. The checked-in config
still ships the wide one.

### S3-5 · Seeding is entirely non-functional **[verified, fixed]**

`reset(seed=...)` forwarded to `MultiAgentEnv.reset`, which seeds `self._np_random` — which
nothing read. All three of the env's random draws went to the global `np.random` instead: the
initial price anchor in `reset`, order sizes in `Action_Helper._set_size`, and the queueing order
in `rand_exec_seq`, whose one caller passes `seed=None` and whose
`sklearn.utils.shuffle(..., random_state=None)` falls through to sklearn's own global
`np.random.mtrand._rand`.

**No episode was reproducible**, which for a research environment whose entire output is
simulated data is disqualifying — none of the generated-LOB figures could be regenerated.

One correction to the original entry, because it changes how urgent this is. **Training runs
were reproducible** — by accident rather than by design. RLlib's `EnvRunner.__init__` calls
`update_global_seed_if_necessary`, which seeds global `random` and `np.random` from
`config.seed + worker_index`, and that covered all three sources. Measured: with global NumPy
seeded, two runs of the same env and actions were identical; with only `reset(seed=123)`, they
diverged. Three caveats made it worth fixing anyway:

* `run.seed` is `null` in the checked-in `train_config.json`, so nothing was seeded by default;
* the seeding happens once per worker at construction, so episode *N* could not be reproduced
  without replaying 1..*N*−1;
* `restart_failed_env_runners` is on by default, and a restarted runner re-seeds from the same
  value — rewinding its stream mid-run, so a run that loses a worker was not reproducible even
  in principle.

**Fixed:** all three sources now read `self.np_random`, gymnasium's per-env `Generator`, which
`super().reset(seed=...)` seeds. `seed=None` deliberately does not re-seed, per the Gymnasium
contract, so consecutive episodes still differ. `rand_exec_seq` honours its `seed` parameter —
accepted since it was written and never used — and shuffles with `Generator.permutation`, which
removed the `scikit-learn` dependency along with it (see S3-6). `test_seeding.py` pins this;
its load-bearing case seeds the *global* stream to two different values and asserts the seeded
episode is unchanged, which fails against the old code in the direction that hid the bug.

### S3-6 · `install_requires` does not match the imports **[verified, fixed]**

`envs/` imports `ray`, `sklearn.utils`, and `six`, none of which were in `install_requires`.
`pip install gym_continuousDoubleAuction` without extras fails on first import. CI never catches
it because it always installs the full `requirements.txt`.

One claim in the original entry was wrong and worth correcting, because acting on it as written
would have left the real dependency in place: **`import ray` in the env is not entirely unused.**
There were *two* ray imports in `continuousDoubleAuction_env.py` — a genuinely dead bare
`import ray`, and `from ray.rllib.env.multi_agent_env import MultiAgentEnv`, which is the base
class. A clean-venv install failed on the second, not the first.

`six` is a Python-2 shim replaceable by `io.StringIO`, but it is imported from
`envs/orderbook/`, which is off-limits to changes (see S3-4) — so it is declared rather than
removed.

`sklearn` is gone entirely. It pulled ~30 MB into every EnvRunner to shuffle ≤8 dicts, and was
the same call that made runs irreproducible; `rand_exec_seq` now uses the env's own
`Generator.permutation`, so fixing S3-5 removed the dependency rather than merely declaring it.

**Fixed:** the dead `import ray` is gone; `ray[rllib]` and `six` are in `install_requires`, which
now matches what the package actually imports, and `scikit-learn` is in neither
`install_requires` nor `requirements.txt` because nothing imports it. The `rllib` extra keeps its
name and carries the rest of the *training* stack (`torch`, `tensorboardX`), so
`pip install -e ".[rllib]"` is unchanged. A second, independent packaging defect was found while
fixing this one — see S3-18.

### S3-18 · The config tree was not in the built distribution **[verified, fixed]**

`setup.py` declared neither `package_data` nor `include_package_data`, and `config/` sits at the
repo root rather than inside the package — so a wheel built from this tree carried **zero** JSON
config files. `config_loader.config_dir()` searches `<pkg>/../config` and `<pkg>/config`; in
`site-packages` neither exists.

The failure lands at *import*, not at first use, because the config reads are default arguments
evaluated at class-definition time in `Exchg_Helper`, `Reward_Helper`, `Action_Helper`,
`State_Helper`, `Trader` and `Account`. Every non-editable install was therefore unusable, which
is why the "Resolved since" entry claiming `setup.py` was fixed for non-editable installs has
been corrected below — it fixed `find_packages()` and left this.

**Fixed:** a `build_py` subclass stages `config/*.json` into `gym_continuousDoubleAuction/config/`
at build time and `package_data` ships it — which is exactly the second location `config_dir()`
already searched and never found. Nothing moves, no documented path changes, and the staged copy
is git-ignored and never preferred in-tree (the repo root is checked first). `MANIFEST.in` carries
the root tree into an sdist so the staging has something to read there too.

### S3-19 · Every episode ran one step longer than `max_step` **[verified, fixed]**

`Done_Helper.set_all_done` compared `self.t_step > self.max_step - 1`, but `step()` increments
`t_step` *after* `set_step_outputs` has computed the flags. The condition first held at
`t_step == max_step`, i.e. on the `max_step + 1`-th step, so `max_step=10` produced 11 calls to
`step()`.

The consequence is quiet rather than dramatic. `TrainConfig.train_batch_size` is defined as
`max_step * num_episodes_per_iter`, so at the checked-in defaults the env delivered 16,388 steps
against a declared batch of 16,384 — and the `sample_timeout_s` sizing note in
`train_config.json` is derived from the same understated figure. Every episode length quoted in
the documentation was off by one for the same reason.

Nothing caught it because the existing loops all stop on `truncateds["__all__"]` without counting
the steps taken to get there.

**Fixed:** the test now reads `self.t_step + 1 >= self.max_step`, written in terms of *steps
taken* rather than as a comparison against `max_step - 1`, which is what made it easy to get
wrong. `test_env_lifecycle.py::TestEpisodeLength` pins the count at several horizons and asserts
that truncation is reported *on* the final step rather than after it.

### S3-20 · The escrow-delta path for order modification was dead **[verified, fixed]**

`Cash_Processor.modify_cash_transfer` computed `diff = order_val - qoute_val` and moved `diff`
between `cash` and `cash_on_hold` — a modify treated as a pure escrow adjustment. Nothing called
it, verified by grep across the package.

It was deleted rather than wired up, because **it is only correct where the live path already
is.** A modify is handled as cancel-and-reprocess: `cancel_cash_transfer` returns the whole old
order value to cash, `OrderBook.modify_order` re-runs the quote through `process_limit_order`,
and whatever is left resting is re-escrowed by `order_in_book_passive_party` — net cash movement
`order_val - residual_val`. When the modify does not match, `residual_val == qoute_val` and the
two are the same expression, which is why NAV conservation never told them apart:

| Modify (bid 10@100) | Escrow-delta would do | Live path does |
|---|---|---|
| → 6@100, no match | cash **+400**, hold −400 | cash **+400**, hold −400 |
| → 14@100, no match | cash **−400**, hold +400 | cash **−400**, hold +400 |
| → 10@101, hits ask@101 | cash −10, hold **+10** | cash −10, hold **−394** |
| → 10@103, hits ask@101 | cash **−30**, hold **+30** | cash **−22**, hold **−382** |

Row 3 shows the escrow leg wrong by the traded value; the cash leg coincides there only because
the fill happened *at* the quoted price, so `residual_val + trade_val == qoute_val` exactly. Row
4 breaks that identity — the fill is 2 ticks better than quoted — and both legs are wrong.

The function has no term for a fill, so it holds cash against quantity no longer in the book.
Re-processing is not an implementation detail of modify; it is what lets a modify cross the
spread, which this function assumes never happens.

**Fixed:** deleted, with the reasoning left at the call site. The six scenarios in
`test_modify_order.py` already constrain the behaviour — three of them cross the book and assert
exact `cash` / `cash_on_hold` / `net_position`, which an escrow-shuffle cannot produce — and a
seventh test now asserts the helper stays gone.

### S3-7 · `sys.exit()` used for error handling in the matching engine

Six live occurrences in `orderbook.py`. `SystemExit` derives from `BaseException`, so inside a
Ray actor it kills the worker rather than surfacing a traceback. Currently unreachable, but one
action-space change away.
**Fix:** `raise ValueError(...)`.

### S3-8 · `build_algo` returns a detached callback on the restore path **[fixed]**

League state *does* survive checkpointing (cloudpickle preserves the callback closure — restored
modules, history and mapping all verified correct). But `build_algo` returned the **fresh, empty**
callback from `build_config` rather than the algorithm's live one. `train()` ignored it, so
training was unaffected; any caller that used it (notebook, tests) drove a detached object.

**Fixed:** the restore path returns `algo_callback(algo)`, the instance RLlib unpickled — the one
holding the restored champion pool — and `None`, loudly, if the restored algorithm has no
`SelfPlayCallback` at all. Four adjacent checkpoint defects went with it: the single overwritten
checkpoint directory, config edits silently discarded on restore, the driver's iteration counter
restarting at zero, and champion metadata existing only inside the cloudpickled callback. See
[18 §5.2–5.3](18_configuration.md#52-the-run-group), [16 §16.8](16_verification_log.md), and
`test_checkpointing.py`.
→ [14 §5.9.1](14_perspective_ai_engineer.md#591-checkpointrestore-what-actually-happens)

### S3-9 · No risk-adjusted performance metrics

NAV, trade count and reward are recorded. Absent: Sharpe/Sortino, max drawdown *as a reported
metric*, hit rate, turnover, inventory statistics, maker/taker ratio, realised-vs-unrealised P&L
split, adverse-selection mark-outs. The counters for several of these already exist and are
discarded after the reward consumes them. `info["NAV"]` is a **string**, round-tripped through
`float()` by every consumer, discarding the exactness `Decimal` was chosen for.

**Partly addressed:** the episode-end NAV conservation check now parses `info["NAV"]` back with
`Decimal` and compares against a `Decimal` total, so that one consumer is exact by construction;
`float()` remains only at the metrics boundary. [16 §16.10](16_verification_log.md) shows the
round trip was harmless at the default `init_cash = 1e6`, but that **above `init_cash ≈ 1e10` the
float check could not resolve its own `1e-6` tolerance** — a genuine breach read as exactly `0.0`
and would have passed a corrupt ledger silently. It also corrects the claim that `nav_tolerance`
was absorbing float noise. The missing risk-adjusted metrics above, and the remaining `float()`
consumers of `info["NAV"]`, are untouched.

### S3-10 · A trader can hold only one resting order per price level **[verified]**

A second limit at the same price *replaces* the first (level volume 7, not 12) —
`_place_limit_order` upserts via `_get_order_ID`. Layering, iceberg and multi-clip quoting are
not expressible. Different price levels are unaffected.

### S3-11 · No entropy bonus, and champion promotion cannot detect passivity **[verified]**

`entropy_coeff = 0.0` (RLlib default). If the learners collapse to "always pass" (S1-3), they
still clear the promotion threshold — 0 beats a negative league mean — so the league fills with
champion snapshots of the do-nothing policy. Related: with `std_dev_multiplier=0.1` a champion is
promoted on the very first eligible iteration **[verified]**, so at the default 16-iteration run
the pool saturates with barely-trained snapshots.
**Fix:** positive decaying `entropy_coeff`; raise `std_dev_multiplier` to 1.5–2.5; refuse to
promote a champion whose trade count is ~0.

### S3-12 · The league ranks a signal that is not comparable across roles

The four shaping terms are not zero-sum, so returns depend on the role a module played that
episode. The promotion threshold is a pooled `mean + k·std` over *all* modules including the
frozen random baselines. A policy can clear it by trading *less*, not *better*.

### S3-13 · γ=0.99 against 4,096-step episodes **[verified]**

Effective horizon ~100 steps = 2.5% of an episode. Strategies with payoff horizons longer than
that (inventory accumulation, sustained market making) are invisible to the return. Only 4
episodes per training iteration also means very few samples of the episode-level randomness
(price anchor, opponent draw). `lambda_=1.0` (RLlib's PPO default, not the usual 0.95) makes
advantages pure Monte-Carlo.

### S3-14 · Zero means three different things in the observation

`0.0` is the sentinel for "level absent", the exact value of a price *at* the midpoint, and — on
a one-sided book, where `M` falls back to that side's L1 price — the value of the best quote
itself. The book starts empty every episode and is frequently one-sided early on, and there is no
validity mask.
**Fix:** an explicit occupancy channel, or an out-of-range sentinel.

### S3-15 · Level index is a non-stationary coordinate

Slot *k* means "the *k*-th occupied price", not a fixed distance from mid, and the action space
selects by the same unstable index. A learned association such as "level 3 is a good place to
quote" has no fixed meaning across steps.
**Fix:** a fixed tick-offset grid shared by observation and action.

### S3-16 · One undrawn opponent kills champion promotion for the rest of the run **[verified, fixed]**

`on_train_result` filtered `None` from `module_episode_returns_mean` but not `NaN`, which is what
RLlib reports for a module the mapping fn did not draw that iteration. One NaN makes the league
mean, std and threshold NaN, and `best_return > threshold` is False against NaN, so no champion
is ever promoted again. Self-reinforcing: each champion added to the pool makes an undrawn
baseline likelier.

Observed in both GPU runs of 2026-08-15 — Colab T4 froze at 4 champions from iteration 12 of 16,
the RTX 4060 docker run from iteration 10 — with `mean=nan std=nan threshold=nan` logged every
iteration after that and no other symptom.

**Fixed.** NaN is filtered alongside `None`, and the excluded modules are named at INFO. Pinned by
`test_champion_trigger.py`.

### S3-17 · Retention deleted each fresh checkpoint in a dirty directory **[verified, fixed]**

`_prune_checkpoints` ranked by iteration number. A run starting from scratch in a directory that
still held an earlier run's `iter_00012/14/16` therefore saw its own `iter_00002` as the oldest of
four and deleted it immediately after the rename that made it real — and the same at 4, 6, 8, 10.
Both GPU runs of 2026-08-15 left the whole first half of the run unrecoverable while preserving
the previous run's saves.

The worse half is restore selection: `list_checkpoints` reports the highest iteration number as
newest, so for the first eleven iterations a `--restore` would have resumed the *earlier* run —
in that instance, the run that trained on nothing ([17 §16](17_changelog.md)).

**Fixed.** Retention ranks by mtime, with the iteration number as tiebreaker, so the save just
written is never the one pruned. A fresh run that finds checkpoints it did not write now warns and
names them, newest first; nothing is deleted, because the directory belongs to the operator.
Pinned by `TestRetention` and `TestForeignCheckpoints` in `test_checkpointing.py`.

### S3-21 · `visualize/` is in no built distribution **[verified, fixed]**

It had no `__init__.py`, so `setuptools.find_packages()` omitted it and a built wheel carried none of
it — while [01](01_overview.md) documents `python -m gym_continuousDoubleAuction.visualize.run_all`
as an entry point. It worked in-tree and under an editable install, which is why nothing noticed,
and the CI packaging job builds a wheel but never imported it.

**Fixed.** Verified by building a wheel: it now carries 11 visualize modules, and a clean venv
outside the checkout imports the package. The packaging job fails if `visualize/run_all.py` is
absent from the wheel. It imports the *package* rather than `run_all`, which needs matplotlib and —
through `visualize_modules → policy_handler` — the whole training stack including torch; that
coupling is now stated in `visualize/__init__`, since `pip install gym_continuousDoubleAuction`
installs these modules but cannot run them.

### S3-22 · The encoder fingerprint does not identify the encoder **[verified, fixed]**

`encoder_fingerprint` hashed the spec *as written* rather than merged against the encoder's
registered defaults. Wrong in both directions, and the two failures are opposites:

- **False mismatch.** A config stating a value equal to its registered default and one omitting it
  describe the identical architecture and fingerprinted differently — a hard error at
  `verify_fingerprint` and `_check_restored_config` over nothing at all.
- **False match**, which is worse. A checkpoint whose spec omitted a key kept its fingerprint when
  the value in `*_DEFAULTS` was later edited, so the architecture changed and the guard said
  nothing — the silent shape mismatch the fingerprint exists to prevent.

The pretrainer had it from the other end. `pretrain(encoder_spec=None)` is documented as "reads the
config file's" and did not: `None` reached `build_module`, which turns a falsy spec into `{}` and
resolves to the *registry* defaults, and `save` then wrote `encoder_fingerprint(encoder_type, None)`.
So a pretrained encoder was built from whatever the code shipped rather than from what the run would
be configured with, and its weights could not load into a training run built from that config block.

**Fixed.** The fingerprint hashes `encoder_settings`, the canonical merged form the encoder is
actually built from, and no longer raises on a spec that does not validate for the type it is asked
about — it reports an identity, and a caller comparing two of them wants "these differ", not an
exception. `pretrain.resolve_spec` is one definition used by `pretrain`, `save` and
`verify_fingerprint`. Verified end to end.

**Also fixed:** `pretrain` refuses `world_model: true` rather than accepting it. It optimises only
the trunk and the predictor, and its loop supplies no `NEXT_OBS`/`ACTIONS`, so the
action-conditioned term never runs — its parameters would be saved randomly initialised and pulled
into a training run by a `strict` load, silently.


---

## S4 — Minor

| ID | Finding |
|---|---|
| S4-1 | **Partly fixed.** The `g_store` trio (`store_handler`, `log_handler`, `plot_handler`, ~270 LOC) has been deleted; `helper.py`'s order-imbalance utilities are still unused (and would be valuable as observation features — S2-7) |
| S4-2 | `envs/agent/random_agent.py` returns the **old 5-tuple** action format; superseded by `RandomRLModule` but still in `Trader`'s MRO **[verified]** |
| S4-3 | Dead methods: `State_Helper.state_diff`, `Action_Helper._set_side/_set_type/_higher/_lower`, `OrderBook.__str__0`, `Order.__str__0`, `OrderList.to_str`. The unread `max_price` parameter of `_set_price` has since been removed |
| S4-4 | ~200 LOC of commented-out code: the old `step` and space getters in `continuousDoubleAuction_env.py`, the old `modify_order` and `get_volume_at_price` in `orderbook.py`, the old `Tuple` `act_space` in `action_helper.py` |
| S4-5 | `test_accounting.py::test_insufficient_funds` is an empty `pass` with a 15-line comment debating the intended behaviour — a TODO shipped as a test |
| S4-6 | No linter, formatter, pre-commit or coverage tooling; type hints only in `train/` and essentially absent from `envs/` |
| S4-7 | `is_render` defaults to **`True`** on the env, so a direct instantiation prints a full book/tape/account dump per step. `_render` also has **side effects** — it nulls `model_actions`/`LOB_actions`/`shuffled_actions` and clears `seq_trades`, so toggling it changes state evolution |
| S4-8 | The Docker image duplicates the dependency list instead of `COPY`ing `requirements.txt` |
| S4-9 | **Fixed.** The per-step record is Parquet with a declared schema, written off the sampling thread and bounded by `episode_sample_every` / `episode_max_bytes`; the two committed `.pkl` files are deleted. Nothing in the repository writes a pickle |
| S4-10 | Mixin-based env architecture: helpers read attributes they do not own, guarded by defensive `getattr` defaults; not independently testable |
| S4-11 | `_process_counter_party` linear-scans all agents per fill; `set_agg_LOB` is called twice per step (the pre-action call is display-only) |
| S4-12 | No `evaluate.py` / serving path — no way to *use* a trained checkpoint |
| S4-13 | No property-based tests, despite the order book having clearly stated invariants (tree volume == Σ level volumes, no crossed book, Σ NAV == Σ initial cash) |
| S4-14 | **Partly fixed.** Refused orders increment `num_rejected_step`, which reaches `infos` and the `order_rejection_fraction` metric; `is_pass_action` separates a deliberate pass. Still open: `modify` / `cancel` with nothing to target has no counter, and no dead action is penalised or visible to the agent |
| S4-15 | `Box(-inf, inf)` observation bounds, though every quantity is boundable; disables RLlib observation filters and space-based sanity checks |
| S4-16 | **Fixed.** `test_shared_history_multi_agent_uniformity` encoded S1-2 as a requirement. It is replaced by a pair that splits the claim: the book prefix must still be shared between agents, the private tail must not be |
| S4-17 | The sign convention on ask blocks is redundant (side is already encoded by block position) and prevents natural weight sharing between the two sides |
| S4-18 | Duplicate `CODEOWNER` and `CODEOWNERS` files at the repo root |
| S4-19 | No env/observation version recorded in checkpoints, so an observation-layout change invalidates old checkpoints silently |

---

## Resolved since the older documentation set

Recorded so nobody re-files them. Each was a real defect at the time.

| Was | Now |
|---|---|
| `custom_model: "model_disc"` never registered | `ModelCatalog` is not read on the new stack; the indirection was removed. Trainable modules use the default PPO module via `DefaultModelConfig` |
| Training code straddled two RLlib API stacks | Entirely new-API-stack. `PolicySpec` wiring replaced by `MultiRLModuleSpec`; the broken `CustomRLModule` (which read `config.action_space.n` against a `Dict` space) and dead old-stack modules deleted |
| Champion trigger read `policy_reward_mean` / `custom_metrics` | Reads `module_episode_returns_mean`, already keyed by real `ModuleID` |
| The printed policy map used different logic than the real mapping | `on_episode_start` calls `env_runner.config.policy_mapping_fn` — the authoritative one |
| Champion snapshots never reached the EnvRunners | Force-pushed with a `WEIGHTS_SEQ_NO`-free `set_state`, with the reasoning in a comment |
| Matchmaking seeded from salted `hash()` | Seeds from `zlib.crc32` — reproducible across processes |
| Evicted champions leaked memory | `Algorithm.remove_module` is called |
| Per-episode pickles were unconditional | Replaced by a bounded Parquet record on a background thread; `episode_data_dir=None` / `--no-episode-data` now disables the accumulation as well as the write (S4-9) |
| `episode_data/` was untracked noise | In `.gitignore`, both paths, with an explanatory comment |
| **No CI** — dead `.travis.yml` | GitHub Actions on Python 3.12: a `test` job (unit → random smoke run → RLlib integration) and a `packaging` job that builds the wheel and uses it from a clean venv outside the checkout |
| `setup.py` broken for non-editable installs | ~~`find_packages()`, real `install_requires` and extras, `__init__.py` files added~~ **Premature.** That pass fixed package discovery and left two defects that still made every non-editable install fail: `install_requires` did not name `ray[rllib]`, `scikit-learn` or `six` (S3-6), and no config JSON was in the distribution at all (S3-18). Both are fixed now, and a wheel built from this tree has been installed into a clean environment and used to construct an env |
| `observation_space`/`action_space` were plain dicts | `observation_spaces`/`action_spaces` (plural, new stack) plus per-agent getters; agent ordering stable across processes |
| Trainable network was an 8-unit bottleneck | `fcnet_hiddens=[256,256]`, `tanh`, `vf_share_layers=False` |
| `test_modify_order_price_change` was `@unittest.expectedFailure` | A normal passing test; the no-crossed-book invariant holds on every modification path |
| `CDA_env_rand.py` used positional constructor args | Takes a config dict, keys actions by agent ID, samples from the env's own action space, and runs in CI |

---

## What is genuinely good

It would misrepresent the repository to list only defects. The following are above the standard
for research code:

- **The matching engine is correct**, including the subtle parts: price/time priority, FIFO
  queues per level, priority loss on size increase and retention on decrease, book-walking for
  aggressive limits, and correct partial fills.
- **The ledger is exact and conserved.** `Decimal` throughout, and total NAV equals total initial
  cash to the cent after 300 random steps **[verified]**.
- **Buying-power logic is subtle** — only the risk-*increasing* portion of an order is
  cash-checked, so closing and covering always succeed, and market orders are priced off the
  contra side with a tape fallback. It said "and right" here until S1-5: the rule was right per
  order and wrong in aggregate, because nothing netted an order against the trader's *other*
  resting orders, so N individually-closing orders were each approved against the same lots. Left
  in the list, amended, because the design is sound and the defect was one missing term in it.
- **Position flips are atomic** (`_covered_side_chg`) — the case most toy exchanges get wrong,
  with four dedicated tests.
- **The RLlib new-API-stack migration was done properly.** Module classes declared through
  `MultiRLModuleSpec` (the only thing the new stack reads), `RandomRLModule` as a true uniform
  sampler rather than a frozen random network, and per-module metrics keyed by real `ModuleID`.
- **The distributed self-play code is the strongest in the repo.** Four load-bearing ordering
  constraints in champion creation, each explained in comments at the RLlib-internals level and
  each covered by a regression test — including the `WEIGHTS_SEQ_NO` force-push and the
  `crc32`-vs-`hash()` determinism fix.
- **Integration tests guard their own premise.** `test_sampling_actually_happens_remotely` and
  `test_learner_group_is_actually_remote` prevent the remote suites from degrading into vacuous
  duplicates — a discipline most codebases lack.
- **Observation normalisation is well reasoned.** Midpoint-relative prices make the
  representation invariant to the random price anchor, and the two scalars that restore what the
  transform discards (`log_mid`, `log1p_spread_ticks`) are documented with their exact rationale,
  including why `0.0` is a safe sentinel.
- **Deterministic ghost-level pricing** replaced a random-price fallback that turned action codes
  into lottery tickets in thin books — correctly motivated and well tested.
- **Dependency pins are explained, not just asserted** (`gymnasium` ↔ Ray coupling; CPU-vs-CUDA
  torch wheel selection; Ray's `/dev/shm` requirement).
- **863 unit tests pass** (plus 112 integration), covering every position-flip path, cash-check edge case, modify-order
  scenario and observation invariant, and — since the encoder group — the contract every selectable
  network must meet.

---

## Suggested sequencing

Roughly two to three weeks of work, ordered so each step unblocks the next.

**Phase 1 — make learning possible (≈2 days)**
1. ~~Scale all reward terms to fractional-NAV units (fixes S1-1, S2-1, S2-3 together)~~ — **done**,
   by `acc.init_nav` rather than a configured `init_cash`, so the scale cannot drift from the
   ledger it normalises
2. Assert the critic learns in CI — **done**: `vf_explained_var >= 1e-3` is a live assertion in
   `integration/test_progress_and_vf.py`. **`grad_clip` is still unset**, which is the open half
   of this item
3. ~~Make the drawdown penalty an increment~~ — **done**, as a *signed* change. The clipped
   `max(0, Δ)` form recommended in [12 §3.4](12_perspective_rl_researcher.md) is an asymmetric
   loss multiplier in disguise and was deliberately not shipped; see [07 §2.1](07_reward_function.md)
4. Normalise observation feature scales (S2-2)

**Phase 2 — make the problem well-posed (≈3–4 days)**
5. ~~Add the private-state observation block (S1-2); delete the uniformity test~~ — **done**,
   9 floats per agent. Own resting orders are the remaining gap
6. Terminate and flatten bankrupt agents (S2-4)
7. `size_mean → Box(0,1)`; scale or drop `size_sigma` (S3-1, S3-2)
8. Positive decaying `entropy_coeff`; raise `std_dev_multiplier`; refuse zero-trade champions (S3-11)
9. ~~One `np.random.Generator` threaded through the env (S3-5)~~ — **done**. All three draws read
   `self.np_random`; `test_seeding.py` pins it, and `scikit-learn` left with the fix

**Phase 3 — fix the observation pipeline (≈3 days)**
10. Normalize the whole stack by the current `M_t`; expose `M_t / M_{t−1} − 1` (S2-6)
11. Finish the tape loop into trade-flow features; wire in `helper.py`'s order imbalance (S2-7)
12. Occupancy mask (S3-14); consider the fixed tick-offset grid (S3-15)

**Phase 4 — market realism (≈3 days)**
13. Maker/taker fees in bps inside settlement (S2-3)
14. Self-match prevention; mark to mid (S2-5)
15. ~~Per-episode desk metrics through `metrics_logger` (S3-9)~~ — **partly done**: NAV spread,
    drawdown, inventory, trade count and maker ratio are metrics ([11 §1.2](11_logging_and_observability.md)).
    Sharpe and max-drawdown-over-the-episode still need the NAV trajectory, which the per-step
    record now holds

**Phase 5 — engineering hygiene (≈3 days)**
16. ~~`logging` replaces `print`; a conservation violation stops the run (S2-8)~~ — **done**. The
    stop moved to the driver once [21 §2.1](21_logging_review.md) found that raising in the episode
    hook stops nothing at `num_env_runners > 0`
17. ~~Fix `install_requires`; drop `sklearn` and the unused `import ray` (S3-6)~~ — **done**, with
    a `packaging` CI job so an installed copy is exercised rather than assumed. `six` is declared
    rather than dropped, because it is imported from the off-limits `envs/orderbook/`
18. `sys.exit` → `raise ValueError` (S3-7)
19. Delete dead code (S4-1..4) — the `g_store` trio (S4-1) and the `build_algo` restore path (S3-8) are done
20. Add `ruff` / `black` / `pre-commit` / `pytest-cov`
