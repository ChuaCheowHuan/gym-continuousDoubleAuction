# 4. Perspective: Financial Trader / Quant

Scope: strategy logic, risk management, market data handling, execution realism,
performance metrics, alignment with financial objectives.

**Headline:** the matching engine is a faithful price/time-priority CDA and the
clearing arithmetic is exact and conserved. The gaps are in the *market model*
around it — no transaction costs, no margin, no self-match prevention, no
liquidation, cash-collateralised shorts, and a metrics layer that reports NAV but
none of the risk-adjusted statistics a trading desk would require.

---

## 4.1 What kind of market is this?

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
| Zero-sum | Yes, exactly (**[verified]**) |

The right mental model is **a closed poker table with a limit order book**, not
an equity market. Every unit of P&L one agent earns is paid by another. There is
no drift, no risk premium, no external alpha. A strategy can only be profitable
by being better at extracting from the other seven participants.

---

## 4.2 Execution realism — what is modelled correctly

This part is genuinely good, and better than most academic LOB simulators.

**Price/time priority is real.** `OrderTree` sorts levels by price; `OrderList`
is a FIFO doubly-linked queue within a level
([`orderlist.py:45-57`](../gym_continuousDoubleAuction/envs/orderbook/orderlist.py#L45-L57)).
Matching consumes from the head
([`orderbook.py:65-69`](../gym_continuousDoubleAuction/envs/orderbook/orderbook.py#L65-L69)).

**Queue-position economics are correct.** Increasing a resting order's size
forfeits priority (moved to the tail); decreasing it retains priority
([`order.py:29-36`](../gym_continuousDoubleAuction/envs/orderbook/order.py#L29-L36),
[`orderbook.py:237-240`](../gym_continuousDoubleAuction/envs/orderbook/orderbook.py#L237-L240)).
This is the actual exchange rule and it is the single most important
microstructure detail for a market-making strategy. Getting it right is a
meaningful signal of care.

**Aggressive limit orders walk the book.** `process_limit_order`
([`orderbook.py:154-186`](../gym_continuousDoubleAuction/envs/orderbook/orderbook.py#L154-L186))
matches against every crossing level until the limit price is exhausted, then
rests the remainder. Market orders sweep until filled or the book is empty
([`orderbook.py:136-152`](../gym_continuousDoubleAuction/envs/orderbook/orderbook.py#L136-L152)).
Partial fills are handled correctly and covered by
`test_partial_fill` and `test_orderbook_volume_sync.py`.

**No locked or crossed book.** Because a crossing order fills on arrival, a
resting book always has `best_ask > best_bid`. The observation code relies on
this to use `log1p_spread_ticks == 0.0` as an unambiguous "no two-sided market"
sentinel ([`state_helper.py:151-165`](../gym_continuousDoubleAuction/envs/exchg/state_helper.py#L151-L165)) —
a nice, tested invariant (`test_orderbook_crossed_book.py`).

**Exact money arithmetic.** Prices, quantities and cash are `Decimal`
throughout ([`order.py:12-15`](../gym_continuousDoubleAuction/envs/orderbook/order.py#L12-L15),
[`account.py:11-23`](../gym_continuousDoubleAuction/envs/account/account.py#L11-L23)),
with `Decimal(str(x))` conversion at the float boundary
([`orderbook.py:49`](../gym_continuousDoubleAuction/envs/orderbook/orderbook.py#L49)).
No float drift in the ledger. This is why the NAV conservation check passes to
the cent.

**Buying power is enforced before execution.** `_order_approved`
([`trader.py:68-111`](../gym_continuousDoubleAuction/envs/agent/trader.py#L68-L111))
computes the *opening* portion of an order — the part that increases risk — and
only cash-checks that. Closing or covering is always permitted. It even
estimates a market order's cost from the contra side's best price, falling back
to the last tape print. `test_cash_check.py::test_position_flip_insufficient_cash`
covers the hard case (long 10, sell 20, only the 10-lot short leg needs cash).

**Cash is reserved, not spent, on order placement.** `order_in_book_passive_party`
moves notional from `cash` to `cash_on_hold`
([`cash_processor.py:15-29`](../gym_continuousDoubleAuction/envs/account/cash_processor.py#L15-L29)),
so NAV is invariant to quoting. Cancels release it
([`cash_processor.py:94-106`](../gym_continuousDoubleAuction/envs/account/cash_processor.py#L94-L106)).
That is the correct broker model and it is why an agent cannot quote infinite
size.

---

## 4.3 Execution realism — what is missing

| Missing | Consequence for strategy learning |
|---|---|
| **Latency** | Order-arrival sequence is a uniform shuffle each step. No agent can be systematically faster, so latency arbitrage / queue-jumping is unlearnable and unpunishable. |
| **Self-match prevention** | **[verified]** an agent can cross its own resting order and print a trade. Wash trading is a legal strategy here. |
| **Order stacking** | **[verified]** a trader can hold only **one** resting order per price level — a second limit at the same price *replaces* the first (level volume 7, not 12). Layering, iceberg and multi-clip quoting are impossible. |
| **Time-in-force / order types** | No IOC, FOK, post-only, stop, or hidden orders. Post-only in particular is fundamental to real market making. |
| **Market impact beyond the book** | Correct within the visible 10 levels; no permanent-impact or resilience model. |
| **Bankruptcy handling** | A negative-NAV agent is never terminated (see §4.5). No forced liquidation, no margin call. |
| **Circuit breakers** | None. The price can jump arbitrarily far on a single sweep of a thin book. |
| **Opening/closing auction** | None. Episodes begin with an empty book and a synthetic price anchor. |

### 4.3.1 Self-matching

**[verified]**:

```
self-trade executed: True | tape len: 1 | same ID both sides: True
```

The code explicitly handles this case rather than preventing it:
`_process_trades` branches on `counter_party.ID == init_party.ID` and routes to
`init_is_counter_cash_transfer`
([`trader.py:275-284`](../gym_continuousDoubleAuction/envs/agent/trader.py#L275-L284),
[`cash_processor.py:55-62`](../gym_continuousDoubleAuction/envs/account/cash_processor.py#L55-L62)).
The accounting is consistent, so it does not corrupt NAV — but it means an agent
can print arbitrary volume at arbitrary prices at zero cost. Because
`mark_to_mkt` uses the **last tape print** as the mark
([`exchg_helper.py:47-51`](../gym_continuousDoubleAuction/envs/exchg/exchg_helper.py#L47-L51)),
this is a direct **mark manipulation channel**: an agent holding inventory can
self-trade one contract at a favourable price and instantly re-mark *everyone's*
book — including its own reward. Real venues ban this (SMP is mandatory on
essentially every regulated venue) for exactly this reason.

**Fix:** in `process_order_list`, skip resting orders whose `trade_id` equals the
incoming `quote['trade_id']` (cancel-newest or cancel-resting semantics), or
reject the order at `_order_approved`.

### 4.3.2 The mark is the last print, however stale or thin

`mark_to_mkt` takes `self.LOB.tape[-1]['price']` unconditionally. Consequences:

- A single 1-lot print re-marks the entire market for every participant.
- On steps with no trades, the previous mark persists and `prev_nav` is not
  updated, so `nav_change` covers a multi-step gap rather than one step.
- Before the very first trade of an episode, NAV is never recomputed and all
  rewards are exactly 0.

A mid-price mark (`(best_bid + best_ask)/2`, falling back to last trade) would be
both more standard and far harder to manipulate.

---

## 4.4 There are no transaction costs

`grep` for fee, commission, rebate, slippage, borrow across the env: nothing.
There is no maker/taker schedule, no exchange fee, no clearing fee, no borrow
cost on shorts, no funding on inventory.

The reward has *proxies* — `trade_penalty=0.05` per fill and
`passive_bonus=0.1` per passive fill
([`reward_helper.py:28-30`](../gym_continuousDoubleAuction/envs/exchg/reward_helper.py#L28-L30)) —
but they are flat per-fill constants and, at the measured per-step NAV scale of
±10⁴, are **5–6 orders of magnitude too small to matter**. Functionally, trading
is free.

Why a trader should care: with zero costs and a zero-sum book, the microstructure
equilibrium is degenerate. There is no bid-ask spread to *earn*, so market making
has no revenue model; there is no cost to crossing, so there is no reason to be
patient. Every real market's structure — the existence of a spread, the
maker/taker split, the value of queue position — is a consequence of costs. Take
them out and the strategy space you are studying is not the one that exists.

**Fix:** charge in basis points of notional, applied inside the settlement path
so it flows through NAV rather than being bolted onto the reward:

```python
fee = notional * (TAKER_BPS if is_aggressor else MAKER_BPS) / 10_000
self.cash -= fee
```

with e.g. taker +2 bps / maker −0.5 bps. Note this makes the market
*slightly* negative-sum in NAV, so the `on_episode_end` conservation check must
be relaxed to `total_nav + total_fees == total_initial_cash`.

---

## 4.5 Risk management

### What exists

- **Solvency gate.** `_order_approved` rejects any new order when `nav <= 0`
  ([`trader.py:79-80`](../gym_continuousDoubleAuction/envs/agent/trader.py#L79-L80)).
- **Buying-power check** on the risk-increasing portion only (§4.2).
- **Full cash collateral** on both longs and shorts — effectively 100% initial
  margin, no leverage. Confirmed by `test_limit_order_placement_hold`: a limit
  *sell* at 102 puts 102 on hold, exactly as a buy would.
- **High-water mark** tracked per account (`max_nav`,
  [`calculate.py:12-13`](../gym_continuousDoubleAuction/envs/account/calculate.py#L12-L13))
  and used as a drawdown penalty in the reward.

### What is missing

| Gap | Detail |
|---|---|
| **No position limit** | Nothing caps `net_position`. Size is bounded only by cash (limit orders up to 5,000 contracts, `limit_max_size = 100 × 10`, [`action_helper.py:9-12`](../gym_continuousDoubleAuction/envs/exchg/action_helper.py#L9-L12)). |
| **No margin call / forced liquidation** | An agent can be marked to a negative NAV and simply sits there. |
| **No per-agent termination on bankruptcy** | **[verified]**: forcing `agent_0.nav = −50` yields `terminateds: {'agent_0': False, …}`. `set_done` records it in `done_set` but `set_all_done` overwrites all flags ([`done_helper.py:32-33`](../gym_continuousDoubleAuction/envs/exchg/done_helper.py#L32-L33)). The episode only ends when **every** agent is bust. |
| **No borrow/locate on shorts** | Unlimited short capacity subject only to cash. |
| **No intraday risk limits** | No max loss, no max order size relative to NAV, no fat-finger check. |
| **Drawdown is punished but not constrained** | The reward taxes drawdown; nothing prevents it. |

The **zombie-agent** problem deserves emphasis. A bankrupt agent cannot place new
orders, so it stops trading — but it keeps accruing the per-step drawdown
penalty (§3.3.3) for the remainder of what may be thousands of steps, and any
resting orders it left in the book stay live and executable. Its episode return
is then dominated by a constant tax unrelated to its decisions, which is exactly
the signal the champion-promotion logic reads.

---

## 4.6 Market data handling

**Format.** The observation is a **normalised L2 snapshot**, 10 levels a side,
frame-stacked 4 deep
([`state_helper.py:70-171`](../gym_continuousDoubleAuction/envs/exchg/state_helper.py#L70-L171)).

**Normalisation is well designed.** Prices are expressed as signed relative
distance from the L1 midpoint, `(M − P_bid)/M` and `−(P_ask − M)/M`. This makes
the representation invariant to the episode's random price level — the right
choice, and the same thing a practitioner does before feeding a book to a model.

Because that transform *destroys* the price level, two scalars restore it:

- `log_mid = log(M)` — recovers the absolute price, which matters because
  `min_tick` is absolute (a 1-unit tick is worth 10× more at price 10 than at
  price 100).
- `log1p_spread_ticks` — the spread measured in the same tick units the action
  space quotes in, with `0.0` reserved as a sentinel for a one-sided book.

The reasoning is spelled out in the source comments
([`state_helper.py:144-165`](../gym_continuousDoubleAuction/envs/exchg/state_helper.py#L144-L165))
and is correct.

**Sizes** use `sqrt` compression with a sign convention marking the side. Sound
in principle; unscaled in practice — **[verified]** the sqrt-size features reach
±51 while the price features stay within ±0.26 (see
[03 §3.8](03_perspective_rl_researcher.md#38-training-stability)).

### What a trader would additionally want in the feature vector

| Feature | Why |
|---|---|
| **Order-flow imbalance** | The single strongest short-horizon predictor in the microstructure literature. Helper code for it already exists — `helper.py:14-26` computes `ord_imb`/`sum_ord_imb` — but it is not wired into the observation. |
| Trade-flow / signed volume | Aggressor-side volume over the last k steps |
| Realised volatility | Rolling σ of mid returns |
| Microprice | `(bid_sz·ask_px + ask_sz·bid_px)/(bid_sz+ask_sz)` — better fair value than mid |
| Book slope / cumulative depth | Liquidity beyond L1 |
| Own queue position | See §3.2 — currently absent entirely |
| Time remaining | Inventory should be flattened near the close |

The `pic/ten_k/` directory contains plots named `ord_imb.png` and `sum_imb.png`,
so order imbalance was studied at some point; it just never became a model input.

---

## 4.7 Performance metrics

### What is measured

| Metric | Where |
|---|---|
| NAV per agent, per step | `info["NAV"]` ([`info_helper.py:16-20`](../gym_continuousDoubleAuction/envs/exchg/info_helper.py#L16-L20)) |
| Cumulative trade count | `info["num_trades"]` |
| Reward | `info["reward"]` |
| `total_profit` = NAV − initial NAV | [`calculate.py:16-22`](../gym_continuousDoubleAuction/envs/account/calculate.py#L16-L22) |
| System NAV / system profit | [`exchg_helper.py:233-251`](../gym_continuousDoubleAuction/envs/exchg/exchg_helper.py#L233-L251) |
| NAV conservation check | end of every episode, callback |
| League mean/std return | logged to RLlib metrics |
| NAV / cumulative-reward plots | `visualize/visualize_nav.py`, `visualize_rewards.py` |

### What is absent

Every risk-adjusted statistic a desk would use:

- **Sharpe / Sortino** on the per-step NAV return series
- **Maximum drawdown** as a reported metric (it is penalised in the reward but
  never reported)
- **Hit rate**, average win / average loss
- **Turnover** and P&L per unit of turnover
- **Inventory statistics** — mean and max |position|, time-weighted inventory
- **Maker/taker fill ratio** — the counters exist (`num_passive_fills_step`) but
  are consumed by the reward and reset, never logged
- **Realised vs unrealised P&L split** — `profit` and `total_profit` exist on the
  account but are not exported to `info`
- **Quote presence / time at the touch** — the basic market-making KPI
- **Adverse selection** — mark-out P&L at t+k after a passive fill

Note also that `info["NAV"]` is serialised as a **string**
([`info_helper.py:18`](../gym_continuousDoubleAuction/envs/exchg/info_helper.py#L18)) —
presumably to survive `Decimal` JSON encoding — and every consumer parses it back
with `float()` ([`callback:251`](../gym_continuousDoubleAuction/train/callbk/league_based_self_play_callback.py#L251),
[`visualize_nav.py`](../gym_continuousDoubleAuction/visualize/visualize_nav.py)).
That round-trip discards the exactness `Decimal` was chosen for, and it makes the
info dict awkward for RLlib metric aggregation.

**Recommendation:** compute per-episode desk metrics in
`SelfPlayCallback.on_episode_end` and push them through `metrics_logger.log_value`
so they land in TensorBoard alongside returns. The episode-end hook already has
everything it needs.

---

## 4.8 Strategy logic — what can actually be learned here?

Mapping the action space to real strategy archetypes:

| Archetype | Expressible? | Blocker |
|---|---|---|
| **Passive market making** | Partially | Can quote at a level with a passive offset — but only **one order per price level**, no post-only, no fee rebate, and the agent cannot see its own queue position or inventory |
| **Directional / momentum** | Barely | Only 4 stacked public snapshots; no trade-flow or volatility features |
| **Mean reversion** | Barely | Same |
| **Inventory management** | **No** | The agent cannot observe its own inventory (§3.2) |
| **Spread capture** | **No** | Zero fees means there is no spread revenue to capture (§4.4) |
| **Order anticipation** | Partially | Frame stacking gives some order-flow history, but no per-participant attribution |
| **Wash / mark manipulation** | **Yes — unintentionally** | No SMP, and the mark is the last print (§4.3.1) |
| **Latency arbitrage** | No | Arrival order is a uniform shuffle |

The uncomfortable summary: under the current configuration, the strategy that
best satisfies the reward is *quote nothing, trade nothing* (see
[03 §3.3.2](03_perspective_rl_researcher.md#332-doing-nothing-is-a-dominant-strategy)),
and the most exploitable non-trivial channel is self-trading to move the mark.
Neither is the intended research object.

---

## 4.9 Alignment with financial objectives

| Stated objective (from the reward's own docstring, [`reward_helper.py:10-21`](../gym_continuousDoubleAuction/envs/exchg/reward_helper.py#L10-L21)) | Achieved? |
|---|---|
| "Maximizing NAV" | Yes — `nav_change` is the dominant term |
| "Reducing number of trades" | No — the 0.05 penalty is ~10⁵× too small |
| "Selective order placement" | No — same, 0.1 penalty |
| "Lowering drawdown risk" | **Over-achieved** — the penalty is ~2× the entire NAV term (**[verified]**) and drives the policy to inaction |
| "Capturing spread" | No — the 0.1 passive bonus is negligible, and there are no spread economics to capture |

The intent is sound and reads like it was written by someone who trades. The
implementation collapses to "NAV change, minus an enormous drawdown tax". Putting
every term on a common scale — fractional-NAV units — would make the stated
objective the realised one.

---

## 4.10 Prioritised trading-realism agenda

| # | Change | Effort | Why |
|---|---|---|---|
| 1 | Express all reward terms in fractional-NAV units | S | Makes the four secondary objectives actually bind |
| 2 | Add maker/taker fees in bps inside settlement | M | Creates spread economics; makes market making a real strategy |
| 3 | Self-match prevention | S | Closes the wash-trade / mark-manipulation channel |
| 4 | Mark to mid, not last print | S | Removes single-print mark manipulation; more standard |
| 5 | Terminate + flatten bankrupt agents | S | Removes zombies and stale resting orders |
| 6 | Expose own position, NAV, drawdown, resting orders in obs | M | Prerequisite for any inventory-aware strategy |
| 7 | Add order-flow imbalance + realised vol to obs (`helper.py` already has OFI) | S | The highest-value predictive features in microstructure |
| 8 | Per-episode desk metrics (Sharpe, max DD, turnover, maker ratio, inventory) | M | Makes "is this agent any good?" answerable |
| 9 | Allow multiple resting orders per price level | M | Unlocks layering / multi-clip quoting |
| 10 | Position limits and a margin/liquidation rule | M | Real risk control rather than a reward penalty |
| 11 | Post-only and IOC order types | M | Required for realistic market making |
