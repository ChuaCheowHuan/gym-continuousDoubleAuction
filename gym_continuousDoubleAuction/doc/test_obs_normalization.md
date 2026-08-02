# Test Documentation - Observation Normalization Unit Tests

This document provides a detailed explanation of the unit tests implemented in [`test_obs_normalization.py`](../test/test_obs_normalization.py). These tests validate the LOB observation normalization pipeline introduced in `set_agg_LOB()`, the action price unnormalization mechanism in `_set_price()`, and all associated safety guards.

---

## Background: What is Being Tested

The observation fed to each RL agent is a normalized snapshot of the Limit Order Book (LOB). Raw prices and volumes are transformed as follows before being passed to the neural network:

- **Bid Prices**: $\text{norm\_P\_bid} = \frac{M - P_{bid}}{M} \ge 0$
- **Ask Prices**: $\text{norm\_P\_ask} = -\left(\frac{|P_{ask}| - M}{M}\right) \le 0$
- **Bid Volumes**: $\text{norm\_V\_bid} = \sqrt{V_{bid}} \ge 0$
- **Ask Volumes**: $\text{norm\_V\_ask} = -\sqrt{V_{ask}} \le 0$

where $M = \frac{P_{bid,1} + |P_{ask,1}|}{2}$ is the **Level 1 Midpoint Price**.

The raw unnormalized snapshot is stored in `self.agg_LOB_raw` and is used by `_set_price()` to resolve agent price-level selections into actual market prices.

---

## Observation Structure (40-element snapshot)

| Index Range | Feature | Expected Sign |
|---|---|---|
| `[0:10]` | Normalized bid prices (10 levels) | $\ge 0$ |
| `[10:20]` | Normalized bid volumes (10 levels) | $\ge 0$ |
| `[20:30]` | Normalized ask prices (10 levels) | $\le 0$ |
| `[30:40]` | Normalized ask volumes (10 levels) | $\le 0$ |

---

## Test Cases

### Group 1: `agg_LOB_raw` Existence & Correctness

#### 1. `test_agg_LOB_raw_exists_after_reset`
**Purpose**: Verifies that `self.agg_LOB_raw` is populated at the correct shape immediately after `env.reset()`.

- **Check**: Attribute exists, is a `numpy.ndarray`, and has shape `(40,)`.
- **Why**: If `agg_LOB_raw` is missing or malformed, `_set_price()` cannot retrieve unnormalized prices and will fall back to normalized values, causing incorrect order placement.

#### 2. `test_agg_LOB_raw_updated_after_step`
**Purpose**: Confirms that `agg_LOB_raw` is refreshed after a new order modifies the book.

- **Scenario**: Place a bid limit order after reset.
- **Check**: `agg_LOB_raw` after the step is not equal to the all-zero reset state and still has shape `(40,)`.
- **Why**: Stale raw data would cause action prices to reference outdated levels.

---

### Group 2: Sign Preservation in Normalized Observations

#### 3. `test_obs_signs_empty_book`
**Purpose**: Validates that an empty book produces an all-zero `(40,)` snapshot with no NaN or spurious values.

- **Scenario**: `env.reset()` with no orders placed.
- **Check**: All 40 elements of the normalized snapshot are exactly `0.0`.
- **Why**: Empty levels must map to 0, not to a normalized value of M (which would be non-zero).

#### 4. `test_bid_obs_non_negative_with_orders`
**Purpose**: After placing multiple bid limit orders, verifies all bid price and size slots are non-negative.

- **Scenario**: Place 4 bid limit orders at different levels.
- **Check**: `snapshot[0:10]` (bid prices) are all $\ge 0$; `snapshot[10:20]` (bid sizes) are all $\ge 0$.
- **Why**: The formula $(M - P_{bid})/M$ and $\sqrt{V_{bid}}$ are non-negative by construction; a regression here would indicate incorrect formula application.

#### 5. `test_ask_obs_non_positive_with_orders`
**Purpose**: After placing multiple ask limit orders, verifies all ask price and size slots are non-positive.

- **Scenario**: Place 4 ask limit orders at different levels.
- **Check**: `snapshot[20:30]` (ask prices) are all $\le 0$; `snapshot[30:40]` (ask sizes) are all $\le 0$.
- **Why**: The negation in $-\left(\frac{|P_{ask}| - M}{M}\right)$ and $-\sqrt{V_{ask}}$ preserves the sign convention; a failure here means the sign was dropped.

---

### Group 3: Midpoint Price Normalization Correctness

#### 6. `test_midpoint_price_normalization_correctness`
**Purpose**: Numerically verifies the exact midpoint-distance price normalization formula.

- **Scenario**: Pin `last_price = 100`. Place an ask at 101 (Level 1, Join) and a bid at 99 (Level 1, Join), so $M = (99 + 101) / 2 = 100$.
- **Check**:
  - Level-1 bid observation $= \frac{100 - 99}{100} = 0.01$.
  - Level-1 ask observation $= -\left(\frac{101 - 100}{100}\right) = -0.01$.
- **Why**: Directly validates the mathematical formula against the code output. Any change in the normalization formula will break this test.

#### 7. `test_level1_bid_ask_symmetric_distance`
**Purpose**: Confirms that at Level 1, the bid and ask normalized magnitudes are exactly equal (since they are symmetric around $M$).

- **Scenario**: Same as test 6 — bid at 99, ask at 101, $M = 100$.
- **Check**: `|norm_bid_price[0]| == |norm_ask_price[0]|` ($= 0.01$).
- **Why**: This symmetry is a key mathematical invariant: both sides are equidistant from the midpoint. A failure indicates the bid and ask formulas are not consistent with each other.

---

### Group 4: Volume Normalization Correctness

#### 8. `test_volume_normalization_sqrt`
**Purpose**: Verifies that the volume in the normalized observation equals $\pm\sqrt{\text{raw volume}}$.

- **Scenario**: Place a bid and an ask with known volumes. Read back `agg_LOB_raw` to get the raw volumes.
- **Check**:
  - `snapshot[10]` (bid size L1) $= \sqrt{\text{raw\_bid\_size}}$
  - `snapshot[30]` (ask size L1) $= -\sqrt{\text{raw\_ask\_size}}$
- **Why**: The $\sqrt{\cdot}$ transformation is the core volume-normalization contract; any regression (e.g., using raw volume or $V^2$) will be caught.

---

### Group 5: Division-by-Zero Safety

#### 9. `test_empty_book_uses_last_price_anchor`
**Purpose**: Ensures that when both bid and ask are absent (both zero), $M$ falls back to `self.last_price` and no numerical errors occur.

- **Scenario**: `env.reset()` (empty book); `env.last_price = 50.0`.
- **Check**: No `NaN` or `Inf` in the snapshot. Since all prices are 0, the entire snapshot is `0.0` (the `np.where` mask prevents division on empty levels).
- **Why**: Division by zero ($M = 0$) would propagate `NaN` to the entire observation and crash training.

#### 10. `test_zero_last_price_fallback`
**Purpose**: Verifies the ultimate safety net when `last_price` itself is 0 or negative (which would make the fallback $M = 0$).

- **Scenario**: Set `env.last_price = 0.0` after reset (simulating a corrupted state).
- **Check**: No `NaN` or `Inf` in the snapshot. (The code clamps $M$ to `100.0` in this case.)
- **Why**: Guards against corner cases where the anchor price is invalid.

---

### Group 6: Action Price Unnormalization

#### 11. `test_action_price_from_populated_book_is_raw`
**Purpose**: Confirms that when an agent selects a price level that has an existing order, `_set_price()` returns the actual raw market price (not the normalized value).

- **Scenario**: Place a bid at 99. Then select Level 0 (Join) for a new bid action.
- **Check**: The resolved action price equals `agg_LOB_raw[0]` (the raw bid Level-1 price, 99), not the normalized value 0.01.
- **Why**: If `_set_price()` accidentally reads from the normalized `agg_LOB` instead of `agg_LOB_raw`, agents would submit orders at completely wrong prices (e.g., 0.01 instead of 99).

#### 12. `test_action_price_is_positive`
**Purpose**: A broad end-to-end sanity check — over 10 random steps, every non-market resolved order price must be strictly positive.

- **Scenario**: Run 10 steps with randomly sampled actions across all agents.
- **Check**: For every action in `env.LOB_actions` where `price != -1.0` (the market order sentinel), assert `price > 0`.
- **Why**: Catches any edge case in ghost pricing, offset computation, or unnormalization that might produce a zero or negative price, which would be invalid for the LOB.

---

## How to Run

From the repository root:

```powershell
python gym_continuousDoubleAuction/test/test_obs_normalization.py
```

Or via the Jupyter notebook (standard library only, no pytest required):
```python
%run ../gym_continuousDoubleAuction/test/test_obs_normalization.py
```
