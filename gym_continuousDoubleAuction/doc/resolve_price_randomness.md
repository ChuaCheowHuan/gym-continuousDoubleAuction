# Technical Proposal: Resolving Price Randomness

To eliminate the "random lottery" effect caused by an empty Order Book (LOB), we propose a deterministic anchoring system. This ensures that every action code has a consistent economic meaning throughout the episode.

## 1. Establishing the Initial Price ($t=0$)

When the environment resets and the order book is completely empty, there is no "market price" to reference. To solve this:

*   **Configurable Anchor**: Add an `initial_price` parameter to the environment configuration (e.g., in `continuousDoubleAuctionEnv.__init__`).
*   **Persistent State**: The environment should maintain a `self.last_price` variable.
*   **Initialization**: At $t=0$, `self.last_price` is set to the `initial_price`.
*   **Implementation**:
    ```python
    # In continuousDoubleAuctionEnv.reset()
    self.last_price = self.config.get("initial_price", 100.0)
    ```

## 2. Determining Prices for Empty Levels

Once the simulation starts, price levels 1–10 in the "Market Depth" table may become empty as orders are filled or cancelled. Instead of falling back to a random number, we use the **Mid-Price** (or `last_price` if no spread exists) as the "Zero Point."

### The "Ghost Level" Strategy
Even if a level has zero volume, it still has a **deterministic price coordinate**. We calculate this by extrapolating from the best available price or the Mid-Price.

**Logic for Price Code $i$ (where $i \in [1, 10]$):**

1.  **Reference Price ($P_{ref}$)**:
    - If the book has a spread: $P_{ref} = \frac{BestBid + BestAsk}{2}$ (Mid-Price).
    - If the book is empty on one or both sides: $P_{ref} = self.last_price$.

2.  **Deterministic Calculation**:
    - **If Buying (Bid side)**: $Price_i = P_{ref} - (i \times TickSize)$
    - **If Selling (Ask side)**: $Price_i = P_{ref} + (i \times TickSize)$

### Advantages of this approach:
*   **Stability**: "Price Level 1" always means "the most aggressive price near the current valuation." "Price Level 10" always means "a very passive price far from the center." 
*   **Predictability**: An agent can learn that level 10 is where it should place "patient" orders, even if nobody else is currently there.
*   **No Discontinuities**: There is no sudden jump from a high-quality price to a random number because the book went thin.

## 3. Dynamic Reference Update
To keep the levels relevant, `self.last_price` must be updated whenever a trade occurs:
```python
# In Exchg_Helper.mark_to_mkt() or do_actions()
if trades:
    self.last_price = trades[-1]['price']
```

This transforms the action space from a "hit-or-miss lottery" into a **stable relative coordinate system**.
