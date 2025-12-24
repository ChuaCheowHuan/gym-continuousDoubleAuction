# New Action Space Design

The action space has been redesigned to be more efficient for Reinforcement Learning agents by reducing sparsity and eliminating non-deterministic stochasticity.

## 1. Structure
The action space for each agent is a `gym.spaces.Dict` with the following components:

| Key | Space | Description |
| :--- | :--- | :--- |
| `category` | `Discrete(9)` | The primary trade action (combines side and type). |
| `size_mean` | `Box(-1.0, 1.0)` | Mean for size sampling (original logic). |
| `size_sigma` | `Box(0.0, 1.0)` | Sigma for size sampling (original logic). |
| `price` | `Discrete(10)` | Market depth level index (0-9 for levels 1-10). |
| `price_offset` | `Discrete(3)` | Position relative to level (0: Passive, 1: Join, 2: Aggressive). |

## 2. Action Categories (`category`)
The `category` field collapses the previous "Side" and "Type" hierarchy:

- **0: Neutral** – No action taken.
- **1-4: Buy Actions** – 1: Market, 2: Limit, 3: Modify, 4: Cancel.
- **5-8: Sell Actions** – 5: Market, 6: Limit, 7: Modify, 8: Cancel.

## 3. Deterministic Price Anchoring
- **Initial Anchor**: Episode starts with `last_price` sampled as an integer from `[initial_price_min, initial_price_max]`.
- **Dynamic Anchor**: `last_price` updates to the **Last Traded Price** from the LOB tape after every trade.
- **Ghost Levels**: If a targeted book level is empty, the price is anchored to `last_price` using deterministic offsets (Bid: `Anchor - (Level * Tick)`, Ask: `Anchor + (Level * Tick)`).

## 4. Relative Price Offsets
- **0: Passive**: 1 tick worse than the level price.
- **1: Join**: Exactly the level price.
- **2: Aggressive**: 1 tick better than the level price (undercut/better).

*Note: The previous price codes 0 and 11 (passive/aggressive boundaries) were removed as they are now redundant with the level/offset combinations.*

## 5. Multi-Order Targeting
- **Modify**: Uses **FIFO** logic, targeting the agent's **oldest existing order** on that side.
- **Cancel**: Matches the specific **Price Level** targeted by the combination of `price` and `price_offset`.

---
*This design ensures that every action combination has a stable and distinct economic meaning.*
