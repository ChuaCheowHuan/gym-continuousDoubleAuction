# Matching Engine

Order book mechanics: data structures, order processing, and the modify-order semantics that were
the subject of a significant bug fix.

Related: [architecture.md](architecture.md) §3 (where this sits), [accounting.md](accounting.md)
(what happens to cash when a fill occurs), [testing.md](testing.md) §1 (the tests that pin this
behaviour down).

---

## 1. Data structures

| Structure | File | Role |
|---|---|---|
| `Order` | [`order.py`](../envs/orderbook/order.py) | One order; node in a doubly linked list. `Decimal` price and quantity. |
| `OrderList` | [`orderlist.py`](../envs/orderbook/orderlist.py) | FIFO queue of all orders at one price. Head = highest time priority. Caches its own `volume`. |
| `OrderTree` | [`ordertree.py`](../envs/orderbook/ordertree.py) | `SortedDict` of price → `OrderList`, plus an `order_id → Order` map and a cached total `volume`. One tree per side. |
| `OrderBook` | [`orderbook.py`](../envs/orderbook/orderbook.py) | Owns both trees and the tape. Entry point for all order processing. |

The `volume` caches on `OrderList` and `OrderTree` are an optimisation, and keeping them in sync
with the actual sum of order quantities is a real invariant with a dedicated regression test
(see [testing.md](testing.md) §1.4).

---

## 2. Order processing

### Limit orders

`process_limit_order` walks the opposite tree while the incoming order crosses it, filling against
each price level in time-priority order, then rests any residual quantity in the book.

A consequence worth stating explicitly, because other parts of the system depend on it: **a resting
book can never be locked or crossed.** Any bid arriving at or above the best ask is filled on
arrival, so a two-sided resting book always has `best_ask - best_bid >= 1` tick. The
`log1p_spread_ticks` observation feature relies on this to keep its zero sentinel unambiguous
(see [observation_space.md](observation_space.md) §3.2).

### Market orders

Market orders sweep across price levels until their quantity is exhausted or the opposite side is
empty. An empty book returns zero trades rather than raising.

### The tape

Every fill appends a `transaction_record` carrying explicit `counter_party` and `init_party`
dictionaries. That party attribution is what lets the accounting layer debit both sides of a fill
and distinguish aggressive from passive execution — which the reward function needs for its passive
fill bonus.

### Order IDs

Every order processed receives a unique, monotonically incrementing ID.

---

## 3. Order modification

### 3.1 The bug that was fixed

`OrderBook.modify_order` originally updated price and quantity **in place** in the `OrderTree`
without re-running the matching engine. A bid could therefore be modified to a price above the best
ask and simply *sit there*, leaving the book crossed — a direct violation of double auction
mechanics. Separately, the trader's cash and hold balances were not adjusted for trades that
occurred *during* a modification, so account balances drifted.

### 3.2 Current book-level logic

| Case | Handling | Queue priority |
|---|---|---|
| Quantity **decreases** at the **same price** | Updated in place | **Kept** |
| Everything else (price move, price cross, quantity increase) | Removed and re-entered via `process_limit_order` | Lost |

Re-processing is what makes the engine correct: it triggers matches if the new price crosses the
book, produces proper `trades` and `residue` records, and moves the order to the back of the queue
— which is what real exchanges do for price changes and size increases.

### 3.3 Trader-level "undo-then-process" accounting

`Trader.__modify_limit_order` runs a three-step flow so that balances stay exact regardless of
whether the modification triggers a fill:

1. **Undo** — the account releases 100% of the value held against the *old* order, back to `cash`.
2. **Process** — the book modification executes, returning any immediate `trades` and the `residue`
   left resting.
3. **Resolve** — the trader's standard path processes the `trades` (updating position and cash) and
   puts the `residue` value back on hold.

### 3.4 The six scenarios

All six are covered by `test_modify_order.py`. Starting state for every walkthrough below:
**$10,000 cash, 0 position**, an existing **bid 10 @ 90** (so $9,100 cash, $900 hold), and a resting
**ask at 100**.

| # | Modification | Handling | Result |
|---|---|---|---|
| 1 | 10 @ 110 — price crosses | Re-process | Release $900 → buy 10 @ 100 for $1,000. **$9,000 cash, $0 hold, +10 position.** |
| 2 | 10 @ 95 — price moves, no cross | Re-process | Release $900 → post 10 @ 95, $950 to hold. **$9,050 cash, $950 hold, 0 position.** |
| 3 | 15 @ 90 — quantity increase | Re-process | Release $900 → post 15 @ 90, $1,350 to hold. **$8,650 cash, $1,350 hold, 0 position.** |
| 4 | 5 @ 90 — quantity decrease, same price | **In place** | Move (10−5) × 90 = $450 from hold to cash. **$9,550 cash, $450 hold, 0 position.** Priority kept. |
| 5 | 15 @ 110 — cross + quantity increase | Re-process | Release $900 → buy 10 @ 100 for $1,000 → rest 5 @ 110, $550 to hold. **$8,450 cash, $550 hold, +10 position.** |
| 6 | 5 @ 110 — cross + quantity decrease | Re-process | Release $900 → buy 5 @ 100 for $500, no residue. **$9,500 cash, $0 hold, +5 position.** |

### 3.5 Order identification

The external API addresses orders by `trade_id`, not by a unique `order_id`. A `modify` command
therefore targets the trader's **oldest existing order** on that side if several are present
(FIFO). `_get_order_ID` is deliberately **price-agnostic for modifications** but remains
**price-sensitive for plain `limit` orders**, so agents can still maintain several orders at
different price levels without accidentally overwriting one another.

---

## 4. Known invariants

These are asserted by the test suite and should be preserved by any change to this layer:

1. `best_bid < best_ask` for any two-sided resting book, including after a modification.
2. `OrderTree.volume` equals the sum of the volumes of every `OrderList` beneath it, including
   after partial fills.
3. Modifying an order's price does not double-delete it from its `OrderList` (a regression that
   previously surfaced as a `ValueError` or a negative internal counter).
4. Order IDs are unique and monotonically increasing.
5. A market order against an empty book is a no-op, not an exception.

Invariant 1 is currently only partially satisfied for one modification path — see
[testing.md](testing.md) §1.1, which documents `test_modify_order_price_change` as an
`@unittest.expectedFailure`.

---

## 5. Caveat: `sys.exit()` in the engine

[`orderbook.py`](../envs/orderbook/orderbook.py) calls `sys.exit()` on several bad-input paths. A
library that kills the interpreter takes down an RLlib rollout worker with a bare exit code and no
traceback. These should be exceptions. Tracked in [known_issues.md](known_issues.md) §3.8.
