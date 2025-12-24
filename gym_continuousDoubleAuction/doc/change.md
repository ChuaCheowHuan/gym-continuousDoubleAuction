# Changes from original_v1 to Current Version (update 20251224)

This document outlines the major changes and modernizations made to the `gym-continuousDoubleAuction` codebase since the `original_v1` branch (released more than 5 years ago).

## 1. Dependency Modernization
The codebase has been updated to support modern RL and Gym ecosystems:
- **Gymnasium Migration**: Switched from the legacy `gym` to `gymnasium`.
- **Ray RLlib Update**: Compatibility updates for Ray 2.4+, specifically handling the transition from `dones` to `terminated` and `truncated`.
- **Type Hinting**: Improved type hinting across core environment files.

## 2. Redesigned Action Space
The action space has been overhauled for better agent learnability and flexibility:
- **Original**: Used a nested `Tuple` structure.
- **Current**: Uses a flattened `Dict` structure per agent.
- **New Features**:
    - **Category Mapping**: Replaced separate `side` and `type` with a unified `category` (0-8) mapping to (None, Buy/Sell x Mkt/Lmt/Mod/Can).
    - **Price Offsets**: Introduced `price_offset` (Passive, Join, Aggressive) allowing agents to bid relative to the reference price levels.
    - **Deterministic Reference**: Prices are now calculated more deterministically relative to the `last_price` anchor.

## 3. Environment API (Ray 2.4+)
The `step` and `reset` methods now follow the newest Multi-Agent Environment standards:
- **`reset()`**: Returns `(observations, infos)` instead of just `observations`.
- **`step()`**: Returns `(obs, rewards, terminateds, truncateds, infos)` (the "5-tuple" return) instead of the old "4-tuple".

## 4. Enhanced Tooling and Documentation
New diagnostic tools and deep-dive documentation have been added:
- **`analyze_unused.py`**: Tool for identifying dead code.
- **`inspect_latest_episode.py`**: Visualization and analysis tool for episode data.
- **Expanded `/doc` folder**: Includes detailed explanations of the new action space, accounting logic, and orderbook mechanics.

## 5. File Reorganization
- Core environment logic in `continuousDoubleAuction_env.py` has been refactored for clarity.
- Updated `OrderBook` logic for better consistency between volume and price updates.
