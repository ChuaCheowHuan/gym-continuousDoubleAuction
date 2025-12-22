# Test OrderBook Double Delete

This document details the micro-accounting processes and steps involved in the `test_orderbook_double_delete_order.py` test case. This test serves as a regression test to ensure that modifying an order's price does not trigger a logic error where the order is removed twice from the internal data structures, leading to corruption or exceptions.

## Test Scenario: `test_modify_order_price_no_double_delete`

This test simulates a simple price modification of an existing bid order and verifies that the operation completes without raising an internal error (specifically a `ValueError` related to list integrity).

### Step-by-Step Process

1.  **Initialization**:
    *   An empty `OrderBook` instance is created.

2.  **Place Initial Bid Order**:
    *   **Action**: A limit buy order (Bid) is placed.
    *   **Details**:
        *   Type: `limit`
        *   Side: `bid`
        *   Quantity: `10`
        *   Price: `100`
        *   Trade ID: `B1`
    *   **Result**: The Order Book registers this order. The `order_id` is captured for subsequent operations. The order is stored in the `OrderList` corresponding to price `100`.

3.  **Modify Order Price**:
    *   **Action**: The previously placed Bid order is modified to a new price.
    *   **Modification Details**:
        *   New Price: `101`
        *   Quantity: `10` (unchanged)
        *   Timestamp: `2`
    *   **Accounting/Logic**:
        *   Typically, changing the price of an order involves two atomic-like micro-steps in the engine:
            1.  **Removal**: The order is removed from the `OrderList` at the old price (`100`).
            2.  **Insertion**: The order (with updated price) is inserted into the `OrderList` at the new price (`101`).
        *   **The Bug Scenario**: The test prevents a specific bug where the update logic might inadvertently attempt to remove the order *again* after it has already been moved, or during the process, leading to a "double delete" scenario. This would often manifest as a `ValueError` (e.g., trying to remove an item not in the list) or an internal counter (like list volume/length) becoming negative.

4.  **Verification**:
    *   **Action**: The `modify_order` call is wrapped in a `try...except` block.
    *   **Assertion**: The test explicitly checks that `ValueError` is *not* raised.
    *   **Success Condition**: The modification completes silently and successfully.
