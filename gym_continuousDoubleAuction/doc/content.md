# Documentation Index

Welcome to the documentation for the `gym-continuousDoubleAuction` environment. This index provides a summary of all available documentation pages to help you navigate the codebase and understand its core mechanisms.

## Core Concepts

*   **[Action Space](action_space.md)**: Describes the Tuple-based action space (Side, Type, Size, and Price Code) used in the Continuous Double Auction environment.
*   **[Action Space Price Code](action_space_price_code.md)**: Explains the relative pricing mechanism (0-11) and how it maps to market depth levels to simplify agent learning.
*   **[New Action Space Design](new_action_space.md)**: Details the redesigned Dict-based action space with unified categories and deterministic price anchoring.
*   **[Reward Function Refinement](reward_function_refinement.md)**: Outlines the multi-factor reward formula designed to encourage NAV growth, selectivity, and risk management.
*   **[Modernization & Changes](change.md)**: Summarizes the updates since version 1, including Gymnasium migration, Ray 2.4 compatibility, and league-based self-play.

## Technical Proposals & Deep Dives

*   **[Action Space Flaws](action_space_flaw.md)**: Analysis of technical and theoretical flaws in the original action space design and their impact on learning stability.
*   **[Resolving Price Randomness](resolve_price_randomness.md)**: Technical proposal for the "Ghost Level" deterministic anchoring system to eliminate randomness in thin books.
*   **[League-Based Self-Play Walkthrough](league_based_self_play_walkthru.md)**: Comprehensive guide to the league-based training system and the champion snapshotting mechanism.

## Testing & Verification

*   **[Accounting Mechanism Tests](test_accounting.md)**: Explanation of unit tests for cash management, position tracking, and atomic position flips.
*   **[Order Modification Logic](test_modify_order.md)**: Details the matching engine logic for order modifications and various accounting scenarios.
*   **[New Action Space Verification](test_new_action_space.md)**: Analysis of unit tests verifying the new action space, including ghost pricing and dynamic anchors.
*   **[Orderbook Core Tests](test_orderbook.md)**: Walkthrough of unit tests for core orderbook components (Order, OrderList, OrderTree) and basic trading logic.
*   **[Crossed Book Invariant](test_orderbook_crossed_book.md)**: Verifies that the order book maintains the fundamental invariant that the best bid price remains below the best ask price after modifications.
*   **[Double Delete Regression](test_orderbook_double_delete_order.md)**: Technical documentation of the regression test ensuring order modifications don't cause internal logic errors.
*   **[Volume Synchronization](test_orderbook_volume_sync.md)**: Verifies that cached total volume statistics in the OrderTree remain synchronized with the actual sum of order volumes.
*   **[League-Based Self-Play Testing](league_based_self_play_testing.md)**: Documentation of unit tests for the champion selection logic and probabilistic mapping.
