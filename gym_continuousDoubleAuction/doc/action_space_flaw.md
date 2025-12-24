# Flaws of the action space design

While the design of the action space is clever in its attempt to generalize across price levels, it has several technical and theoretical flaws that can hinder the learning stability and efficiency of RL agents.

## 1. The "Empty Book" Randomness Trap

One of the most significant flaws is in `action_helper.py` within the `_within_price_slot` function. If the Limit Order Book (LOB) is thin and a price level is empty (`price == 0`), the environment generates a completely random price for that code:

```python
if price == 0:
    set_price = random.randrange(min_tick, max_price, min_tick)
```

**The Flaw**: This introduces extreme non-stationarity. An agent might learn that "Price Code 3" is a safe, passive placement. If liquidity vanishes, "Price Code 3" suddenly becomes a random lottery. This makes it incredibly difficult for a neural network to converge on a stable value function or policy.

## 2. Forced Aggression (The "+1/-1 Tick" Problem)

The mapping for price codes 1–10 is designed to always offset by 1 tick:

- Bids: Level Price + 1  
- Asks: Level Price - 1  

**The Flaw**: It is impossible for an agent to "join" a level (i.e., place an order at the exact same price as an existing level). They are forced to either be 1 tick better than the existing level or be 1 tick better than a worse level. This forces a "penny-war" behavior by design, which might not be optimal and prevents agents from learning more passive liquidity-providing strategies.

## 3. High Variance in Action Sampling (Mean/Sigma for Size)

The agent must output both a mean and a sigma for the order size.

**The Flaw**: Reinforcement learning agents (especially those using Gaussian policies) often struggle to balance exploration and exploitation when both the mean and variance are learnable parameters for a single action.  
**Impact**: An agent might accidentally learn a high sigma, making its order sizes essentially random noise. This prevents the agent from executing precise strategies, such as buying exactly enough shares to close a position or clearing a specific level of the book.

## 4. Sparse & Redundant Action Space

The action space is a broad tuple, but many combinations are "Dead Actions":

- If Side is 0 (None), the other 4 components (Type, Mean, Sigma, Price) are entirely ignored.  
- If Type is 0 (Market), the Price Code is ignored.  

**The Flaw**: A large percentage of the mathematical action space has zero effect on the environment. The agent spends a significant portion of its training time exploring "garbage" combinations, which slows down the learning process significantly.

## 5. Blindness to Market Macro-Structure

The Price Code is hardcoded to the top 10 levels of the book.

**The Flaw**: If the market spread is wide or the book is empty, the 10 levels might represent a tiny or irrelevant window of the actual price range.  
**Impact**: The agent cannot "fish" for orders far outside the current spread. It cannot place deep-out-of-the-money orders that might be profitable during high-volatility events (flash crashes, etc.) because it can only "see" and "target" the immediate vicinity of the current best bid/ask.

## 6. Interaction Complexity (Discrete-Continuous Hybrid)

Mixing Discrete (`Side`, `Type`, `Price Code`) with Box/Continuous (`Mean`, `Sigma`) in a single tuple can be problematic for certain RL algorithms.

- Algorithms like DQN struggle with the continuous components.  
- Algorithms like PPO/SAC require specific handling (like MultiDiscrete or complex branching heads) to effectively learn policies across such heterogeneous action types.

## Summary

The design is highly opinionated: it forces the agent to behave like a high-frequency trader focusing on the "inner" book. However, the stochastic noise (random prices on empty levels) and the forced tick-offsets make it a very "noisy" environment for standard RL agents to master.