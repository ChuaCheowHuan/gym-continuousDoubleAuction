"""The structure hidden inside this env's flat observation vector.

The env hands RLlib a 1-D `Box` of `n_hist * snapshot_dim` floats. That vector
is not unstructured - it is a chronological stack of `n_hist` order-book
snapshots, each of which is itself a `book_rows x k_rows` grid plus `extra_dim`
market-level scalars:

    obs  = [ snapshot(t-n_hist+1), ..., snapshot(t) | private ]   <- oldest first

    snapshot = [ bid_price(0..k-1),      <- book_rows=4 fields, k_rows=10 levels,
                 bid_size (0..k-1),         laid out FIELD-major
                 ask_price(0..k-1),
                 ask_size (0..k-1),
                 log_mid, log1p_spread_ticks,
                 mid_return, signed_volume,
                 log1p_trade_count, trade_direction ]   <- extra_dim=6 scalars

    private  = private_dim per-agent floats, appended ONCE after the whole
               stack rather than per frame - position, cash, NAV, drawdown and
               so on, then the OWN-BOOK block: this agent's resting size at
               each of the k_rows public levels, bids then asks, then its
               order counts and the dead-action flag. See
               State_Helper.private_fields. The book prefix is shared between
               agents; only this tail differs.

The MLP encoder throws all of that away and sees `n_hist * snapshot_dim`
unrelated numbers. Every other encoder recovers it through this class, which is
the single place the layout is written down on the model side.

`from_obs_space` derives `n_hist` from the observation space rather than reading
it from config: `book_rows`, `k_rows`, `extra_dim` and `private_dim` come from
`tunable_constants.json` (the same group `State_Helper` reads), and `n_hist` is
whatever makes the arithmetic match the space the env actually declared. A space
whose book part is not a whole number of snapshots is a layout bug and raises,
rather than silently reshaping into garbage.

Why the private block is a separate tail rather than extra channels
-------------------------------------------------------------------
`tokenize` builds tokens `max(book_rows + own_channels, extra_dim)` channels
wide. Folding the whole `private_dim` into that width would pay attention over
padding on every level of every snapshot to carry numbers that belong to no
level. So the split happens before tokenisation and an encoder that wants the
tail projects it separately and appends it as a single token; `split_private`
is that seam. The one exception is the own-book block, which IS per level: its
two sizes ride on the newest snapshot's level tokens as channels 4 and 5, where
the level tokens were zero-padded to the scalars' width anyway. Older
snapshots' level tokens carry zeros there - the env records own orders only
for now.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import gymnasium as gym

from gym_continuousDoubleAuction.config_loader import group

#: Field order within a snapshot's book block, matching the `np.concatenate` in
#: `State_Helper.set_agg_LOB`. Named here so a token's channels can be
#: identified in a test or a debugger without counting offsets by hand.
BOOK_FIELDS = ("bid_price", "bid_size", "ask_price", "ask_size")

#: Scalar order within a snapshot's trailing block, same source
#: (`State_Helper.EXTRA_FIELDS`).
EXTRA_FIELDS = (
    "log_mid", "log1p_spread_ticks", "mid_return", "signed_volume",
    "log1p_trade_count", "trade_direction",
)


@dataclass(frozen=True)
class ObsLayout:
    """How to read the flat observation vector as a (time, level, field) grid."""

    n_hist: int
    book_rows: int
    k_rows: int
    extra_dim: int
    private_dim: int
    #: Index in the private tail where this agent's own-book block starts:
    #: `k_rows` own bid sizes, then `k_rows` own ask sizes, level-aligned with
    #: the public book (State_Helper.private_fields). None when the tail does
    #: not carry one - a layout built by hand in a test, or a pre-S3-24 env -
    #: in which case `tokenize` adds no own-size channels.
    own_book_offset: Optional[int] = None

    @property
    def own_channels(self) -> int:
        """Extra channels a level token carries for own bid/ask size: 2 or 0."""
        return 2 if self.own_book_offset is not None else 0

    @property
    def book_dim(self) -> int:
        """Floats in one snapshot's book block."""
        return self.book_rows * self.k_rows

    @property
    def snapshot_dim(self) -> int:
        """Floats in one snapshot."""
        return self.book_dim + self.extra_dim

    @property
    def book_flat_dim(self) -> int:
        """Floats in the stacked book part, i.e. everything but the private tail."""
        return self.n_hist * self.snapshot_dim

    @property
    def flat_dim(self) -> int:
        """Floats in the whole observation, private block included."""
        return self.book_flat_dim + self.private_dim

    @property
    def num_tokens_time(self) -> int:
        """Tokens under `time` tokenisation: one per snapshot."""
        return self.n_hist

    @property
    def num_tokens_level(self) -> int:
        """Tokens under `level` tokenisation: one per book level."""
        return self.k_rows

    @property
    def num_tokens_both(self) -> int:
        """Tokens under `both` tokenisation: one per (snapshot, level) cell."""
        return self.n_hist * self.k_rows

    @classmethod
    def from_obs_space(cls, obs_space: gym.Space) -> "ObsLayout":
        """Derive the layout from a single agent's observation space.

        Raises:
            TypeError: if the space is not a 1-D Box - the layouts below all
                assume the flat vector the env declares today, and a nested or
                multi-dimensional space means the env changed underneath them.
            ValueError: if the flat size is not a whole number of snapshots.
        """
        if not isinstance(obs_space, gym.spaces.Box) or len(obs_space.shape) != 1:
            raise TypeError(
                "ObsLayout expects the flat 1-D Box observation this env "
                f"declares; got {obs_space!r}. An encoder that tokenises the "
                "observation cannot infer the (time, level, field) grid from "
                "a space of that shape."
            )

        layout = group("tunable_constants.json", "observation_layout")
        book_rows = layout["book_rows"]
        k_rows = layout["k_rows"]
        extra_dim = layout["extra_dim"]
        private_dim = layout["private_dim"]

        snapshot_dim = book_rows * k_rows + extra_dim
        flat_dim = int(obs_space.shape[0])
        book_flat_dim = flat_dim - private_dim
        n_hist, remainder = divmod(book_flat_dim, snapshot_dim)
        if remainder or n_hist < 1:
            raise ValueError(
                f"Observation space of {flat_dim} floats, less a "
                f"{private_dim}-float private block, leaves {book_flat_dim} - "
                f"not a whole number of {snapshot_dim}-float snapshots "
                f"(book_rows={book_rows} * k_rows={k_rows} + "
                f"extra_dim={extra_dim}). Either the env's observation changed "
                "without observation_layout in tunable_constants.json "
                "following it, or this space did not come from this env."
            )

        # Does this private tail carry the own-book block? Ask the env's own
        # definition of the block rather than assuming: a tail of exactly the
        # width `private_fields(k_rows)` describes has it at the offset that
        # function fixes, and any other width does not.
        from gym_continuousDoubleAuction.envs.exchg.state_helper import (
            own_book_offset,
            private_fields,
        )

        offset = None
        if private_dim == len(private_fields(k_rows)):
            offset = own_book_offset()

        return cls(
            n_hist=n_hist,
            book_rows=book_rows,
            k_rows=k_rows,
            extra_dim=extra_dim,
            private_dim=private_dim,
            own_book_offset=offset,
        )


def split_private(obs, layout: "ObsLayout"):
    """Split a flat observation batch into its book part and its private tail.

    Args:
        obs: `(B, layout.flat_dim)`.
        layout: the layout to split against.

    Returns:
        `(book, private)` of widths `layout.book_flat_dim` and
        `layout.private_dim`. `tokenize` takes the first; an encoder that wants
        the second projects it itself - see this module's docstring for why it
        is not folded into the token width.
    """
    return obs[..., : layout.book_flat_dim], obs[..., layout.book_flat_dim :]
