# Test OrderBook Crossed Book

This document details the micro-accounting processes and steps involved in the `test_orderbook_crossed_book.py` test case. The primary objective of this test is to verify that the `OrderBook` maintains the invariant that the best bid price must always be strictly less than the best ask price (i.e., the book is not "crossed") after an order modification.

## Test Scenario: `test_modify_order_does_not_cross_book`

This test simulates a scenario where a user attempts to modify an existing bid order to a price that crosses the spread (i.e., is higher than the current best ask).

### Step-by-Step Process

1.  **Initialization**:
    *   An empty `OrderBook` instance is created.

2.  **Place Initial Ask Order**:
    *   **Action**: A limit sell order (Ask) is placed.
    *   **Details**:
        *   Type: `limit`
        *   Side: `ask`
        *   Quantity: `10`
        *   Price: `100`
        *   Trade ID: `S1`
    *   **Result**: The Order Book now has a best ask of `100`.

3.  **Place Initial Bid Order**:
    *   **Action**: A limit buy order (Bid) is placed.
    *   **Details**:
        *   Type: `limit`
        *   Side: `bid`
        *   Quantity: `10`
        *   Price: `90`
        *   Trade ID: `B1`
    *   **Result**: The Order Book now has a best bid of `90`. The spread is `10` (100 - 90). The `order_id` of this bid is captured.

4.  **Modify Bid Order (The Critical Step)**:
    *   **Action**: The previously placed Bid order (from Step 3) is modified.
    *   **Modification Details**:
        *   New Price: `110`
        *   Quantity: `10` (unchanged)
    *   **Context**: The new price (`110`) is significantly higher than the current best ask (`100`).
    *   **Accounting/Logic Expectation**:
        *   When a bid price is updated to cross the ask, the matching engine should typically execute a trade immediately against the matching ask order(s).
        *   Alternatively, if the system does not support aggressive modifications matching immediately, it must ensure the book state doesn't remain "crossed" (where Best Bid >= Best Ask) in a resting state.

5.  **Verification**:
    *   **Action**: Retrieve the current `best_bid` and `best_ask` prices from the order book.
    *   **Assertion**: Check if both a best bid and best ask exist. If they do, assert that `best_bid < best_ask`.
    *   **Failure Condition**: If `best_bid >= best_ask`, the book is "crossed," indicating a corruption of market state or a failure in the matching engine logic during modification.
