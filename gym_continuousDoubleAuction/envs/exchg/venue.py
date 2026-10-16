"""What the composed components ask of the exchange (issue #152).

The reward model, episode status, info builder and liquidation engine used to be mixins:
base classes of the env that reached for whatever they needed on `self`, so which of the
env's ~100 attributes each depended on was knowable only by reading it. They are objects
now, and the exchange hands them what they need. A component that works on the exchange's
state at all (the liquidation engine, the episode status) takes a `Venue`, and this is the
whole of what it may use. `Exchg_Helper` implements it; a test can supply a small fake.
"""
from __future__ import annotations

from typing import Any, List, Protocol


class Venue(Protocol):
    #: Every trader, live or not, in ID order.
    traders: List[Any]
    #: The limit order book of the episode in progress.
    LOB: Any
    #: The price grid agents quote on.
    min_tick: Any
    #: Index of the step being completed.
    t_step: int

    def mark_price(self) -> Any:
        """The price accounts are marked at."""

    def mark_to_mkt(self) -> None:
        """Re-mark every account at the current mark price."""

    def is_live(self, trader: Any) -> bool:
        """Whether the trader still takes part in the episode."""

    def invalidate_snapshot(self) -> None:
        """Say the book changed since the last snapshot, so the next step rebuilds it."""
