# The Price Code Mechanism

The Price Code mechanism is a relative pricing system that allows the agent to place orders based on the current state of the Market Depth (the top 10 rows of the Order Book) rather than using absolute currency values.

In this environment, an agent's action includes a `price_code` which is an integer from **0 to 11**. This code is translated into a real price in [`action_helper.py:L226-281`](#).

## Mapping of the Price Code (0–11)

The mechanism divides the pricing into three categories:

### 1. The "Aggressive" Code: 11  
This code is used to "tighten the spread" or "jump the queue."

- **Bid**: Sets price to **Best Bid + 1 tick**. (You become the new highest bidder).  
- **Ask**: Sets price to **Best Ask - 1 tick**. (You become the new lowest seller).

### 2. The "Market Depth" Codes: 1 to 10  
These codes correspond directly to the 10 levels of the Limit Order Book visible in the agent's observation.

- **Code 1**: Targets the 1st level (Best Bid/Ask).  
- **Code 2**: Targets the 2nd level, and so on.

However, the logic adds a small adjustment to ensure the order is competitive within that slot:

- **Bid**: Price = Level Price + 1 tick.  
- **Ask**: Price = Level Price - 1 tick.

### 3. The "Passive" Code: 0  
This is used to place orders "behind" the visible book.

- **Bid**: Sets price to **Worst Visible Bid - 1 tick**.  
- **Ask**: Sets price to **Worst Visible Ask + 1 tick**.

## Logic Summary Table

| Price Code | Target Location        | Bid Logic             | Ask Logic              |
|------------|------------------------|-----------------------|------------------------|
| 11         | Beyond Best Price      | Best Bid + 1          | Best Ask - 1           |
| 1 – 10     | Specific LOB Level     | Level Price + 1       | Level Price - 1        |
| 0          | Behind Worst Price     | Worst Bid - 1         | Worst Ask + 1          |

## Special Cases

- **Empty Book Slot**: If the agent chooses a price code for a level that is currently empty (`0.0` in the observation), the mechanism defaults to a randomly generated price within the environment's price range.
- **Market Orders**: If the action type is set to "Market" (`type: 0`), the `price_code` is ignored, and the price is set to `-1.0` internally to signal the matching engine to execute immediately at any available price.

## Why This Exists?

This mechanism is a form of **Action Space Abstraction**. By using codes 0–11, the agent doesn't need to learn the absolute value of money (e.g., $10,000). It only needs to learn "relative" concepts like:

- "I want to be 1 tick better than the current best price", or  
- "I want to match the 3rd level of depth."

This significantly simplifies the learning process for the AI.