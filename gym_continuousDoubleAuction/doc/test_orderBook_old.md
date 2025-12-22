# Walkthrough - Legacy Orderbook Unit Test Explanation (`test_orderBook_old.py`)

This document explains the legacy unit tests for the `OrderBook` mechanism. Unlike modern tests, these rely on string representation comparisons to verify the state of the book and the trade tape.

---

## core Methodology

The tests in this file initialize an `OrderBook` and a set of predefined limit orders. They process these orders and then compare the `str(order_book)` output against expected multi-line string constants. This validates:
- Price-Time priority in the Bids/Asks lists.
- Correct assignment of `order_id` and `timestamp`.
- Traceability through the `trade_id`.
- Accuracy of the trade `tape`.

---

## Test Cases Detailed Explanation

### 1. `test_1`: Initial Book Population
**Purpose**: Verifies that passive limit orders are correctly sorted and displayed in the book.
- **Process**: Adds 8 limit orders (4 Bids, 4 Asks) at various prices.
- **Verification**:
    - **Bids**: Sorted descending by price (99, 99, 98, 97). For identical prices, sorted by timestamp (FIFO).
    - **Asks**: Sorted ascending by price (101, 101, 101, 103). For identical prices, sorted by timestamp (FIFO).
    - **Tape**: Remains empty as no orders cross.

### 2. `test_2`: Basic Crossing (Full/Partial Fill)
**Purpose**: Validates what happens when a new order crosses the best available price.
- **Scenario**: A Bid for 2 units @ 102 is submitted against a book where the best Ask is 101.
- **Verification**:
    - A trade of 2 units occurs at the **resting price** (101).
    - The resting Ask's size is reduced from 5 to 3.
    - The trade is recorded on the tape with `counter_party_ID` 100 and `init_party_ID` 109.

### 3. `test_3`: Sweeping the Book (Large Crossing Order)
**Purpose**: Tests the "Sweeping" effect where a large order matches multiple existing orders and the remainder is posted to the book.
- **Scenario**: A large Bid for 50 units @ 102 is submitted.
- **Verification**:
    - It matches all remaining Asks at the 101 price level (sizes 3, 5, and 5).
    - Total traded: 13 units.
    - Remaining: 37 units (50 - 13) are posted to the Bid side of the book at price 102.
    - The tape records these as distinct trade events.

### 4. `test_4`: Market Order Execution
**Purpose**: Verifies that Market Orders take liquidity regardless of price until fulfilled or liquidity runs out.
- **Scenario**: A Market Ask for 40 units is submitted.
- **Verification**:
    - It immediately matches the top Bid (size 37 @ 102).
    - It then matches the next Bid (size 3 @ 99) to complete the 40 unit request.
    - The Bids at 102 and the first Bid at 99 are removed or reduced.
    - Resulting Tape shows the progression from the best bid downwards.
