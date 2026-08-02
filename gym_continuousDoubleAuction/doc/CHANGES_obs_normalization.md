# Orderbook Observation Normalization & Action Price Unnormalization — Change Log

## Overview

This document details the implementation of **midpoint-based price normalization** and **square-root volume normalization** for stacked orderbook observations in `gym-continuousDoubleAuction`, alongside the **action price unnormalization mechanism**. 

---

## 1. Motivation

### Why Normalize Observations?

Raw limit order book (LOB) snapshots feature large, unbounded price values (e.g. $100.0$) and high-variance volume sizes (e.g. $1000.0$ shares). Feeding raw values directly to neural network agents can cause gradient instability and slow convergence. 

1. **Symmetric Price Normalization**: By scaling price depth relative to the **Level 1 Midpoint Price ($M$)**, price features become scale-invariant percentages representing relative depth distance from the top of the book.
2. **Variance-Stabilizing Volume Normalization**: Applying $\sqrt{\text{volume}}$ dampens extreme volume spikes while preserving relative liquidity signals.
3. **Observation Sign Preservation**: Bids remain non-negative ($\ge 0$) and asks remain non-positive ($\le 0$), maintaining spatial distinction between buy and sell depth.
4. **Action Price Unnormalization**: While agents perceive normalized observations, their discrete price choices (levels 0–9) must resolve to real, unnormalized market prices when placing orders into the actual LOB.

---

## 2. Mathematical Formulation

### 2.1 Level 1 Midpoint Price ($M$)
Let $P_{bid, 1} = \text{bid\_price\_list}[0]$ and $P_{ask, 1} = |\text{ask\_price\_list}[0]|$.

$$M = \begin{cases} 
\frac{P_{bid, 1} + P_{ask, 1}}{2} & \text{if } P_{bid, 1} > 0 \text{ and } P_{ask, 1} > 0 \\
P_{bid, 1} & \text{if } P_{bid, 1} > 0 \text{ and } P_{ask, 1} = 0 \\
P_{ask, 1} & \text{if } P_{bid, 1} = 0 \text{ and } P_{ask, 1} > 0 \\
\text{self.last\_price} & \text{if both } P_{bid, 1} = 0 \text{ and } P_{ask, 1} = 0
\end{cases}$$

If $M \le 0$, $M$ safely defaults to $100.0$ to prevent any possibility of division by zero.

### 2.2 Price Normalization
For level $k \in \{0 \dots 9\}$:
- **Bid Price Observation**:
  $$\text{norm\_P\_bid}_k = \begin{cases} \frac{M - P_{bid, k}}{M} & \text{if } P_{bid, k} > 0 \\ 0.0 & \text{if } P_{bid, k} = 0 \end{cases}$$
  *(Since $P_{bid, k} \le M$, $\text{norm\_P\_bid}_k \ge 0$ represents the percentage distance below the midpoint).*

- **Ask Price Observation**:
  $$\text{norm\_P\_ask}_k = \begin{cases} -\left( \frac{|P_{ask, k}| - M}{M} \right) & \text{if } |P_{ask, k}| > 0 \\ 0.0 & \text{if } |P_{ask, k}| = 0 \end{cases}$$
  *(Since $|P_{ask, k}| \ge M$, the distance is non-negative and negated to preserve the negative ask sign convention).*

### 2.3 Volume Normalization
For level $k \in \{0 \dots 9\}$:
- **Bid Size Observation**: $\text{norm\_V\_bid}_k = \sqrt{V_{bid, k}} \ge 0$
- **Ask Size Observation**: $\text{norm\_V\_ask}_k = -\sqrt{V_{ask, k}} \le 0$

---

## 3. Code Modifications

### 3.1 `gym_continuousDoubleAuction/envs/exchg/state_helper.py`
- Updated `set_agg_LOB()`:
  - Generates unnormalized raw snapshot `self.agg_LOB_raw`.
  - Calculates Level 1 midpoint $M$ with fallbacks.
  - Applies price normalization $(\frac{M - P_{bid}}{M}, -\frac{|P_{ask}| - M}{M})$ and volume normalization $(\pm\sqrt{V})$.
  - Returns flattened 40-element normalized snapshot.

### 3.2 `gym_continuousDoubleAuction/envs/exchg/action_helper.py`
- Updated `_set_price()`:
  - Accesses `self.agg_LOB_raw` via `getattr(self, 'agg_LOB_raw', self.agg_LOB)` to retrieve unnormalized level prices.
  - Converts agent price-level selections into actual unnormalized market order prices.

### 3.3 `gym_continuousDoubleAuction/envs/exchg/exchg_helper.py` & `continuousDoubleAuction_env.py`
- Initialized `self.agg_LOB_raw = {}` across constructor and `reset()` routines.

---

## 4. Test Suite

### `gym_continuousDoubleAuction/test/test_obs_normalization.py` *(new file)*

A `unittest`-based test suite (no pytest dependency) covering all normalization invariants:

| Test | What it verifies |
|---|---|
| `test_agg_LOB_raw_exists_after_reset` | `self.agg_LOB_raw` is present and shaped `(40,)` after `reset()`. |
| `test_agg_LOB_raw_updated_after_step` | `agg_LOB_raw` changes after placing an order. |
| `test_obs_signs_empty_book` | Empty book produces an all-zero normalized snapshot. |
| `test_bid_obs_non_negative_with_orders` | Bid price and size features are $\ge 0$ after orders are placed. |
| `test_ask_obs_non_positive_with_orders` | Ask price and size features are $\le 0$ after orders are placed. |
| `test_midpoint_price_normalization_correctness` | Normalized Level-1 bid and ask prices match manual computation of $(M - P_{bid})/M$ and $-(|P_{ask}| - M)/M$. |
| `test_level1_bid_ask_symmetric_distance` | Level-1 normalized bid and ask distances are equal in magnitude ($=$ half-spread $/M$). |
| `test_volume_normalization_sqrt` | Size features equal $\pm\sqrt{\text{raw volume}}$. |
| `test_empty_book_uses_last_price_anchor` | No NaN or Inf appears when the book is empty (fallback to `last_price`). |
| `test_zero_last_price_fallback` | No NaN or Inf appears when `last_price` is 0 (fallback to `100.0`). |
| `test_action_price_from_populated_book_is_raw` | Agent price-level selection resolves to the actual unnormalized market price from `agg_LOB_raw`. |
| `test_action_price_is_positive` | All non-market resolved order prices are strictly $> 0$ across random steps. |

**Run from the repository root:**
```powershell
python gym_continuousDoubleAuction/test/test_obs_normalization.py
```

