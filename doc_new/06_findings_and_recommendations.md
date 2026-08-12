# 6. Consolidated Findings and Recommendations

Severity-ranked across all three perspectives. **[verified]** marks a finding
confirmed by executing the code; raw output is in
[07_verification_log.md](07_verification_log.md).

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

`vf_clip_param` defaults to 10.0 and is never overridden, while value targets are
NAV sums in the 10⁴–10⁶ range. `torch.clamp(vf_loss, 0, 10.0)` is flat there, so
`∂L_vf/∂θ = 0` for every sample.

```
vf_loss            10.0            ← pinned at the clip bound
vf_loss_unclipped  3,847,340.5  /  31,965,536.0
vf_explained_var   -0.000165    /  -0.000135     ← critic explains 0% of variance
```

PPO degenerates to REINFORCE with a batch-standardised baseline. Silent: the
reported `total_loss` looks small and stable because 10.0 of it is a constant.

**Fix.** Normalise `nav_change` by `init_cash` in the reward (preferred — also
fixes S1-3 and S2-3), or set `vf_clip_param` to a commensurate value and add
`grad_clip`. Then assert `vf_explained_var > 0` in CI.
→ [03 §3.4](03_perspective_rl_researcher.md#34-the-critic-cannot-learn--vf_clip_param-saturation)

### S1-2 · Observation contains no private state **[verified]**

Every agent receives the byte-identical 168-float public book vector
(`distinct obs vectors across 3 agents: 1`). Absent: `net_position`, `VWAP`,
`nav`, `max_nav`, `cash`, own resting orders, agent identity, time remaining.

The reward is literally `f(nav, prev_nav, max_nav, …)` — all unobserved. The
drawdown term depends on `max_nav`, a path functional over the whole episode, so
this is not partial observability a recurrent net can recover. It also makes the
`modify` and `cancel` categories (4 of 9) blind.

**Fix.** Append a ~9-float normalised private block per agent and stop
broadcasting one shared vector.
→ [03 §3.2](03_perspective_rl_researcher.md#32-the-observation-contains-no-private-state)

### S1-3 · Doing nothing is a dominant strategy **[verified]**

| Policy | Total return, 4 agents × 300 steps |
|---|---|
| All agents `category=0` (pass) | **0.0 exactly** |
| Random trading | **−883,786** |

NAV is conserved exactly (total 4,000,000 at both ends), so `Σ nav_change = 0`,
but the loss-aversion multiplier and the drawdown level make the reward strictly
negative-sum. `(pass, …, pass)` is both a Nash equilibrium and the joint optimum,
and gradient descent finds it early because the fastest way to raise return is to
stop trading. Empty-market collapse is the predicted outcome.

**Fix.** Remove the systematic negative bias: make the drawdown penalty an
increment (S2-1), scale the micro-penalties to reward units (S2-3), and reduce
or drop the asymmetric multiplier.
→ [03 §3.3.2](03_perspective_rl_researcher.md#332-doing-nothing-is-a-dominant-strategy)

---

## S2 — Major

### S2-1 · Drawdown is penalised as a level, not an increment **[verified]**

`max_nav` is monotone within an episode, so a drawdown is re-charged **every
step** until NAV exceeds the old peak. Measured over 300 steps × 4 random agents:
drawdown = **−519,143**, roughly **2×** the entire NAV term (−264,587). At
`max_step=4096` a 1,000-unit early drawdown costs ~800,000.

Side effects: not potential-based (changes the optimum, not just the shaping);
magnitude scales with `max_step`, making episode length a hidden risk-aversion
knob; non-Markov in the observation.

**Fix.** `-drawdown_penalty * max(0, new_dd - prev_dd)`.
→ [03 §3.3.3](03_perspective_rl_researcher.md#333-the-drawdown-term-is-a-level-not-a-delta)

### S2-2 · Unnormalised observation scales saturate the `tanh` MLP **[verified]**

| Feature block | Range |
|---|---|
| normalised prices | ±0.26 |
| sqrt sizes | **±51** |
| `log_mid` | 4.16 … 4.28 |

A ~250× spread into a `tanh` first layer with no `MeanStdFilter` or
normalisation connector. Size features saturate and dominate; price features
contribute almost nothing.

**Fix.** Divide sizes by a reference scale; centre `log_mid`.
→ [03 §3.8](03_perspective_rl_researcher.md#38-training-stability)

### S2-3 · Transaction-cost proxies are ~10⁵× too small

`order_penalty=0.1`, `trade_penalty=0.05`, `passive_bonus=0.1` against per-step
NAV moves of ±10⁴ **[verified]**. Three of the reward's five stated objectives —
"reducing number of trades", "selective order placement", "capturing spread" —
therefore have no effect. There are no real fees anywhere in the simulator, so
market making has no revenue model and crossing the spread has no cost.

**Fix.** Charge maker/taker fees in basis points of notional inside settlement so
they flow through NAV; relax the NAV-conservation assertion to account for fees.
→ [04 §4.4](04_perspective_financial_trader.md#44-there-are-no-transaction-costs)

### S2-4 · Bankrupt agents are never terminated **[verified]**

Forcing `agent_0.nav = −50`:

```
terminateds: {'agent_0': False, 'agent_1': False, 'agent_2': False, '__all__': False}
done_set:    {'agent_0'}
```

`set_done` records bankruptcy, then `set_all_done` overwrites every per-agent
flag with `False`
([`done_helper.py:32-33`](../gym_continuousDoubleAuction/envs/exchg/done_helper.py#L32-L33)).
The agent keeps emitting transitions, keeps accruing the per-step drawdown tax
(S2-1), and its resting orders stay live and executable. Its module return is
then dominated by a constant unrelated to its policy — and that return is what
champion promotion reads.

**Fix.** Set `terminateds[agent] = True` for members of `done_set`, cancel their
resting orders, and stop scoring them.

### S2-5 · Self-matching enables mark manipulation **[verified]**

An agent can cross its own resting order (`same ID both sides: True`). The
accounting handles it consistently, so NAV stays conserved — but `mark_to_mkt`
uses the **last tape print** as the mark for *everyone*
([`exchg_helper.py:47-51`](../gym_continuousDoubleAuction/envs/exchg/exchg_helper.py#L47-L51)).
An agent holding inventory can self-trade one contract at a chosen price and
instantly re-mark the whole market, including its own reward. Every regulated
venue mandates self-match prevention for exactly this reason.

**Fix.** Skip resting orders whose `trade_id` matches the incoming order in
`process_order_list`; and mark to mid rather than last print.
→ [04 §4.3.1](04_perspective_financial_trader.md#431-self-matching)

### S2-6 · No logging framework; the callback prints 42 diagnostics per episode

Zero `import logging` in the repository; 88 `print()` calls in library code.
With `num_env_runners > 0` every remote worker prints independently, with no
level filter, no worker attribution, and no off switch. Only three custom values
reach TensorBoard. The NAV-conservation check — a **hard ledger invariant** —
prints `FAILED` rather than raising or emitting a metric.

**Fix.** `logging` for diagnostics; `metrics_logger.log_value` for anything
worth plotting; raise on conservation violation.
→ [05 §5.4](05_perspective_ai_engineer.md#54-observability)

---

## S3 — Moderate

### S3-1 · Half the `size_mean` action range is a no-op **[verified]**

`_set_size` applies `abs()` to the Gaussian sample, so `mean=+0.5` and
`mean=−0.5` produce identical sizes under the same seed. `size_mean` is declared
on `Box(-1, 1)`; the optimum is bimodal at `±m`, which a unimodal Gaussian head
resolves by drifting toward 0 — i.e. minimum size.
**Fix:** declare `Box(0, 1)`.

### S3-2 · The `size_sigma` head is inert **[verified]**

`sigma ∈ [0,1]` is used as an *absolute* standard deviation while means are
49.5·|m| or 499.5·|m|. Across its full range the size varies by ±1 contract on a
base of 250. The policy pays entropy cost for a control that does nothing.
**Fix:** scale it, or delete it.

### S3-3 · Size is sampled by the environment, outside the policy's log-prob

The policy emits distribution parameters and the env draws the sample, so the
realised size is not part of the action whose log-probability PPO uses in the
importance ratio. Irreducible advantage variance.
**Fix:** emit size directly as a `Box` action.

### S3-4 · `tick_size` config is silently discarded **[verified]**

```
config=0.25 | LOB.tick_size before reset=0.25 | after reset=1 | action min_tick=1
```

`reset()` hardcodes `OrderBook(1, ...)`. Combined with the price anchor drawn
from `randint(10, 100)`, the *relative* tick varies **10×** across episodes — a
large uncontrolled non-stationarity, only partly mitigated by exposing `log_mid`.
Related: `initial_price_min/max` are read by `reset()` but omitted from
`TrainConfig.env_config`, so training cannot narrow the range.

### S3-5 · `install_requires` does not match the imports

`envs/` imports `ray`, `sklearn.utils`, and `six`, none of which are in
`install_requires`. `pip install gym_continuousDoubleAuction` without extras
fails on first import. CI never catches it because it always installs the full
`requirements.txt`.

`import ray` in the env is entirely unused; `six` is a Python-2 shim replaceable
by `io.StringIO`; `sklearn.utils.shuffle` pulls ~30 MB into every EnvRunner to
shuffle ≤8 dicts, and — passing `random_state=None`
([`action_helper.py:96`](../gym_continuousDoubleAuction/envs/exchg/action_helper.py#L96)) —
is why runs are not bit-reproducible even with `--seed` set.

### S3-6 · `sys.exit()` used for error handling in the matching engine

8 occurrences in `orderbook.py`. `SystemExit` derives from `BaseException`, so
inside a Ray actor it kills the worker rather than surfacing a traceback.
Currently unreachable, but one action-space change away.
**Fix:** `raise ValueError(...)`.

### S3-7 · `build_algo` returns a detached callback on the restore path **[verified]**

League state *does* survive checkpointing (cloudpickle preserves the callback
closure — restored modules, history and mapping all verified correct). But
`build_algo` returns the **fresh, empty** callback from `build_config` rather
than the algorithm's live one. `train()` ignores it, so training is unaffected;
any caller that uses it (notebook, tests) drives a detached object.
→ [05 §5.9.1](05_perspective_ai_engineer.md#591-checkpointrestore-what-actually-happens)

### S3-8 · No risk-adjusted performance metrics

NAV, trade count and reward are recorded. Absent: Sharpe/Sortino, max drawdown
*as a reported metric*, hit rate, turnover, inventory statistics, maker/taker
ratio, realised-vs-unrealised P&L split, adverse-selection mark-outs. The
counters for several of these already exist and are discarded after the reward
consumes them. `info["NAV"]` is a **string**, round-tripped through `float()` by
every consumer, discarding the exactness `Decimal` was chosen for.

### S3-9 · A trader can hold only one resting order per price level **[verified]**

A second limit at the same price *replaces* the first (level volume 7, not 12) —
`_place_limit_order` upserts via `_get_order_ID`. Layering, iceberg and
multi-clip quoting are not expressible.

### S3-10 · No entropy bonus, and champion promotion cannot detect passivity

`entropy_coeff = 0.0` (RLlib default). If the learners collapse to "always pass"
(S1-3), they still clear the promotion threshold — 0 beats a negative league mean
— so the league fills with champion snapshots of the do-nothing policy. Related:
with `std_dev_multiplier=0.1` a champion is promoted on the very first eligible
iteration **[verified]**, so at the default 16-iteration run the pool saturates
with barely-trained snapshots.
**Fix:** positive decaying `entropy_coeff`; refuse to promote a champion whose
trade count is ~0.

### S3-11 · γ=0.99 against 4,096-step episodes

Effective horizon ~100 steps = 2.5% of an episode. Strategies with payoff
horizons longer than that (inventory accumulation, sustained market making) are
invisible to the return. Only 4 episodes per training iteration also means very
few samples of the episode-level randomness (price anchor, opponent draw).

---

## S4 — Minor

| ID | Finding |
|---|---|
| S4-1 | ~500 LOC of dead code in `train/`: the `g_store` trio (`store_handler`, `log_handler`, `plot_handler`) depends on a detached Ray actor that is never created; `helper.py`'s order-imbalance utilities are unused (and would be valuable as observation features) |
| S4-2 | `envs/agent/random_agent.py` returns the **old 5-tuple** action format; superseded by `RandomRLModule` but still in `Trader`'s MRO |
| S4-3 | Dead methods: `State_Helper.state_diff`, `Action_Helper._set_side/_set_type/_higher/_lower`, `OrderBook.__str__0`, `Order.__str__0`, `OrderList.to_str`; `max_price` is a parameter of `_set_price` that its body never reads |
| S4-4 | ~200 LOC of commented-out code (`env.py:100-133,178-207`; `orderbook.py:260-318`; `action_helper.py:23-36`) |
| S4-5 | `test_accounting.py::test_insufficient_funds` is an empty `pass` with a comment debating the intended behaviour — a TODO shipped as a test |
| S4-6 | No linter, formatter, pre-commit or coverage tooling; type hints only in `train/` (9 defs) and essentially absent from `envs/` (1) |
| S4-7 | `is_render` defaults to **`True`** on the env, so a direct instantiation prints a full book/tape/account dump per step |
| S4-8 | The Docker image duplicates the dependency list instead of `COPY`ing `requirements.txt` |
| S4-9 | Episode data is `pickle` (arbitrary code execution on load); two `.pkl` fixtures are committed |
| S4-10 | Mixin-based env architecture: helpers read attributes they do not own, guarded by defensive `getattr` defaults; not independently testable |
| S4-11 | `_process_counter_party` linear-scans all agents per fill; `set_agg_LOB` is called twice per step (the pre-action call is display-only) |
| S4-12 | No `evaluate.py` / serving path — no way to *use* a trained checkpoint |
| S4-13 | No property-based tests, despite the order book having clearly stated invariants (tree volume == Σ level volumes, no crossed book, Σ NAV == Σ initial cash) |

---

## What is genuinely good

It would misrepresent the repository to list only defects. The following are
above the standard for research code:

- **The matching engine is correct**, including the subtle parts: price/time
  priority, FIFO queues per level, priority loss on size increase and retention
  on decrease, book-walking for aggressive limits, and correct partial fills.
- **The ledger is exact and conserved.** `Decimal` throughout, and total NAV
  equals total initial cash to the cent after 300 random steps **[verified]**.
- **Buying-power logic is subtle and right** — only the risk-*increasing* portion
  of an order is cash-checked, so closing and covering always succeed, and market
  orders are priced off the contra side with a tape fallback.
- **The RLlib new-API-stack migration was done properly.** Module classes declared
  through `MultiRLModuleSpec` (the only thing the new stack reads),
  `RandomRLModule` as a true uniform sampler rather than a frozen random network,
  and per-module metrics keyed by real `ModuleID`.
- **The distributed self-play code is the strongest in the repo.** Four
  load-bearing ordering constraints in champion creation, each explained in
  comments at the RLlib-internals level and each covered by a regression test —
  including the `WEIGHTS_SEQ_NO` force-push and the `crc32`-vs-`hash()`
  determinism fix.
- **Integration tests guard their own premise.**
  `test_sampling_actually_happens_remotely` and
  `test_learner_group_is_actually_remote` prevent the remote suites from
  degrading into vacuous duplicates — a discipline most codebases lack.
- **Observation normalisation is well reasoned.** Midpoint-relative prices make
  the representation invariant to the random price anchor, and the two scalars
  that restore what the transform discards (`log_mid`, `log1p_spread_ticks`) are
  documented with their exact rationale, including why `0.0` is a safe sentinel.
- **Dependency pins are explained, not just asserted** (`gymnasium` ↔ Ray
  coupling; CPU-vs-CUDA torch wheel selection; Ray's `/dev/shm` requirement).
- **90 unit tests pass in under 9 seconds**, covering every position-flip path,
  cash-check edge case and observation invariant.

---

## Suggested sequencing

Roughly two weeks of work, ordered so each step unblocks the next.

**Phase 1 — make learning possible (≈2 days)**
1. Scale all reward terms to fractional-NAV units (fixes S1-1, S2-1, S2-3 together)
2. Set `grad_clip`; assert `vf_explained_var > 0` in CI
3. Make the drawdown penalty an increment
4. Normalise observation feature scales

**Phase 2 — make the problem well-posed (≈3 days)**
5. Add the private-state observation block (S1-2)
6. Terminate and flatten bankrupt agents (S2-4)
7. `size_mean → Box(0,1)`; scale or drop `size_sigma`
8. Positive decaying `entropy_coeff`; refuse zero-trade champions

**Phase 3 — market realism (≈3 days)**
9. Maker/taker fees in bps inside settlement
10. Self-match prevention; mark to mid
11. Order-flow imbalance + realised volatility in the observation (`helper.py` already has OFI)
12. Per-episode desk metrics through `metrics_logger`

**Phase 4 — engineering hygiene (≈3 days)**
13. `logging` replaces `print`; conservation violation raises
14. Fix `install_requires`; drop `six` and `sklearn`; seed the shuffle
15. `sys.exit` → `raise ValueError`
16. Delete dead code; fix the `build_algo` restore path
17. Add `ruff`/`black`/`pre-commit`/`pytest-cov`
