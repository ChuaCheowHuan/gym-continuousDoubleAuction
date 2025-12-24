# Test OrderBook Volume Sync

This document details the micro-accounting processes and steps involved in the `test_orderbook_volume_sync.py` test case. The primary objective is to verify that the high-level volume aggregation (tracked by `OrderTree.volume`) remains synchronized with the actual sum of individual order volumes in the book, especially after partial execution events.

## Test Scenario: `test_partial_fill_volume_sync`

This test simulates a scenario where a resting limit order is partially filled by an incoming marketable order. It verifies that the Order Book correctly updates its total volume counters to reflect the remaining quantity.

### Step-by-Step Process

1.  **Initialization**:
    *   An empty `OrderBook` instance is created.
    *   A helper method `get_calculated_volume(side)` is defined to manually iterate through the underlying data structure (`price_map`) and sum up the volume of every `OrderList`. This serves as the "ground truth" for verification.

2.  **Place Initial Ask Order**:
    *   **Action**: A limit sell order (Ask) is placed.
    *   **Details**:
        *   Type: `limit`
        *   Side: `ask`
        *   Quantity: `10`
        *   Price: `100`
        *   Trade ID: `S1`
    *   **Accounting Result**:
        *   The Ask `OrderTree` should now contain one order of size `10`.
        *   `OrderTree.volume` (the cached/tracked total) should be `10`.
    *   **Verification**:
        *   Assert `OrderTree.volume` == `10`.
        *   Assert `get_calculated_volume('ask')` == `10`.

3.  **Execute Partial Fill**:
    *   **Action**: A limit buy order (Bid) is placed that matches the existing ask but for a smaller quantity.
    *   **Details**:
        *   Type: `limit` (effectively acts as a marketable limit order)
        *   Side: `bid`
        *   Quantity: `4`
        *   Price: `100` (matches the Ask price)
        *   Trade ID: `B1`
    *   **Micro-Accounting Steps**:
        1.  **Matching**: The engine identifies the Ask at `100` as a match.
        2.  **Execution**: `4` units are traded.
        3.  **Update**: The resting Ask order's quantity is reduced from `10` to `6` (`10 - 4`).
        4.  **Tree Update**: The `OrderTree` tracking the asks must decrease its total volume count by `4`.

4.  **Final Verification**:
    *   **Action**: Retrieve the final volume from the `OrderTree` property and calculate the "ground truth" sum again.
    *   **Assertion**:
        *   `OrderTree.volume` must be `6`.
        *   `get_calculated_volume('ask')` must be `6`.
    *   **Failure Condition**: If `OrderTree.volume` remains `10` or becomes some other incorrect value (e.g., if it didn't account for the partial fill), the test fails, indicating a "desynchronization" between the cached volume statistic and the actual orders.
