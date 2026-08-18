# 13. Perspective: Financial Trader / Quant

Scope: strategy logic, risk management, market data handling, execution realism, performance
metrics, alignment with financial objectives.

**Headline:** the matching engine is a faithful price/time-priority CDA and the clearing
arithmetic is exact and conserved. The gaps are in the *market model* around it — no transaction
costs, no margin, no self-match prevention, no liquidation, cash-collateralised shorts, and a
metrics layer that reports NAV but none of the risk-adjusted statistics a trading desk would
require.

---

## 1. What kind of market is this?

| Property | Implementation |
|---|---|
| Venue type | Single continuous double auction, price/time priority |
| Instrument | One unnamed contract, no expiry, no dividend, no carry |
| Participants | Only the RL agents — no exogenous flow, no designated market maker |
| Price formation | Fully endogenous; seeded by a random anchor in `[10, 100]` |
| Tick | 1.0 currency unit, fixed |
| Depth exposed | 10 levels per side |
| Fees | **None** |
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
always permitted. It even estimates a market order's cost from the contra side's best price,
falling back to the last tape print.
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
| **Latency** | Order-arrival sequence is a uniform shuffle each step. No agent can be systematically faster, so latency arbitrage / queue-jumping is unlearnable and unpunishable. |
| **Self-match prevention** | **[verified]** an agent can cross its own resting order and print a trade. Wash trading is a legal strategy here. |
| **Order stacking** | **[verified]** a trader can hold only **one** resting order per price level per side — a second limit at the same price *replaces* the first (level volume 7, not 12). Layering, iceberg and multi-clip quoting are impossible. |
| **Time-in-force / order types** | No IOC, FOK, post-only, stop, or hidden orders. Post-only in particular is fundamental to real market making. |
| **Market impact beyond the book** | Correct within the visible 10 levels; no permanent-impact or resilience model. |
| **Bankruptcy handling** | A negative-NAV agent is never terminated (§5). No forced liquidation, no margin call. |
| **Circuit breakers** | None. The price can jump arbitrarily far on a single sweep of a thin book. |
| **Opening/closing auction** | None. Episodes begin with an empty book and a synthetic price anchor. |

### 3.1 Self-matching

**[verified]**:

```
self-trade executed: True | tape len: 1 | same ID both sides: True
```

The code explicitly *handles* this case rather than preventing it: `_process_trades` branches on
`counter_party.ID == init_party.ID` and routes to `init_is_counter_cash_transfer`. The accounting
is consistent, so it does not corrupt NAV — but it means an agent can print arbitrary volume at
arbitrary prices at zero cost.

Because `mark_to_mkt` uses the **last tape print** as the mark, this is a direct **mark
manipulation channel**: an agent holding inventory can self-trade one contract at a favourable
price and instantly re-mark *everyone's* book — including its own reward. Real venues ban this
(SMP is mandatory on essentially every regulated venue) for exactly this reason.

**Fix:** in `process_order_list`, skip resting orders whose `trade_id` equals the incoming
`quote['trade_id']` (cancel-newest or cancel-resting semantics), or reject the order at
`_order_approved`.

### 3.2 The mark is the last print, however stale or thin

`mark_to_mkt` takes `self.LOB.tape[-1]['price']` unconditionally. Consequences:

- A single 1-lot print re-marks the entire market for every participant.
- On steps with no trades, the previous mark persists and `prev_nav` is not updated, so
  `nav_change` covers a multi-step gap rather than one step.
- Before the very first trade of an episode, NAV is never recomputed and all rewards are exactly
  0.

A mid-price mark (`(best_bid + best_ask)/2`, falling back to last trade) would be both more
standard and far harder to manipulate.

---

## 4. There are no transaction costs

`grep` for fee, commission, rebate, slippage, borrow across the env: nothing. There is no
maker/taker schedule, no exchange fee, no clearing fee, no borrow cost on shorts, no funding on
inventory.

The reward has *proxies* — `trade_penalty=0.05` per fill and `passive_bonus=0.1` per passive fill
— but they are flat per-fill constants and, at the measured per-step NAV scale of ±10⁴, are
**5–6 orders of magnitude too small to matter**. Functionally, trading is free.

Why a trader should care: with zero costs and a zero-sum book, the microstructure equilibrium is
degenerate. There is no bid-ask spread to *earn*, so market making has no revenue model; there is
no cost to crossing, so there is no reason to be patient. Every real market's structure — the
existence of a spread, the maker/taker split, the value of queue position — is a consequence of
costs. Take them out and the strategy space you are studying is not the one that exists.

**Fix:** charge in basis points of notional, applied inside the settlement path so it flows
through NAV rather than being bolted onto the reward:

```python
fee = notional * (TAKER_BPS if is_aggressor else MAKER_BPS) / 10_000
self.cash -= fee
```

with e.g. taker +2 bps / maker −0.5 bps. Note this makes the market *slightly* negative-sum in
NAV, so the `on_episode_end` conservation check must be relaxed to
`total_nav + total_fees == total_initial_cash`.

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

### What is missing

| Gap | Detail |
|---|---|
| **No position limit** | Nothing caps `net_position`. Size is bounded only by cash and by `limit_max_size = 1000` in the action space (`limit_size_mean_mul = 499.5`, so a full-scale draw is ≈ 500 contracts). |
| **No margin call / forced liquidation** | An agent can be marked to a negative NAV and simply sits there. |
| **No per-agent termination on bankruptcy** | **[verified]**: forcing `agent_0.nav = −50` yields `terminateds: {'agent_0': False, …}`. `set_done` records it in `done_set` but `set_all_done` overwrites all flags. The episode only ends when **every** agent is bust. |
| **No borrow/locate on shorts** | Unlimited short capacity subject only to cash. |
| **No intraday risk limits** | No max loss, no max order size relative to NAV, no fat-finger check. |
| **Drawdown is punished but not constrained** | The reward taxes drawdown; nothing prevents it. |

The **zombie-agent** problem deserves emphasis. A bankrupt agent cannot place new orders, so it
stops trading — but it keeps accruing the per-step drawdown penalty for the remainder of what may
be thousands of steps, and any resting orders it left in the book stay live and executable. Its
episode return is then dominated by a constant tax unrelated to its decisions, which is exactly
the signal the champion-promotion logic reads.

---

## 6. Market data handling

**Format.** The observation is a **normalised L2 snapshot**, 10 levels a side, frame-stacked 4
deep. Full spec in [05_observation_space.md](05_observation_space.md).

**Normalisation is well designed.** Prices are expressed as signed relative distance from the L1
midpoint, `(M − P_bid)/M` and `−(P_ask − M)/M`. This makes the representation invariant to the
episode's random price level — the right choice, and the same thing a practitioner does before
feeding a book to a model.

Because that transform *destroys* the price level, two scalars restore it:

- `log_mid = log(M)` — recovers the absolute price, which matters because `min_tick` is absolute
  (a 1-unit tick is worth 10× more at price 10 than at price 100).
- `log1p_spread_ticks` — the spread measured in the same tick units the action space quotes in,
  with `0.0` reserved as a sentinel for a one-sided book.

The reasoning is spelled out in the source comments and is correct.

**Sizes** use `sqrt` compression with a sign convention marking the side. Sound in principle;
unscaled in practice — **[verified]** the sqrt-size features reach ±47 while the price features
stay within ±0.58 in the same rollout.

### What a trader would additionally want in the feature vector

| Feature | Why |
|---|---|
| **Order-flow imbalance** | The single strongest short-horizon predictor in the microstructure literature. Helper code for it already exists — `train/helper/helper.py` computes `ord_imb` / `sum_ord_imb` — but it is imported by nothing. |
| **Trade flow / signed volume** | Aggressor-side volume over the last k steps. The tape loop in `set_agg_LOB` is a dead placeholder where this was clearly intended ([05](05_observation_space.md) §7.3). |
| Realised volatility | Rolling σ of mid returns |
| Microprice | `(bid_sz·ask_px + ask_sz·bid_px)/(bid_sz+ask_sz)` — better fair value than mid |
| Book slope / cumulative depth | Liquidity beyond L1 |
| Own queue position | See §5 and [12](12_perspective_rl_researcher.md) §2 — currently absent entirely |
| Time remaining | Inventory should be flattened near the close |

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
| League mean/std return, league size, promotions, idle modules | RLlib metrics |
| NAV, drawdown, reward decomposition, execution-quality and order-book charts | `visualize/run_all.py` |

### What is absent

The gap has narrowed from "nothing but NAV" to a specific list. The counters and levels a desk
statistic is computed *from* are all captured now — inventory, drawdown, maker fills, spread — and
the per-step Parquet record holds the NAV trajectory the path-dependent ones need. What is missing
is the reduction, not the input:

- **Sharpe / Sortino** on the per-step NAV return series — computable from the record, not computed
- **Maximum drawdown over the episode** — the per-step *level* is reported; the episode maximum is
  not reduced into a metric
- **Hit rate**, average win / average loss
- **Turnover** and P&L per unit of turnover
- **Time-weighted inventory** — mean and max |position| are metrics; the time-weighted version is not
- **Realised vs unrealised P&L split** — `profit` and `total_profit` exist on the account but are
  not exported to `info`
- **Quote presence / time at the touch** — the basic market-making KPI. This one genuinely needs
  new computation: nothing tracks how long an agent's order rested at the best price
- **Adverse selection** — mark-out P&L at t+k after a passive fill. Also new computation

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

**Recommendation:** the remaining reductions belong in `SelfPlayCallback.on_episode_end` beside
the ones already there, or in `visualize/` for anything that needs the whole trajectory. See
[11_logging_and_observability.md](11_logging_and_observability.md) §1.2 and §2.

---

## 8. Strategy logic — what can actually be learned here?

Mapping the action space to real strategy archetypes:

| Archetype | Expressible? | Blocker |
|---|---|---|
| **Passive market making** | Partially | Can quote at a level with a passive offset — but only **one order per price level**, no post-only, no fee rebate, and the agent cannot see its own queue position or inventory |
| **Directional / momentum** | Barely | Only 4 stacked public snapshots; no trade-flow or volatility features |
| **Mean reversion** | Barely | Same |
| **Inventory management** | **No** | The agent cannot observe its own inventory |
| **Spread capture** | **No** | Zero fees means there is no spread revenue to capture (§4) |
| **Order anticipation** | Partially | Frame stacking gives some order-flow history, but no per-participant attribution and the frames are not comparable ([05](05_observation_space.md) §7.1) |
| **Wash / mark manipulation** | **Yes — unintentionally** | No SMP, and the mark is the last print (§3.1) |
| **Latency arbitrage** | No | Arrival order is a uniform shuffle |

The uncomfortable summary: under the current configuration, the strategy that best satisfies the
reward is *quote nothing, trade nothing* (see
[12_perspective_rl_researcher.md](12_perspective_rl_researcher.md) §3.3), and the most
exploitable non-trivial channel is self-trading to move the mark. Neither is the intended
research object.

---

## 9. Alignment with financial objectives

| Stated objective (from the reward's own docstring) | Achieved? |
|---|---|
| "Maximizing NAV" | Yes — `nav_change` is the dominant term |
| "Reducing number of trades" | No — the 0.05 penalty is ~10⁵× too small |
| "Selective order placement" | No — same, 0.1 penalty |
| "Lowering drawdown risk" | **Over-achieved** — the penalty is ~2.4× the entire NAV term (**[verified]**) and drives the policy to inaction |
| "Capturing spread" | No — the 0.1 passive bonus is negligible, and there are no spread economics to capture |

The intent is sound and reads like it was written by someone who trades. The implementation
collapses to "NAV change, minus an enormous drawdown tax". Putting every term on a common scale —
fractional-NAV units — would make the stated objective the realised one.

---

## 10. Prioritised trading-realism agenda

| # | Change | Effort | Why |
|---|---|---|---|
| 1 | Express all reward terms in fractional-NAV units | S | Makes the four secondary objectives actually bind |
| 2 | Add maker/taker fees in bps inside settlement | M | Creates spread economics; makes market making a real strategy |
| 3 | Self-match prevention | S | Closes the wash-trade / mark-manipulation channel |
| 4 | Mark to mid, not last print | S | Removes single-print mark manipulation; more standard |
| 5 | Terminate + flatten bankrupt agents | S | Removes zombies and stale resting orders |
| 6 | Expose own position, NAV, drawdown, resting orders in obs | M | Prerequisite for any inventory-aware strategy |
| 7 | Add order-flow imbalance + signed trade volume + realised vol to obs (`helper.py` already has OFI; the tape loop is a ready-made hook) | S | The highest-value predictive features in microstructure |
| 8 | Per-episode desk metrics (Sharpe, max DD, turnover, maker ratio, inventory) | M | Makes "is this agent any good?" answerable |
| 9 | Allow multiple resting orders per price level | M | Unlocks layering / multi-clip quoting |
| 10 | Position limits and a margin/liquidation rule | M | Real risk control rather than a reward penalty |
| 11 | Post-only and IOC order types | M | Required for realistic market making |
| 12 | An exogenous information process (a latent fundamental + informed traders) | L | Turns redistribution into price discovery, which is what the microstructure framing needs |
