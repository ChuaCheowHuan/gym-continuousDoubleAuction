# 15. Consolidated Findings and Recommendations

Severity-ranked across all three perspectives and both source documentation sets. **[verified]**
marks a finding confirmed by executing the code; raw output is in
[16_verification_log.md](16_verification_log.md).

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

### S1-1 · PPO's critic receives zero gradient **[verified]**

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

**Fix.** Normalise `nav_change` by `init_cash` in the reward (preferred — also fixes S2-1 and
S2-3), or set `vf_clip_param` to a commensurate value and add `grad_clip`. Then assert
`vf_explained_var > 0` in CI.
→ [12 §4](12_perspective_rl_researcher.md#4-the-critic-cannot-learn--vf_clip_param-saturation)

### S1-2 · Observation contains no private state **[verified]**

Every agent receives the byte-identical 168-float public book vector (`distinct obs vectors
across agents: 1`). Absent: `net_position`, `VWAP`, `nav`, `max_nav`, `cash`, own resting orders,
agent identity, time remaining.

The reward is literally `f(nav, prev_nav, max_nav, …)` — all unobserved. Two states with
identical books but opposite inventory require opposite optimal actions and are
indistinguishable. The drawdown term depends on `max_nav`, a path functional over the whole
episode, so this is not partial observability a recurrent net can recover. It also makes the
`modify` and `cancel` categories (4 of 9) blind.

**Fix.** Append a ~9-float normalised private block per agent and stop broadcasting one shared
vector. Delete `test_shared_history_multi_agent_uniformity`, which currently asserts the defect.
→ [12 §2](12_perspective_rl_researcher.md#2-the-observation-contains-no-private-state)

### S1-3 · Doing nothing is a dominant strategy **[verified]**

| Policy | Total return, 4 agents × 300 steps |
|---|---|
| All agents `category=0` (pass) | **0.0 exactly** |
| Random trading | **−591,027** |

NAV is conserved exactly (total 4,000,000.00 at both ends), so `Σ nav_change = 0`, but the
loss-aversion multiplier and the drawdown level make the reward strictly negative-sum.
`(pass, …, pass)` is both a Nash equilibrium and the joint optimum, and gradient descent finds it
early because the fastest way to raise return is to stop trading. Empty-market collapse is the
predicted outcome.

**Fix.** Remove the systematic negative bias: make the drawdown penalty an increment (S2-1),
scale the micro-penalties to reward units (S2-3), and reduce or drop the asymmetric multiplier.
→ [12 §3.3](12_perspective_rl_researcher.md#33-doing-nothing-is-a-dominant-strategy)

---

## S2 — Major

### S2-1 · Drawdown is penalised as a level, not an increment **[verified]**

`max_nav` is monotone within an episode, so a drawdown is re-charged **every step** until NAV
exceeds the old peak. Measured over 300 steps × 4 random agents: drawdown = **−416,473**, roughly
**2.4×** the entire NAV term (−174,502). At `max_step=4096` a 1,000-unit early drawdown costs
~800,000.

Side effects: not potential-based (changes the optimum, not just the shaping); magnitude scales
with `max_step`, making episode length a hidden risk-aversion knob; non-Markov in the observation.

**Fix.** `-drawdown_penalty * max(0, new_dd - prev_dd)`.
→ [12 §3.4](12_perspective_rl_researcher.md#34-the-drawdown-term-is-a-level-not-a-delta)

### S2-2 · Unnormalised observation scales saturate the `tanh` MLP **[verified]**

| Feature block | Range (one 300-step rollout) |
|---|---|
| normalised prices | ±0.58 |
| sqrt sizes | **±47** |
| `log_mid` | 3.68 … 4.04 |

An ~80–250× spread (book-dependent; a second run measured ±0.26 vs ±51) into a `tanh` first layer
with no `MeanStdFilter` or normalisation connector. Size features saturate and dominate; price
features contribute almost nothing.

**Fix.** Divide sizes by a reference scale; centre `log_mid`.
→ [05 §7.5](05_observation_space.md#75-feature-scales-differ-by-one-to-two-orders-of-magnitude-after-normalization)

### S2-3 · Transaction-cost proxies are ~10⁵× too small **[verified]**

`order_penalty=0.1`, `trade_penalty=0.05`, `passive_bonus=0.1` against per-step NAV moves of
−10,949 … +6,126. Three of the reward's five stated objectives — "reducing number of trades",
"selective order placement", "capturing spread" — therefore have no effect. There are no real
fees anywhere in the simulator, so market making has no revenue model and crossing the spread has
no cost.

**Fix.** Charge maker/taker fees in basis points of notional inside settlement so they flow
through NAV; relax the NAV-conservation assertion to account for fees.
→ [13 §4](13_perspective_financial_trader.md#4-there-are-no-transaction-costs)

### S2-4 · Bankrupt agents are never terminated **[verified]**

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

**Fix.** Set `terminateds[agent] = True` for members of `done_set`, cancel their resting orders,
and stop scoring them.

### S2-5 · Self-matching enables mark manipulation **[verified]**

An agent can cross its own resting order (`same ID both sides: True`). The accounting handles it
consistently, so NAV stays conserved — but `mark_to_mkt` uses the **last tape print** as the mark
for *everyone*. An agent holding inventory can self-trade one contract at a chosen price and
instantly re-mark the whole market, including its own reward. Every regulated venue mandates
self-match prevention for exactly this reason.

**Fix.** Skip resting orders whose `trade_id` matches the incoming order in `process_order_list`;
and mark to mid rather than last print.
→ [13 §3.1](13_perspective_financial_trader.md#31-self-matching)

### S2-6 · Every frame in the observation stack has a different normalizer

`set_agg_LOB` computes `M` from the book at that moment; `prep_next_state` appends the
already-normalized frame to the deque. Frames *t−3 … t* each carry their own `M_{t−3} … M_t`, so
**they cannot be differenced meaningfully** — which is the entire purpose of stacking them. A
resting order at a fixed absolute price appears to move whenever the midpoint moves.

Partially mitigated by the per-frame `log_mid`, which lets the agent recover each frame's
normalizer, but the network must then learn to undo the rescaling itself.

**Fix.** Keep raw snapshots in the deque, normalize the whole stack once at emission by `M_t`,
and expose `M_t / M_{t−1} − 1`.
→ [05 §7.1](05_observation_space.md#71-each-frame-in-the-stack-is-normalized-by-a-different-denominator)

### S2-7 · No trade-flow information — the tape loop is dead code

`set_agg_LOB` iterates the tape, uses nothing, and increments a discarded counter. The body is a
commented-out `write` copy-pasted from `OrderBook.__str__`. The observation therefore contains
**zero information about executions**: no last traded price, no trade direction, no signed
volume, no trade count.

In a continuous double auction, aggressive order flow is the single most predictive public
signal — more so than the resting book, which is largely stale intentions. Order-imbalance
helpers already exist in `train/helper/helper.py`, unused.

**Fix.** Finish the loop into signed-volume / trade-count / direction features, and wire in
`ord_imb`.
→ [05 §7.3](05_observation_space.md#73-the-tape-loop-is-dead-code--there-is-no-trade-flow-information-at-all)

### S2-8 · No logging framework; the callback prints 42 diagnostics per episode **[verified]**

Zero `import logging` in the repository; ~86 `print()` calls in `envs/` + `train/`. With
`num_env_runners > 0` every remote worker prints independently, with no level filter, no worker
attribution, and no off switch. Only three custom values reach TensorBoard. The NAV-conservation
check — a **hard ledger invariant** — prints `FAILED` rather than raising or emitting a metric.

**Fix.** `logging` for diagnostics; `metrics_logger.log_value` for anything worth plotting; raise
on conservation violation.
→ [11 §4](11_logging_and_observability.md#4-recommended-minimum)

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

### S3-4 · `tick_size` config is silently discarded **[partly fixed]**

`tick_size` used to exist as two independent values: a hardcoded `min_tick = 1` in
`Action_Helper` that actually drove prices, and an `OrderBook` argument that was stored and never
read. Setting the config key therefore changed nothing anywhere.

**Fixed:** `Action_Helper.min_tick` now comes from the `tick_size` config key, so the key controls
the price grid agents quote on. Both defaults were 1, so behaviour at default config is unchanged.

**Deliberately not fixed — the action layer should be the single definition, and `OrderBook`'s
copy should be deleted.** `OrderBook` still accepts a `tick_size`, stores it, and never reads it;
`reset()` still hardcodes `OrderBook(1, ...)`. That argument makes it look as though the matching
engine enforces a grid, which it does not — there is no rounding or tick validation anywhere in
the matching path.

The reason to delete rather than enforce: there is exactly **one** price producer in the system.
Every price reaching `process_order` comes from `_set_price` via `place_order`, and `_set_price`
builds prices as `anchor ± k × min_tick`, so output is on the grid by construction. A snapping or
validation step in the book would re-derive a guarantee the producer already provides. Deleting
the parameter is also nearly free: 9 of the 11 `OrderBook(...)` call sites already use the no-arg
form, and dropping it makes the hardcoded `1` in `reset()` disappear rather than need a fix.

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

Related, and still open: the price anchor is drawn from `randint(10, 100)`, so with a fixed tick
the *relative* tick varies **10×** across episodes — a large uncontrolled non-stationarity, only
partly mitigated by exposing `log_mid`. `initial_price_min/max` are read by `reset()` but omitted
from `TrainConfig.env_config`, so training cannot narrow the range.

### S3-5 · Seeding is entirely non-functional

`reset(seed=...)` forwards to `MultiAgentEnv.reset`, which seeds `self._np_random` — which
nothing uses. The env draws initial price and order sizes from global `np.random`, and
`rand_exec_seq(actions, None)` always passes `random_state=None`, so the shuffle ignores RLlib's
`seed` too.

**No episode is reproducible.** For a research environment whose entire output is simulated data
this is disqualifying — none of the generated-LOB figures can be regenerated. The
`rand_exec_seq` signature already accepts a seed; nothing passes one.
**Fix:** one `np.random.Generator` on the env, threaded through size sampling, initial price and
the shuffle.

### S3-6 · `install_requires` does not match the imports **[verified]**

`envs/` imports `ray`, `sklearn.utils`, and `six`, none of which are in `install_requires`.
`pip install gym_continuousDoubleAuction` without extras fails on first import. CI never catches
it because it always installs the full `requirements.txt`.

`import ray` in the env is entirely unused; `six` is a Python-2 shim replaceable by
`io.StringIO`; `sklearn.utils.shuffle` pulls ~30 MB into every EnvRunner to shuffle ≤8 dicts —
and is the same call that makes runs irreproducible (S3-5).

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
[18 §5.1–5.2](18_configuration.md#51-the-run-group), [16 §16.8](16_verification_log.md), and
`test_checkpointing.py`.
→ [14 §5.9.1](14_perspective_ai_engineer.md#591-checkpointrestore-what-actually-happens)

### S3-9 · No risk-adjusted performance metrics

NAV, trade count and reward are recorded. Absent: Sharpe/Sortino, max drawdown *as a reported
metric*, hit rate, turnover, inventory statistics, maker/taker ratio, realised-vs-unrealised P&L
split, adverse-selection mark-outs. The counters for several of these already exist and are
discarded after the reward consumes them. `info["NAV"]` is a **string**, round-tripped through
`float()` by every consumer, discarding the exactness `Decimal` was chosen for.

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

---

## S4 — Minor

| ID | Finding |
|---|---|
| S4-1 | ~270 LOC of dead telemetry in `train/`: the `g_store` trio (`store_handler`, `log_handler`, `plot_handler`) depends on a detached Ray actor that is **never created** **[verified]**; `helper.py`'s order-imbalance utilities are unused (and would be valuable as observation features — S2-7) |
| S4-2 | `envs/agent/random_agent.py` returns the **old 5-tuple** action format; superseded by `RandomRLModule` but still in `Trader`'s MRO **[verified]** |
| S4-3 | Dead methods: `State_Helper.state_diff`, `Action_Helper._set_side/_set_type/_higher/_lower`, `OrderBook.__str__0`, `Order.__str__0`, `OrderList.to_str`; `max_price` is a parameter of `_set_price` that its body never reads |
| S4-4 | ~200 LOC of commented-out code (`continuousDoubleAuction_env.py:100-133,178-207`; `orderbook.py:260-318`; `action_helper.py:23-36`) |
| S4-5 | `test_accounting.py::test_insufficient_funds` is an empty `pass` with a 15-line comment debating the intended behaviour — a TODO shipped as a test |
| S4-6 | No linter, formatter, pre-commit or coverage tooling; type hints only in `train/` and essentially absent from `envs/` |
| S4-7 | `is_render` defaults to **`True`** on the env, so a direct instantiation prints a full book/tape/account dump per step. `_render` also has **side effects** — it nulls `model_actions`/`LOB_actions`/`shuffled_actions` and clears `seq_trades`, so toggling it changes state evolution |
| S4-8 | The Docker image duplicates the dependency list instead of `COPY`ing `requirements.txt` |
| S4-9 | Episode data is `pickle` (arbitrary code execution on load); two `.pkl` fixtures are committed |
| S4-10 | Mixin-based env architecture: helpers read attributes they do not own, guarded by defensive `getattr` defaults; not independently testable |
| S4-11 | `_process_counter_party` linear-scans all agents per fill; `set_agg_LOB` is called twice per step (the pre-action call is display-only) |
| S4-12 | No `evaluate.py` / serving path — no way to *use* a trained checkpoint |
| S4-13 | No property-based tests, despite the order book having clearly stated invariants (tree volume == Σ level volumes, no crossed book, Σ NAV == Σ initial cash) |
| S4-14 | Rejected and unmatched orders return empty lists silently — nothing logged, penalised or surfaced in `infos`, so the dead-action fraction is unmeasurable |
| S4-15 | `Box(-inf, inf)` observation bounds, though every quantity is boundable; disables RLlib observation filters and space-based sanity checks |
| S4-16 | `test_shared_history_multi_agent_uniformity` encodes S1-2 as a requirement and must be deleted when private state is added |
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
| Per-episode pickles were unconditional | `episode_data_dir=None` / `--no-episode-data` disables them |
| `episode_data/` was untracked noise | In `.gitignore`, both paths, with an explanatory comment |
| **No CI** — dead `.travis.yml` | GitHub Actions, 3.11/3.12 matrix, three staged jobs |
| `setup.py` broken for non-editable installs | `find_packages()`, real `install_requires` and extras, `__init__.py` files added |
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
- **Buying-power logic is subtle and right** — only the risk-*increasing* portion of an order is
  cash-checked, so closing and covering always succeed, and market orders are priced off the
  contra side with a tape fallback.
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
- **90 unit tests pass**, covering every position-flip path, cash-check edge case, modify-order
  scenario and observation invariant.

---

## Suggested sequencing

Roughly two to three weeks of work, ordered so each step unblocks the next.

**Phase 1 — make learning possible (≈2 days)**
1. Scale all reward terms to fractional-NAV units (fixes S1-1, S2-1, S2-3 together)
2. Set `grad_clip`; assert `vf_explained_var > 0` in CI
3. Make the drawdown penalty an increment
4. Normalise observation feature scales (S2-2)

**Phase 2 — make the problem well-posed (≈3–4 days)**
5. Add the private-state observation block (S1-2); delete the uniformity test
6. Terminate and flatten bankrupt agents (S2-4)
7. `size_mean → Box(0,1)`; scale or drop `size_sigma` (S3-1, S3-2)
8. Positive decaying `entropy_coeff`; raise `std_dev_multiplier`; refuse zero-trade champions (S3-11)
9. One `np.random.Generator` threaded through the env (S3-5)

**Phase 3 — fix the observation pipeline (≈3 days)**
10. Normalize the whole stack by the current `M_t`; expose `M_t / M_{t−1} − 1` (S2-6)
11. Finish the tape loop into trade-flow features; wire in `helper.py`'s order imbalance (S2-7)
12. Occupancy mask (S3-14); consider the fixed tick-offset grid (S3-15)

**Phase 4 — market realism (≈3 days)**
13. Maker/taker fees in bps inside settlement (S2-3)
14. Self-match prevention; mark to mid (S2-5)
15. Per-episode desk metrics through `metrics_logger` (S3-9)

**Phase 5 — engineering hygiene (≈3 days)**
16. `logging` replaces `print`; conservation violation raises (S2-8)
17. Fix `install_requires`; drop `six`, `sklearn` and the unused `import ray` (S3-6)
18. `sys.exit` → `raise ValueError` (S3-7)
19. Delete dead code (S4-1..4) — the `build_algo` restore path (S3-8) is done
20. Add `ruff` / `black` / `pre-commit` / `pytest-cov`
