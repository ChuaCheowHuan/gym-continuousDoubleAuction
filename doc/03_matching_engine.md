# 3. Matching Engine

Order book mechanics: data structures, order processing, and the modify-order semantics that were
the subject of a significant bug fix.

Related: [02_architecture.md](02_architecture.md) §2.2 (where this sits),
[04_accounting.md](04_accounting.md) (what happens to cash when a fill occurs),
[10_testing.md](10_testing.md) §1 (the tests that pin this behaviour down).

Adapted from `dyn4mik3/OrderBook`. **This is the most correct layer in the repository** — it gets
the subtle microstructure rules right, which is unusual for an academic LOB simulator.

---

## 1. Data structures

| Structure | File | Role |
|---|---|---|
| `Order` | [`order.py`](../gym_continuousDoubleAuction/envs/orderbook/order.py) | One order; node in a doubly linked list. `Decimal` price and quantity. |
| `OrderList` | [`orderlist.py`](../gym_continuousDoubleAuction/envs/orderbook/orderlist.py) | FIFO queue of all orders at one price. Head = highest time priority. Caches its own `volume`. |
| `OrderTree` | [`ordertree.py`](../gym_continuousDoubleAuction/envs/orderbook/ordertree.py) | `SortedDict` of price → `OrderList`, plus an `order_id → Order` map and a cached total `volume`. One tree per side. |
| `OrderBook` | [`orderbook.py`](../gym_continuousDoubleAuction/envs/orderbook/orderbook.py) | Owns both trees and the tape. Entry point for all order processing. |

The `volume` caches on `OrderList` and `OrderTree` are an optimisation, and keeping them in sync
with the actual sum of order quantities is a real invariant with a dedicated regression test
(see [10_testing.md](10_testing.md) §1.4).

**Exact money arithmetic.** Prices, quantities and cash are `Decimal` throughout, with
`Decimal(str(x))` conversion at the float boundary
([`orderbook.py:49`](../gym_continuousDoubleAuction/envs/orderbook/orderbook.py#L49)). There is
no float drift in the ledger, which is why NAV conservation holds to the cent.

---

## 2. Order processing

### 2.1 Limit orders

`process_limit_order`
([`orderbook.py:154-186`](../gym_continuousDoubleAuction/envs/orderbook/orderbook.py#L154-L186))
walks the opposite tree while the incoming order crosses it, filling against each price level in
time-priority order, then rests any residual quantity in the book.

A consequence worth stating explicitly, because other parts of the system depend on it: **a
resting book can never be locked or crossed.** Any bid arriving at or above the best ask is
filled on arrival, so a two-sided resting book always has `best_ask - best_bid >= 1` tick. The
`log1p_spread_ticks` observation feature relies on this to keep its zero sentinel unambiguous
(see [05_observation_space.md](05_observation_space.md) §3.2).

### 2.2 Market orders

`process_market_order`
([`orderbook.py:136-152`](../gym_continuousDoubleAuction/envs/orderbook/orderbook.py#L136-L152))
sweeps across price levels until the quantity is exhausted or the opposite side is empty. An
empty book returns zero trades rather than raising.

### 2.3 Queue-position economics

`process_order_list`
([`orderbook.py:58-133`](../gym_continuousDoubleAuction/envs/orderbook/orderbook.py#L58-L133))
consumes strictly from the head of each `OrderList`, and
[`order.py:29-36`](../gym_continuousDoubleAuction/envs/orderbook/order.py#L29-L36) implements the
real exchange rule for resting-order amendments:

| Amendment | Queue priority |
|---|---|
| Quantity **decreases** at the same price | **Kept** — updated in place |
| Quantity **increases**, or price moves | **Lost** — moved to the tail |

This is the single most important microstructure detail for a market-making strategy, and
getting it right is a meaningful signal of care.

### 2.4 The tape

Every fill appends a `transaction_record` carrying explicit `counter_party` and `init_party`
dictionaries:

```python
transaction_record['counter_party'] = {'ID': ..., 'side': ..., 'order_id': ...,
                                       'new_book_quantity': ...}
transaction_record['init_party']    = {'ID': ..., 'side': ..., 'order_id': None,
                                       'new_book_quantity': None}
```

That party attribution is what lets the accounting layer debit both sides of a fill and
distinguish aggressive from passive execution — which the reward function needs for its
passive-fill bonus, and which `mark_to_mkt` needs for the price.

### 2.5 Order IDs

Every order processed receives a unique, monotonically incrementing ID (`next_order_id`).

### 2.6 What is *not* enforced

| Missing | Consequence |
|---|---|
| **Self-match prevention** | An agent can cross its own resting order and print a trade. **[verified]** — this is a mark-manipulation channel; see [13_perspective_financial_trader.md](13_perspective_financial_trader.md) §3.1. |
| **Multiple orders per price level per trader** | A trader holds at most one resting order per (side, price). A second limit at the same price *replaces* the first. **[verified]** — see §3.5. |
| **Time-in-force / order types** | No IOC, FOK, post-only, stop or hidden orders. |
| **Latency model** | Arrival order is a uniform shuffle each env step. |
| **Circuit breakers, halts, auctions** | None. Price can jump arbitrarily far on a single sweep of a thin book. |

---

## 3. Order modification

### 3.1 The bug that was fixed

`OrderBook.modify_order` originally updated price and quantity **in place** in the `OrderTree`
without re-running the matching engine. A bid could therefore be modified to a price above the
best ask and simply *sit there*, leaving the book crossed — a direct violation of double auction
mechanics. Separately, the trader's cash and hold balances were not adjusted for trades that
occurred *during* a modification, so account balances drifted.

### 3.2 Current book-level logic

| Case | Handling | Queue priority |
|---|---|---|
| Quantity **decreases** at the **same price** | Updated in place | **Kept** |
| Everything else (price move, price cross, quantity increase) | Removed and re-entered via `process_limit_order` | Lost |

Re-processing is what makes the engine correct: it triggers matches if the new price crosses the
book, produces proper `trades` and `residue` records, and moves the order to the back of the
queue — which is what real exchanges do for price changes and size increases.

### 3.3 Trader-level "undo-then-process" accounting

`Trader.__modify_limit_order`
([`trader.py:177-192`](../gym_continuousDoubleAuction/envs/agent/trader.py#L177-L192))
runs a three-step flow so balances stay exact regardless of whether the modification fills:

1. **Undo** — `acc.cancel_cash_transfer(order)` releases 100% of the value held against the *old*
   order, back to `cash`.
2. **Process** — `orderBook.modify_order` executes, returning any immediate `trades` and the
   `residue` left resting.
3. **Resolve** — the trader's standard path processes the `trades` (updating position and cash)
   and `order_in_book_passive_party` puts the residue value back on hold.

### 3.4 The six scenarios

All six are covered by `test_modify_order.py`. Starting state for every walkthrough:
**$10,000 cash, 0 position**, an existing **bid 10 @ 90** (so $9,100 cash, $900 hold), and a
resting **ask at 100**.

| # | Modification | Handling | Result |
|---|---|---|---|
| 1 | 10 @ 110 — price crosses | Re-process | Release $900 → buy 10 @ 100 for $1,000. **$9,000 cash, $0 hold, +10 position.** |
| 2 | 10 @ 95 — price moves, no cross | Re-process | Release $900 → post 10 @ 95, $950 to hold. **$9,050 cash, $950 hold, 0 position.** |
| 3 | 15 @ 90 — quantity increase | Re-process | Release $900 → post 15 @ 90, $1,350 to hold. **$8,650 cash, $1,350 hold, 0 position.** |
| 4 | 5 @ 90 — quantity decrease, same price | **In place** | Move (10−5) × 90 = $450 from hold to cash. **$9,550 cash, $450 hold, 0 position.** Priority kept. |
| 5 | 15 @ 110 — cross + quantity increase | Re-process | Release $900 → buy 10 @ 100 for $1,000 → rest 5 @ 110, $550 to hold. **$8,450 cash, $550 hold, +10 position.** |
| 6 | 5 @ 110 — cross + quantity decrease | Re-process | Release $900 → buy 5 @ 100 for $500, no residue. **$9,500 cash, $0 hold, +5 position.** |

### 3.5 Order identification

The external API addresses orders by `trade_id`, not by a unique `order_id`. `_get_order_ID`
([`trader.py:214-247`](../gym_continuousDoubleAuction/envs/agent/trader.py#L214-L247))
collects every resting order whose `trade_id` matches the caller, then:

- **`modify`** — deliberately **price-agnostic**: returns the trader's **oldest** matching order
  on that side (`min` by timestamp, FIFO).
- **`limit` and `cancel`** — **price-sensitive**: returns only the order at exactly the requested
  price, so agents can maintain several orders at *different* price levels without overwriting
  one another.

The consequence of the `limit` branch is the upsert behaviour in `_place_limit_order`: if an
order already rests at that exact price for that trader, a new limit *modifies* it rather than
adding a second. **[verified]** — two bids of 5 and 7 lots at price 90 from the same trader leave
one order and a level volume of 7, not 12. Placing at a *different* price does create a second
level, as expected.

This makes layering, iceberg and multi-clip quoting inexpressible. See
[13_perspective_financial_trader.md](13_perspective_financial_trader.md) §8.

### 3.6 Cancellation

`_cancel_limit_order` locates the order at the named price, calls `orderBook.cancel_order`, and
then `acc.cancel_cash_transfer(order)` to release the escrow. If nothing matches, it silently
returns empty lists — no penalty, no signal, nothing in `infos`.

---

## 4. Known invariants

These are asserted by the test suite and should be preserved by any change to this layer:

1. `best_bid < best_ask` for any two-sided resting book, **including after a modification**.
2. `OrderTree.volume` equals the sum of the volumes of every `OrderList` beneath it, including
   after partial fills.
3. Modifying an order's price does not double-delete it from its `OrderList` (a regression that
   previously surfaced as a `ValueError` or a negative internal counter).
4. Order IDs are unique and monotonically increasing.
5. A market order against an empty book is a no-op, not an exception.

> **Correction to the older documentation.** `doc/matching_engine.md` §4 stated that invariant 1
> was "only partially satisfied" because `test_modify_order_price_change` was marked
> `@unittest.expectedFailure`. That is no longer true — there is no `expectedFailure` anywhere in
> the repository, and the test asserts `get_best_bid() == Decimal('101')` and passes. Invariant 1
> holds on every modification path.

---

## 5. Caveat: `sys.exit()` in the engine

[`orderbook.py`](../gym_continuousDoubleAuction/envs/orderbook/orderbook.py) calls `sys.exit()`
on six bad-input paths (lines 39, 55, 151, 185, 200, 225; two more are commented out):

```python
if quote['quantity'] <= 0:
    sys.exit('process_order() given order of quantity <= 0')
```

`sys.exit` raises `SystemExit`, which derives from `BaseException`, not `Exception`. Inside a Ray
EnvRunner actor this will not be caught by ordinary handlers: it kills the worker, RLlib marks it
unhealthy, and the training run degrades or hangs rather than failing with a usable traceback.
These should all be `raise ValueError(...)`.

Currently unreachable in practice — decoded size is `rint(abs(N(...))) + min_size ≥ 1` — but it
is one action-space change away from being reachable. Tracked as S3-6 in
[15_findings_and_recommendations.md](15_findings_and_recommendations.md).
