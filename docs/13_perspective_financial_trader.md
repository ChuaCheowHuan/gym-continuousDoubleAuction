# 13. Perspective: Financial Trader / Quant

Scope: strategy logic, risk management, market data handling, execution realism, performance
metrics, alignment with financial objectives.

**Headline:** the matching engine is a faithful price/time-priority CDA and the clearing
arithmetic is exact and conserved. The market model around it now has maker/taker fees (opt-in),
self-match prevention, a mid-price mark, maintenance margin with liquidation and auto-deleveraging,
and the risk-adjusted statistics a desk would ask for. What remains is structural: no exogenous
information process, cash-collateralised shorts with no borrow cost, no position limits, no order
types beyond limit and market, and no latency model. The defects this document used to list, and
how each was fixed, are in [29_fixed_issues.md](29_fixed_issues.md).

---

## 1. What kind of market is this?

| Property | Implementation |
|---|---|
| Venue type | Single continuous double auction, price/time priority |
| Instrument | One unnamed contract, no expiry, no dividend, no carry |
| Participants | Only the RL agents — no exogenous flow, no designated market maker |
| Price formation | Fully endogenous; seeded by a random anchor in `[10, 100]` |
| Tick | `tick_size`, 1.0 currency unit by default |
| Depth exposed | ±10 ticks around the reference price (`book_mode: "grid"`), or 10 levels per side (`"levels"`) |
| Fees | Maker/taker in bps of notional (`maker_fee_bps`, `taker_fee_bps`); **0 by default** |
| Settlement | Instantaneous, T+0, no clearing house |
| Short selling | Allowed, 100% cash-collateralised, no borrow fee, no locate |
| Leverage | **None** — 1:1 cash-collateralised both directions |
| Halts / limits / auctions | None |
| Zero-sum in NAV | Yes, exactly (**[verified]**) |

The right mental model is **a closed poker table with a limit order book**, not an equity market.
Every unit of P&L one agent earns is paid by another. There is no drift, no risk premium, no
external alpha. A strategy can only be profitable by being better at extracting from the other
participants.

**No exogenous information process, so there is nothing to discover.** The classic microstructure
setups this evokes (Kyle, Glosten–Milgrom) all require informational asymmetry to generate
meaningful price discovery, spreads, and adverse selection. Without a fundamental value, informed
traders, news, or exogenous liquidity demand, "profit" is purely redistribution among agents
reacting to each other, and any emergent LOB shape is an artifact of the action-space
parameterization rather than of a market mechanism. The environment is a valid *game*; the
framing as a market simulator overreaches.

---

## 2. Execution realism — what is modelled correctly

This part is genuinely good, and better than most academic LOB simulators.

**Price/time priority is real.** `OrderTree` sorts levels by price; `OrderList` is a FIFO
doubly-linked queue within a level. Matching consumes from the head.

**Queue-position economics are correct.** Increasing a resting order's size forfeits priority
(moved to the tail); decreasing it retains priority. This is the actual exchange rule and it is
the single most important microstructure detail for a market-making strategy. Getting it right is
a meaningful signal of care.

**Aggressive limit orders walk the book.** `process_limit_order` matches against every crossing
level until the limit price is exhausted, then rests the remainder. Market orders sweep until
filled or the book is empty. Partial fills are handled correctly and covered by `test_partial_fill`
and `test_orderbook_volume_sync.py`.

**No locked or crossed book.** Because a crossing order fills on arrival, a resting book always
has `best_ask > best_bid`. The observation code relies on this to use
`log1p_spread_ticks == 0.0` as an unambiguous "no two-sided market" sentinel — a nice, tested
invariant (`test_orderbook_crossed_book.py`), and one that now holds on *every* modification path.

**Exact money arithmetic.** Prices, quantities and cash are `Decimal` throughout, with
`Decimal(str(x))` conversion at the float boundary. No float drift in the ledger. This is why the
NAV conservation check passes to the cent.

**Buying power is enforced before execution.** `_order_approved` computes the *opening* portion
of an order — the part that increases risk — and only cash-checks that. Closing or covering is
always permitted, a cancel is never checked, a modify may spend the escrow it releases, and margin
held against a resting *exit* order counts as buying power for a new position. A market order is
priced across every level it would sweep, not at the touch. (The defects this rule once had are
[S1-5](29_fixed_issues.md#s1-5--the-cash-check-is-bypassable-position-is-not-bounded-by-capital-verified-fixed), [S2-13](29_fixed_issues.md#s2-13--a-cancel-was-cash-checked-like-a-new-order-so-an-over-committed-trader-could-not-cancel-verified-fixed) and S2-14.)
`test_cash_check.py::test_position_flip_insufficient_cash` covers the hard case (long 10, sell
20, only the 10-lot short leg needs cash). This is subtle and right.

**Cash is reserved, not spent, on order placement.** `order_in_book_passive_party` moves notional
from `cash` to `cash_on_hold`, so NAV is invariant to quoting. Cancels release it. That is the
correct broker model and it is why an agent cannot quote infinite size.

**Position flips are atomic.** `_covered_side_chg` closes the old position and opens the new one
in a single transaction with cash and NAV preserved throughout — the case most toy exchanges get
wrong, with four dedicated tests.

---

## 3. Execution realism — what is missing

| Missing | Consequence for strategy learning |
|---|---|
| **Latency** | Order-arrival sequence is a uniform shuffle each step (or a batch clear, `step_clearing: "batch"`). No agent can be systematically faster, so latency arbitrage / queue-jumping is unlearnable and unpunishable. |
| **Order stacking, by default** | A trader holds one resting order per price level per side unless `allow_multiple_orders_per_level` is set (off by default, [S3-10](29_fixed_issues.md#s3-10--a-trader-can-hold-only-one-resting-order-per-price-level-verified-fixed---as-an-option)). With it off, a second limit at the same price replaces the first, so layering and multi-clip quoting need the option. |
| **Time-in-force / order types** | No IOC, FOK, post-only, stop, or hidden orders. Post-only in particular is fundamental to real market making. |
| **Market impact beyond the book** | Correct within the visible book; no permanent-impact or resilience model. |
| **Circuit breakers** | None. The price can jump arbitrarily far on a single sweep of a thin book. |
| **Opening/closing auction** | None. Episodes begin with an empty book and a synthetic price anchor. |

### 3.1 Self-matching is prevented

An incoming order that would cross the trader's own resting order withdraws that resting order
first (cancel-resting SMP, `Trader._prevent_self_match`), as every regulated venue requires.

### 3.2 The mark is the midpoint

Accounts are marked at the L1 midpoint when the book is two-sided (`mark_price_source: "mid"`), so
a single 1-lot print no longer re-marks the market; `"last"` reproduces the old last-print mark.
Moving the mark now takes a real two-sided market, and moving the mid means posting a better quote
somebody else can lift.

Self-matching combined with a last-print mark used to be a free mark-manipulation channel:
[S2-5](29_fixed_issues.md#s2-5--self-matching-enables-mark-manipulation-verified-fixed); what else the last-print mark did is in
[29](29_fixed_issues.md#13-32--the-mark-was-the-last-print-however-stale-or-thin).

---

## 4. Transaction costs are opt-in

Maker/taker fees in basis points of notional are charged inside settlement and collected by an
exchange ledger, so NAV conservation reads `sum(NAV) + fees == starting cash`
([04](04_accounting.md) §9, [18](18_configuration.md) §3.0.4). The taker pays `taker_fee_bps`,
the maker `maker_fee_bps` (negative is a rebate). **Both ship at 0**, and borrow cost and funding
are absent.

So a default run is still a cost-free market, and the trader's objection still applies to it.
With zero costs and a zero-sum book, the microstructure equilibrium is degenerate: there is no
bid-ask spread to *earn*, so market making has no revenue model, and no cost to crossing, so there
is no reason to be patient. Every real market's structure (the existence of a spread, the
maker/taker split, the value of queue position) is a consequence of costs. A run that studies
market making should set the fees; the reward's `passive_bonus == trade_penalty` expresses a small
spread price on its own.

When there were no fees at all and the reward's proxies were too small to matter: [S2-3](29_fixed_issues.md#s2-3--transaction-cost-proxies-are-10⁵-too-small-verified-fixed) and
[29](29_fixed_issues.md#13-4--there-were-no-transaction-costs).

---

## 5. Risk management

### What exists

- **Solvency gate.** `_order_approved` rejects any new order when `nav <= 0`.
- **Buying-power check** on the risk-increasing portion only (§2).
- **Full cash collateral** on both longs and shorts — effectively 100% initial margin, no
  leverage. Confirmed by `test_limit_order_placement_hold`: a limit *sell* at 102 puts 102 on
  hold, exactly as a buy would.
- **High-water mark** tracked per account (`max_nav`) and used as a drawdown penalty in the
  reward.
- **Maintenance margin and liquidation.** A trader whose equity falls to `maintenance_margin` of
  its position's value is closed out in the book, with auto-deleveraging for what the book cannot
  absorb; a trader at NAV <= 0 is terminated individually and its orders leave the book
  ([04](04_accounting.md) §8).

### What is missing

| Gap | Detail |
|---|---|
| **No position limit** | Nothing caps `net_position`. Size is bounded only by cash and by `limit_max_size = 1000` in the action space (`limit_size_mul = 499.5`, so a full-scale size is ≈ 500 contracts). |
| **No borrow/locate on shorts** | Unlimited short capacity subject only to cash. |
| **No intraday risk limits** | No max loss, no max order size relative to NAV, no fat-finger check. |
| **Drawdown is punished but not constrained** | The reward taxes drawdown; nothing prevents it. |

A bankrupt agent used to keep its flag at `False` and linger as a zombie charged a drawdown every
step: [S2-4](29_fixed_issues.md#s2-4--bankrupt-agents-are-never-terminated-verified-fixed).

---

## 6. Market data handling

**Format.** The observation is a **normalised L2 snapshot**, 10 levels a side, frame-stacked 4
deep. Full spec in [05_observation_space.md](05_observation_space.md).

**Normalisation is well designed.** In the level view prices are expressed as relative distance
from the L1 midpoint, `(M − P_bid)/M` and `(P_ask − M)/M`, both non-negative; in the default grid
view each cell is a fixed tick offset from the reference price. Either way the representation is
invariant to the episode's random price level — the right choice, and the same thing a
practitioner does before feeding a book to a model.

Because that transform *destroys* the price level, two scalars restore it:

- `log_mid = log(M)` — recovers the absolute price, which matters because `min_tick` is absolute
  (a 1-unit tick is worth 10× more at price 10 than at price 100).
- `log1p_spread_ticks` — the spread measured in the same tick units the action space quotes in,
  with `0.0` reserved as a sentinel for a one-sided book.

The reasoning is spelled out in the source comments and is correct.

**Sizes** are `sqrt(V / limit_max_size)`, units-free like the prices, so every book feature lands
within ±1.2 ([05](05_observation_space.md) §2.3). They used to reach ±47 against prices within
±0.58: [S2-2](29_fixed_issues.md#s2-2--unnormalised-observation-scales-saturate-the-tanh-mlp-verified-fixed).

### What a trader would additionally want in the feature vector

| Feature | Why |
|---|---|
| **Order-flow imbalance over a window** | The single strongest short-horizon predictor in the microstructure literature. Each frame carries the last step's `signed_volume`, trade count and direction ([05](05_observation_space.md) §3.4, [S2-7](29_fixed_issues.md#s2-7--no-trade-flow-information--the-tape-loop-is-dead-code-verified-fixed)); a longer window is only what the 4-frame stack gives |
| Realised volatility | Rolling σ of mid returns |
| Microprice | `(bid_sz·ask_px + ask_sz·bid_px)/(bid_sz+ask_sz)` — better fair value than mid |
| Book slope / cumulative depth | Liquidity beyond L1 |
| Own queue position | The agent sees its own resting size at each level ([05](05_observation_space.md) §1.0.1) but not where in the queue it sits |

The `pic/ten_k/` directory contains plots named `ord_imb.png` and `sum_imb.png`, so order
imbalance was studied at some point; it just never became a model input.

---

## 7. Performance metrics

### What is measured

| Metric | Where |
|---|---|
| NAV per agent, per step | `info["NAV"]` ([`info_helper.py`](../gym_continuousDoubleAuction/envs/exchg/info_helper.py)), and the `nav` / `nav_str` columns of the Parquet record |
| Inventory, VWAP, cash, cash-on-hold, position value | `info`, per agent per step, and their own columns |
| Drawdown level and the running peak | `info["drawdown"]`, `info["max_nav"]` |
| Top of book and the raw spread | `info["best_bid"]` / `["best_ask"]` / `["spread"]` — recorded rather than derived and discarded |
| Per-step activity | `num_trades_step`, `num_passive_fills_step`, `order_step_placed`, `num_rejected_step`, `is_pass_action` |
| Reward, decomposed | `info["reward"]` and `info["reward_terms"]` — five signed contributions summing to it |
| Cumulative trade count | `info["num_trades"]` |
| `total_profit` = NAV − initial NAV | [`calculate.py`](../gym_continuousDoubleAuction/envs/account/calculate.py) |
| System NAV / system profit | [`exchg_helper.py`](../gym_continuousDoubleAuction/envs/exchg/exchg_helper.py) |
| NAV conservation check | end of every episode, callback |
| Per-episode desk metrics | `episode_nav_mean/_min/_max`, `mean_agent_drawdown`, `mean_abs_net_position`, `mean_num_trades`, `maker_fill_ratio_max` |
| Risk-adjusted performance, per module | `module_sharpe`, `module_sortino`, `module_max_drawdown`, `module_hit_rate`, `module_position_turnover`, `module_mean_abs_position`, `module_max_abs_position` ([11](11_logging_and_observability.md) §1.2) |
| P&L attribution, per module | `module_realised_pnl`, `module_unrealised_pnl`, and adverse-selection mark-outs `module_markout_<h>` for each `markout_horizons` entry |
| League mean/std return, league size, promotions, idle modules | RLlib metrics |
| NAV, drawdown, reward decomposition, execution-quality and order-book charts | `visualize/run_all.py` |

### What is absent

Most of what a desk would ask for is now reduced into a metric ([S3-9](29_fixed_issues.md#s3-9--no-risk-adjusted-performance-metrics-fixed)). Still absent:

- **Average win / average loss**, and P&L per unit of turnover
- **Time-weighted inventory**: mean and max |position| are metrics; the time-weighted version is not
- **Quote presence / time at the touch**, the basic market-making KPI. Nothing tracks how long an
  agent's order rested at the best price

One caveat on the maker/taker ratio, because the obvious version of it is a tautology here: in a
closed double auction exactly one side of every fill is passive, so the *aggregate* maker share is
0.5 in every episode regardless of behaviour. A real 3-iteration run reported 0.5000 three times,
which is what exposed it. `maker_fill_ratio_max` — the most maker-like agent's share of its own
fills, among agents with enough fills for the ratio to mean anything — is the version that carries
information.

Note also that `info["NAV"]` is serialised as a **string**. That is deliberate: it is the exact
`str()` of a `Decimal`, and the conservation check parses it back with `Decimal` rather than
`float`, which is what makes the check exact instead of approximate. The other money fields are
floats, because they are read for plots and diagnostics where a float is both sufficient and
directly usable. The Parquet record carries both — `nav` for arithmetic and `nav_str` for the
exact value.

**Recommendation:** the remaining reductions belong in `train/performance.py` beside the ones
already there, or in `visualize/` for anything that needs the whole trajectory. See
[11_logging_and_observability.md](11_logging_and_observability.md) §1.2 and §2.

---

## 8. Strategy logic — what can actually be learned here?

Mapping the action space to real strategy archetypes:

| Archetype | Expressible? | Blocker |
|---|---|---|
| **Passive market making** | Partially | Can quote at a tick offset with a passive or joining price, and sees its inventory and resting size; one order per price level unless `allow_multiple_orders_per_level` is set, no post-only, and fees (so a rebate) only if configured |
| **Directional / momentum** | Partially | Trade-flow scalars and four comparable stacked frames; no volatility feature |
| **Mean reversion** | Partially | Same |
| **Inventory management** | **Yes** | Position, exposure, entry price and time remaining are in the private block |
| **Spread capture** | Only with fees on | At default fees the only spread price is `passive_bonus == trade_penalty`, a small one (§4) |
| **Order anticipation** | Partially | Comparable frames give order-flow history, but no per-participant attribution |
| **Wash / mark manipulation** | **No** | Self-match prevention and a mid mark (§3) |
| **Latency arbitrage** | No | Arrival order is a uniform shuffle |

Inventory-aware market making is now expressible, and the manipulation channel is closed. What a
policy will actually learn is an open research question rather than one the environment answers
by construction. The table as it stood before the fixes, when the best response was *quote
nothing, trade nothing*, is in
[29](29_fixed_issues.md#13-8--what-could-be-learned-before-the-fixes).

---

## 9. Alignment with financial objectives

| Stated objective (from the reward's own docstring) | Achieved? |
|---|---|
| "Maximizing NAV" | Yes — `nav_change` is the dominant term, and zero-sum across agents |
| "Reducing number of trades" | Yes, as a price — `order_penalty` and `trade_penalty` are fractions of starting capital calibrated against the measured move distribution |
| "Selective order placement" | Same |
| "Lowering drawdown risk" | Yes — the drawdown term charges the signed change, which telescopes to the final drawdown instead of taxing every step under the peak |
| "Capturing spread" | Partly — a passive fill is net-free and an aggressive one costs 0.2 bps; real spread economics need the fees (§4) |

Every term is on a common scale, fractional-NAV units, so the stated objective is the realised one.
How it used to collapse to "NAV change, minus an enormous drawdown tax" is in
[29](29_fixed_issues.md#13-9--alignment-with-the-rewards-stated-objectives-before-the-fixes).

---

## 10. Prioritised trading-realism agenda

Items 1–9 of the original agenda are done, and the liquidation half of 10: fractional-NAV reward
units, fees, self-match prevention, a mid mark, bankrupt termination, private state, trade flow,
desk metrics, multiple orders per level, and maintenance margin with liquidation. The table, with
what closed each item, is in [29](29_fixed_issues.md#13-10--the-trading-realism-agenda-done-items).
What is left (position limits, post-only and IOC orders, an exogenous information process) is
in [15](15_findings_and_recommendations.md#open-from-the-perspective-reviews).
