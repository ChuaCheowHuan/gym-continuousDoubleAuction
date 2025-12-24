The action space in this MARL (Multi-Agent Reinforcement Learning) codebase is designed for a Continuous Double Auction (CDA) environment. Each agent (trader) chooses actions that are translated into orders for a Limit Order Book (LOB).

The action space for each agent is a `gym.spaces.Tuple` containing 5 components:

1. **Side (`Discrete(3)`)**  
   Determines the direction of the trade:  
   - `0`: None (Neutral/No action).  
   - `1`: Bid (Buy).  
   - `2`: Ask (Sell).

2. **Type (`Discrete(4)`)**  
   Determines the type of order to be placed or the action to take on existing orders:  
   - `0`: Market Order – Executes immediately at the best available price.  
   - `1`: Limit Order – Placed at a specific price; stays in the book if not matched.  
   - `2`: Modify Order – Updates an existing order for the trader in the LOB.  
   - `3`: Cancel Order – Removes an existing order from the LOB.

3. **Size Mean (`Box[-1.0, 1.0]`)** & **4. Size Sigma (`Box[0.0, 1.0]`)**  
   These two components control the Quantity (Size) of the order using a stochastic sampling method:  
   - The Mean is scaled differently based on order types (Market orders typically have smaller maximum sizes than Limit orders).  
   - The final size is sampled from a Normal Distribution using these parameters: `Normal(scaled_mean, sigma)`.  
   - The result is taken as an absolute value, rounded, and incremented by 1 (to ensure the size is at least 1).

5. **Price Code (`Discrete(12)`)**  
   Instead of absolute prices, the environment uses a relative pricing mechanism based on the current Market Depth (the 10 best price levels currently in the LOB). This allows agents to learn strategies like "matching the best bid" or "undercutting" without worrying about absolute price values.  

   The 12 price codes map as follows:  
   - `0` (**Passive/Extreme**): Sets a price 1 tick lower than the lowest bid (if buying) or 1 tick higher than the highest ask (if selling).  
   - `1 - 10` (**Within Book**): Maps directly to the 10 price levels currently visible in the market depth table.  
     - For Bids: Price at level + 1 tick.  
     - For Asks: Price at level - 1 tick.  
   - `11` (**Aggressive**): Sets a price 1 tick higher than the current best bid (if buying) or 1 tick lower than the current best ask (if selling).

**Why this design?**  
- **Relative Generalization**: By using "Price Codes" instead of absolute prices, the agent's policy can generalize across different price regimes.  
- **Stochastic Exploration**: The Mean/Sigma approach for order size allows the reinforcement learning agent to learn both the average desired size and the level of "uncertainty" or exploration it wants to apply to its trade volumes.  
- **Complex Interaction**: Including "Modify" and "Cancel" allows for sophisticated high-frequency trading behaviors like "spoofing" or rapid price adjustments.