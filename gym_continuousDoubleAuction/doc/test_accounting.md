# Walkthrough - Accounting Mechanism Unit Test Explanation

This document provides a detailed, step-by-step explanation of the unit tests implemented in `test_accounting.py`. These tests validate the micro accounting processes, including cash management, position tracking, and Net Asset Value (NAV) calculations within the Continuous Double Auction (CDA) environment.

---

## core Concepts: Micro Accounting Processes

The system tracks several key metrics for each trader:
- **Cash**: Available liquid capital.
- **Cash on Hold**: Capital locked due to active limit orders.
- **Position Value**: The current market value of open positions (long or short).
- **Net Position**: The quantity of the asset held (positive for long, negative for short).
- **NAV (Net Asset Value)**: Total wealth, calculated as `Cash + Cash on Hold + Unrealized P&L` (or more simply in this system: `Cash + Cash on Hold + Position Value`).

---

## Test Cases Detailed Explanation

### 1. `test_limit_order_placement_hold`
**Purpose**: Verifies that placing a limit order correctly "locks" cash.
- **Long Scenario**: Trader A places a Limit Buy for 1 unit @ 100.
    - **Step 1**: Cash decreases by 100.
    - **Step 2**: Cash on hold increases by 100.
    - **Step 3**: NAV remains constant at 1000.
- **Short Scenario**: Trader B places a Limit Sell for 1 unit @ 102.
    - **Step 1**: Cash decreases by 102 (acting as margin).
    - **Step 2**: Cash on hold increases by 102.
    - **Step 3**: NAV remains constant at 1000.

### 2. `test_limit_order_cancellation`
**Purpose**: Ensures that cancelling an order releases the locked cash.
- **Process**: Place a limit order (long or short) and then immediately cancel it.
- **Verification**: Cash should return to the original balance, and cash on hold should return to zero.

### 3. `test_market_short_matching`
**Purpose**: Validates the accounting when a market sell order (short) matches a passive buy order.
- **Agent A (Passive Maker, Long)**:
    - Hold is released.
    - Net position becomes +1.
    - Position value becomes 100.
- **Agent B (Aggressive Taker, Short)**:
    - Cash decreases by 100 (immediate margin payment).
    - Net position becomes -1.
    - Position value becomes 100.
- **NAV Verification**: Both traders maintain a NAV of 1000.

### 4. `test_market_long_matching`
**Purpose**: Validates the accounting when a market buy order matches a passive sell order.
- Similar logic to Case 3, but with sides reversed. Agent A becomes short and Agent B becomes long.

### 5. `test_partial_fill`
**Purpose**: Verifies accounting state when only part of a limit order is executed.
- **Scenario**: Agent A Bids 2 @ 100. Agent B Sells 1 @ 100.
- **Step 1**: Agent A initially has 200 locked in "Hold".
- **Step 2**: After 1 unit matches, 1 unit remains in "Hold" (100) and 1 unit becomes "Position Value" (100).
- **Verification**: Total wealth (Cash + Hold + PosVal) remains consistent.

### 6. `test_mark_to_market_long`
**Purpose**: Tests the unrealized P&L calculation when the market price moves for a long position.
- **Scenario**: Long 1 @ 100.
- **Price Shift UP (110)**: NAV increases to 1010 (+10 profit).
- **Price Shift DOWN (90)**: NAV decreases to 990 (-10 loss).

### 7. `test_mark_to_market_short`
**Purpose**: Tests the unrealized P&L calculation for a short position.
- **Price Shift UP (110)**: NAV decreases to 990 (Short loss when price rises).
- **Price Shift DOWN (90)**: NAV increases to 1010 (Short profit when price falls).

### 8. `test_insufficient_funds`
**Purpose**: (Corner Case) Checks how the system handles orders exceeding available equity.
- **Note**: Currently, the system validates `nav > 0` before approving orders, potentially allowing high leverage.

### 9. `test_market_order_empty_book`
**Purpose**: Ensures no accounting changes occur if a market order finds no liquidity.

### 10-13. Position Flips (Aggressor & Passive)
**Purpose**: These complex tests verify that flipping from Long to Short (or vice versa) correctly handles the closing of one position and the opening of another in a single atomic transaction.
- **Logic**: If Long 1 and Sell 2, the first Sell closes the Long (releasing capital) and the second Sell opens a Short (locking capital).
- **Verification**: The tests ensure `net_position` correctly transitions from +1 to -1 (or -1 to +1) and that cash/NAV balances are perfectly preserved throughout the transition.
