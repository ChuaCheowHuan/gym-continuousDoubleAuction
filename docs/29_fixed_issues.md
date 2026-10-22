# 29. Fixed Issues

Every problem the documentation records as fixed, in one place. Each entry says what was wrong,
how it was found or measured, and what fixed it. The other documents describe the code as it is
and link here for the history of a defect, rather than carrying it inline.

- **Finding IDs are unchanged.** `S1-1` … `S4-28` and `R-n` are the IDs the register, the GitHub
  issues, the tests and the changelog use; an entry here is the same finding that
  [15_findings_and_recommendations.md](15_findings_and_recommendations.md) used to hold.
- **Open work is not here.** What is still open, including the parts of a fixed finding left
  undone, is in [15](15_findings_and_recommendations.md).
- **The history files stay where they are.** [17_changelog.md](17_changelog.md) records what
  changed and when; [16_verification_log.md](16_verification_log.md) holds the raw output of each
  probe. Neither is edited to match this document.

Severity is the label the finding was filed with: **S1** blocking, **S2** major, **S3** moderate,
**S4** minor ([15](15_findings_and_recommendations.md) has the legend). **[verified]** marks a
finding confirmed by executing the code.

---

## At a glance

| ID | Problem | Issue |
|---|---|---|
| [S1-1](#s1-1--ppos-critic-receives-zero-gradient-verified-fixed) | PPO's critic receives zero gradient | [#91](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/91) |
| [S1-2](#s1-2--observation-contains-no-private-state-verified-fixed) | Observation contains no private state | [#92](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/92) |
| [S1-3](#s1-3--doing-nothing-is-a-dominant-strategy-verified-fixed) | Doing nothing is a dominant strategy | [#93](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/93) |
| [S1-4](#s1-4--the-default-standalone-env-could-not-trade-verified-fixed) | The default standalone env could not trade | [#94](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/94) |
| [S1-5](#s1-5--the-cash-check-is-bypassable-position-is-not-bounded-by-capital-verified-fixed) | The cash check is bypassable; position is not bounded by capital | [#95](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/95) |
| [S2-1](#s2-1--drawdown-is-penalised-as-a-level-not-an-increment-verified-fixed) | Drawdown is penalised as a level, not an increment | [#96](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/96) |
| [S2-2](#s2-2--unnormalised-observation-scales-saturate-the-tanh-mlp-verified-fixed) | Unnormalised observation scales saturate the `tanh` MLP | [#97](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/97) |
| [S2-3](#s2-3--transaction-cost-proxies-are-10⁵-too-small-verified-fixed) | Transaction-cost proxies are ~10⁵× too small | [#98](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/98) |
| [S2-4](#s2-4--bankrupt-agents-are-never-terminated-verified-fixed) | Bankrupt agents are never terminated | [#99](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/99) |
| [S2-5](#s2-5--self-matching-enables-mark-manipulation-verified-fixed) | Self-matching enables mark manipulation | [#100](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/100) |
| [S2-6](#s2-6--every-frame-in-the-observation-stack-has-a-different-normalizer-verified-fixed) | Every frame in the observation stack has a different normalizer | [#101](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/101) |
| [S2-7](#s2-7--no-trade-flow-information--the-tape-loop-is-dead-code-verified-fixed) | No trade-flow information — the tape loop is dead code | [#102](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/102) |
| [S2-8](#s2-8--no-logging-framework-the-callback-prints-42-diagnostics-per-episode--fixed) | No logging framework; the callback prints 42 diagnostics per episode | [#103](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/103) |
| [S2-9](#s2-9--the-jepa-anti-collapse-hinge-contributes-zero-gradient-verified-fixed) | The JEPA anti-collapse hinge contributes zero gradient | [#104](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/104) |
| [S2-10](#s2-10--the-lstm-encoder-is-invariant-to-the-order-of-the-grid-it-exists-to-preserve-verified-fixed) | The `lstm` encoder is invariant to the order of the grid it exists to preserve | [#105](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/105) |
| [S2-11](#s2-11--vwap-goes-negative-on-a-partial-close-and-the-observation-then-reports-flat-verified-fixed) | `VWAP` goes negative on a partial close, and the observation then reports "flat" | [#106](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/106) |
| [S2-12](#s2-12--gymnasiummake-raises-verified-fixed) | `gymnasium.make(...)` raises | [#107](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/107) |
| [S2-13](#s2-13--a-cancel-was-cash-checked-like-a-new-order-so-an-over-committed-trader-could-not-cancel-verified-fixed) | A cancel was cash-checked like a new order, so an over-committed trader could not cancel | [#108](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/108) |
| [S2-14](#s2-14--a-market-order-is-cash-checked-at-the-touch-but-pays-every-level-it-sweeps-verified-fixed) | A market order is cash-checked at the touch but pays every level it sweeps | [#109](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/109) |
| [S2-15](#s2-15--closing-a-losing-position-realises-the-loss-into-cash-without-a-cash-check-verified-fixed) | Closing a losing position realises the loss into cash without a cash check | [#228](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/228) |
| [S3-1](#s3-1--half-the-size_mean-action-range-is-a-no-op-verified-fixed) | Half the `size_mean` action range is a no-op | [#110](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/110) |
| [S3-2](#s3-2--the-size_sigma-head-is-inert-verified-fixed) | The `size_sigma` head is inert | [#111](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/111) |
| [S3-3](#s3-3--size-is-sampled-by-the-environment-outside-the-policys-log-prob-verified-fixed) | Size is sampled by the environment, outside the policy's log-prob | [#112](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/112) |
| [S3-4](#s3-4--the-order-books-tick_size-is-inert-verified-fixed) | The order book's `tick_size` is inert | [#113](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/113) |
| [S3-5](#s3-5--seeding-is-entirely-non-functional-verified-fixed) | Seeding is entirely non-functional | [#114](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/114) |
| [S3-6](#s3-6--install_requires-does-not-match-the-imports-verified-fixed) | `install_requires` does not match the imports | [#115](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/115) |
| [S3-7](#s3-7--sysexit-used-for-error-handling-in-the-matching-engine-fixed) | `sys.exit()` used for error handling in the matching engine | [#119](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/119) |
| [S3-8](#s3-8--build_algo-returns-a-detached-callback-on-the-restore-path-fixed) | `build_algo` returns a detached callback on the restore path | [#120](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/120) |
| [S3-9](#s3-9--no-risk-adjusted-performance-metrics-fixed) | No risk-adjusted performance metrics | [#121](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/121) |
| [S3-10](#s3-10--a-trader-can-hold-only-one-resting-order-per-price-level-verified-fixed---as-an-option) | A trader can hold only one resting order per price level | [#122](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/122) |
| [S3-11](#s3-11--no-entropy-bonus-and-champion-promotion-cannot-detect-passivity-verified-fixed) | No entropy bonus, and champion promotion cannot detect passivity | [#123](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/123) |
| [S3-12](#s3-12--the-league-ranks-a-signal-that-is-not-comparable-across-roles-fixed---as-an-option) | The league ranks a signal that is not comparable across roles | [#124](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/124) |
| [S3-13](#s3-13--γ099-against-4096-step-episodes-verified-fixed) | γ=0.99 against 4,096-step episodes | [#125](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/125) |
| [S3-14](#s3-14--zero-means-three-different-things-in-the-observation-verified-fixed) | Zero means three different things in the observation | [#126](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/126) |
| [S3-15](#s3-15--level-index-is-a-non-stationary-coordinate-verified-fixed) | Level index is a non-stationary coordinate | [#127](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/127) |
| [S3-16](#s3-16--one-undrawn-opponent-kills-champion-promotion-for-the-rest-of-the-run-verified-fixed) | One undrawn opponent kills champion promotion for the rest of the run | [#128](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/128) |
| [S3-17](#s3-17--retention-deleted-each-fresh-checkpoint-in-a-dirty-directory-verified-fixed) | Retention deleted each fresh checkpoint in a dirty directory | [#129](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/129) |
| [S3-18](#s3-18--the-config-tree-was-not-in-the-built-distribution-verified-fixed) | The config tree was not in the built distribution | [#116](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/116) |
| [S3-19](#s3-19--every-episode-ran-one-step-longer-than-max_step-verified-fixed) | Every episode ran one step longer than `max_step` | [#117](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/117) |
| [S3-20](#s3-20--the-escrow-delta-path-for-order-modification-was-dead-verified-fixed) | The escrow-delta path for order modification was dead | [#118](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/118) |
| [S3-21](#s3-21--visualize-is-in-no-built-distribution-verified-fixed) | `visualize/` is in no built distribution | [#130](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/130) |
| [S3-22](#s3-22--the-encoder-fingerprint-does-not-identify-the-encoder-verified-fixed) | The encoder fingerprint does not identify the encoder | [#131](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/131) |
| [S3-23](#s3-23--nav-conservation-is-exact-only-to-decimal-context-rounding-verified-fixed) | NAV conservation is exact only to Decimal context rounding | [#132](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/132) |
| [S3-24](#s3-24--modify-and-cancel-cannot-be-aimed-so-they-are-mostly-dead-actions-verified-fixed) | `modify` and `cancel` cannot be aimed, so they are mostly dead actions | [#133](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/133) |
| [S3-25](#s3-25--within-a-step-the-shuffle-decided-who-traded-and-at-what-price-verified-fixed---as-an-option) | Within a step, the shuffle decided who traded and at what price | [#134](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/134) |
| [S3-26](#s3-26--a-modify-with-nothing-to-modify-cancelled-the-traders-other-quotes-verified-fixed) | A `modify` with nothing to modify cancelled the trader's other quotes | [#135](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/135) |
| [S3-27](#s3-27--closing-escrow-was-counted-in-time-order-not-fill-order-verified-fixed) | Closing escrow was counted in time order, not fill order | [#136](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/136) |
| [S3-28](#s3-28--at-a-non-integer-tick-the-observation-and-the-action-could-use-grids-one-tick-apart-verified-fixed) | At a non-integer tick the observation and the action could use grids one tick apart | [#137](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/137) |
| [S3-29](#s3-29--three-training-metrics-read-wrong-at-the-moments-they-matter-verified-fixed) | Three training metrics read wrong at the moments they matter | [#138](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/138) |
| [S3-30](#s3-30--trainevaluate-did-not-see-a-mid-episode-bankruptcy-verified-fixed) | `train.evaluate` did not see a mid-episode bankruptcy | [#139](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/139) |
| [S3-31](#s3-31--the-probes-contiguous-split-leaked-targets-across-its-seams-verified-fixed) | The probe's contiguous split leaked targets across its seams | [#140](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/140) |
| [S3-32](#s3-32--continual-backprop-a-silent-no-op-on-lstm-and-its-state-in-every-weight-sync-verified-fixed) | Continual Backprop: a silent no-op on `lstm`, and its state in every weight sync | [#141](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/141) |
| [S3-33](#s3-33--the-reward-charts-dropped-dead_action_penalty-verified-fixed) | The reward charts dropped `dead_action_penalty` | [#142](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/142) |

S4-1 … S4-28 are in [§ S4](#s4--minor), the 2026-10-07 review's R-items in
[§ R](#from-the-2026-10-07-review), problems fixed before the register existed in
[§ Older](#resolved-before-the-register), and fixed problems recorded outside the register in
[§ Other documents](#fixed-problems-recorded-in-other-documents).

---

## S1 — Blocking

### S1-1 · PPO's critic receives zero gradient **[verified, fixed]**

_Tracked in [#91](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/91)._

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
→ [12 §4](12_perspective_rl_researcher.md#4-the-critic),
[07 §2.1](07_reward_function.md)

### S1-2 · Observation contains no private state **[verified, fixed]**

_Tracked in [#92](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/92)._

Every agent received the byte-identical 168-float public book vector (`distinct obs vectors
across agents: 1`). Absent: `net_position`, `VWAP`, `nav`, `max_nav`, `cash`, own resting orders,
agent identity, time remaining.

The reward is literally `f(nav, prev_nav, max_nav, …)` — all unobserved. Two states with
identical books but opposite inventory require opposite optimal actions and were
indistinguishable. The drawdown term depends on `max_nav`, a path functional over the whole
episode, so this was not partial observability a recurrent net could recover. It also made the
`modify` and `cancel` categories (4 of 9) blind.

**Fixed.** The observation is now `[ n_hist × snapshot | private ]` - 193 floats when this was
first closed, 216 since the own-book block (S3-24 phase 1) completed it: the book prefix is still
shared and computed once, and a per-agent block is appended.
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

**Still open when this was fixed:** own resting orders and agent identity. Own resting orders have
been in the block since S3-24 (the own-book rows, [05](05_observation_space.md) §1.0.1), so
`modify` and `cancel` are no longer blind; agent identity is still absent and is listed as open in
[15](15_findings_and_recommendations.md).
→ [12 §2](12_perspective_rl_researcher.md#2-the-observation-and-the-agents-private-state),
[05 §1.0](05_observation_space.md)

### S1-3 · Doing nothing is a dominant strategy **[verified, fixed]**

_Tracked in [#93](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/93)._

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
→ [12 §3.3](12_perspective_rl_researcher.md#33-doing-nothing-is-not-dominant-and-cannot-be-beaten-on-average),
[07 §4.3](07_reward_function.md)

### S1-4 · The default standalone env could not trade **[verified, fixed]**

_Tracked in [#94](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/94)._

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

_Tracked in [#95](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/95)._

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

**The tail, measured and then closed (2026-09-18).** The escrow charges full notional for *any*
resting order, including one that only closes, and the cash check treated that escrow as spent. So
a trader long 10 with its exit ask resting could not open anything else, although the ask's fill
could only reduce its risk. Measured under random play ([16](16_verification_log.md) §16.18):

| `init_cash` | refusals | while closing-side escrow existed | would have passed had it counted |
|---|---|---|---|
| 20,000 | 3,712 | 1,602 (43%) | 793 (21%) |
| 100,000 | 607 | 508 (84%) | 409 (67%) |

Fixed in the approval predicate rather than the ledger: `Trader._closing_escrow` sums the escrow
held against this trader's resting orders on the side that reduces its position, capped at the
quantity that actually closes (`|net_position|`, oldest order first), and `_order_approved` counts
it as spendable beside `cash` and the replaced order's release. The ledger is untouched, so every
partial-fill path in `Cash_Processor` still sees escrow equal to full notional. The one visible
consequence is that `cash` may sit below zero by at most that closing escrow while both orders
rest; `cash + cash_on_hold` never does, and NAV is unaffected — `test_orderbook_properties.py`
asserts the first under random play, and `test_cash_check.py::TestClosingEscrowIsSpendable`
pins the cases. The same measurement after the fix: 3,241 and 340 refusals respectively.

---

## S2 — Major

### S2-1 · Drawdown is penalised as a level, not an increment **[verified, fixed]**

_Tracked in [#96](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/96)._

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
→ [12 §3.4](12_perspective_rl_researcher.md#34-the-drawdown-term-charges-a-change-not-a-level),
[07 §4.1](07_reward_function.md)

### S2-2 · Unnormalised observation scales saturate the `tanh` MLP **[verified, fixed]**

_Tracked in [#97](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/97)._

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
→ [05 §7.5, below](#05-75--a-bare-square-root)

### S2-3 · Transaction-cost proxies are ~10⁵× too small **[verified, fixed]**

_Tracked in [#98](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/98)._

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

**Real fees, fixed.** `maker_fee_bps` and `taker_fee_bps` charge each fill a fee in basis points of
its notional, taken out of cash inside `Account.process_acc` so it flows through the ledger. The
taker (the aggressing order) pays the taker rate, the maker the maker rate (negative is a rebate);
a self-trade and ADL pay nothing. Each account keeps `fees_paid` and the exchange's ledger is their
sum, so conservation is `sum(NAV) + fees == starting cash`, still exact, and the callback's check
counts the fees. The cash check reserves the largest fee so a fill cannot overdraw. Both rates ship
at 0, so nothing changes for a run that does not set them; turning them on changes the game
([04](04_accounting.md) §9, [18](18_configuration.md) §3.0.4, `test_fees.py`). Borrow cost and
funding remain absent.
→ [13 §4](13_perspective_financial_trader.md#4-transaction-costs-are-opt-in),
[07 §4.2](07_reward_function.md)

### S2-4 · Bankrupt agents are never terminated **[verified, fixed]**

_Tracked in [#99](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/99)._

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

_Tracked in [#100](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/100)._

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
→ [13 §3.1](13_perspective_financial_trader.md#31-self-matching-is-prevented)

### S2-6 · Every frame in the observation stack has a different normalizer **[verified, fixed]**

_Tracked in [#101](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/101)._

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
→ [05 §2.2](05_observation_space.md#22-prices--fractional-distance-from-m)

### S2-7 · No trade-flow information — the tape loop is dead code **[verified, fixed]**

_Tracked in [#102](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/102)._

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
→ [05 §7.3, below](#05-73--the-tape-loop-that-built-nothing)

### S2-8 · No logging framework; the callback prints 42 diagnostics per episode — **fixed**

_Tracked in [#103](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/103)._

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

_Tracked in [#104](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/104)._

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

_Tracked in [#105](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/105)._

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

_Tracked in [#106](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/106)._

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

_Tracked in [#107](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/107)._

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

### S2-13 · A cancel was cash-checked like a new order, so an over-committed trader could not cancel **[verified, fixed]**

_Tracked in [#108](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/108)._

`Trader._order_approved` ran the same check for every order type: compute the "opening" size,
multiply by the price, compare against `cash`. For a `cancel` that is meaningless — a cancel
places nothing, it *returns* escrow to cash — but it was applied anyway, with the cancel's own
(irrelevant) size and price as the notional. The consequence is exactly backwards from what a
solvency gate is for: **a trader whose cash was fully escrowed in resting orders was refused the
one action that would have freed it.**

Measured, before the fix ([16](16_verification_log.md) §16.17):

```
after limit  10 @ 100:  cash 0    on_hold 1000   rejected 0
after cancel        :   cash 0    on_hold 1000   rejected 1   orders resting 1
after modify 5 @ 100:   cash 0    on_hold 1000   rejected 1   resting qty 10
```

The same trap caught a `modify` that shrank an order, and a `modify` that re-priced one at the
same or lower notional: `cancel_cash_transfer` hands the old order's escrow back *before* the new
quote is processed, but the check did not know that and compared against the pre-release `cash`.

Why it matters for learning rather than only for tidiness: the refusal is silent to the agent
(`num_rejected_step` increments, nothing else happens), so from the policy's side "cancel" simply
does nothing whenever it is over-committed. The agents most in need of managing their quotes are
the ones for whom quote management was switched off, and the `order_rejection_fraction` metric
counted these as if they were orders quoted past the agent's means.

**Fixed.** A `cancel` is approved unconditionally once the `nav > 0` gate passes (a bankrupt
trader is terminated and its orders pulled by `cancel_all_orders`, not by an action). For `modify`
and for a `limit` at a price the trader already rests at — the upsert path — the escrow the
replaced order releases is added to the cash the check may spend, so re-pricing and shrinking
always pass and only a genuine increase in notional beyond `cash + released` is refused.
`_replaced_order` returns the order as well as its id, so the same lookup that excludes it from
`_resting_exposure` (S1-5) supplies the released amount. Seven tests in `test_cash_check.py` pin
each case, including that a bankrupt trader still cannot act.

### S2-14 · A market order is cash-checked at the touch but pays every level it sweeps **[verified, fixed]**

_Tracked in [#109](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/109)._

`Trader._order_approved` priced a market order's opening size at the best opposite price. A sweep
pays deeper levels too, so the check passed an order the trader could not afford. With cash 1,000, a
market buy of 10 against asks of 1 @ 100 and 9 @ 200 was approved and left cash at **−900**
([16](16_verification_log.md) §16.27). Batch clearing was wider still: the check runs when an order is
queued and the price is only known at clearing, one uniform price that can sit above the price the
order was checked at, for a market order, for a limit sell opening a short (a short pays its notional
in cash, at the clearing price rather than at its limit) and for a resting ask that fills above the
limit its escrow was posted at. Measured under random play with fees off, 4 agents at 3,000 cash,
`liquidation: off`: 22 of 12,000 agent-steps under batch ended with `cash + cash_on_hold` below zero,
worst −82 ([16](16_verification_log.md) §16.28).

**Fixed.** Two parts, both opening-risk only, since closing needs no cash for the closing contracts.

- *Sequential:* the order is priced by walking the opposite book (`Trader._sweep_cost`), charging the
  contracts that open at the level they reach. The trader's own resting orders are skipped, because
  self-match prevention cancels them first; a thin book costs what it can fill.
- *Batch:* once `clear_batch` has chosen its price it asks the env
  (`Trader.can_pay_at_clearing`) whether each order that would trade can pay for the fill there. An
  order that cannot sits out and the auction runs again without it, until everyone left can pay. A
  queued order that sat out lapses, market or limit, and counts as rejected (resting a limit at its own
  price would put it beside the orders it could not afford to trade with, and cross the book); a
  resting ask simply stays, and a leftover limit that would now cross what rests lapses uncounted. The question is put for the order's full size, so it can turn away an order that
  would have fit after rationing and never admit one that does not
  ([06](06_action_space.md) §8.2).

Both change which orders are approved, so they change the game the policy plays; they are what the
cash check was always meant to do. `test_overdraw.py`.

### S2-15 · Closing a losing position realises the loss into cash without a cash check **[verified, fixed]**

_Tracked in [#228](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/228)._

Found while fixing S2-14. `Trader._order_approved` returned `True` at once for an order that only
closes, and charged a flip only for its opening part, but covering a short that is under water
realises its loss into cash (NAV is unchanged; the loss moves from `position_val` to `cash`). Cash
moves for the closing part of an order only when the position reaches zero: a partial close pays the
lots' market value and leaves the result in the value of the lots still open, and the final lot
settles the whole `position_val` into cash. A long's is its market value, never negative; a short
posted its notional as collateral and is worth `2 × cost_basis − |position| × price`, which turns
negative once the price passes twice the entry. So a trader with little cash could cover a losing
short, or flip out of it, and end with `cash + cash_on_hold` below zero, with the shortfall surfacing
steps later when a resting bid filled. Reproduced under random play (seed 114): short 1 lot with
`position_val` −574 and cash 3,270; a crossing limit bid of 91 @ 35 is approved (its 90 opening
contracts cost 3,150), covers the short at 34 and opens a long, and `cash` goes to −433 with NAV
still 2,696; five steps later a fill takes `cash + cash_on_hold` from 652 to −83. Counting every
trader, the unfixed code overdrew 32 and 61 of 51,200 agent-steps under sequential clearing (fees off
and at 100 bps; worst −293 and −340), and none under batch ([16](16_verification_log.md) §16.29).

**Fixed.** A buy that takes a short flat or past flat now reserves the loss it realises
(`Trader._loss_on_cover`: `max(0, cost of the covering lots − 2 × cost_basis)`, priced at the limit,
by the sweep for a market order, or at the clearing price under batch) on top of whatever it opens.
A partial cover, a short not past its collateral and any sell reserve nothing. The consequence is
the one the check is for: a trader whose short is under water by more than its free cash can no longer
flatten it with an order (it takes a liquidation, `liquidation`, to remove it). A resting bid that
would cover the short holds the same reserve against later orders (`_resting_cover_loss`), since it is
not escrowed. The alternative, a liquidity margin call, was not built. `test_overdraw.py`.

---

## S3 — Moderate

### S3-1 · Half the `size_mean` action range is a no-op **[verified, fixed]**

_Tracked in [#110](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/110)._

`_set_size` applies `abs()` to the Gaussian sample, so `mean=+0.5` and `mean=−0.5` produce
identical sizes under the same seed. `size_mean` is declared on `Box(-1, 1)`; the optimum is
bimodal at `±m`, which a unimodal Gaussian head resolves by drifting toward 0 — i.e. minimum
size. The gradient kink sits exactly where the policy initializes.

**Fixed.** `action_space.size_mean_low` is `0.0`, so the space is `Box(0, 1)` and the eleven means from 0 to 1 give eleven
different sizes, for market and limit orders alike. `ACTION_LAYOUT_VERSION` 3 refused a checkpoint trained on the signed
range. Changelog [17](17_changelog.md) §65. The head itself was then replaced by the single `size` head of S3-2 and S3-3
(layout 4, §66).

### S3-2 · The `size_sigma` head is inert **[verified, fixed]**

_Tracked in [#111](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/111)._

`sigma ∈ [0,1]` is used as an *absolute* standard deviation while means are 49.5·|m| or 499.5·|m|.
Across its full range the size varies by ±1 contract on a base of 250. The policy pays entropy
cost for a control that does nothing.

**Fixed.** Deleted: the size is now one `size` head, `Box(0, 1)`, and there is no sigma. Measured before the change, 4,000
limit sizes at `size_mean = 0.5` had a standard deviation of 0, 0.37, 0.58 and 1.05 at sigma 0, 0.25, 0.5 and 1.0, on a base
of 250. `ACTION_LAYOUT_VERSION` is 4, so a checkpoint with the old heads is refused at restore. Changelog
[17](17_changelog.md) §66.

### S3-3 · Size is sampled by the environment, outside the policy's log-prob **[verified, fixed]**

_Tracked in [#112](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/112)._

The policy emits distribution parameters and the env draws the sample, so the realised size is
not part of the action whose log-probability PPO uses in the importance ratio — and the agent
never observes the realisation. Irreducible advantage variance.

**Fixed.** The policy emits `size` directly as a `Box` action and `Action_Helper._set_size` draws nothing, so the size
an order gets is the action PPO scores. Before the change one action under eight env seeds gave sizes
251, 251, 251, 253, 250, 250, 252, 251; now it gives one
(`test_new_action_space.py::TestSizeHead`). The spread was small only because S3-2's sigma was; the structure was the
defect. Per-step order sizes no longer consume the env's random stream, so a seeded episode is not the one it was before
the change. Changelog [17](17_changelog.md) §66.

### S3-4 · The order book's `tick_size` is inert **[verified, fixed]**

_Tracked in [#113](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/113)._

`tick_size` used to exist as two independent values: a hardcoded `min_tick = 1` in
`Action_Helper` that actually drove prices, and an `OrderBook` argument that was stored and never
read. Setting the config key therefore changed nothing anywhere.

**Fixed, in three steps across three passes.** `Action_Helper.min_tick` comes from the `tick_size`
config key, so the key controls the grid agents quote on. `reset()` stopped rebuilding the book
with a literal. And on 2026-09-18 the book's dead parameter was deleted: `OrderBook` takes only
`tape_display_length`, `OrderBook(0.0001, 10)` is a `TypeError`, and the `inert_tick_size_copy`
block that documented the literal is gone from `tunable_constants.json`. There is now exactly one
definition of the tick, the action layer's, and the code no longer suggests a guarantee the
matching path does not provide — the book keys its price map on whatever `Decimal` it is handed and
never did enforce a grid. The `envs/orderbook/` package was off-limits until this pass; the
invariant suite (`test_orderbook_properties.py`) is what made lifting that safe.

**The float-grid caveat, re-measured and fixed.** An earlier version of this entry said
`_set_price` "emits on-grid prices by construction" and that off-grid drift was rare — one
combination over all anchors and six ticks. That analysis covered only the *anchor* path
(`ref_price ± k × min_tick`). The *level* path, taken whenever the targeted book level is
occupied, read the resting price out of `agg_LOB_raw`, which was a **float32** array: a level at
100.1 read back as `100.0999984741211`, and adding a float offset to that gave
`100.19999694824219`. `OrderBook.process_order` keys its price map on `Decimal(str(price))` with
no rounding, so **every re-quote at an occupied level on a non-integer tick opened a new price
level one ulp away from the one the agent meant**, and `Trader._get_order_ID` — which compared the
book's `Decimal` against the action's `float` — never found the trader's own order, so cancels
were silent no-ops and a limit at the same price rested a second order instead of upserting.
Measured at `tick_size` 0.1: one new level per step from an agent quoting the same level every
step ([16](16_verification_log.md) §16.17).

Three changes close it, all on the action side: `agg_LOB_raw` is float64 (the emitted observation
is still cast to float32 at emission); `_set_price` snaps its result to the tick grid in `Decimal`
before returning it; and `_get_order_ID` compares prices as `Decimal(str(price))`, the same
conversion the book applies on the way in. `test_tick_grid.py` (18 tests) asserts every level and
offset lands on the grid for seven ticks including 0.3 and 0.0001, that re-quoting a level upserts,
that a cancel at a fractional price finds its order, and that NAV is conserved under random play
at `tick_size` 0.1.

Related, and still open as a *default*: the price anchor is drawn from `randint(10, 100)`, so with
a fixed tick the *relative* tick varies **10×** across episodes — a large uncontrolled
non-stationarity, only partly mitigated by exposing `log_mid`. What has changed is that this is
now a choice rather than a limitation: `initial_price_min` / `initial_price_max` are `TrainConfig`
fields and are forwarded by `env_config`, so a run can narrow the range. The checked-in config
still ships the wide one.

### S3-5 · Seeding is entirely non-functional **[verified, fixed]**

_Tracked in [#114](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/114)._

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

_Tracked in [#115](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/115)._

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

### S3-7 · `sys.exit()` used for error handling in the matching engine **[fixed]**

_Tracked in [#119](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/119)._

Six live occurrences in `orderbook.py`. `SystemExit` derives from `BaseException`, so inside a
Ray actor it kills the worker rather than surfacing a traceback. Currently unreachable, but one
action-space change away.

**Fixed (2026-09-18).** All six raise `ValueError` naming the method and the value it refused
(`process_order(): order quantity must be > 0, got 0 (trade_id 1)`), the two commented-out copies
are deleted with the dead code around them, and `test_orderbook_new.py::
TestMalformedInputRaisesInsteadOfExiting` pins each path and asserts that nothing raises
`SystemExit`. `import sys` is gone from the module.

### S3-8 · `build_algo` returns a detached callback on the restore path **[fixed]**

_Tracked in [#120](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/120)._

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

### S3-9 · No risk-adjusted performance metrics **[fixed]**

_Tracked in [#121](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/121)._

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
was absorbing float noise. The remaining `float()` consumers of `info["NAV"]` are untouched.

**Fixed, in part** (issue #121, changelog [17](17_changelog.md) §78). `train/performance.py` keeps O(1)
state per agent from the exact NAV and net position, and the callback logs per module, meaned over
the iteration: `module_sharpe`, `module_sortino` (per-step returns, not annualised), `module_max_drawdown`
(over the path), `module_hit_rate`, `module_position_turnover`, `module_mean_abs_position` and
`module_max_abs_position`. A metric undefined for an episode is left out, not logged as 0. The maker
share already existed (`maker_fill_ratio_max`).

**Fixed, the rest** (issue #286, changelog [17](17_changelog.md) §80). The account now tracks realised P&L
(booked on the closing part of a fill, against the average entry; fees excluded) and the callback logs
`module_realised_pnl` and `module_unrealised_pnl`; they satisfy `NAV - init_nav == realised + unrealised -
fees_paid` exactly. Adverse-selection mark-outs are `module_markout_<h>` for each `markout_horizons` entry
(default 1 and 10 steps): the signed fill quantity times the mid `h` steps later, less the signed fill value,
per contract filled. Forced fills (liquidation, ADL) are realised P&L but are not counted as the agent's
executions.

### S3-10 · A trader can hold only one resting order per price level **[verified, fixed - as an option]**

_Tracked in [#122](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/122)._

A second limit at the same price *replaces* the first (level volume 7, not 12) —
`_place_limit_order` upserts via `_get_order_ID`. Layering, iceberg and multi-clip quoting are
not expressible. Different price levels are unaffected.

**Fixed as an option** (issue #122, changelog [17](17_changelog.md) §79): `allow_multiple_orders_per_level`
(env key, default `false` = the behaviour above) makes a limit always a new order. The default is
deliberately unchanged, so no existing run or checkpoint moves. One branch in `Trader._get_order_ID`,
which the cash check shares.

### S3-11 · No entropy bonus, and champion promotion cannot detect passivity **[verified, fixed]**

_Tracked in [#123](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/123)._

`entropy_coeff = 0.0` (RLlib default). If the learners collapse to "always pass" (S1-3), they
still clear the promotion threshold — 0 beats a negative league mean — so the league fills with
champion snapshots of the do-nothing policy. Related: with `std_dev_multiplier=0.1` a champion is
promoted on the very first eligible iteration **[verified]**, so at the default 16-iteration run
the pool saturates with barely-trained snapshots.

**Fixed**, all three parts, and the third turned out not to be covered by the second:

- `ppo.entropy_coeff` 0.01 falling to `entropy_coeff_final` 0.001 over `entropy_decay_iters` 16
  iterations (RLlib's default was 0.0). A real two-iteration run applies 0.008875, which is the
  linear value at 512 of 4,096 steps (`curr_entropy_coeff` in the learner results).
- `league_self_play.std_dev_multiplier` 1.5, the bottom of the recommended range. 2.5 is not
  safe to ship: with n modules nobody can be more than `sqrt(n − 1)` standard deviations above
  the mean (2.65 at the default 8, 1.73 at 4), so a multiplier at or above that never promotes
  anyone. `SelfPlayCallback` now warns at construction when that is so.
- `league_self_play.min_champion_trades` 1.0: a candidate that traded under that many times per
  episode over the iteration is refused (`result["league"]["refused_passive"]` is 1, a warning is
  logged, nothing else changes). **Measured:** a do-nothing `policy_0` (return 0.0) against six
  modules losing money is promoted at multiplier 0.1, **and at 1.5**, and refused only with the
  guard. The per-module trade counts reach the driver as `module_trades_per_episode`; absent
  counts do not block (they warn), so the guard cannot stop the league growing by itself.

The shipped values of the entropy bonus are the usual PPO range, not tuned on this env.
`test_champion_guard.py` (26) and `integration/test_champion_guard_wiring.py` (3, a real run).
Changelog [17](17_changelog.md) §69. Doc [08](08_self_play_league.md) §10.

### S3-12 · The league ranks a signal that is not comparable across roles **[fixed - as an option]**

_Tracked in [#124](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/124)._

The four shaping terms are not zero-sum, so returns depend on the role a module played that
episode. The promotion threshold is a pooled `mean + k·std` over *all* modules including the
frozen random baselines. A policy can clear it by trading *less*, not *better*.

**Fixed as an option** (issue #124, changelog [17](17_changelog.md) §79):
`league_self_play.promotion_reference: "excluding_baselines"` computes the threshold over the trainable
modules and champions only. Default `pooled`, unchanged. The bias runs both ways, depending on where the
baselines sit: just under the learners they lower the bar a candidate clears, far below they raise it past
a clearly better learner (both pinned in `test_s3_moderate_fixes.py`). "Trading less" is guarded by
`min_champion_trades` (S3-11). While the non-baseline set is too small for the multiplier to be clearable
the threshold falls back to the pooled one, so the league can still start.

### S3-13 · γ=0.99 against 4,096-step episodes **[verified, fixed]**

_Tracked in [#125](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/125)._

Effective horizon ~100 steps = 2.5% of an episode. Strategies with payoff horizons longer than
that (inventory accumulation, sustained market making) are invisible to the return. Only 4
episodes per training iteration also means very few samples of the episode-level randomness
(price anchor, opponent draw). `lambda_=1.0` (RLlib's PPO default, not the usual 0.95) makes
advantages pure Monte-Carlo.

**Fixed** (issue #125, changelog [17](17_changelog.md) §79): `gamma` and `lambda_` are `ppo` config keys now,
shipped at **0.999** and **0.95** (effective horizon about 1,000 steps, GAE variance reduction back). They are the
usual choices for a long episode, **not tuned on this env and not shown to be better**; they change what every
default run optimises, so results trained at 0.99 / 1.0 are not comparable. In the restore fingerprint. The
4-episodes-per-iteration point is `num_episodes_per_iter`, untouched.

### S3-14 · Zero means three different things in the observation **[verified, fixed]**

_Tracked in [#126](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/126)._

`0.0` was the sentinel for "level absent", the exact value of a price *at* the midpoint, and — on
a one-sided book, where `M` fell back to that side's L1 price — the value of the best quote
itself. The book starts empty every episode and is frequently one-sided early on, and there was no
validity mask.

**Measured before the fix, 2026-09-18** (20 seeded random-play episodes × 400 steps per config,
[16](16_verification_log.md) §16.23). Shipped config: 92.0% of steps two-sided, **7.8% one-sided**,
0.1% empty; **627 of 53,604 occupied price cells (1.17%) read exactly 0.0**, every one the lone best
quote of a one-sided book; a further 2,273 of 159,960 occupied cells in the older frames read 0.0.
Stress config (6 agents, 20,000 cash, anchors 5–500, tick 0.1): 23.5% two-sided, **32% one-sided,
44.5% empty**; **2,556 of 11,663 occupied cells (21.9%) read 0.0**. No occupied cell away from L1
ever read 0.0 in the newest frame: the ambiguity was entirely the one-sided case.

**Fixed** by both proposed routes at once ([05](05_observation_space.md) §1.3, §2.1): two occupancy
rows per snapshot (`1.0` where the level holds an order, carried in the raw frame so every frame
keeps its own), and the last trade as the reference price of a one-sided book, which is the chain
`mark_price` has used since S2-5, so the observation and the NAV mark agree. After: the occupancy
row equals `size > 0` on every cell of every step; the occupied cells still reading 0.0 (0.66%
shipped, 11.2% stress) are quotes resting exactly at the last print — a real state, now labelled.
Observation layout version 4, 296 floats. `train.compare` before and after in §16.23.

**What the measurement also settled.** The extreme price tails found while deriving the S4-15
bounds — an ask at 23× the midpoint, a `vwap_vs_mid` of −31 — were traced cell by cell: every one
sat in a book whose midpoint had **random-walked down to one to three ticks**, mostly two-sided.
They are not this row's; they are S3-15's additive-tick coordinate at work, and they are the first
numbers that row has had against it.

### S3-15 · Level index is a non-stationary coordinate **[verified, fixed]**

_Tracked in [#127](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/127)._

Slot *k* meant "the *k*-th occupied price", not a fixed distance from mid, and the action space
selected by the same unstable index. A learned association such as "level 3 is a good place to
quote" had no fixed meaning across steps.

**Measured before the fix, 2026-09-18** (20 seeded random-play episodes × 400 steps per config,
[16](16_verification_log.md) §16.24). Shipped config: the best level sat **3.8 ± 2.5 ticks** from
the reference (range −20 to +27), the second **7.0 ± 3.8**, the fifth **12.9 ± 4.8**; the price at
a given slot changed between consecutive steps on **35–54%** of the steps it was occupied on both.
The action's price code *j* landed at a realised distance of 3.6 ticks (code 0) rising only to 9.4
(code 9) with a standard deviation of ~5 ticks throughout, codes 1–6 indistinguishable at 6.5–7.2.
Same picture at the stress config.

**Fixed** by exactly the proposed grid ([05](05_observation_space.md) §1.4, [06](06_action_space.md)
§2.1.1): `book_mode: "grid"`, two size rows over `2 × k_rows + 1` tick offsets from the reference
price, every frame re-gridded against the newest reference, and price code *j* quoting *j* ticks
from the reference on the passive side. After: code *j* lands at ***j* ± 0.9 ticks** (the offset
head) on both sides at both configs, and a ±10-tick window covers **93%** of resting volume against
73% before, because the agents now quote on the grid; ±16 covers 99.5%. The `levels` layout is
kept as `book_mode: "levels"` for comparison, the mode travels in the layout stamp, and
`train.compare --set book_mode=...` runs either. Observation layout version 5, 224 floats.
`train.compare` before and after in §16.24.

### S3-16 · One undrawn opponent kills champion promotion for the rest of the run **[verified, fixed]**

_Tracked in [#128](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/128)._

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

_Tracked in [#129](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/129)._

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

### S3-18 · The config tree was not in the built distribution **[verified, fixed]**

_Tracked in [#116](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/116)._

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

_Tracked in [#117](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/117)._

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

_Tracked in [#118](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/118)._

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

### S3-21 · `visualize/` is in no built distribution **[verified, fixed]**

_Tracked in [#130](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/130)._

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

_Tracked in [#131](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/131)._

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

### S3-23 · NAV conservation is exact only to Decimal context rounding **[verified, fixed]**

_Tracked in [#132](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/132)._

[16](16_verification_log.md) §16.10 established that conservation is "exact under Decimal" and
the config note for `nav_tolerance` says the expected error is 0. The Hypothesis suite found
otherwise on its first run (seed 161, `tick_size` 1): a 4-agent total of `399999.9999999999999999999999`
against 400,000. Re-measured on the tree *before* this pass's ledger change, so it is not a
regression: over 12,000 random-play steps at `init_cash` 100,000, **17.6% of steps** carry a
non-zero conservation error, the worst being `7E-22`.

The cause is the VWAP-based ledger. `_size_increase` stores `VWAP = (|pos| x VWAP + trade_val) /
total_size`, a quotient that rounds at the 28-digit context whenever it does not terminate, and
`mark_to_mkt` then builds `position_val` as `|pos| x VWAP + |pos| x (mark - VWAP)`, two products
that round independently. Algebraically the VWAP cancels; numerically it leaves a residual of one
unit in the 22nd place. §16.10's probe happened on a 300-step sequence where the residuals
cancelled, which is what "exactly conserved 300/300" recorded.

Nothing downstream is wrong: the error is 27 orders of magnitude below the tolerance, and the
tolerance is what the training-time check applies. What is wrong is the *claim*. It is corrected
here, in §16.10's heading, and in `test_orderbook_properties.py`, which asserts conservation to
`nav_tolerance` rather than to zero and says why.

**Fixed (2026-09-18, the same day).** `Account.cost_basis` is the position's basis as the exact
`Decimal` sum of trade values, and it is what every ledger path reads and writes: `_size_increase`
adds the trade value, `_size_decrease` subtracts it (the realised-P&L roll is unchanged, it is
now simply *stated* as a sum), `_covered` resets it, `_neutral` and `_covered_side_chg` set it to
the opening value, and `mark_to_mkt` forms `position_val` from it with one product,
`|pos| × mark`. `VWAP` is a derived property, `cost_basis / |net_position|`, kept for display and
for the tests that build a position by hand through its setter. Re-measured over the same 12,000
random-play steps: **0 steps with a non-zero residual**, at `tick_size` 1 and at 0.1; the property
suite asserts conservation with `==` again ([16](16_verification_log.md) §16.19). The
`nav_tolerance` note's claim of exactness is true once more, and says why.

### S3-24 · `modify` and `cancel` cannot be aimed, so they are mostly dead actions **[verified, fixed]**

_Tracked in [#133](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/133)._

Two of the eight order categories are order management, and an agent cannot use either on
purpose. Measured under uniformly random play, 5 seeds × 400 steps × 6 agents
([16](16_verification_log.md) §16.19):

| action | issued | agent had ≥1 resting order | hit an order |
|---|---|---|---|
| `cancel` | 2,738 | 73% | **7%** of issued (10% of those with an order) |
| `modify` | 2,659 | 71% | 48% of issued (67% of those with an order) |

Agents hold 1.6 resting orders on average (median 1, p90 4, none on 26% of agent-steps). Three
causes, in the order they bite:

1. **The agent cannot see its own orders.** The private block carries `cash_on_hold` — how much is
   escrowed — but not where. Which levels hold its orders, how many, on which side: none of it
   is observable ([05](05_observation_space.md) §7.7, the S1-2 tail). A cancel is therefore a guess
   about state the policy was never shown.
2. **A cancel is aimed by exact price.** `_get_order_ID` matches the agent's order at the price
   `price_code` + `price_offset` resolves to. There are 10 levels × 3 offsets = 30 codes, the agent
   typically has one order, and two of the three offsets name a price one tick off any level - so
   even a policy that *knew* where its order sat has one code in thirty that hits it, and a random
   one hits 7% of the time.
3. **A modify is aimed by FIFO, and re-priced by level.** It always targets the agent's oldest
   order on that side, and its `price_code` names the *new* price, so it cannot choose which order
   to move. Its 48% hit rate is simply "did the agent have any order on that side".

The 2026-09-18 pass made both actions *honest* — a cancel is never cash-checked (S2-13), prices sit
on the grid so a hit is possible on any tick (S3-4), and a miss is counted (S4-14) — but not
*aimable*. This is the plan for that, in the order the pieces depend on each other. Every phase is
a structural change to the observation or action layout, so the whole plan is one new
checkpoint generation, not several.

**Phase 1 — show the agent its own orders (closes the S1-2 tail).** Add an "own book" block to
the private tail: for each of the `k_rows` levels on each side, this agent's resting size at that
level, on the same `√(V / limit_max_size)` scale and sign convention as the public book, plus two
scalars for own order count per side over a cap. That is `2 × k_rows + 2 = 22` floats, taking the
observation from 193 to 216. It slots into the level tokenisation the encoders already use — a
level token gains an "own size" channel — so `obs_layout.py` and `tokenize.py` change in one place
each. `PRIVATE_FIELDS` and `observation_layout.private_dim` are the two definitions to move
together; the constructor check catches a mismatch. Deliverable: the block, its tests (own size at
a level equals the sum of own orders there; zero elsewhere; sign; the shared/private split test in
`test_observation_history.py` extended), and [05](05_observation_space.md) §1 and §7.7 rewritten.
About a day.

**Phase 2 — aim by slot, not by price.** Add an `order_slot: Discrete(max_own_orders + 1)`
component to the action `Dict`. For `cancel`, `order_slot = k` names the agent's k-th own order on
that side counted from the touch (best price first, oldest first within a level, the same order
Phase 1 lists them in); `price_code` and `price_offset` are ignored, and slot 0 means "all on this
side". For `modify`, `order_slot` names the order and `price_code` + `price_offset` name where it
goes, so a modify can finally choose which order to move; the `size` head keeps its meaning. A slot
beyond the agent's count is `num_unmatched_step`, as now. `Trader._get_order_ID` grows a
`by_slot` path; `_prevent_self_match`, `_resting_exposure` and `_replaced_order` are unaffected
because they resolve through the same lookup. `RandomRLModule` samples the new component for free
and RLlib's `Dict` action distribution handles it without a custom model. Deliverable: the
component, `tunable_constants.json` → `action_space.max_own_orders` (8, above the measured p90 of
4), the decode in `_set_action_mkt_depth`, and tests that a cancel at slot k removes exactly that
order on any tick. Expected effect on the same random-play measurement: a cancel hits whenever
`slot ≤ count`, so roughly 60–70% of issued rather than 7%. About a day.

**Phase 3 — make a miss visible to the policy, not only to the log.** `num_unmatched_step` reaches
`info`, the record and the metrics; the policy sees none of those. Two options, both small, in
order of preference: (a) add `unmatched_last_step` (0/1) to the private block so the consequence
of a dead action is in the next observation, which is what a recurrent or stacked policy can learn
from; (b) a `dead_action_penalty` reward coefficient, default **0.0**, because any non-zero value
makes the game negative-sum (S1-3) and has to be weighed against that. Ship (a); expose (b) as a
knob and leave the decision to a measured run. Half a day.

**Phase 4 — prove it learned.** Run `train.compare` before and after at the scaled-down protocol,
three seeds, reading `unmatched_action_fraction`, `pass_action_fraction` and the maker ratio
beside returns: the claim to test is "agents that can aim cancels quote more and hold fewer stale
orders", and the first two metrics are the ones that would show it. Then the Hypothesis suite
extended with slot-aimed sequences, so the book and escrow invariants are asserted under the new
action shape too. Half a day plus the runs.

**Sequencing and risk.** Phases 1 and 2 are both structural (`n_hist`-class changes: a checkpoint
from before cannot be restored after), so land them in one change and record a layout version in
the checkpoint while at it — that is S4-19, and this is the moment it stops being hypothetical.
Phase 2 without Phase 1 gives an agent a precise instrument it cannot see the target of; Phase 1
without Phase 2 shows it a target it cannot hit. The modify semantics change (FIFO → slot) is the
one behaviour change an existing policy would feel; the comparison in Phase 4 is what says whether
it mattered.

**Done (2026-09-18, all four phases; [17](17_changelog.md) §47, [16](16_verification_log.md) §16.20).**

- *Phase 1.* `State_Helper.private_fields(k_rows)` is `[9 base | own bid sizes (k) | own ask
  sizes (k) | own counts (2) | unmatched_last_step]`, 32 at `k_rows` 10 when this phase landed; the
  nine action-mask entries since appended make it 41, and the observation 233 floats. `own_book` reads the live book after the step's orders, so level k of the own book is
  level k of the newest snapshot, and `tokenize` writes the two own sizes into channels 4 and 5 of
  the newest snapshot's level tokens - the channels the scalars' width had left as zero padding -
  so the transformer, LSTM, MoE and JEPA encoders see them per level at no extra width.
- *Phase 2.* `order_slot: Discrete(max_own_orders + 1)`, `max_own_orders` 4 (the measured p90).
  Slot k is the k-th own order from the touch; 0 is "all" for a cancel and the oldest for a modify.
  **One design change against the plan as written:** a slot past the agent's count is *clamped*
  to its deepest order rather than counted as a miss. Measured under random play, a head with dead
  upper slots made modify worse than the FIFO rule it replaced (48% → 23% of issued modifies
  landed) while cancel rose only from 7% to 19%, and a learned policy gains nothing from dead
  slots because it can read its own-order counts. Clamped: 35–36% of issued modifies and cancels
  land, 58–62% of those where the agent had anything resting, and the only miss left is a side
  with nothing on it. A cancel no longer reads `price`.
- *Phase 3.* `unmatched_last_step` in the private block, and a sixth reward term
  `dead_action_penalty` shipped at 0.0 with the S1-3 warning on the knob.
- *Phase 4.* `train.compare` collects the rejection, unmatched and maker metrics; run before and
  after at three seeds × 8 iterations of the scaled-down protocol (§16.20). At that scale the
  policies are still near random, so the run proves the protocol and the plumbing, not the
  learning claim; that needs the run at scale. The Hypothesis suite drives slot-aimed modifies and
  cancels through every invariant.
- *S4-19.* `envs/layout_version.py` stamps every checkpoint with the observation and action layout
  versions and field lists; `build_algo` refuses a mismatch by name.

### S3-25 · Within a step, the shuffle decided who traded and at what price **[verified, fixed - as an option]**

_Tracked in [#134](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/134)._

All agents act at the same instant, but the engine matched the step's orders one by one in a
random order, so a crossing pair traded at whichever price arrived first and the first arrival had
first claim on resting liquidity. Measured under random play ([16](16_verification_log.md)
§16.26): the first agent in the shuffle filled on **58.1%** of its fresh orders and the last on
**49.1%**, monotonically down the queue; trading steps printed at 1.58 prices on average and up
to 5.

**Fixed as `step_clearing: "batch"`** ([06](06_action_space.md) §8): the step's new orders clear
together against the resting book at one uniform price (volume-maximising, then least imbalance,
then nearest the reference), resting orders keep time priority, the marginal level is rationed
under `matching_rule`. After: the fill curve is flat (57.7% to 57.1%), every trading step prints
one price, and executed volume falls from 51 to 43 contracts a step - the call auction's price for
its fairness. `sequential` stays the default, because a continuous double auction is what the
project simulates; `matching_rule: "pro_rata"` is the other pluggable regime. NAV is conserved
exactly under every combination, and `train.compare --set` runs them under identical seeds. The
first batch run also surfaced a settlement bug - a resting order filled at a better price than its
limit released more escrow than it held - found not by NAV conservation, which the error preserved,
but by the S4-15 clip counter on `cash_on_hold`; `Trader.settle_batch` re-bases the escrow first.

### S3-26 · A `modify` with nothing to modify cancelled the trader's other quotes **[verified, fixed]**

_Tracked in [#135](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/135)._

`place_order` ran the cash check and self-match prevention before asking whether a `modify` had a
resting order to act on. So a `modify` that changed nothing still cancelled the trader's own
opposite-side orders, and it was counted as *rejected* or *unmatched* depending on whether cash
happened to be short. It is now settled first, as an unmatched miss. A trader that cannot act at
all (NAV ≤ 0, or frozen mid-liquidation) is still refused, through `Trader._can_act()`, which
`_order_approved` shares. `test_unmatched_actions.py`.

### S3-27 · Closing escrow was counted in time order, not fill order **[verified, fixed]**

_Tracked in [#136](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/136)._

`_closing_escrow` (S1-5) credits the escrow of the orders that would close a position as
spendable. It promised to walk them in fill priority but sorted by timestamp, while the book fills
best price first. A long 10 with an older ask at 200 and a newer ask at 100 was credited 2,000
instead of the 1,000 that actually closes it, so opening orders passed a check they should have
failed. It now walks `_own_orders_from_touch`, the one definition of fill priority the slots and
the own-book observation already use. `test_cash_check.py`.

### S3-28 · At a non-integer tick the observation and the action could use grids one tick apart **[verified, fixed]**

_Tracked in [#137](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/137)._

The stored frame was float32, and the observation snapped its grid origin from that frame's
midpoint, while `reference_price()`, which `_set_price` and the own-book block quote from, snapped
the float64 one. A one-tick spread puts the midpoint exactly half a tick off the grid, where the
two roundings can disagree: 40 to 120 of every 200 one-tick books at ticks 0.3, 0.1, 0.05 and
0.01, none at the shipped tick of 1 ([16](16_verification_log.md) §16.27). Then a price code and
the agent's own-book cells sat one tick off the grid it was shown. The frame is float64 now; the
emitted observation is still float32. `test_tick_grid.py`.

### S3-29 · Three training metrics read wrong at the moments they matter **[verified, fixed]**

_Tracked in [#138](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/138)._

- `league.promoted` and `champions_promoted` were the change in champion count across the
  trigger. A full league evicts before it promotes, so every promotion after it filled read 0.
  They now count the new champion ids.
- `nav_conservation_error` was logged with `window=1`, the last episode's value, so an episode
  that destroyed 500 of NAV followed by a conserved one read 0.0. It is reduced by max.
- The episode account metrics (`episode_nav_min`/`_mean`/`_max`, drawdown, inventory, trades)
  read the last env step's infos, which an agent terminated earlier is not part of, so they left
  out the agents with the extreme outcomes. They read each agent's own last info.

`test_champion_trigger.py`, `test_nav_callback.py` (the last two against a real `MetricsLogger`
and `MultiAgentEpisode`).

### S3-30 · `train.evaluate` did not see a mid-episode bankruptcy **[verified, fixed]**

_Tracked in [#139](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/139)._

It read `terminated` from the last step, which a terminated agent has left, so a bankruptcy before
the end read as none, and that agent's activity fractions were divided by the whole episode's
length. Termination is recorded when it happens, and each agent's fractions use the steps it
played. `test_evaluate.py`.

### S3-31 · The probe's contiguous split leaked targets across its seams **[verified, fixed]**

_Tracked in [#140](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/140)._

Below three episodes the probe splits on contiguous rows. A target at row *t* reads row *t + h*, so
the last *h* training rows were labelled from validation observations and the last *h* validation
rows from test ones. `split_masks` takes the horizon as `purge` and leaves those rows out. The
episode split, the usual one, needed no change. `test_probe.py`.

### S3-32 · Continual Backprop: a silent no-op on `lstm`, and its state in every weight sync **[verified, fixed]**

_Tracked in [#141](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/141)._

Layer discovery finds 0 replaceable layers in `lstm` (4 in `mlp` and `transformer`, 16 in
`moe_transformer`, 6 in `jepa`), so `cbp_enabled` on `lstm` trained exactly like CBP off, with no
message. It now logs a WARNING naming the module and the scope that fixes it, and
`cbp_scope: "recurrent"` makes CBP cover the LSTM core: the top layer's hidden units, with the four
gates' rows of `weight_ih` and `weight_hh` as incoming and the unit's column of `weight_hh` and of the
head as outgoing ([25](25_continual_backprop.md) §3.4). That finds 2 layers per trainable module in
`lstm` (1 under `vf_share_layers`) and changes nothing for any other encoder; it fires inside a real
PPO update through RLlib's recurrent connectors. This makes the mechanism possible on `lstm`; it does
not show that it helps there. (A league run on `lstm` used to fail at its first champion whatever CBP did; fixed, #278, changelog [17](17_changelog.md) §71.) Separately, `CBPLearnerMixin.get_state` added its per-layer
tensors whatever components were asked for, so each iteration's weights-only sync copied them off
the device and threw them away. It now honours the component filter; a full checkpoint still
carries them. `test_cbp.py`, `test_cbp_recurrent.py` (21), `integration/test_cbp_wiring.py` (5 more).
Changelog [17](17_changelog.md) §70.

### S3-33 · The reward charts dropped `dead_action_penalty` **[verified, fixed]**

_Tracked in [#142](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/142)._

`TERM_COLORS` had five colours and was zipped against six `REWARD_TERMS`, so the decomposition and
the training means left the sixth term out, and the plotted terms no longer summed to the total
beside them, which reads as an accounting break. The variance-share stack drew it in `nav_term`'s
colour. Colours are keyed by term name, and a term without one fails at import.
`test_visualize_reward_terms.py`.

---

## S4 — Minor

| ID | Finding |
|---|---|
| S4-1 ([#143](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/143)) | **Fixed.** The `g_store` trio (~270 LOC) was deleted earlier; `train/helper/helper.py` (33 LOC, imported by nothing) is deleted too (2026-09-18). Its order-imbalance idea reached the observation by another route: S2-7's `signed_volume` |
| S4-2 ([#144](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/144)) | **Fixed.** `envs/agent/random_agent.py` is deleted and `Trader` no longer inherits from it; `RandomRLModule` is the one random policy (2026-09-18) |
| S4-3 ([#145](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/145)) | **Fixed.** Every dead method listed is deleted: `OrderBook.__str__0`, `Order.__str__0`, `OrderList.to_str`, the shadowed `Order.next_order`/`prev_order`, `State_Helper.state_diff`, `Action_Helper._set_side/_set_type/_higher/_lower`. The unread `max_price` parameter of `_set_price` was removed earlier |
| S4-4 ([#146](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/146)) | **Fixed.** All ~200 LOC of commented-out code are gone: the old `modify_order` and `get_volume_at_price` in `orderbook.py`, the old `step` and space getters in `continuousDoubleAuction_env.py`, the old `Tuple` `act_space` in `action_helper.py` |
| S4-5 ([#147](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/147)) | **Fixed.** `test_accounting.py::test_insufficient_funds` asserts the refusal, the untouched ledger and the approved affordable half; it was an empty `pass` under a 15-line comment |
| S4-6 ([#148](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/148)) | **Fixed.** pyflakes is enforced by `test_lint.py` (zero findings); `ruff format` was run once over the tree (188 files, quotes preserved, notebooks excluded) and `test_types.py` fails the suite if `ruff format --check` finds anything to change; `mypy` is configured for `envs/` and held at **zero errors** (it reported 110, 85 of them one finding: a mixin reading an attribute another class creates - see S4-10); `[tool.coverage.report] fail_under = 84` against **86.4%** line-and-branch measured on the unit suite (79.1% when this was written), `__main__` guards excluded. `ruff` (pinned) and `mypy` are in the `dev` extra. Not done: `train/` is not under mypy yet, and the threshold applies where `pytest --cov` is run - CI cannot be edited from here (no `workflow` scope), so it is a local and documented gate, not a CI one ([10](10_testing.md) §7; changelog [17](17_changelog.md) §82) |
| S4-7 ([#149](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/149)) | **Fixed.** `is_render` defaults to `false` in `env_defaults.json` (`CDA_rand --render` and a DEBUG `cda_log_level` are the two ways to ask for it), and `_render` is read-only: the nulling of `model_actions`/`LOB_actions`/`shuffled_actions` and clearing of `seq_trades`/`seq_order_in_book` is gone, so toggling the render cannot change what the next step sees. Every one of those fields is reassigned at the top of `step()` or in `do_actions` anyway |
| S4-8 ([#150](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/150)) | **Fixed.** `docker/ml/dockerfile_ray_torch` `COPY`s `requirements.txt` on its own layer and installs from it (plus jupyterlab and notebook); the hand-maintained copy of the list is gone, and torch stays the CUDA wheel because the file's `torch>=2.13.0,<3` is already satisfied |
| S4-9 ([#151](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/151)) | **Fixed.** The per-step record is Parquet with a declared schema, written off the sampling thread and bounded by `episode_sample_every` / `episode_max_bytes`; the two committed `.pkl` files are deleted. Nothing in the repository writes a pickle |
| S4-10 ([#152](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/152)) | **Fixed, with a stated remainder.** The defensive `getattr` reads were already gone. Four of the six mixins sharing the env's `self` are composed objects now: `RewardModel`, `EpisodeStatus`, `InfoBuilder` and `LiquidationEngine`, each taking its inputs explicitly (the last two through a narrow `Venue` protocol), with `Exchg_Helper` forwarding the attributes callers have always read (`env.order_penalty`, `env.done_set`, ...). What `State_Helper` and `Action_Helper` still share - and what `Calculate` and `Cash_Processor` share on the account - is declared in `SharedState` / `AccountState` and checked by `mypy`. Not done: unwinding the state/action pair itself, which share the observation layout and the book snapshot on every call ([02](02_architecture.md) §2.4; changelog [17](17_changelog.md) §82) |
| S4-11 ([#153](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/153)) | **Fixed, after measuring.** The counter-party lookup is O(1) in the env (trader IDs index the roster; the scan is the fallback for arbitrary lists) - though at 0.2 µs for eight agents it never mattered. The pre-action `set_agg_LOB` was 5.9% of a 1.05 ms step and is now rebuilt only when the book changed since the post-action snapshot - which is exactly when `set_done` pulled a bankrupt trader's orders, tracked by `_snapshot_stale` - or when the render wants its "@ t-1" table. Behaviour is unchanged: the two snapshots were identical in every other case ([16](16_verification_log.md) §16.21) |
| S4-12 ([#154](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/154)) | **Fixed.** `python -m gym_continuousDoubleAuction.train.evaluate --checkpoint <iter_n>` restores a checkpoint, refuses a foreign layout by name, and rolls episodes with its own `policy_mapping_fn` assigning modules - so the random baselines and champions play their parts - taking actions through `forward_inference` the way the env runner does, including the unsquash of the normalised Box heads. Per module it reports return, NAV change, trades and the three activity fractions; `--seed` pins episode seeds so two checkpoints are compared on the same anchors; `--deterministic` takes the mode. [26](26_runbook.md) §26.9.1; `test_evaluate.py` and `integration/test_evaluate_checkpoint.py` |
| S4-13 ([#155](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/155)) | **Fixed.** `test_orderbook_properties.py` (Hypothesis) asserts, for any order sequence: every tree cache equals a walk of its contents, time priority within a level, no locked or crossed book, escrow equals own resting notional, positions net to zero; and under random env play at three ticks, NAV conservation **exactly**, `cash + cash_on_hold >= 0`, and every price on the grid. Its first run found two things the example suite had not: S3-23, and a size-reducing modify that bumped a resting order's timestamp while keeping its queue position |
| S4-14 ([#156](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/156)) | **Fixed.** Refused orders increment `num_rejected_step`; `is_pass_action` separates a deliberate pass; and a `modify` / `cancel` that names no resting order increments `num_unmatched_step`, which reaches `info`, the episode record and the `unmatched_action_fraction` metric. The three fractions together bound how much of an episode's activity changed nothing in the book. Whether a dead action should be *penalised* is a reward-design question and is left as such. **Since 2026-09-18 the impossible half is masked** ([06](06_action_space.md) §7): the observation says which categories are possible and the modules refuse the rest, taking the unmatched fraction from 29.6% to 0.2% under random play; the rejection fraction at a thin-cash config barely moves (33.9% → 33.2%), because those refusals are size-driven and a category mask cannot reach the size head - a measured pointer at S3-1 to S3-3 |
| S4-15 ([#157](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/157)) | **Fixed, after measuring.** The Box has finite bounds from `observation_bounds` in `tunable_constants.json`, one `[low, high]` per feature family: exact where the range is an identity (`(M − P)/M < 1`, tanh, the `[0, 1]` fields), otherwise measured over 20 episodes × 400 steps of random play at the shipped config and 20 at a stress config, with at least 4× headroom ([05](05_observation_space.md) §1.2, [16](16_verification_log.md) §16.22). `set_next_state` clips to them and counts what it clipped: `num_obs_clipped_step` in `info` and the record, `obs_clip_fraction` in the metrics and `train.compare`. The counter is the answer to "a wrong bound is a silent clip" - it found one on the first smoke test (older frames' price rows go negative against the newest midpoint; the `[0, 1]` bid bound clipped 192 elements in 50 steps) and reads 0 over the 112,000 agent-steps measured with the shipped bounds. Layout version 3 with S4-17 |
| S4-16 ([#158](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/158)) | **Fixed.** `test_shared_history_multi_agent_uniformity` encoded S1-2 as a requirement. It is replaced by a pair that splits the claim: the book prefix must still be shared between agents, the private tail must not be |
| S4-17 ([#159](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/159)) | **Fixed, after measuring.** Ask prices and sizes are positive in the raw snapshot, the normalised frame, the own-book block and the L1 read; `_set_price`, the probe's `depth_imbalance` and the order-book visualizer read them so. `OBSERVATION_LAYOUT_VERSION` is 3 and a version-2 checkpoint is refused by name (S4-19) - same width, different meaning, which a shape check would never catch. `train.compare` at the S3-24 protocol (mlp and transformer, three seeds, 8 iterations) before and after: [16](16_verification_log.md) §16.22 |
| S4-18 ([#160](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/160)) | **Fixed** (earlier than this row admitted: the tree has carried only `CODEOWNERS` for several passes; the row was stale) |
| S4-19 ([#161](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/161)) | **Fixed.** `envs/layout_version.py` writes the observation and action layout versions, the private-field list and the action-key list into every checkpoint's `league_state.json`; `train.build_algo` compares before restoring and refuses a mismatch naming what differs. A pre-stamp sidecar is layout 1 by definition |
| S4-20 ([#162](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/162)) | **Fixed.** `OrderBook.modify_order` accepted quantity 0 and left a zero-size order resting, which a later sweep would print as a zero-size trade. It raises `ValueError` as `process_order` already did |
| S4-21 ([#163](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/163)) | **Fixed.** `liquidation_horizon: null` raised a bare `TypeError`, `true` was taken as a horizon of 1, and `maintenance_margin: NaN` raised `decimal.InvalidOperation`. Each is now the same `ValueError` naming the key as any other out-of-range value |
| S4-22 ([#164](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/164)) | **Fixed.** A champion adopted on restore has no recorded return, and `train.export` then raised ranking `None` against floats (`--list` and the eviction log line too). Unranked champions are skipped, printed as `n/a`, and an all-unranked league is an error naming `--module-id` |
| S4-23 ([#165](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/165)) | **Fixed.** `train.compare` probed the newest save in a run's directory, which a re-run with fewer iterations left from the previous sweep; it takes the save at this run's final iteration. `--set` could not parse a list or dict field (`fcnet_hiddens=[128,128]` raised from `int()`); container fields are parsed as JSON |
| S4-24 ([#166](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/166)) | **Fixed.** `config_loader.load` returned the cache's own objects, so appending to one `TrainConfig`'s list default changed every later one. It returns a deep copy |
| S4-25 ([#167](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/167)) | **Fixed.** When the episode recorder's live-episode cap evicted an episode still in flight, its later steps started a fresh buffer that `finish_episode` marked `episode_complete`. Evicted ids are remembered and their tail is dropped. The cap stays at 8 |
| S4-26 ([#168](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/168)) | **Fixed.** A restore refused by `build_algo`'s post-restore checks dropped the algorithm without `stop()`, so its actors kept their CPUs. It is stopped before the error propagates |
| S4-27 ([#169](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/169)) | **Fixed.** With `ray_log_encoding` set, package logs stopped propagating to root even when Ray applied no `LoggingConfig`, so nothing printed them. Propagation is restored on those paths |
| S4-28 ([#170](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/170)) | **Fixed.** Text that described the code wrongly: `visualize.run_all --help` printed no description; the probe's rank table always claimed the default threshold; the tape comment named the wrong end; a duplicated comment block in `state_helper`; `effective_rank` called itself the papers' rank (it is a threshold rank, [23](23_probe_harness.md) §8); the pretrain docstring's probe command could not find the module; nine comments pointed the action mask at [06](06_action_space.md) §6 rather than §7 |

---

## From the 2026-10-07 review

The R-items from that review that are fixed. The ones that were documented or guarded rather than
fixed are open decisions in [15](15_findings_and_recommendations.md).

| ID | Finding |
|---|---|
| R-1 ([#171](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/171)) | **Fixed** ([17](17_changelog.md) §86). Tick rule: a clearing price above the pre-batch mid is buyer-initiated, below it seller-initiated, equal repeats the last direction (buyer before any). Measured: 294 buyer / 267 seller on both-in-batch trades, was 519 / 0. Was: In batch clearing, a trade whose two sides both arrived in the batch always records the buyer as initiator, which would bias `signed_volume` and `trade_direction`. Who "initiates" inside a call auction is a design choice |
| R-2 ([#172](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/172)) | **Fixed** ([17](17_changelog.md) §86). The bankrupt trader's orders are pulled in `liquidate()`, before the observation is built, in every mode. Was: With `liquidation: "off"`, a bankrupt trader's orders are cancelled inside `set_step_outputs`, so the observations and the action masks of one step may be built from two different books |
| R-3 ([#173](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/173)) | **Fixed** ([17](17_changelog.md) §86). At NAV <= 0 the close is tried at the touch (that level only) before ADL; `maintenance_margin: 0` is refused. Was: With no margin cushion (`maintenance_margin: 0`, or NAV run out), the bankruptcy band never reaches the opposite touch at a mid mark, so the whole forced close may go to ADL |
| R-4 ([#174](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/174)) | **Fixed** ([17](17_changelog.md) §86). `max_nav` is raised once per step, after the cascade (`Account.update_peak`), not by every `cal_nav`. Was: Intermediate re-marks during a liquidation cascade may ratchet `max_nav`, charging drawdown against a peak never seen at a step boundary. Touches the reward |
| R-5 ([#175](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/175)) | **Fixed** ([17](17_changelog.md) §87). The stamp records how wide each action head is (`action_sizes`), derived from the config the space is built from and held equal to a real env's space by a test. Was: The checkpoint layout stamp (S4-19) does not record `n_hist` or `max_own_orders`. `n_hist` is already a structural restore key, so only `max_own_orders` may be uncovered |
| R-6 ([#176](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/176)) | **Fixed** ([17](17_changelog.md) §86). A failed snapshot after `add_module` calls `remove_module` with the corrected mapping function; a second failure only logs. Was: A champion snapshot that fails and is rolled back may stay in remote env runners' policy-mapping function |
| R-8 ([#178](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/178)) | **Fixed** ([17](17_changelog.md) §86). Eviction moved to after a successful snapshot (make-before-break); a failed snapshot leaves the league whole. Was: A full league evicts its oldest champion before taking a snapshot that can fail, so a failure shrinks the league. [08](08_self_play_league.md) documents the ordering as load-bearing, so a change must keep its constraints |
| R-9 ([#179](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/179)) | **Fixed** ([17](17_changelog.md) §87). `train()` holds `chkpt/.run.lock` (run id, pid, host); a second live run on the folder is refused with the way out, a stale lock is taken over. Was: Concurrent runs share one checkpoint tree and can overwrite each other's saves. Sharing is documented as deliberate |
| R-10 ([#180](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/180)) | **Fixed** ([17](17_changelog.md) §87). `episode_max_live_episodes` (config, floor 8) replaces the literal; the run raises it to `num_envs_per_env_runner`. Was: **[verified]** The episode recorder's live-episode cap is 8 and the callback never sets it, so a runner with more concurrent sampled episodes drops the extra ones (S4-25 stopped them being written as fragments). Tying the cap to `num_envs_per_env_runner` is the open half |
| R-13 ([#183](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/183)) | **Fixed (flag, off)** ([17](17_changelog.md) §87). `cbp_compensate_mean` moves the mean contribution into the next bias; off by default so the paper's rule, which `docs/16` §16.13 measured, stays the baseline. Was: Continual Backprop zeroes a replaced unit's outgoing weights without moving its mean contribution into the next layer's bias, so the output jumps; a saturated tanh unit scores low under `overall` utility and goes first |
| R-14 ([#184](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/184)) | **Fixed** ([17](17_changelog.md) §87). The hook merges a layer's statistics across the calls of one step, row-weighted and exact. Was: The CBP activation hook keeps only the last forward call's statistics: MoE experts run once per top-k slot, and JEPA runs the trunk a second time on the masked context |
| R-15 ([#185](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/185)) | **Fixed** ([17](17_changelog.md) §87). `JEPARLModule.compute_values` runs with the objective off; EMA steps equal optimiser steps (6 and 6, was 8 and 6). Mask sampling has its own generator. Was: With `vf_share_layers: true`, JEPA's `compute_values` pass may run the auxiliary objective and an extra EMA step |
| R-16 ([#186](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/186)) | **Fixed** ([17](17_changelog.md) §87). `order_slot` added to the world model's action embedding; a test holds the embedded heads equal to `ACTION_KEYS`. Was: The JEPA world model's action embedding omits the `order_slot` head |
| R-17 ([#187](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/187)) | **Fixed** ([17](17_changelog.md) §87). `from_obs_space` raises `AmbiguousObsLayout` for a width that fits two modes; the run's `book_mode` reaches the encoder and the probe (`--book-mode`), and the probe builds its encoders against the corpus layout. Was: **[verified]** `build_encoder_config` calls `ObsLayout.from_obs_space` without the run's `book_mode`, so some widths are ambiguous (grid at `n_hist` 11 has the width of levels at 8); `train.probe` likewise builds encoders from the default env config rather than the corpus's layout. The fix threads `book_mode` through four files |

---

## Resolved before the register

Recorded so nobody re-files them. Each was a real defect at the time.

| Was | Now |
|---|---|
| `custom_model: "model_disc"` never registered ([#190](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/190)) | `ModelCatalog` is not read on the new stack; the indirection was removed. Trainable modules use the default PPO module via `DefaultModelConfig` |
| Training code straddled two RLlib API stacks ([#191](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/191)) | Entirely new-API-stack. `PolicySpec` wiring replaced by `MultiRLModuleSpec`; the broken `CustomRLModule` (which read `config.action_space.n` against a `Dict` space) and dead old-stack modules deleted |
| Champion trigger read `policy_reward_mean` / `custom_metrics` ([#192](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/192)) | Reads `module_episode_returns_mean`, already keyed by real `ModuleID` |
| The printed policy map used different logic than the real mapping ([#193](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/193)) | `on_episode_start` calls `env_runner.config.policy_mapping_fn` — the authoritative one |
| Champion snapshots never reached the EnvRunners ([#194](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/194)) | Force-pushed with a `WEIGHTS_SEQ_NO`-free `set_state`, with the reasoning in a comment |
| Matchmaking seeded from salted `hash()` ([#195](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/195)) | Seeds from `zlib.crc32` — reproducible across processes |
| Evicted champions leaked memory ([#196](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/196)) | `Algorithm.remove_module` is called |
| Per-episode pickles were unconditional ([#197](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/197)) | Replaced by a bounded Parquet record on a background thread; `episode_data_dir=None` / `--no-episode-data` now disables the accumulation as well as the write (S4-9) |
| `episode_data/` was untracked noise ([#198](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/198)) | In `.gitignore`, both paths, with an explanatory comment |
| **No CI** — dead `.travis.yml` ([#199](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/199)) | GitHub Actions on Python 3.12: a `test` job (unit → random smoke run → RLlib integration) and a `packaging` job that builds the wheel and uses it from a clean venv outside the checkout |
| `setup.py` broken for non-editable installs ([#200](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/200)) | ~~`find_packages()`, real `install_requires` and extras, `__init__.py` files added~~ **Premature.** That pass fixed package discovery and left two defects that still made every non-editable install fail: `install_requires` did not name `ray[rllib]`, `scikit-learn` or `six` (S3-6), and no config JSON was in the distribution at all (S3-18). Both are fixed now, and a wheel built from this tree has been installed into a clean environment and used to construct an env |
| `observation_space`/`action_space` were plain dicts ([#201](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/201)) | `observation_spaces`/`action_spaces` (plural, new stack) plus per-agent getters; agent ordering stable across processes |
| Trainable network was an 8-unit bottleneck ([#202](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/202)) | `fcnet_hiddens=[256,256]`, `tanh`, `vf_share_layers=False` |
| `test_modify_order_price_change` was `@unittest.expectedFailure` ([#203](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/203)) | A normal passing test; the no-crossed-book invariant holds on every modification path |
| `CDA_env_rand.py` used positional constructor args ([#204](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/204)) | Takes a config dict, keys actions by agent ID, samples from the env's own action space, and runs in CI |

---

## The recommended sequence of work

The order of work the register recommended, kept as it was ticked off. Every struck-through item
is done; the items still open are listed in [15](15_findings_and_recommendations.md).

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
4. ~~Normalise observation feature scales (S2-2)~~ — **done**

**Phase 2 — make the problem well-posed (≈3–4 days)**
5. ~~Add the private-state observation block (S1-2); delete the uniformity test~~ — **done**,
   9 floats per agent then; the agent's own resting orders and the action mask have since joined
   it (41 floats, S3-24)
6. ~~Terminate and flatten bankrupt agents (S2-4)~~ — **done**
7. ~~`size_mean → Box(0,1)`; scale or drop `size_sigma`~~ — **done** (S3-1, S3-2, S3-3): one `size` head
8. ~~Positive decaying `entropy_coeff`; raise `std_dev_multiplier`; refuse zero-trade champions (S3-11)~~ — **done**
9. ~~One `np.random.Generator` threaded through the env (S3-5)~~ — **done**. All three draws read
   `self.np_random`; `test_seeding.py` pins it, and `scikit-learn` left with the fix

**Phase 3 — fix the observation pipeline (≈3 days)**
10. ~~Normalize the whole stack by the current `M_t`; expose `M_t / M_{t−1} − 1` (S2-6)~~ — **done**
11. ~~Finish the tape loop into trade-flow features; wire in `helper.py`'s order imbalance (S2-7)~~ —
    **done**; the imbalance arrived as `signed_volume` (S4-1)
12. ~~Occupancy mask (S3-14); the fixed tick-offset grid (S3-15)~~ — **both done**; the grid is
    the default layout and the level view is kept for comparison

**Phase 4 — market realism (≈3 days)**
13. ~~Maker/taker fees in bps inside settlement (S2-3)~~ — **done**, opt-in (both rates 0)
13a. ~~Price a market order's whole sweep in the cash check (S2-14)~~ — **done**, and batch clearing
    re-clears without the orders its owners cannot pay for. The loss a cover realises is reserved too
    (S2-15)
14. ~~Self-match prevention; mark to mid (S2-5)~~ — **done**
15. ~~Per-episode desk metrics through `metrics_logger` (S3-9)~~ — **partly done**: NAV spread,
    drawdown, inventory, trade count and maker ratio are metrics ([11 §1.2](11_logging_and_observability.md)).
    Sharpe and max-drawdown-over-the-episode still need the NAV trajectory, which the per-step
    record now holds

**Phase 5 — engineering hygiene (≈3 days)**
16. ~~`logging` replaces `print`; a conservation violation stops the run (S2-8)~~ — **done**. The
    stop moved to the driver once [11 §5.2.1](11_logging_and_observability.md) found that raising in the episode
    hook stops nothing at `num_env_runners > 0`
17. ~~Fix `install_requires`; drop `sklearn` and the unused `import ray` (S3-6)~~ — **done**, with
    a `packaging` CI job so an installed copy is exercised rather than assumed. `six` is declared
    rather than dropped, because it is imported from the off-limits `envs/orderbook/`
18. ~~`sys.exit` → `raise ValueError` (S3-7)~~ — **done**
19. Delete dead code (S4-1..4) — the `g_store` trio (S4-1) and the `build_algo` restore path (S3-8) are done
20. Add `ruff` / `black` / `pre-commit` / `pytest-cov` — `ruff` and `pytest-cov` are configured
    (S4-6); a formatter and `pre-commit` are not

---

## Fixed problems recorded in other documents

Defects that the topic documents described and that were fixed without a register ID of their
own, or with more detail than the register entry kept. Grouped by the document that described
them; the document now links here.


### From 01 · Overview

Source: [01_overview.md](01_overview.md).
Bare section numbers (§) and "this document" in this group refer to [01](01_overview.md).

#### 01 §1.6 · A plain install failed on first import

Register: [S3-6](29_fixed_issues.md#s3-6--install_requires-does-not-match-the-imports-verified-fixed), [S3-18](29_fixed_issues.md#s3-18--the-config-tree-was-not-in-the-built-distribution-verified-fixed)

`pip install gym_continuousDoubleAuction` **without** extras used to fail on first import, because
`install_requires` did not name `ray[rllib]` or `six` and no config JSON reached the wheel. Both
are fixed (S3-6 and S3-18), and the `packaging` CI job builds the wheel, installs it into a clean
venv outside the checkout, and steps an env there.

### From 02 · Architecture

Source: [02_architecture.md](02_architecture.md).
Bare section numbers (§) and "this document" in this group refer to [02](02_architecture.md).

#### 02 §2.5 · Per-agent terminateds were rebuilt as all-False

Register: [S2-4](29_fixed_issues.md#s2-4--bankrupt-agents-are-never-terminated-verified-fixed)

`set_all_done` rebuilt `terminateds` and `truncateds` as all-`False` dicts and set only `__all__`,
so a bankrupt agent was never individually terminated and kept being stepped for the rest of the
episode.

#### 02 §2.6 · is_render defaulted to true

Register: [S4-7](29_fixed_issues.md#s4--minor)

- **`is_render` defaults to `True`.** `TrainConfig` overrides it, and `render()` is additionally
  gated on the logger being enabled for DEBUG — so a direct `continuousDoubleAuctionEnv({...})`
  at the default INFO level builds no tables at all. Raise the level and it dumps the book, the
  tape and every account on every step.

#### 02 §2.7 · tick_size was two independent values

Register: [S3-4](29_fixed_issues.md#s3-4--the-order-books-tick_size-is-inert-verified-fixed)

`tick_size` used to be two independent values — a hardcoded `min_tick = 1` in `Action_Helper` that
actually drove prices, and an `OrderBook` argument that was stored and never read — so setting the
key changed nothing anywhere. Two of the three halves are fixed:

| | Then | Now |
|---|---|---|
| `Action_Helper.min_tick` | hardcoded `1` | the `tick_size` config key — this is what builds every price |
| `reset()` | `OrderBook(1, ...)` | `OrderBook(self.tape_display_length)` — the book takes no tick |
| `OrderBook.tick_size` | stored, never read | **deleted** (2026-09-18); `OrderBook(0.0001, 10)` is a `TypeError` |

There is no rounding or tick validation anywhere in the matching path; the book's parameter makes
it look as though there is. The recommendation is to **delete** the book's copy rather than
enforce it, because there is exactly one price producer in the system and `_set_price` emits
on-grid prices by construction. It is deferred only because `envs/orderbook/` is off-limits to
changes. See [18_configuration.md](18_configuration.md) §6 and S3-4 in
[15_findings_and_recommendations.md](15_findings_and_recommendations.md).

#### 02 §2.10 · Four things worth knowing that are no longer true

Before the fixes, 02 warned about these before anyone touched the env:

- **Per-agent `terminateds` are rebuilt as all-`False` every step.** Only `__all__` is ever set,
  so a single bankrupt agent keeps being stepped for the rest of the episode (S2-4).
- **Rendering has side effects.** `_render` nulls `model_actions` / `LOB_actions` /
  `shuffled_actions` and clears `seq_trades` and `seq_order_in_book`, so toggling `is_render`
  changes state evolution (S4-7).
- **The bare `import ray` in the env** (S3-6) is gone; the `MultiAgentEnv` import is the real
  dependency.
- **A fair amount of commented-out dead code** (old `step`, old action space, old `modify_order`,
  old space getters) was left in place as inline history — roughly 200 LOC (S4-4).

### From 03 · Matching Engine

Source: [03_matching_engine.md](03_matching_engine.md).
Bare section numbers (§) and "this document" in this group refer to [03](03_matching_engine.md).

#### 03 §3.1 · `modify_order` updated the book in place

Register: none (the test that pinned it is in [Resolved before the register](29_fixed_issues.md#resolved-before-the-register), #203).

`OrderBook.modify_order` originally updated price and quantity **in place** in the `OrderTree`
without re-running the matching engine. A bid could therefore be modified to a price above the
best ask and simply *sit there*, leaving the book crossed — a direct violation of double auction
mechanics. Separately, the trader's cash and hold balances were not adjusted for trades that
occurred *during* a modification, so account balances drifted.

#### 03 §4 · Invariant 1 was documented as partial

Register: none.

> **Correction to the older documentation.** `docs/matching_engine.md` §4 stated that invariant 1
> was "only partially satisfied" because `test_modify_order_price_change` was marked
> `@unittest.expectedFailure`. That is no longer true — there is no `expectedFailure` anywhere in
> the repository, and the test asserts `get_best_bid() == Decimal('101')` and passes. Invariant 1
> holds on every modification path.

#### 03 §5 · `sys.exit` in the matching engine

Register: [S3-7](29_fixed_issues.md#s3-7--sysexit-used-for-error-handling-in-the-matching-engine-fixed).

Until 2026-09-18 these were `sys.exit(...)`. `SystemExit` derives from `BaseException`, not
`Exception`, so inside a Ray EnvRunner actor it was not caught by ordinary handlers: it killed the
worker, RLlib marked it unhealthy and restarted it, and the run degraded rather than failing with a
usable traceback. None of the six is reachable from the action layer — decoded size is
`rint(abs(N(...))) + min_size ≥ 1` — but they were one action-space change away, and they are
what a test can now assert (`test_orderbook_new.py::TestMalformedInputRaisesInsteadOfExiting`).
Tracked as S3-7 in [15_findings_and_recommendations.md](15_findings_and_recommendations.md), fixed.

### From 04 · Accounting

Source: [04_accounting.md](04_accounting.md).
Bare section numbers (§) and "this document" in this group refer to [04](04_accounting.md).

#### 04 §1 · The basis was a rounded quotient

Register: [S3-23](29_fixed_issues.md#s3-23--nav-conservation-is-exact-only-to-decimal-context-rounding-verified-fixed).

Until 2026-09-18 the ledger stored `VWAP = cost / size` and rebuilt the basis as `size × VWAP`; the
quotient rounds at the 28-digit context whenever it does not terminate, and `mark_to_mkt` then
multiplied it back in two independently rounded products, so conservation held only to about one
unit in the 22nd decimal place. `cost_basis` is now primary.

#### 04 §3 · Closing escrow counted as spent

Register: [S1-5](29_fixed_issues.md#s1-5--the-cash-check-is-bypassable-position-is-not-bounded-by-capital-verified-fixed).

Treating escrow held against a trader's own closing orders as spent refused two thirds of all
orders at `init_cash` 100,000 under random play ([16](16_verification_log.md) §16.18). It is now
spendable (`_closing_escrow`, capped at `|net_position|`).

#### 04 §8 · A bankrupt trader's position stayed open

Register: none (liquidation was added 2026-09-19).

Until 2026-09-19 the only risk control on an open position was the solvency gate: at `nav <= 0`
the trader was terminated and its resting orders pulled, but its **position stayed open** and
`mark_to_mkt` kept marking it to the end of the episode. A short has no loss ceiling, so a bankrupt
short went on losing — measured in `CDA_train.ipynb` at −1.9M against a 1M start — and every
contract of that loss was a gain for the agents on the other side, paid by a counterparty that
could not act and whose policy was never charged for it. Liquidation
([04](04_accounting.md) §8) closes the position while its collateral still covers the close.

### From 05 · Observation Space

Source: [05_observation_space.md](05_observation_space.md).
Bare section numbers (§) and "this document" in this group refer to [05](05_observation_space.md).

#### 05 §7.3 · The tape loop that built nothing

Register: [S2-7](29_fixed_issues.md#s2-7--no-trade-flow-information--the-tape-loop-is-dead-code-verified-fixed)

The loop in `set_agg_LOB` as it stood before the fix:

```python
if self.LOB.tape != None and len(self.LOB.tape) > 0:
    num = 0
    for entry in reversed(self.LOB.tape):
        if num < self.LOB.tape_display_length:
            # tempfile.write(...)
            num += 1
        else:
            break
```

`entry` is never used. It *looked* like it was building tape features; it built nothing. This was
the largest missing *public* feature, and the placeholder loop suggests it was intended to be there.

#### 05 §7.5 · A bare square root

Register: [S2-2](29_fixed_issues.md#s2-2--unnormalised-observation-scales-saturate-the-tanh-mlp-verified-fixed)

A bare `sqrt` stabilised variance *within* the size block and left the cross-block mismatch
untouched — arguably worse than no normalisation, because the documentation asserted the
observation was normalised. The 22 well-scaled features (prices and the two scalars) fed the same
linear layer as the 20 size features and were up to ~250× smaller, so the price half was close to
invisible at initialisation and the size units saturated `tanh` immediately.

#### 05 §6 · Feature scales before the fix

Register: [S2-2](29_fixed_issues.md#s2-2--unnormalised-observation-scales-saturate-the-tanh-mlp-verified-fixed)

Before [17](17_changelog.md) §37.4, sizes were a bare `sqrt(V)` reaching **±47** beside prices of
±0.4, a standard-deviation ratio of **220×**, and `log_mid` was an uncentred 4.55–4.64. Two earlier
probes on that code measured maxima of 47.01 and 51.19 for the size block; the absolute numbers
moved with the book and the ratio did not. The negated-ask convention also prevented weight sharing
between the two sides, which is part of why S4-17 made both sides positive.

### From 06 · Action Space

Source: [06_action_space.md](06_action_space.md).
Bare section numbers (§) and "this document" in this group refer to [06](06_action_space.md).

#### 06 §4 · The size heads that were degenerate

Register: [S3-1](29_fixed_issues.md#s3-1--half-the-size_mean-action-range-is-a-no-op-verified-fixed),
[S3-2](29_fixed_issues.md#s3-2--the-size_sigma-head-is-inert-verified-fixed),
[S3-3](29_fixed_issues.md#s3-3--size-is-sampled-by-the-environment-outside-the-policys-log-prob-verified-fixed)

Until the action layout moved to version 4 the size was two heads, `size_mean` and `size_sigma`,
and `_set_size` turned them into a size with
`rint(abs(N(mean_mul × size_mean, size_sigma)))`, drawn from `self.np_random`. The verified outputs
behind the three findings:

**Half the `size_mean` range was a no-op (S3-1).** The `abs()` folded the distribution; same RNG
seed:

```
mean=+0.5 -> [250.0, 250.0, 250.0, 250.0, 250.0]
mean=-0.5 -> [250.0, 250.0, 250.0, 250.0, 250.0]   identical: True
```

The optimum was bimodal at `±m`, which fights the unimodal Gaussian policy: the head is pushed
toward mean 0 by symmetric gradients, and mean 0 means *minimum* size. Fixed first by declaring the
range `Box(0, 1)` (action layout 3), then by the single head.

**The `size_sigma` head was inert (S3-2).** `sigma` was an **absolute** standard deviation while
means were 49.5·|m| (market) or 499.5·|m| (limit); 4,000 limit sizes at `size_mean = 0.5`:

```
sigma=0.0 -> std 0.00 (all 250);  sigma=0.25 -> 0.37;  sigma=0.5 -> 0.58;  sigma=1.0 -> 1.05
```

Deleted rather than rescaled: with the size sampled by the policy there is nothing left for a sigma
to control.

**Environment-side sampling broke the log-probability (S3-3).** One action, eight env seeds, eight
draws:

```
size_mean=0.5, size_sigma=1.0 -> sizes [251, 251, 251, 253, 250, 250, 252, 251]
```

The spread was small because sigma was small, but the structure was wrong: advantage variance that
no amount of data removes.

`_set_price` also carried a `max_price` parameter its body never read; it was removed.

### From 08 · League-Based Self-Play

Source: [08_self_play_league.md](08_self_play_league.md).
Bare section numbers (§) and "this document" in this group refer to [08](08_self_play_league.md).

#### 08 §5.2 · The ordering constraints as bugs

Register: none; see also [09 §4](#09-4--bugs-that-only-existed-at-non-default-values).

- **Constraint 1.** Reading weights through `learner_group._learner` raised on every snapshot
  attempt under a remote LearnerGroup and was swallowed by the broad `except`, leaving the league
  permanently empty while printing one error line per iteration. That same broad handler masked
  the `learner_group._learner is None` bug for an entire training run.
- **Constraint 4.** Without constraint 4, the champion *acting in the environment* stays at its random initialisation
for the entire run while the trained snapshot sits unused in the LearnerGroup. Combined with the
`MultiRLModuleSpec` issue in §2, this meant **no self-play was taking place at all** before the
migration.

### From 09 · Distributed Training: `num_env_runners` and `num_learners`

Source: [09_distributed_training.md](09_distributed_training.md).
Bare section numbers (§) and "this document" in this group refer to [09](09_distributed_training.md).

#### 09 §4 · Bugs that only existed at non-default values

Register: none; [08 §5.2](#08-52--the-ordering-constraints-as-bugs) has the snapshot-side detail.
§3.1 below means [09](09_distributed_training.md) §3.1.

Every bug in this section has been fixed in the current tree — the commit is named inline, and
each has regression coverage that runs at the non-default value. They are documented because the
structural gap that produced them has not gone away.

Both settings default to `0` in `TrainConfig`, which is the one configuration where everything
lives in a single process. Every bug below was invisible there and only appeared once a setting
went to `1` or more — because that is what created a second process with its own stale copy of
something the driver mutates.

##### 4.1 `num_env_runners > 0`: champion pool published one snapshot late

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

##### 4.2 `num_learners > 0`: champion snapshotting failed on every attempt

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

##### 4.3 The pattern

All three bugs (this document's two, plus the `WEIGHTS_SEQ_NO` one found earlier in the
migration) trace to the same root cause: code written and tested only at
`num_env_runners=0, num_learners=0`, where the driver's objects and the "remote" objects are
literally the same object, so nothing about process boundaries could go wrong.

**Any new code touching `SelfPlayCallback` or champion snapshotting should be exercised against
both `TestLeagueWiringRemoteEnvRunners` and `TestLeagueWiringRemoteLearner`, not just the
default-config tests, before being considered correct.**

#### 09 §5 · The batch scaled with `num_learners` (#299)

Register: none (GitHub issue #299, fixed in #303).

Before #299 was fixed, `train_batch_size` was passed to RLlib per learner, so N learners meant N
times the episodes per iteration and an entropy decay N times shorter. `train_batch_size` is now
the whole iteration's batch and is divided across the learners ([17](17_changelog.md) §92).

### From 10 · Testing

Source: [10_testing.md](10_testing.md).
Bare section numbers (§) and "this document" in this group refer to [10](10_testing.md).

#### 10 §6.2.2 · The critic test was an xfail

Register: [S1-1](29_fixed_issues.md#s1-1--ppos-critic-receives-zero-gradient-verified-fixed).

`test_the_critic_actually_explains_something` was a strict xfail until S1-1 was fixed; the fix made
it XPASS, which failed the build exactly as the marker's reason said it would, and the marker was
then deleted. The suite has had no xfail since.

#### 10 §1.1 · `test_modify_order_price_change` was documented as an expected failure

Register: none ([Resolved before the register](29_fixed_issues.md#resolved-before-the-register), #203).

> **Correction.** `docs/testing.md` described `test_modify_order_price_change` as
> `@unittest.expectedFailure`, "documenting a known limitation rather than asserting
> correctness". There is no `expectedFailure` anywhere in the repository; the test asserts and
> passes.

#### 10 Side effects · Test output was committed

Register: none ([Resolved before the register](29_fixed_issues.md#resolved-before-the-register), #198).

The two `episode_data/test_ep_*.pkl` files an earlier revision noted as committed — output of the
old tests, not fixtures anything read — are gone from the repository.

#### 10 §7 · Why the packaging job exists

Register: [S3-6](29_fixed_issues.md#s3-6--install_requires-does-not-match-the-imports-verified-fixed), [S3-18](29_fixed_issues.md#s3-18--the-config-tree-was-not-in-the-built-distribution-verified-fixed).

Every CI step installs the full `requirements.txt` from a checkout, which is exactly why both halves
of S3-6 / S3-18 went unnoticed — `install_requires` did not name `ray[rllib]` or `six`, and no config
JSON reached the distribution at all, so an installed copy raised `FileNotFoundError` on import
while CI stayed green.

> **Correction.** `docs/known_issues.md` §4 and `docs/testing.md` §7 stated that "nothing enforces
> the test suite — there is no CI". That has not been true since the Ray 2.56 migration.

#### 10 §8 · Closed test gaps

Register: none (several have their own issues, linked in the table).

Rows struck from the gaps table in [10](10_testing.md) §8 once each was closed. The parts left open
are still rows there.

| Gap | How it was closed |
|---|---|
| ~~**The learning-signal assertion is an xfail, not a guard**~~ | **Closed.** S1-1 is fixed and the `vf_explained_var >= 1e-3` threshold in `integration/test_progress_and_vf.py` is a live assertion — see §6.2.2. What is still unchecked is narrower than it was: `vf_loss` saturation, and "returns improve" across iterations. |
| ~~**`test_accounting.py::test_insufficient_funds` is an empty `pass`**~~ | **Closed.** It asserts the refusal, the untouched ledger and the approved affordable half. |
| ~~**No information-content tests for the observation**~~ ([#205](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/205)) | **Closed.** `test_obs_information.py` (30 tests, both book modes) asks what the observation can tell apart: different resting prices, sizes and sides, a trade in the flow fields, accounts by owner, and each information-carrying field moving under random play. Reintroducing the dead tape loop (S2-7), dropping the ask row from the grid or zeroing the private block fails 4, 2 and 8 of them. It does not say the observation is *sufficient* to trade well; that is #206. |
| ~~**`test_shared_history_multi_agent_uniformity` encodes a defect as a requirement**~~ | **Closed.** S1-2 is fixed and the test is replaced by a pair that splits the claim — the book prefix stays shared, the private tail must not be. See §4.2. |
| ~~**Reproducibility is untested**~~ | **Closed.** `test_seeding.py` (11 tests) asserts two identically-seeded episodes match and two differently-seeded ones do not, across all three randomness sources — and does it while seeding the *global* NumPy stream to different values, so it cannot pass for the wrong reason. What remains untested is reproducibility of a whole multi-worker *training run*, which is a different claim. |
| ~~**Edge cases in league matchmaking**~~ ([#207](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/207)) | **Closed.** `test_matchmaking_edges.py` (20 tests). It found one: all-zero weights gave NaN probabilities and a crash at the first episode; the pool now draws uniformly with one warning, and negative, non-finite or non-numeric weights are refused by name at construction. |
| ~~**No property-based tests**~~ | **Closed.** `test_orderbook_properties.py` (§2.5). Its first run found two defects the example suite had not, which is the argument for it. |
| ~~**No coverage measurement**~~ ([#208](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/208)) | **Closed: measured and thresholded** (by #148). `pytest --cov` (pytest-cov in the `dev` extra, scoped by `pyproject.toml`) on the unit suite: **86.4%** line-and-branch over `envs/` and `train/` (79.1% when first measured), (**86.9%** once `visualize/`, no longer omitted, is measured too, #211), with `fail_under = 84` so the run fails below it and `__main__` guards excluded. Least covered: `probe/__main__` (0%, run by hand), `cbp_learner` (32%, its tests are in the integration suite), `CDA_rand` (18%, the CI smoke run), `evaluate` (64% from the unit half; the integration test covers the rest). The floor applies where `--cov` is run; CI does not run it (the workflow cannot be edited from here). |
| ~~**No performance regression test**~~ ([#209](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/209)) | **Closed.** `test_speed_regression.py` (4 tests): budgets are multiples of a calibration loop timed on the same machine (about 10x over today's cost), and two checks compare the code with itself at two sizes. An O(n) scan per insert fails two; a 20 ms slower step fails the third. |
| ~~**`envs/orderbook/test/example.py` and `genOrders.py`**~~ ([#210](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/210)) | **Closed.** `example.py` had been failing its own string asserts (the printed form had drifted) and `genOrders.py` was Python 2. Both are deleted; `test_orderbook_scripts.py` asserts the example's outcomes and checks a seeded shadow model against the book. |
| ~~**`visualize/` is almost entirely untested**~~ ([#211](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/211)) | **Closed.** `test_visualize_scripts.py` (32 tests) runs the loader, the six chart scripts, `run_all` and both inspectors on synthetic runs and asserts on the data each plots. Changing the complete-episode filter, a column name, the snapshot slice or an output filename each fails it. `visualize/` is now measured in coverage (it was omitted). |

### From 11 · Logging and observability

Source: [11_logging_and_observability.md](11_logging_and_observability.md).
Bare section numbers (§) and "this document" in this group refer to [11](11_logging_and_observability.md).

#### 11 §0 · No logging framework, and a conservation check that printed

Register: [S2-8](29_fixed_issues.md#s2-8--no-logging-framework-the-callback-prints-42-diagnostics-per-episode--fixed)

**Status.** This used to be the weakest engineering area in the repository: no logging framework
at all, ~86 `print()` calls, and a conservation check that reported a corrupt ledger by printing
`FAILED`. Both are fixed - see §1.3 and §1.5. Coverage was the next gap and is largely closed:
the custom metrics of §1.2 and a typed, queryable per-step record (§1.1). What is left in §2 now needs
new computation rather than aggregation of something already in hand.

#### 11 §1.1 · A short run wrote no episode record

Finished episodes waited for `episode_rows_per_file` rows or for an `atexit` handler, which Ray
does not reliably run when it stops an env runner: a short run wrote nothing (issue #245, changelog
§75). A file is now also written at the end of every sample (`on_sample_end`).

#### 11 §1.1 · The pickled episode record

Register: [S4-9](29_fixed_issues.md#s4--minor)

The per-step record was a `pickle.dump` of the whole episode performed inline in
`on_episode_end`. Five things were wrong with it ([11 §5.2.2–5.2.4, §5.5–5.6](11_logging_and_observability.md)): it
was untyped and executed arbitrary code on load; it ran on the sampling hot path; a failure raised
into the hook, which on a remote env runner restarts the worker; `--no-episode-data` disabled the
write but kept the ~34 MB per episode of accumulation; and it was unbounded.

**The measurement that made the bounds necessary.** At `max_step=4096` and 8 agents a step is 8,314
pickled bytes, so an episode was **~34 MB** — held in memory and then serialised, per episode, per
worker. `runtime_profiles.json` had estimated ~10 MB.

The two `.pkl` files that used to sit committed under `episode_data/` — leftover output from an
older version of `test_nav_callback.py`, not fixtures anything read — have been removed. Nothing
in the repository writes a pickle any more.

#### 11 §1.2 · maker_fill_ratio measured a conservation identity

The first version of the maker share was summed over all agents, which in a closed double auction is
exactly `0.5` in every episode whatever anyone did. A real 3-iteration run reported `0.5000` three
times. The full narrative is in 21 §7 ([29](29_fixed_issues.md#21-7--what-was-found-while-implementing)).

#### 11 §1.4 · The g_store telemetry that could not run

Register: [S4-1](29_fixed_issues.md#s4--minor)

`train/storage/store_handler.py`, `train/logger/log_handler.py` and `train/plotter/plot_handler.py`
were ~270 LOC that looked like a telemetry pipeline and were a broken one: all three depended on a
detached Ray actor named `g_store` that **was never created anywhere**, so every entry point into
them would have raised at call time. They have been deleted, along with the now-orphaned
`plot_defaults` group in `tunable_constants.json` that only `plot_handler` read. Git history has
them if the design is ever wanted back.

#### 11 §1.5 · Raising in the episode hook stopped nothing

Register: [S2-8](29_fixed_issues.md#s2-8--no-logging-framework-the-callback-prints-42-diagnostics-per-episode--fixed)

Raising inside `on_episode_end` worked only at `num_env_runners=0`: the hook runs on the env
runner, so the raise arrived as a `RayTaskError` from `sample()`, and `restart_failed_env_runners`
(True by default) made `EnvRunnerGroup` log it through Ray's own logger and restart the actor -
`algo.train()` returned normally. The raise also destroyed the evidence, since
`synchronous_parallel_sample` asks each runner for `(sample(), get_metrics())` in one call. See
[11 §5.2.1](11_logging_and_observability.md). `NavConservationError` subclasses `AssertionError`, so anything
written to catch the old behaviour still does.

#### 11 §1.5 · A float check that could not resolve its tolerance

Register: [S3-9](29_fixed_issues.md#s3-9--no-risk-adjusted-performance-metrics-fixed)

`nav_tolerance` was once credited with absorbing a `float()` round trip. That round trip was harmless
at the default `init_cash` — but above `init_cash ≈ 1e10` it made the check unable to resolve this
very tolerance, passing corrupt ledgers silently. See [16 §16.10](16_verification_log.md).

#### 11 §1.9 · The run narrative lived only in scrollback

§1.6 gave the run a machine-readable history and §1.7 gave the step one, but the log itself was
still written only to stdout. So a finished run left its *numbers* on disk and its *narrative* in
scrollback — the per-episode NAV tables, the league statistics, and the ERROR that immediately
precedes a `strict_nav_check` raise. [17 §17](17_changelog.md) records two GPU runs diagnosed
exactly that way, after the fact, from a terminal buffer.

Every process now writes

#### 11 §1.10 · Thread- and process-safety holes

Three of the four holes this section examined were real and none of them was covered by a test.

**Setup, within a process.** Was *not* safe. `get_logger` checks `_configured` and then acts on
it, and `configure()` closes and removes the existing handlers before adding replacements.
`addHandler` is individually atomic under logging's own module lock, but that *sequence* is not:
two threads inside it produce duplicate handlers, or one closes a handler the other is emitting
through. The whole swap is now under `_configure_lock`. The window was small - the first
`get_logger` normally happens at import, which the import lock serialises - but "small" is not a
property a test can hold you to.

Three of those were previously weaker than they looked:

* **A pid is not a unique key.** It is unique per *node*. On a multi-node run with `log_base_dir`
  on a shared filesystem - NFS, or the Drive mount Colab uses - two workers on different nodes can
  hold the same pid and open the same `run.<pid>.log`, which is the exact rotation race the
  per-worker name exists to prevent. The name now carries Ray's worker id, which is unique
  cluster-wide, behind the pid, which is what the `pid=` field of each line matches. Ray is read
  out of `sys.modules` rather than imported: importing it here would make every consumer of the module (`--help` included) pay for ray, and
  would put the import ahead of `configure()` and `runtime.apply_env_vars()`, which `main()` runs
  before `ray.init`.
* **The driver's own files were not covered at all.** `run.log` carries no pid, and `log_base_dir`
  defaulted to a fixed `results`, so two concurrent runs - or a notebook session alongside a CLI
  run - shared both it and `progress.jsonl`. §1.11 is the fix.
* **The episode record's directory was not covered either.** The episode id kept two *writers*
  apart, which was never the weak part; the *path* was a bare relative string, resolved inside each
  worker against whatever working directory it inherited, and shared by every concurrent run. It is
  absolute and run-scoped now (§1.1, [11 §5.2.3](11_logging_and_observability.md)). The per-writer file naming
  is what lets each process enforce its own byte cap without deleting another's files.

**The `iter=` tag is process-wide, not per-thread.** It was a `ContextVar`, chosen so it would be
per-thread. That was the wrong model twice over: a new thread starts from an empty context, so a
line the driver logged from any thread but the loop read `iter=-` while the process knew the
answer; and a value set inside a Ray actor task is not guaranteed to still be in context for the
next task, which is what §1.12's broadcast needs. It is now a module global - one training loop per
process, so the iteration is a property of the process. Assignment of an int is atomic under the
GIL, so it needs no lock.

#### 11 §1.11 · Two runs wrote into one directory

Everything above keeps the *processes of one run* from colliding. Nothing kept two runs apart:
`log_base_dir` was a fixed `results`, so a second run wrote the same `run.log` and appended to the
same `progress.jsonl`.

Each run now gets

#### 11 §1.12 · Worker lines carried no iteration

§1.9 noted that a worker's lines read `iter=-` because "the worker genuinely does not know which
iteration its episode belongs to", and put recovering that association down as a change to what
RLlib hands the callbacks. That was too pessimistic. The driver knows the number, and
`foreach_env_runner` already reaches every runner; it only had to be sent.

`_broadcast_iteration` does that

#### 11 §1.13 · A dying run left its reason in scrollback

`main()` was `try: train(cfg) / finally: ray.shutdown()`, with no `except`. An unhandled exception
- including the `strict_nav_check` `AssertionError` whose entire purpose is to stop a run loudly
enough to be diagnosed afterwards - unwound to Python's default hook, which writes to `sys.stderr`
outside logging. So `run.log` ended mid-narrative and the reason for the ending was in scrollback,
which is the failure §1.9 exists to fix.

Three things now catch it:

#### 11 §1.14 · The stream handler wrote to stderr

`logging.StreamHandler()` with no argument writes to **stderr**, which is what this package did
while §1.3, §1.9 and `tunable_constants.json` all described it as stdout. It matters:
`python -m gym_continuousDoubleAuction.train.train > run.txt` captured none of the output a run
exists to produce. It is now explicitly `sys.stdout`.

#### 11 §1.6 · No per-iteration record

`train()` calls `algo.train()` directly rather than through `tune.Tuner`, so nothing writes
`progress.csv` or TensorBoard event files. Each iteration's result dict used to be summarised into
one log line and dropped, which left a finished run with checkpoints, scrollback, and no queryable
record of how it got there.

Every iteration now appends

#### 11 §2.1 · vf_explained_var was not logged

Register: [S1-1](29_fixed_issues.md#s1-1--ppos-critic-receives-zero-gradient-verified-fixed)

Done, and no longer on this list: **`vf_explained_var`** — the one metric that exposes the frozen
critic (S1-1), and whose absence is why that defect survived. `_log_iteration` now prints it per
trainable module on every iteration, read from `result["learners"][<module_id>]` and keyed on
`trainable_policy_ids`, since only the modules in `policies_to_train` appear in that block.

`test/integration/test_progress_and_vf.py` asserts in CI that a real run reports it, finite, for
every trainable module. It deliberately does **not** assert `!= 0.0`: while S1-1 was open this
repository reported values around 1e-5, so that assertion would have passed on a critic that was
entirely dead. The substantive threshold (`>= 1e-3`) is what distinguishes them, and it is now a
**live assertion** - it was a strict xfail pinning S1-1, XPASSed on the first run after the fix
exactly as the marker's reason said it would, and the marker was deleted. See
[10 §6.2.2](10_testing.md).

#### 11 §3 · Persistence problems that are gone

Seven things are no longer in this table.

The three about the episode record all went with `pickle` (§1.1): the files are Parquet, so there is
no arbitrary code execution on load; every row carries `run_id`, `iteration` and `wall_time`, so
correlating with training progress is a join rather than a filename sort; and growth is bounded by
`episode_sample_every` and `episode_max_bytes` rather than being off/on.

The other four: logging itself is levelled, attributable, switchable and durable, written to a
rotating file per process as well as stdout (§1.3, §1.9), and the `g_store` dead code is gone
(§1.4); `progress.jsonl` is the per-iteration machine-readable record (§1.6); the run log does not
re-create the unbounded-growth problem it would otherwise have added, because `file_max_bytes` and
`file_backup_count` bound it; and two runs no longer write into each other's files (§1.11) - never
listed here, but the more serious of the two, since a shared `run.log` loses lines to a rotation
race and a shared `progress.jsonl` can interleave two writers inside one JSON line.

#### 11 §3 · Rotation discarded the earliest output first

Issue #216.

`file_backup_count` × `file_max_bytes` caps the run log at 60 MB, which at DEBUG is reached quickly — and it was the start of a run, where divergence usually begins, that was dropped. Fixed by `file_keep_head` ([11](11_logging_and_observability.md) §5.2.5).

#### 11 §4 · Recommended additions that are done

Done, and no longer on this list: `logging` in place of `print`; stopping a run on a NAV
conservation violation with a `nav_conservation_error` metric (§1.5 - the *stop* moved to the
driver, the metric did not); writing each iteration's result dict to `progress.jsonl` (§1.6);
logging `vf_explained_var` per trainable module with a CI assertion behind it (§2.1); and the four
metric calls this section used to sketch, all four of which now exist:

```python
# in on_train_result / on_episode_end - all of these are live
metrics_logger.log_value("champions_promoted", promoted, reduce="sum")
metrics_logger.log_value("mean_agent_drawdown", dd, window=10)
metrics_logger.log_value("pass_action_fraction", n_pass / n_actions, window=10)
metrics_logger.log_value(f"reward_term_var_share_{term}", variance / total, window=10)
```

The shape of this document has changed with them. It used to end "capture is now good, aggregation
is four league-and-NAV metrics"; aggregation is now 28 metrics (§1.2), and what is left is
genuinely different in kind - things that need a *new computation*, not a reduction of something
already in hand.

### From 12 · Perspective: Reinforcement Learning Researcher

Source: [12_perspective_rl_researcher.md](12_perspective_rl_researcher.md).
Bare section numbers (§) and "this document" in this group refer to [12](12_perspective_rl_researcher.md).

The RL researcher's analysis of defects that are now fixed: the argument for why each one mattered
to learning, and the fixes that were proposed against it.

#### 12 §2 · The observation contained no private state

Register: [S1-2](29_fixed_issues.md#s1-2--observation-contains-no-private-state-verified-fixed)

**Was the single biggest flaw.** **[verified]**: all agents received the byte-identical 168-float
vector, at reset and at every step:

```
obs dim per agent: (168,) | distinct obs vectors across agents: 1
```

The observation was built once per step from the public book and broadcast:

```python
states = {f'agent_{i}': stacked_obs for i in range(len(self.traders))}
```

Nothing in the vector encoded:

| Missing | Where it lives | Why the agent needs it |
|---|---|---|
| `net_position` | `Account.__init__` | Sign and size of inventory determine whether a fill opens or closes risk |
| `VWAP` | `Account.__init__` | Entry price ⇒ unrealised P&L direction |
| `nav`, `prev_nav` | `Account.__init__`, re-derived in `Calculate.mark_to_mkt` | **The reward is literally `nav − prev_nav`** |
| `max_nav` | `Account.__init__`, updated in `Calculate.cal_nav` | The drawdown penalty is `0.2·(max_nav − nav)` |
| `cash`, `cash_on_hold` | `Account.__init__`, moved by `Cash_Processor` | Determines which orders `_order_approved` will reject |
| own resting orders | `LOB.bids/asks.order_map` | Modify/cancel actions are meaningless without knowing what is resting |
| agent identity | — | Two agents in the same state cannot differentiate roles |
| `t_step` / time remaining | `continuousDoubleAuctionEnv.step` | End-of-episode inventory liquidation is a different problem than mid-episode trading |

**Consequence.** The reward was a deterministic function of state variables the policy could not
see. That is not "hard to learn", it is **ill-posed**: two states with identical books but opposite
inventory require opposite optimal actions and were indistinguishable to the policy. Nor was it
ordinary partial observability that a recurrent network could paper over: the drawdown term
depends on `max_nav`, a *path functional* over the entire episode. Formally the process was not an
MDP in the agent's observation, and the residual variance was not reducible by any policy over
those observations.

Two secondary effects:

- The `modify` and `cancel` action categories (4 of the 9 category values) were effectively blind.
  `_get_order_ID` silently no-oped if nothing matched. ~44% of the discrete action mass was
  unlearnable.
- Frame stacking (`n_hist=4`) adds *public* temporal context, which is genuinely useful for
  order-flow inference, but it cannot substitute for the private state.

**The proposed fix.** Append a per-agent feature block to the snapshot, normalised against
`init_cash`, and stop broadcasting a single vector:

```python
private = np.array(
    [
        net_position / max_position_scale,
        (nav - init_cash) / init_cash,
        (max_nav - nav) / init_cash,  # current drawdown
        cash / init_cash,
        cash_on_hold / init_cash,
        (VWAP - M) / M if net_position else 0.0,
        resting_bid_notional / init_cash,
        resting_ask_notional / init_cash,
        1.0 - t_step / max_step,  # time remaining
    ],
    dtype=np.float32,
)
```

A ~9-float addition per snapshot, and the single highest-value *structural* change in the
repository at the time; `test_shared_history_multi_agent_uniformity`, which asserted the defect,
had to go with it. What shipped is close to this: 9 private floats normalised by the account's own
`init_nav` ([17](17_changelog.md) §30), later extended to 41 with the agent's own resting orders
and the action mask ([17](17_changelog.md) §47).

#### 12 §3.6 · The reward coefficients were function-local literals

Register: none (fixed alongside [S2-3](29_fixed_issues.md#s2-3--transaction-cost-proxies-are-10⁵-too-small-verified-fixed)).

All five reward constants were function-local literals, with the code comment "Internal defaults,
can be moved to config". They are now `env_config` keys, read from the `environment` group of
`config/train_config.json` (falling back to `config/env_defaults.json` for a bare env), so they are
captured in the checkpoint's config and sweepable by Tune. Making them reachable did not make them
right; the values themselves were fixed by S1-1, S2-1 and S2-3.

#### 12 §4 · The critic could not learn: `vf_clip_param` saturation

Register: [S1-1](29_fixed_issues.md#s1-1--ppos-critic-receives-zero-gradient-verified-fixed)

**This was the single most consequential finding.** RLlib's PPO clips the value-function loss:

```python
vf_loss = torch.pow(value_fn_out - batch[Postprocessing.VALUE_TARGETS], 2.0)
vf_loss_clipped = torch.clamp(vf_loss, 0, config.vf_clip_param)  # default 10.0
```
(`ray/rllib/algorithms/ppo/torch/ppo_torch_learner.py:99-100`)

`TrainConfig` never set `vf_clip_param`, so it stayed at **10.0**, while value targets were
undiscounted-scale NAV sums in the 10⁴–10⁷ range. `torch.clamp` is **flat** above the bound, so
`∂vf_loss_clipped/∂θ = 0` for every sample.

**[verified]**: one real training iteration on the shipped config path (`num_agents=4`,
`num_trained_agents=2`, `max_step=64`, `num_epochs=1`, `minibatch_size=64`):

```
== policy_0 ==
   vf_loss                 10.0             ← pinned at vf_clip_param
   vf_loss_unclipped       13,015,503.0
   vf_explained_var        8.91e-05         ← critic explains ~0% of return variance
   total_loss              9.254            ← 10.0 of which is the constant vf term
   policy_loss             -0.747
   entropy                 8.844
   curr_entropy_coeff      0.0
== policy_1 ==
   vf_loss                 10.0
   vf_loss_unclipped       10,513,565.0
   vf_explained_var        5.42e-05
   total_loss              9.484
   entropy                 7.949
```

`policy_2` / `policy_3` are `RandomRLModule`s and produce no losses, as expected.

Downstream consequences:

1. **GAE degenerated.** RLlib's PPO default was `lambda_=1.0`, so the advantage was already the
   Monte-Carlo return minus `V(s)`. With `V` a constant-ish untrained function, the advantage was
   essentially the raw return.
2. **PPO became REINFORCE with a batch baseline.** Advantages *are* standardised per module in the
   new stack (`GeneralAdvantageEstimation` divides by the batch std), so the update did not
   explode, but the variance reduction a critic exists to provide was entirely absent.
3. **The loss metric was a decoy.** `total_loss ≈ 9.3` looked small and stable; 10.0 of it was a
   constant. `vf_explained_var` was the metric that exposed it, and nothing in the code surfaced it.

**Fixes proposed, in order of preference:**

- **Normalise the reward.** Divide `nav_change` by `init_cash` (or by a running return scale) so
  rewards are O(10⁻³) and returns are O(1). This fixes the critic, the drawdown scaling, and the
  micro-term irrelevance in one change. *This is what shipped, by `acc.init_nav`.*
- **Or** set `vf_clip_param` to something commensurate (e.g. `1e9`), effectively disabling it, and
  add `grad_clip` to control the resulting large gradients.
- **Or** enable a reward-scaling connector / `PopArt`-style value normalisation.

Then **assert on `vf_explained_var`** in the integration suite so the regression cannot recur
silently. That assertion is now live in `integration/test_progress_and_vf.py`.

#### 12 §9 · The prioritised research agenda, as completed

Register: the IDs in the table.

The agenda this document set out. Every item is done.

| # | Change | Effort | Expected impact | Done by |
|---|---|---|---|---|
| 1 | Scale rewards by `init_cash` | S | Critic unblocked | S1-1, by `acc.init_nav`; the `vf_explained_var` guard is live |
| 2 | Add private state to the observation | M | Makes the reward learnable at all | S1-2; own resting orders since S3-24 |
| 3 | Make the drawdown penalty an increment | S | Removes the episode-length-dependent risk tax | S2-1, as a *signed* change ([07](07_reward_function.md) §4.1 on why clipping it would not have) |
| 4 | Re-scale the micro-penalties; express costs in bps | S | Restores the intended incentives | S2-3; real fees opt-in |
| 5 | `size_mean → Box(0,1)`; scale or drop `size_sigma` | S | Recovers half the action range, removes a null control | S3-1 to S3-3, one `size` head |
| 6 | Normalise observation feature scales | S | Removes `tanh` saturation | S2-2 |
| 7 | Terminate bankrupt agents individually | S | Stops zombie transitions polluting returns | S2-4 |
| 8 | `entropy_coeff > 0` with decay; raise `std_dev_multiplier`; refuse champions with ~0 trades | S | Guards against passivity collapse | S3-11 |
| 9 | Normalise the whole obs stack by the current `M_t`; add trade-flow features | M | Makes frame stacking informative | S2-6, S2-7 |
| 10 | Emit size directly as an action | M | Removes unrecorded env-side stochasticity from the ratio | S3-3 |
| 11 | Assert `vf_explained_var > 0` in the integration suite | S | Prevents §4 from silently regressing | S1-1 |
| 12 | Raise γ toward 0.999 or shorten episodes | S | Makes long-horizon strategies expressible | S3-13 (γ 0.999, λ 0.95) |
| 13 | One `np.random.Generator` on the env | S | Reproducibility | S3-5 |
| 14 | Surface rejected / no-op order counts in `infos` | S | Makes the dead-action fraction measurable | S4-14 |

### From 13 · Perspective: Financial Trader / Quant

Source: [13_perspective_financial_trader.md](13_perspective_financial_trader.md).
Bare section numbers (§) and "this document" in this group refer to [13](13_perspective_financial_trader.md).

The trader's view of the market model as it was before the realism fixes: what a desk would have
objected to, and the fixes proposed.

#### 13 §3.2 · The mark was the last print, however stale or thin

Register: [S2-5](29_fixed_issues.md#s2-5--self-matching-enables-mark-manipulation-verified-fixed)

`mark_to_mkt` took `self.LOB.tape[-1]['price']` unconditionally. Consequences:

- A single 1-lot print re-marked the entire market for every participant.
- On steps with no trades, the previous mark persisted and `prev_nav` was not updated, so
  `nav_change` covered a multi-step gap rather than one step.
- Before the very first trade of an episode, NAV was never recomputed and all rewards were exactly
  0.

A mid-price mark (`(best_bid + best_ask)/2`, falling back to the last trade) was proposed as both
more standard and far harder to manipulate. That is what `mark_price_source: "mid"` does.

#### 13 §4 · There were no transaction costs

Register: [S2-3](29_fixed_issues.md#s2-3--transaction-cost-proxies-are-10⁵-too-small-verified-fixed)

`grep` for fee, commission, rebate, slippage, borrow across the env found nothing: no maker/taker
schedule, no exchange fee, no clearing fee, no borrow cost on shorts, no funding on inventory. The
reward's proxies (`trade_penalty=0.05` per fill, `passive_bonus=0.1` per passive fill) were flat
per-fill constants 5–6 orders of magnitude too small to matter at the measured per-step NAV scale
of ±10⁴. Functionally, trading was free.

The proposed fix was to charge in basis points of notional inside the settlement path, so the fee
flows through NAV rather than being bolted onto the reward:

```python
fee = notional * (TAKER_BPS if is_aggressor else MAKER_BPS) / 10_000
self.cash -= fee
```

with e.g. taker +2 bps / maker −0.5 bps, and the conservation check relaxed to
`total_nav + total_fees == total_initial_cash`. That is the shape of what shipped
(`maker_fee_bps`, `taker_fee_bps`, an exchange fee ledger), with both rates at 0 by default.

#### 13 §8 · What could be learned, before the fixes

Register: S1-2, S1-3, S2-3, S2-5, S2-6, S2-7.

The strategy-archetype table as it stood when the agent saw no private state, fees did not exist,
frames were incomparable and the mark was the last print:

| Archetype | Expressible? | Blocker |
|---|---|---|
| **Passive market making** | Partially | Only one order per price level, no post-only, no fee rebate, and the agent could not see its own queue position or inventory |
| **Directional / momentum** | Barely | Only 4 stacked public snapshots; no trade-flow or volatility features |
| **Mean reversion** | Barely | Same |
| **Inventory management** | **No** | The agent could not observe its own inventory |
| **Spread capture** | **No** | Zero fees meant there was no spread revenue to capture |
| **Order anticipation** | Partially | Frame stacking gave some order-flow history, but no per-participant attribution and the frames were not comparable |
| **Wash / mark manipulation** | **Yes — unintentionally** | No SMP, and the mark was the last print |
| **Latency arbitrage** | No | Arrival order is a uniform shuffle |

The summary then: the strategy that best satisfied the reward was *quote nothing, trade nothing*,
and the most exploitable non-trivial channel was self-trading to move the mark.

#### 13 §9 · Alignment with the reward's stated objectives, before the fixes

Register: [S1-3](29_fixed_issues.md#s1-3--doing-nothing-is-a-dominant-strategy-verified-fixed), [S2-1](29_fixed_issues.md#s2-1--drawdown-is-penalised-as-a-level-not-an-increment-verified-fixed), [S2-3](29_fixed_issues.md#s2-3--transaction-cost-proxies-are-10⁵-too-small-verified-fixed).

| Stated objective (from the reward's own docstring) | Achieved then? |
|---|---|
| "Maximizing NAV" | Yes — `nav_change` was the dominant term |
| "Reducing number of trades" | No — the 0.05 penalty was ~10⁵× too small |
| "Selective order placement" | No — same, 0.1 penalty |
| "Lowering drawdown risk" | **Over-achieved** — the penalty was ~2.4× the entire NAV term (**[verified]**) and drove the policy to inaction |
| "Capturing spread" | No — the 0.1 passive bonus was negligible, and there were no spread economics to capture |

The implementation collapsed to "NAV change, minus an enormous drawdown tax". Putting every term
on a common scale, fractional-NAV units, was the recommended fix, and is what shipped.

#### 13 §10 · The trading-realism agenda, done items

Register: the IDs in the table. The open items stay in [13](13_perspective_financial_trader.md) §10.

| # | Change | Effort | Why | Done by |
|---|---|---|---|---|
| 1 | Express all reward terms in fractional-NAV units | S | Makes the four secondary objectives bind | S1-1, S2-3 |
| 2 | Add maker/taker fees in bps inside settlement | M | Creates spread economics | S2-3, opt-in |
| 3 | Self-match prevention | S | Closes the wash-trade / mark-manipulation channel | S2-5 |
| 4 | Mark to mid, not last print | S | Removes single-print mark manipulation | S2-5 (`mark_price_source`) |
| 5 | Terminate + flatten bankrupt agents | S | Removes zombies and stale resting orders | S2-4, R-2, maintenance-margin liquidation ([04](04_accounting.md) §8) |
| 6 | Expose own position, NAV, drawdown, resting orders in obs | M | Prerequisite for any inventory-aware strategy | S1-2, S3-24 |
| 7 | Add order-flow imbalance + signed trade volume to obs | S | The highest-value predictive features | S2-7 (`signed_volume`, trade count, direction); realised volatility is not added |
| 8 | Per-episode desk metrics (Sharpe, max DD, turnover, maker ratio, inventory) | M | Makes "is this agent any good?" answerable | S3-9 |
| 9 | Allow multiple resting orders per price level | M | Unlocks layering / multi-clip quoting | S3-10, as an option |
| 10 (half) | A margin/liquidation rule | M | Real risk control rather than a reward penalty | Maintenance margin with ADL ([04](04_accounting.md) §8); position limits are still open |

### From 14 · Perspective: AI Engineer

Source: [14_perspective_ai_engineer.md](14_perspective_ai_engineer.md).
Bare section numbers (§) and "this document" in this group refer to [14](14_perspective_ai_engineer.md).

The engineering audit as first measured, against a tree of 7,478 Python lines with 90 unit tests
and no logging module. Every gap below is fixed; the current state is in
[14](14_perspective_ai_engineer.md).

#### 14 §5.1 · The original code-quality snapshot

Register: [S2-8](29_fixed_issues.md#s2-8--no-logging-framework-the-callback-prints-42-diagnostics-per-episode--fixed), [S3-7](29_fixed_issues.md#s3-7--sysexit-used-for-error-handling-in-the-matching-engine-fixed), [S4-6](29_fixed_issues.md#s4--minor).

| Signal | Measurement |
|---|---|
| Python LOC | 7,478 across 63 files |
| Test LOC | ~2,430 |
| Unit tests | 90, **all passing** |
| Integration tests | 13 across 3 classes covering local / remote-EnvRunner / remote-Learner |
| CI | GitHub Actions on Python 3.12: a `test` job (unit → random smoke run → RLlib integration) and a `packaging` job that installs the built wheel into a clean venv |
| `logging` module usage | **0** — everything is `print()` |
| `print()` calls in `envs/` + `train/` | ~86, incl. **42 in the self-play callback** and 13 in the env |
| `sys.exit()` in library code | 6 in `orderbook.py` (S3-7) |
| Broad `except Exception` in the callback | 2 (one deliberate, one questionable) |
| Type hints | present in `train/`; absent in most of `envs/` |
| Linter / formatter config | none |
| Pre-commit hooks | none |

#### 14 §5.2 · The costs of the six-mixin environment

Register: [S4-10](29_fixed_issues.md#s4--minor). Reward, done, info and liquidation are composed
objects now; the state/action pair still shares one `self` (open, in [15](15_findings_and_recommendations.md)).

**Costs:**

- **No enforced interface.** `State_Helper` reads `self.LOB`, `self.traders`, `self.last_price`,
  `self.min_tick` — none of which it owns or declares. `getattr(self, 'n_hist', 4)` and
  `getattr(self, 'last_price', 100.0)` are defensive workarounds for exactly this.
- **Not independently testable.** You cannot unit-test the reward without a full env;
  `test_reward_logic.py` works around it by instantiating a bare `Reward_Helper()` with a
  `MockTrader`, which happens to work only because `set_reward` touches nothing else.
- **Namespace collisions are silent.** Five mixins sharing one `self` means any attribute name
  reused across them overwrites without warning.
- **Fragile initialisation.** Whether `MultiAgentEnv.__init__` runs at all depends on which mixin
  happens to lack an `__init__`, and a stray kwarg reaching `object.__init__` raises `TypeError`
  — which is how a real bug once surfaced as
  `AttributeError: … has no attribute 'min_tick'`.

#### 14 §5.4 · Observability as first audited

Register: [S2-8](29_fixed_issues.md#s2-8--no-logging-framework-the-callback-prints-42-diagnostics-per-episode--fixed), [S4-7](29_fixed_issues.md#s4--minor).

- **No logging framework at all.** **[verified]** zero `import logging` in the repository.
- **~86 `print()` calls** in `envs/` + `train/`, 42 of them in `SelfPlayCallback` — including a
  3+-line banner per episode start listing the full policy map, five `DEBUG:`-prefixed lines and
  a full NAV table per episode end.
- With `num_env_runners > 0`, **every remote worker prints this independently**, with no level
  filtering, no worker attribution, and no way to turn it off short of editing the source.
- `env.render()` defaults to **`is_render=True`** on the env, so any direct instantiation dumps
  the book, tape and every account per step through pandas.
- **Only three custom values reach TensorBoard** (`league_size`, `league_mean_return`,
  `league_std_return`). Everything a practitioner would actually watch — NAV distribution,
  drawdown, trade counts, maker/taker ratio, champion promotions, `vf_explained_var` — is printed
  to stdout and then lost.
- The **NAV conservation check** is a good idea implemented as a `print("… FAILED …")`. A
  conservation violation is a hard ledger-invariant break; it should raise or emit a counter
  metric.

#### 14 §5.7 · The testing gaps as first audited

Register: S1-1 (learning-signal assertion), S4-6 (coverage), S4-5 (`test_insufficient_funds`),
S4-13 (property-based tests), S4-11 (`test_speed_regression.py`).

| Gap | Risk |
|---|---|
| **No learning-signal assertion** | Nothing checks `vf_explained_var`, `vf_loss` saturation, or that returns improve. This is exactly how the frozen critic went unnoticed. |
| **No coverage measurement** | No `pytest-cov`, no threshold. |
| **`test_accounting.py::test_insufficient_funds` is an empty `pass`** with a 15-line comment debating what the behaviour should be — a TODO shipped as a test. |
| **No property-based tests** | The order book is an ideal Hypothesis target: "tree volume == Σ level volumes", "no crossed book", "Σ NAV == Σ initial cash" hold for *any* order sequence. |
| **No performance regression test** | Nothing catches a 10× slowdown in the matching engine. |

#### 14 §5.11 · The engineering agenda, as first set

Register: the IDs named. Items 9, 12 and 15 are not finished and stay in
[14](14_perspective_ai_engineer.md) §5.11.

| # | Change | Effort | Why |
|---|---|---|---|
| 1 | Return the algorithm's live callback from `build_algo` on the restore path (§5.9.1) | S | Callers got a detached, empty league object |
| 2 | Replace all `print()` with `logging`; route callback diagnostics through `metrics_logger` | M | Multi-worker runs are currently unobservable |
| 3 | Fix `install_requires` (add `ray` / `scikit-learn` / `six`, or remove those imports) | S | The package does not install correctly as declared |
| 4 | Drop `six` → stdlib `io.StringIO`; drop `sklearn.utils.shuffle` → `random.shuffle` (seeded); drop the unused `import ray` | S | Removes a Py2 shim and a ~30 MB dependency; fixes reproducibility |
| 5 | `sys.exit` → `raise ValueError` in `orderbook.py` | S | Prevents worker kills |
| 6 | Raise (or emit a metric) on a NAV conservation violation instead of printing `FAILED` | S | A corrupt ledger should not be a log line |
| 7 | Add `vf_explained_var` / learning-signal assertions to CI | S | Would have caught the frozen critic |
| 8 | Delete the `g_store` trio and other dead code | S | Removed a misleading "working" telemetry path |
| 9 | Add `ruff` + `black` + pre-commit; add `pytest-cov` with a threshold | S | Baseline hygiene |
| 10 | Make the Docker image `COPY requirements.txt` instead of duplicating it | S | Removes drift |
| 11 | Add an `evaluate.py` that loads a checkpoint and runs deterministic episodes | M | There is currently no way to *use* a trained policy |
| 12 | Move `TrainConfig` under `tune.Tuner` | M | Free scheduling, fault tolerance, sweeps |
| 13 | Property-based tests (Hypothesis) for book invariants | M | The invariants are already known and stated |
| 14 | Record `SNAPSHOT_DIM` / an env version in the checkpoint | S | Turns a silent checkpoint mismatch into a clear error |
| 15 | Refactor mixins → composition | L | Makes reward/obs variants swappable |

Closed by: 1 S3-8; 2 S2-8; 3 and 4 S3-6 and S3-5 (`six` declared rather than dropped); 5 S3-7;
6 S2-8; 7 S1-1; 8 S4-1 to S4-4; 10 S4-8; 11 S4-12; 13 S4-13; 14 S4-19.

### From 18 · Configuration

Source: [18_configuration.md](18_configuration.md).
Bare section numbers (§) and "this document" in this group refer to [18](18_configuration.md).

#### 18 §2 · The dataclass and the file disagreed

The dataclass said `num_cpus_per_env_runner = 1.0` and `num_gpus_per_learner = 0.75` while the file
said `0.25` and `0.25`; a run without `--config` silently used the dataclass pair. Every field's
default now reads the file (`_default("key")`).

#### 18 intro · The policy helpers kept their own network defaults (#327)

Register: none (GitHub issue #327, found by the 2026-10-20 docs review).

`create_multi_agent_config` and `build_multi_rl_module_spec` declared `fcnet_activation="tanh"`
and `vf_share_layers=False`, a second copy of the `ppo` group. TrainConfig always passes both, so a
training run was unaffected; a direct caller, such as [08](08_self_play_league.md)'s example, got
the Python copy. Both default to `None` now, which `default_model_config` reads from the file, as
`fcnet_hiddens` already did. `test_config_sources.py` pins it ([17](17_changelog.md) §103).

#### 18 §5.2 · num_iters restarted at zero on every resume

`num_iters` was a count on a driver loop that restarted at zero, which made 16 configured iterations
mean 16 *more* every time a run resumed.

#### 18 §5.2 · Every save overwrote one checkpoint directory

Register: [S3-8](29_fixed_issues.md#s3-8--build_algo-returns-a-detached-callback-on-the-restore-path-fixed)

Every save overwrote one directory, which left a run with exactly one recoverable state: no way back
from a league that collapsed at iteration 12, and a save interrupted partway — the event
checkpointing exists to survive — destroyed the only copy.

#### 18 §6 · tick_size was inert, then off-grid on a fractional tick

Register: [S3-4](29_fixed_issues.md#s3-4--the-order-books-tick_size-is-inert-verified-fixed)

**This used to be two independent values.** `Action_Helper.min_tick` was a hardcoded `1` that
actually drove prices, while the configured `tick_size` was passed to an `OrderBook` argument that
was stored and never read. Setting `tick_size` therefore had no effect anywhere. Both values were
1, so wiring `min_tick` to the config key changed no behaviour at the current config.

**`reset()` no longer discards it.** It used to rebuild the book as `OrderBook(1, ...)` regardless
of configuration; it now uses `self.tick_size`. The change is inert — see below — but there is no
reason to keep a second value in the env.

**Every price the action layer emits is on this grid, for any tick.** `_set_price` snaps its
result to `min_tick` in `Decimal` before returning it, and `Trader._get_order_ID` compares prices
as `Decimal(str(price))`, the book's own conversion. Neither was true until the 2026-09-18 pass:
the level path read prices from a float32 snapshot, so on `tick_size` 0.1 every re-quote at an
occupied level opened a new price level one float-ulp away and a cancel never found its order
([15](15_findings_and_recommendations.md) S3-4, [16](16_verification_log.md) §16.17). At the
default `tick_size` of 1 nothing changes.

**The book's copy is gone.** `OrderBook` used to accept a `tick_size`, store it, and never read
it; its literal default of `0.0001` was the one value in the project not read from `config/`. On
2026-09-18 the parameter was deleted along with the `inert_tick_size_copy` block that documented
it. There is no rounding or tick validation anywhere in the matching path, and now nothing
suggests there is: the grid is the action layer's alone.

#### 18 §6.1 · Float-grid caveat

Register: [S3-4](29_fixed_issues.md#s3-4--the-order-books-tick_size-is-inert-verified-fixed)

This subsection used to say `_set_price` performed no quantization and that off-grid drift was
rare: one combination over all anchors 10–100 and six ticks. That count covered the *anchor* path
only. The *level* path — taken whenever the targeted book level is occupied — read the resting
price out of `agg_LOB_raw`, a float32 array, so a level at 100.1 read back as
`100.0999984741211` and the offset was added to that in float. On any non-integer tick every
re-quote at an occupied level therefore opened a new price-map entry one float-ulp from the one
the agent meant, and a cancel or same-price limit never found the trader's own order
([15](15_findings_and_recommendations.md) S3-4, [16](16_verification_log.md) §16.17).

Closed on 2026-09-18: `agg_LOB_raw` is float64, `_set_price` snaps its result to the tick grid
with a `Decimal` quantize before returning it, and `Trader._get_order_ID` compares as
`Decimal(str(price))`. `test_tick_grid.py` asserts the grid for ticks {1, 0.5, 0.1, 0.05, 0.01,
0.3, 0.0001} on both paths. Ticks of `1`, `0.5` and `0.25` were never affected on the anchor path
and are exact throughout now.

### From 21 · Logging review

Source: the logging review, once its own page (`21_logging_review.md`) and now [11](11_logging_and_observability.md) §5.
Bare section numbers (§) and "this document" in this group are the review's: its §N is [11](11_logging_and_observability.md) §5.N.

The audit of logging under multiple env runners and learners. Every finding below is fixed; [11](11_logging_and_observability.md) §5 keeps
the audit's structure with the current state of each, and links here.

#### 21 §2.1 · strict_nav_check restarted a worker instead of stopping the run

Register: [S2-8](29_fixed_issues.md#s2-8--no-logging-framework-the-callback-prints-42-diagnostics-per-episode--fixed)

_Tracked in [#212](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/212)._

This is the most serious finding, because the feature's stated purpose is to stop a corrupt run
loudly, and at the repository's own GPU profile (`num_env_runners=2`) it does not.

`on_episode_end` runs on the env runner. Its `raise AssertionError(message)` therefore surfaces as a
`RayTaskError` from the remote `sample()` call, and:

* `EnvRunnerGroup._ignore_ray_errors_on_env_runners = config.ignore_env_runner_failures or
  config.restart_failed_env_runners` **[verified]** `env/env_runner_group.py:181-183`;
* `restart_failed_env_runners` defaults to **True** **[verified]** `algorithms/algorithm_config.py:600`;
* `foreach_env_runner` passes that flag into
  `FaultTolerantActorManager.handle_remote_call_result_errors`, whose `ignore_ray_errors` branch is
  `logger.exception(result_or_error.get())` — log and continue **[verified]**
  `utils/actor_manager.py:779-788`.

So on a distributed run the assertion kills one env-runner actor, RLlib restarts it (tolerating 100
consecutive failures by default), and `algo.train()` returns normally. The run continues training on
a ledger the check just declared corrupt.

Two aggravating details:

* The traceback is logged through **Ray's** logger, not this package's, so it does not reach
  `run.log`. With `log_level: "WARN"` it reaches Ray's stderr and nothing else. The one line the
  whole §1.13 excepthook machinery exists to preserve is the one line that escapes it.
* A restarted env runner is a fresh process: it has lost `set_iteration`, so its lines read `iter=-`
  until the next `_broadcast_iteration`, and it opens a *new* `run.<pid>.<worker>.log` (see §2.5).

At `num_env_runners=0` — the default and what CI runs — the callback executes in the driver and the
assertion does stop the run. That is why this has never been observed.

#### 21 §2.2 · The per-step store accumulated with episode data disabled

_Tracked in [#213](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/213)._

`on_episode_step` appended to `self.store[episode.id_]` unconditionally; only the *write* in
`on_episode_end` was guarded by `episode_data_dir is not None`. So `--no-episode-data` / `episode_data_dir: null` removes the I/O and keeps the
memory.

**[verified]** by driving the callback with `episode_data_dir=None` for 1000 steps: 1000 step dicts
retained.

The cost is not small. A step dict for this repository's training shape (8 agents, `obs` of
`(168,) float32` — the observation width when this was measured, now 233 — the full 21-field
`info`) pickles to **8,314 bytes** **[verified]**, so one 4,096-step episode is **~34 MB** on disk
and appreciably more live in Python objects, held per concurrent episode per runner. The widened
observation makes that a floor rather than an estimate. `runtime_profiles.json` estimated ~10 MB; it is off by 3.4×, and has
been corrected.

#### 21 §2.3 · episode_data_dir was neither absolute nor run-scoped

_Tracked in [#214](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/214)._

Compare the two paths a worker writes:

| Path | Made absolute | Reaches the worker via | Run-scoped |
|---|---|---|---|
| log dir | yes, `os.path.abspath` in `logging_setup.configure` | `$CDA_LOG_DIR` **and** `runtime_env` | yes (`run_dir`) |
| `episode_data_dir` | no | pickled into the callback | **no** |

`episode_data_dir` defaults to the relative string `"episode_data"`, and `os.makedirs` +
`open` in the callback resolve it against **the worker process's cwd**. Today that is usually the
driver's cwd, because nothing sets `runtime_env["working_dir"]` — but it is an accident, not a
guarantee: any future use of `working_dir`, any Ray job submission, or any multi-node run scatters
the pickles into per-worker directories with no error and no log line. The log directory was given
`abspath` for exactly this reason; the episode directory was not.

It is also not run-scoped, so two concurrent runs write into one directory. Collision is unlikely
(episode IDs are UUID-ish) but "unlikely" is what §1.11 of doc 11 rejected for `run.log`.

#### 21 §2.4 · The pickle write was synchronous, on the sampling hot path

Register: [S4-9](29_fixed_issues.md#s4--minor)

_Tracked in [#215](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/215)._

`pickle.dump` of ~34 MB happens inside `on_episode_end`, in the env runner, between sampling steps.
On the Colab/GPU profile that is 4 episodes × 2 runners per iteration — ~136 MB of blocking,
uninstrumented I/O per iteration, against a `sample_timeout_s` budget the config file already warns
is tight. A slow or FUSE-backed filesystem (`episode_data_root` on Drive is explicitly called out as
something to avoid, and the profile does avoid it) turns into timed-out iterations that train on
nothing — the exact failure `_log_iteration`'s "trained on no samples" warning was added for, with a
cause nothing currently points at.

There is also no `try`/`except` around it. Every other instrumentation writer in this repository
(`_append_progress`, `_build_file_handler`) refuses to take down a run that is otherwise fine; this
one raises into `on_episode_end`, and by §2.1 that means a killed and restarted env runner.

#### 21 §2.5 · Log files proliferated with worker restarts

_Tracked in [#216](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/216)._

The per-process naming that makes concurrent writes safe also means the *set* of files is unbounded:
every restarted env runner (§2.1 makes restarts a normal event, not an exceptional one) opens a new
`run.<pid>.<worker>.log`. `file_backup_count` bounds each file at 6 × 10 MB; it does not bound the
number of files. A long run that loses runners repeatedly accumulates 60 MB of quota per incarnation.

The related point doc 11 §3 already makes — rotation discards the *start* of a run, where divergence
begins — is worse here, because a worker's file is where the NAV tables live.

**Fixed** (issue #216, [17](17_changelog.md) §83). When a worker opens its run log it keeps only the newest `file_max_worker_files` worker logs in the directory (a log with its rotated backups and head counts as one) and removes the rest, so the set is bounded and not only each file. And `file_keep_head` keeps the first `file_max_bytes` of every log as `<name>.head`, copied once at the first rotation and never rotated away, so the start of a run - where divergence begins - survives. Size the pruning above the number of runners plus learners: an idle live runner whose file is older than the newest N would lose its file.

#### 21 §2.6 · Learner processes never received an iteration

_Tracked in [#217](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/217)._

`_broadcast_iteration` targets `algo.env_runner_group` only. At `num_learners > 0` the learner
actors are separate processes that: receive `$CDA_LOG_LEVEL` / `$CDA_LOG_DIR` through the
`runtime_env` (so they do write a `run.<pid>.<worker>.log`), but never receive an iteration, so
every line they emit reads `iter=-` forever. This package logs little from the learner today, so the
impact is cosmetic — but the repository's own GPU profile sets `num_learners=0`, which means the
path is untested rather than fine.

**Fixed** (issue #217, [17](17_changelog.md) §83). `_broadcast_iteration` also calls `learner_group.foreach_learner` when the learners are remote actors (`num_learners > 0`); with a local learner it is the driver's process and already tagged. A learner that does not answer within the timeout is a warning, as for env runners. Tested against a fake group; the repository's profiles use `num_learners=0`, so no real remote learner was run.

#### 21 §2.7 · The runtime_env did not cover the cluster's own logging

_Tracked in [#218](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/218)._

`merge_runtime_env()` correctly closes the `ray.init(address=...)` gap for env vars. Two residual
cases:

* `$CDA_LOG_DIR` is exported as an **absolute** path. On a multi-node cluster that path must exist,
  and be writable, on every node — otherwise `_build_file_handler` warns (correctly, non-fatally)
  and that node's NAV tables exist nowhere. The warning goes to the worker's stdout, which is
  forwarded to the driver console but not into `run.log`.
* Nothing captures Ray's *own* logger output into the package's run log, so RLlib's diagnostics —
  "No samples returned from remote workers", the swallowed traceback from §2.1, env-runner restart
  notices — are in a different stream from the narrative they explain.

**Fixed** (issue #218, [17](17_changelog.md) §83). Both residual cases. The same round trip that carries the iteration returns each process's run-log path, so the driver logs a warning into `run.log` when a process was meant to write one and has none (the directory missing or unwritable on its node), and announces each path once. And `capture_ray_logs` attaches the run-log file handler to the Ray loggers records end at (`ray`, `ray.rllib`, and any other that has turned propagation off), de-duplicated per record, so RLlib's diagnostics land in the same file with the same `pid=` and `iter=` fields. Checked on a real two-runner run: a Ray `DeprecationWarning` from `ray._common.deprecation` appeared in the worker's log. The stream handler is not mirrored - Ray prints its own records to the console.

#### 21 §3.2 · In-flight episodes leaked from store and _activity

_Tracked in [#219](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/219)._

Both dicts are keyed by episode id and pruned only in `on_episode_end`. An episode that is discarded
without ending never gets pruned. That happens whenever the runner force-resets:
`MultiAgentEnvRunner._sample` calls `_reset_envs_and_episodes()` when `force_reset or num_episodes
is not None or self._needs_initial_reset` **[verified]** `env/multi_agent_env_runner.py:290`, and it
sets `_needs_initial_reset = True` after any episode-count sampling call and after env creation.
`on_episode_end` is not called for what it throws away.

At this repository's settings (timestep-based sampling, `max_step` truncation guaranteeing episode
ends) the leak is bounded and rare. It is worth fixing anyway because the leaked unit is not a
counter, it is up to 4,096 step dicts × `num_envs_per_env_runner` — ~34 MB per event, never freed
for the life of the worker.

#### 21 §3.3 · The iteration tag was stale after a missed broadcast

_Tracked in [#220](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/220)._

`_broadcast_iteration` is best-effort with a 10 s timeout and `healthy_only=True`. A runner that is
restarting, unhealthy, or slow at that moment is skipped silently (correctly — it must not stop
training), and its lines carry the *previous* iteration, not `-`, because the global is still set
from last time. A stale-but-plausible number is harder to spot than a dash. Applying the broadcast is
safe with respect to sampling: PPO's `synchronous_parallel_sample` blocks, so the broadcast cannot
land mid-episode.

**Fixed** (issue #220, [17](17_changelog.md) §83). A remote runner clears the tag in `on_sample_end`, so a runner the next broadcast misses reads `iter=-` rather than the previous iteration; the broadcast that does arrive sets it again before sampling. The local runner (worker index 0) shares the driver's process and is left alone. Lines a remote runner logs between samples now read `-`, which is true: it is not sampling for any iteration then.

#### 21 §3.4 · Duplicate narrative on the console

_Tracked in [#221](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/221)._

The package logger's `propagate` is deliberately left on, and Ray forwards worker stdout to the
driver console (`log_to_driver` defaults True). So a worker's NAV table appears once in that
worker's file and again on the driver's console prefixed `(MultiAgentEnvRunner pid=...)`. Harmless,
but it makes the console misleading as a record of *what the driver knows*, and it is why the
per-worker files matter more than the console suggests.

**Fixed** (issue #221, [17](17_changelog.md) §83). A worker that is writing its own file echoes only `worker_console_level` (default `WARNING`) and above to stdout, so the NAV table is in its file and not twice; warnings and errors still reach the driver console, and the driver logs each worker's file path once. The driver, and a worker with no file, echo everything. **A change in what a console shows:** the per-episode narrative from remote runners is no longer live on the console; set `worker_console_level` to `INFO` (or empty) to restore it. Verified on a real two-runner run: 0 NAV tables on the console, 6 in each worker's file.

#### 21 §7 · What was found while implementing

Nine things the review did not predict. The last six came out of re-reading the finished work rather
than out of building it, which is the argument for doing that pass at all — and the last four came
out of cross-checking channels against each other and against the *other* entry point, which no
single-channel reading would have caught.

**A 30-second hang at process exit.** ([#222](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/222)) The recorder's first design stopped its writer thread with a
sentinel value on the queue. `close()` is called at exit, and the one moment it is called under load
is the one moment the queue is full — so the `put` failed, the thread never learned to stop, and the
join sat out its whole timeout. Two tests took exactly 30.00s, which is what made it visible. It is
a `threading.Event` now, with the writer polling; the same two tests take 8s total.

**The `on_train_result` metrics are one iteration late.** ([#223](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/223)) The hook is handed a `result` that has
already been compiled, so `champions_promoted` reads `1.0` in the row *after* the promotion. This
has always been true of `league_size` and the return statistics — the new champion metrics simply
make it visible against a known event. Documented rather than corrected: the lag is uniform, and one
documented offset is better than a correction that has to be undone if RLlib changes the order.

**Live state should not be pickled at all.** ([#224](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/224)) The callback is cloudpickled into every env runner and
every checkpoint, and it was carrying its in-flight episode tallies along. The unpickling side is a
different process; a tally for an episode it never ran is not bookkeeping it should continue.
`__getstate__` now ships the configuration and nothing else — which is also what makes the
recorder's thread and queue safe to own.

**`maker_fill_ratio` was a tautology.** ([#225](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/225)) The first version divided the episode's passive fills by its
trades, aggregated across all agents. In a closed double auction that is exactly `0.5` in every
episode whatever anyone did: `process_acc` runs once per side of every trade, both sides increment
`num_trades_step`, and only the passive side increments `num_passive_fills_step`. A real
3-iteration run reported `0.5000` three times — a constant so clean it reads like a working metric.
It also mixed a cumulative field (`num_trades`) with a per-step one
(`num_passive_fills_step`, zeroed by `exchg_helper` on every step), so even per agent it was
measuring the last step against the whole episode.

It is `maker_fill_ratio_max` now: per-agent shares accumulated over the episode, reported as the
maximum across agents with at least five fills. 0.5 everywhere means nobody is specialising; one
agent at 0.9 against the others' 0.3 is a policy that has learnt to quote and wait. The same run now
reports 0.794, 0.837, 0.645. The floor on fills matters — one passive fill out of one trade is 1.0,
and with eight agents the maximum would otherwise sit there all run on noise.

The lesson generalises past this metric: **an aggregate over all agents of a two-sided quantity is a
conservation identity, not an observation.** Anything summing a maker/taker, buyer/seller or
long/short quantity across a closed market has the same defect waiting in it.

**The one-iteration lag turned out to be fixable.** §7's third item above said it was documented
rather than corrected. Re-reading RLlib's call site showed the correction is sanctioned: the hook
runs before `Trainable.log_result` "so that the user has a chance to mutate the result", and the
TODO beside the `metrics_logger` argument says there is "probably no point in adding more Stats
here". The callback now writes `result["league"]`, which lands in the row for the iteration it
describes, and keeps the metrics channel unchanged for readers that consume RLlib metrics rather
than the result dict. Verified: `promoted` reads 1 in iteration 1's row, where the promotion
happened.

#### 21 §8 · Corrections to other documents, and three more defects

| Doc | Was | Now |
|---|---|---|
| `11 §1.5` | "`strict_nav_check` defaults to true … so the run stops" | The stop is the driver's, from a metric; the hook reports (§2.1 here) |
| `11 §1.1` | Per-episode pickles, flag switches the record off | Parquet, bounded, run-scoped; the flag now switches off the accumulation too |
| `11 §1.2` | "Six metrics is the entirety" | 27, with the `on_train_result` lag documented |
| `11 §3` | Three persistence problems about the `.pkl` files | Gone with `pickle`; one new entry for the unbounded run-log file *count* |
| `11 §4` | Four sketched `log_value` calls "to add" | All four exist; the list is now things needing new computation |
| `config/runtime_profiles.json` | "~10MB per 4096-step episode" | ~34 MB, measured at the training shape |

**Two channels disagreed about how many episodes there were.** The same run recorded 8 distinct
`episode_id`s in Parquet and 6 NAV tables in the logs. Both were right: `on_episode_end` fires only
for episodes that actually end, while `close` writes whatever was in flight. The fragments were real
rows and worth keeping, but nothing marked them, so any per-episode aggregate over the file counted
them as episodes. There is an `episode_complete` column now, and the two channels agree exactly.

The general form is worth remembering: **two independent records of the same events are the cheapest
correctness check available, and they only help if someone actually compares the counts.** Three of
the findings on this page came from doing that once.

**The excepthook guard was racy.** `install_excepthooks` has an idempotence flag it checks and then
sets, and `configure` called it *outside* `_configure_lock` - the same check-then-act shape, in the
same file, as the bug that lock was added for. Two threads would each chain a hook onto the
previous one, and every unhandled exception would be logged twice. It is inside the lock now, with a
test that pins the mechanism and not just the outcome.

**The iteration broadcast under-delivered silently.** `foreach_env_runner` defaults to
`healthy_only=True` and skips a runner that is restarting or slower than the 10s timeout. That
runner keeps whatever iteration it was last told, so its lines and its recorded rows carry the
*previous* iteration rather than `-`. A stale but plausible number is worse than a missing one,
because nothing about it looks wrong. Blocking sampling until every runner acknowledges a log field
is not the trade to make, so the broadcast still degrades - but it now says when it fell short.

**The notebook path turned propagation off without the thing that justifies it.**
`configure_run_logging` disables propagation to the root logger whenever `ray_log_encoding` is set,
reasoning that Ray is about to configure root and both handlers would print every line twice. That
reasoning holds only if the `ray.init` that follows applies a `LoggingConfig` - `train.main` does,
and `runtime.ray_init_kwargs` did not. A notebook run therefore had propagation off with nothing
taking its place: no duplication, but no Ray-side formatting either, and a `logging.basicConfig()`
in a cell would have stopped showing package lines. `ray_init_kwargs(rt, cfg)` now adds the
`logging_config`, so the two entry points agree.

The general form again: **a decision made in one place and acted on in another will drift**, and the
two entry points into this repository are exactly where that drift lives.

### From 22 · JEPA integration

Source: [22_jepa_integration.md](22_jepa_integration.md).
Bare section numbers (§) and "this document" in this group refer to [22](22_jepa_integration.md).

#### 22 §2.3 · The reward carried almost no signal

Register: [S1-1](29_fixed_issues.md#s1-1--ppos-critic-receives-zero-gradient-verified-fixed), [S1-3](29_fixed_issues.md#s1-3--doing-nothing-is-a-dominant-strategy-verified-fixed)

Three findings compounded when the JEPA proposal was written:

- **S1-1** — `vf_clip_param = 10` against NAV-scale targets pinned `vf_loss` at the clip bound.
  `vf_explained_var ≈ 9e-05`. PPO was REINFORCE with a batch-standardised baseline.
- **S1-3** — the reward was strictly negative-sum over a NAV-conserving market. All-pass scored
  exactly `0.0`; random trading scored `−591,027`. Passivity was both a Nash equilibrium and the
  joint optimum.
- **§7** — the default budget is ~262k env steps against a realistic need of 10⁷–10⁸.

So the gradient reaching the encoder was a high-variance signal pointing at a degenerate policy,
delivered in small quantities.

#### 22 §3.2 · The observation had no private state

Register: [S1-2](29_fixed_issues.md#s1-2--observation-contains-no-private-state-verified-fixed)

> **Status.** S1-2 is closed for inventory, cash, NAV, drawdown, VWAP and time remaining: the
> observation carries a 9-float private tail ([17](17_changelog.md) §30). **Resting orders are
> still absent**, so the third bullet below is half-collected and the first still stands.

S1-2: every agent received the byte-identical public book vector — `distinct obs vectors across
agents: 1`. A JEPA world model over *that* observation modelled the market's evolution and could
not represent inventory, VWAP, NAV, drawdown or resting orders, because none of them was in its
input.

Consequences, and where each now stands:

- **Still open.** The latent cannot fully support the four of nine action categories (`modify`,
  `cancel`) that stay partly blind: an agent sees `cash_on_hold` but not *which* orders that cash
  is committed to.
- **Unchanged, and not a defect.** An action-conditioned predictor (§4.3) conditioned on *this*
  agent's action is fitting the conditional expectation over seven unobserved opponent actions.
  Its loss has a nonzero floor, and that floor is the residual multi-agent stochasticity rather
  than underfitting — §33.4 of [17](17_changelog.md) says the same about the shipped world model.
- **Collected.** With the private block in place, action-conditioning is now the materially more
  interesting object it promised to be: "what does the book — and my position — look like after I
  send this order" is a *market-impact* model, which is the quantity the project exists to study.

#### 22 §3.3 · The per-frame normalizer contaminated a predictive target

Register: [S2-6](29_fixed_issues.md#s2-6--every-frame-in-the-observation-stack-has-a-different-normalizer-verified-fixed)

S2-6: each stacked frame is normalised by its **own** L1 midpoint `M_t`, so a price at `t-3` and
the same price at `t` have different encodings. For a *classification*-flavoured encoder that is a
nuisance. For a *predictive* objective it is worse: "predict the latent of frame `t` from frames
`t-3..t-1`" partly means "predict the renormalisation", and the predictor can score well by
modelling an artefact of the observation pipeline rather than the market.

`log_mid` is in the observation, so `M_t` is recoverable and the artefact is learnable rather than
information-destroying — which is precisely the problem. **Fix S2-6 (normalise the whole stack by
the current `M_t`) before running any time-axis masking**, or the ablation in §4.2 will not mean
what it says.

### From 23 · Probe harness

Source: [23_probe_harness.md](23_probe_harness.md).
Bare section numbers (§) and "this document" in this group refer to [23](23_probe_harness.md).

#### 23 §1 · The two blockers to a returns-based comparison

Register: [S1-1](29_fixed_issues.md#s1-1--ppos-critic-receives-zero-gradient-verified-fixed), [S1-3](29_fixed_issues.md#s1-3--doing-nothing-is-a-dominant-strategy-verified-fixed)

Training each architecture and comparing returns could not answer the encoder question while these
stood:

| Finding | Consequence for an architecture comparison |
|---|---|
| **S1-1** | `vf_clip_param = 10` against NAV-scale targets pinned `vf_loss` at the clip bound. `vf_explained_var ≈ 9e-05`. PPO was REINFORCE with a batch baseline |
| **S1-3** | The reward was strictly negative-sum over a NAV-conserving market; all-pass scored exactly `0.0` and random trading `−591,027`. Passivity was the joint optimum |

Run an encoder comparison through that reward and the winner is whichever architecture descends
fastest to doing nothing.

#### 23 §7 · One row per step: the reason changed with S1-2

Register: [S1-2](29_fixed_issues.md#s1-2--observation-contains-no-private-state-verified-fixed)

The *reason* for that default has changed, and the change matters. While S1-2 was open every agent
received the byte-identical public book vector, so the eight rows were exact duplicates: keeping
one discarded nothing and avoided a leak, because a row's duplicates would otherwise land on both
sides of the split. **That premise no longer holds.** [17](17_changelog.md) §30 gave each agent its
own private tail, so the eight rows now differ in their last `private_dim` floats. Keeping one is
therefore a real choice — it drops seven agents' private state — and it is still the right default
for the public-book targets this harness scores, none of which read the private tail.

#### 23 §7 · Stale row-selection reasoning after the private-state work

The reason for keeping one row per step was left describing duplicate rows after the private-state
work gave each agent its own tail. This is the sort of thing a comment gets to be quietly wrong about
for a long time. It was found by the review in [17](17_changelog.md) §34.5 — a regression introduced
by the private-state work itself, which fixed the reader's `snapshots` slice and left the row
selection reasoning behind it untouched.

#### 23 §12 · A relative `--out` or `--checkpoint` path failed (#316)

Register: none (GitHub issue #316, found by the 2026-10-20 docs review).

`train.pretrain` with its default `--out pretrained/jepa`, and `train.probe`, `train.export` and
`train.evaluate` given `--checkpoint results/chkpt/iter_<n>` (the form every runbook command uses),
failed with pyarrow's `URI has empty scheme`: Ray's `save_to_path`, `RLModule.from_checkpoint` and
`Algorithm.from_checkpoint` read a bare relative path as a URI. `pretrain` failed after writing
`encoder.pt`, leaving a checkpoint the probe refused. The three call sites now pass an absolute
path, as `train.train` already did; `test_evaluate.py` and `test_pretrain.py` pin it
([17](17_changelog.md) §100).

### From 25 · Continual Backprop

Source: [25_continual_backprop.md](25_continual_backprop.md).
Bare section numbers (§) and "this document" in this group refer to [25](25_continual_backprop.md).

#### 25 §3.2 · The reward paid for passivity

Register: [S1-1](29_fixed_issues.md#s1-1--ppos-critic-receives-zero-gradient-verified-fixed), [S1-3](29_fixed_issues.md#s1-3--doing-nothing-is-a-dominant-strategy-verified-fixed)

- **S1-3** — the reward was strictly negative-sum over a NAV-conserving market. All-pass scored
  exactly `0.0`; random trading scored `−591,027`. Passivity was both a Nash equilibrium and the
  joint optimum.
- **S1-1** — `vf_clip_param = 10` against NAV-scale targets pinned `vf_loss` at the clip bound;
  `vf_explained_var ≈ 9e-05`.

#### 25 §3.4 · A league run on lstm failed once a champion existed

- **A league run on `lstm` used to fail once a champion existed** (issue #278, found while
  reviewing this change, and reproducible with CBP off). RLlib mis-shaped a stateful module's
  log-probability when two agents shared it in a step; fixed in `train/model/action_dist.py`
  (changelog §71), so recurrent CBP now runs through a league.

#### 25 §R-14 · Only the last call of a step counted

Register: [R-14](29_fixed_issues.md#from-the-2026-10-07-review)

A layer that runs more than once in a step (each MoE expert once per top-k slot; the JEPA trunk on the
masked and the full input) was judged only on its last call. The hook now merges the calls' statistics
by row count (R-14, #184).


### From 30 · Extensions

Source: [30_extensions.md](30_extensions.md).
Bare section numbers (§) and "this document" in this group refer to [30](30_extensions.md).
Found by the 2026-10-22 review of gym-CDA, cda-cbp and cda-discorl; each was reproduced before it
was filed.

#### 30 §5 · `train.evaluate` restored without the extension guards (#336)

Register: none (GitHub issue #336).

`train.evaluate` checked only the layout stamp before `Algorithm.from_checkpoint`. A checkpoint
trained with an extension that is not installed failed inside RLlib, which swallows the unpickle
`ImportError` and builds with no config: `'NoneType' object has no attribute 'to_dict'`. It now
runs `extensions.check_installed` and `check_pickled_classes_load` first, as a training resume
does, and names the missing extension or module. `test_evaluate.py`
(`TestARestoreIsGuardedLikeTraining`) pins both ([17](17_changelog.md) §107).

#### 30 §1 · Every installed extension was imported by every run (#337)

Register: none (GitHub issue #337).

`extensions.discover()` loaded every entry point in `gym_cda.extensions` on its first call, and
`TrainConfig` calls it to validate even with nothing enabled. With cda-discorl installed every run
imported JAX (1.3 s for `TrainConfig()`), and one package whose import failed broke every run.
`available()` now lists the entry points without importing them and `load(name)` imports one;
the training path loads only the names a config enables or a checkpoint records.
`test_extensions.py` (`TestOnlyWhatIsEnabledIsLoaded`) installs a package whose import raises
beside the dummy one ([17](17_changelog.md) §107).

#### 30 §8 · Continual Backprop could not see the heads an extension adds (#338)

Register: none (GitHub issue #338).

`layout.trunk_outputs` reported only `pi` and `vf` as the heads reading a trunk. cda-discorl's
`aux_pi` and `disco_heads` read the actor embedding too, so a CBP replacement zeroed the new
unit's outgoing weights in `pi` and left those heads reading it with the old unit's weights
(measured: the `aux_pi` column kept Σ|w| = 8.4, and its output moved by 0.013). A module class
now declares `extra_trunk_heads`, merged across its MRO and reported as `TrunkOutput.extra_heads`;
cda-cbp and cda-discorl use it. `test_model_layout.py` (`TestExtraTrunkHeads`) pins it
([17](17_changelog.md) §107).

#### 30 §1 · The version did not move with the extension API (#339)

Register: none (GitHub issue #339).

The extension API grew under version 2.0.0 (`adam_settings`, `effective_rank`'s tensor input,
tuned Adam inside the extensions, and now lazy loading and `extra_trunk_heads`), so an extension
pinned `>=2.0,<3` could not say it needed them. `setup.py`, `CITATION.cff` and the README citation
say 2.1.0, and a test in `test_extensions.py` (`TestThePackageVersion`) holds the three equal
([17](17_changelog.md) §107).
