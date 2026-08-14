# Accounting

The cash, position, and NAV model. This is the most carefully engineered part of the repository and
the part with the tightest test coverage.

Related: [matching_engine.md](matching_engine.md) (what produces the fills),
[testing.md](testing.md) §2 (the tests), [reward_function.md](reward_function.md) (what consumes
these numbers).

---

## 1. Quantities tracked per trader

[`account.py`](../envs/account/account.py):

| Field | Meaning |
|---|---|
| `cash` | Available liquid capital |
| `cash_on_hold` | Capital escrowed against resting limit orders |
| `position_val` | Market value of the open position |
| `net_position` | Signed quantity held — positive long, negative short |
| `VWAP` | Volume-weighted average entry price |
| `nav` | Net asset value = `cash + cash_on_hold + position_val` |
| `max_nav` | High-water mark of NAV, used for the drawdown penalty |
| `num_trades_step`, `num_passive_fills_step`, `order_step_placed` | Per-step reward counters, reset at the end of each step |

All arithmetic is `Decimal`. This is what makes the simulation exactly zero-sum: total NAV across
all traders is conserved and equals total initial cash, and `total_sys_profit ≈ 0`. The invariant is
checked at runtime in `exchg_helper.py` and again by the league callback at episode end.

---

## 2. The escrow model

[`cash_processor.py`](../envs/account/cash_processor.py) implements a simple margin/escrow scheme:

- **Resting an order** moves `size × price` from `cash` to `cash_on_hold`. This is what stops
  agents placing unlimited orders.
- **Cancelling** moves it back.
- **Filling** converts the held amount into `position_val` (and realised cash movement).

Both sides are escrowed. A limit *sell* holds cash as margin exactly as a limit *buy* does, so a
short position is cash-backed rather than free.

**NAV is invariant across placement and cancellation.** Moving money between `cash` and
`cash_on_hold` does not change wealth, and the tests assert this explicitly.

---

## 3. Order approval

`Trader._order_approved` ([`trader.py`](../envs/agent/trader.py)) gates every order on two
conditions:

1. **NAV must be positive.** A bankrupt trader can place nothing.
2. **The opening portion must be cash-backed.**

The second condition is the subtle one. Only the part of an order that *increases* exposure needs
cash:

```
if the order is on the same side as the current position:
    opening_size = size                          # increasing
else:
    opening_size = max(0, size - abs(net_position))   # decreasing, covering, or flipping
```

If `opening_size <= 0` the order is purely closing and is approved without a cash check — you never
need capital to flatten. Otherwise `opening_size × est_price` is compared against `cash`.

For market orders (`price == -1.0`) the estimate is the best price on the opposite side, falling
back to the last tape price, falling back to 1.

---

## 4. Position transitions

`Account.process_acc` branches on the current position sign and on what the fill does to it:

| Transition | Handling |
|---|---|
| Increase (same side) | Add to position, update VWAP |
| Decrease (opposite side, smaller than position) | Realise P&L on the closed portion, release capital |
| Full cover (exactly flat) | Realise everything, position and `position_val` go to zero |
| **Flip** (opposite side, larger than position) | `_covered_side_chg` — close the old position *and* open the new one atomically |

The flip case is the one most toy exchanges get wrong. If a trader is long 1 and sells 2, the first
unit closes the long (releasing capital) and the second opens a short (locking capital), in a single
transaction, with `net_position` moving from +1 to −1 and cash/NAV preserved throughout. Four
dedicated tests cover it — aggressor and passive, in both directions.

---

## 5. Mark to market

`mark_to_mkt` revalues every account at the last tape price each step, producing unrealised P&L:

- **Long 1 @ 100**, price → 110: NAV +10. Price → 90: NAV −10.
- **Short 1 @ 100**, price → 110: NAV −10. Price → 90: NAV +10.

`cal_nav` in [`calculate.py`](../envs/account/calculate.py) also updates `max_nav` whenever a new
peak is reached, which is what the drawdown term of the reward reads.

---

## 6. Worked example: partial fill

Agent A bids 2 @ 100; Agent B sells 1 @ 100.

| Stage | A's cash | A's hold | A's position value | A's NAV |
|---|---|---|---|---|
| After placing the bid | −200 | +200 | 0 | unchanged |
| After 1 unit fills | −200 | 100 | 100 | unchanged |

One unit stays escrowed against the still-resting half of the order; the other has become a
position. Wealth never moved.
