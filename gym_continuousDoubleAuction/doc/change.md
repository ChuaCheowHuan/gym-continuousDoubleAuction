# Changes from original_v1 to Current Version 2 (update 20251224)

This document outlines the modernizations made to the `gym-continuousDoubleAuction` codebase since the `original_v1` branch (released more than 5 years ago).

## 1. Dependency Modernization
The codebase has been updated to support modern RL and Gym ecosystems:
- **Gymnasium Migration**: Switched from the legacy `gym` to `gymnasium`.
- **Ray RLlib Update**: Compatibility updates for Ray 2.4+, specifically handling the transition from `dones` to `terminated` and `truncated`.

## 2. Environment API (Ray 2.4+)
The `step` and `reset` methods now follow the newest Multi-Agent Environment standards:
- **`reset()`**: Returns `(observations, infos)` instead of just `observations`.
- **`step()`**: Returns `(obs, rewards, terminateds, truncateds, infos)` (the "5-tuple" return) instead of the old "4-tuple".

## 3. Self-Play Evolution: League-Based vs. Naive
The training methodology has evolved from simple self-play to a robust league-based system:

- **Legacy (`original_v1`)**: Used **Naive Self-Play** with competitive weight copying. Two policies competed, and the winner's weights were periodically copied to the loser. 
- **Current (MARL League-Based)**: Implements **League-Based Self-Play** with **Champion Snapshotting**:
    - **Independent Evolution**: Multiple learning policies evolve independently without direct weight copying.
    - **Champion Preservation**: Exceptional policy performances are frozen as "Champions" and added to an opponent pool.
    - **Dynamic Matchmaking**: Learning agents face a rotating mix of initial random opponents and historical champions.
    - **Stability**: Prevents "forgetting" by ensuring agents continue to perform well against past strong strategies.
    - **Diversity**: Maintains a rolling window of diverse strategies to prevent agents from over-optimizing against a single opponent.

## 4. Redesigned Action Space
The action space has been overhauled for better agent learnability and flexibility:
- **Original**: Used a nested `Tuple` structure.
- **Current**: Uses a flattened `Dict` structure per agent.
- **New Features**:
    - **Category Mapping**: Replaced separate `side` and `type` with a unified `category` (0-8) mapping to (None, Buy/Sell x Mkt/Lmt/Mod/Can).
    - **Price Offsets**: Introduced `price_offset` (Passive, Join, Aggressive) allowing agents to bid relative to the reference price levels.
    - **Deterministic Reference**: Prices are now calculated more deterministically relative to the `last_price` anchor.

## 5. Robust Testing (Accounting & Orderbook)
The core engine is now shielded by a rigorous testing suite:
- **Granular Unit Testing**: Switched from manual scripts to a formal `unittest` framework, ensuring every component (Order, Tree, List) and process (NAV calculation, Position tracking) is validated.
- **Precision Accounting**: Replaced standard floats with `Decimal` in all accounting calculations to eliminate rounding errors in financial simulations.
- **Complex Scenario Coverage**: Specialized tests now cover edge cases like **Position Flips** (Atomic Long-to-Short transitions), **Crossed Books**, and **Volume Synchronization** issues.

## 6. Enhanced Documentation
Deep-dive documentation have been added:
- **Expanded `/doc` folder**: Includes detailed explanations of the new action space, accounting logic, and orderbook mechanics.
