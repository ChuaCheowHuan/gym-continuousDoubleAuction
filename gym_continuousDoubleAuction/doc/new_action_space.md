# New Action Space Design

The action space has been redesigned to be more efficient for Reinforcement Learning agents by reducing sparsity and eliminating non-deterministic stochasticity.

## 1. Structure
The action space for each agent is a `gym.spaces.Dict` with the following components:

| Key | Space | Description |
| :--- | :--- | :--- |
| `category` | `Discrete(9)` | The primary trade action (combines side and type). |
| `size_mean` | `Box(-1.0, 1.0)` | Mean for size sampling (original logic). |
| `size_sigma` | `Box(0.0, 1.0)` | Sigma for size sampling (original logic). |
| `price` | `Discrete(12)` | Relative price level (0-11). |

## 2. Action Categories (`category`)
The `category` field collapses the previous "Side" and "Type" hierarchy:

- **0: Neutral** – No action taken.
- **1: Buy Market** – Buy at best available price.
- **2: Buy Limit** – Place a buy order at the chosen price level.
- **3: Buy Modify** – Move the oldest existing buy order to a new price.
- **4: Buy Cancel** – Cancel a buy order at the specific price level.
- **5: Sell Market** – Sell at best available price.
- **6: Sell Limit** – Place a sell order at the chosen price level.
- **7: Sell Modify** – Move the oldest existing sell order to a new price.
- **8: Sell Cancel** – Cancel a sell order at the specific price level.

## 3. Deterministic Price Anchor ("Ghost Levels")
To ensure that price codes (0-11) always have a consistent economic meaning even when the Order Book is thin or empty, the environment uses a deterministic anchoring system:

- **Initial Anchor**: At the start of an episode ($t=0$), an `initial_price` is sampled as an **integer** from a configurable range (`initial_price_min` to `initial_price_max`).
- **Dynamic Anchor**: The anchor updates to the **Last Traded Price** whenever a trade occurs on the tape.
- **Mapping**: If a price level in the book is empty, the price is calculated as an offset from this anchor:
  - **Bids**: `Anchor - (LevelIndex * TickSize)`
  - **Asks**: `Anchor + (LevelIndex * TickSize)`

## 4. Multi-Order Targeting
When an agent has multiple orders in the book:
- **Modify**: Uses **FIFO** logic, targeting the agent's **oldest existing order** on that side.
- **Cancel**: Matches the specific **Price Level** targeted by the `price` field.

---
*Note: This design eliminates the previous "Empty Book Randomness" flaw where thin books triggered completely random price generation.*
