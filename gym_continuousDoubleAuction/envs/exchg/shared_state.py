"""What the state and action mixins share on `self` (issue #152).

`State_Helper` builds observations; `Action_Helper` decodes actions and builds the action
mask. Each reads attributes the other creates (the book, the traders, the tick, the layout
sizes) and calls methods the other defines, and both are mixins of `Exchg_Helper`. That
coupling is real and is not unwound here: it is written down, in one place the type checker
reads, so that a missing or renamed shared attribute is a type error rather than an
`AttributeError` found at runtime, and so that the contract between the two is findable.

The declarations are for the checker only; nothing here exists at runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List

if TYPE_CHECKING:
    import numpy as np

    from ..agent.trader import Trader
    from ..orderbook.orderbook import OrderBook


class SharedState:
    if TYPE_CHECKING:
        # The exchange, set by `Exchg_Helper` and the env.
        LOB: OrderBook
        traders: List[Trader]
        t_step: int
        np_random: np.random.Generator
        agg_LOB_raw: Any  # the raw snapshot array; `{}` before the first one
        # The price grid and last print, set by `Action_Helper`.
        min_tick: Any
        last_price: float
        limit_max_size: Any
        # The episode length shown to agents, set by the env.
        time_left_horizon: int
        # The observation layout, set by `State_Helper`.
        book_rows: int
        k_rows: int
        book_mode: str

        def reference_price(self) -> float:
            """`State_Helper.reference_price`: the grid's origin."""

        def action_mask_for(self, trader: Trader, n_bid: int, n_ask: int) -> np.ndarray:
            """`Action_Helper.action_mask_for`: which categories the trader can take."""
