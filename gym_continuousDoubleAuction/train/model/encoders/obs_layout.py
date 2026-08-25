"""The structure hidden inside this env's flat observation vector.

The env hands RLlib a 1-D `Box` of `n_hist * snapshot_dim` floats. That vector
is not unstructured - it is a chronological stack of `n_hist` order-book
snapshots, each of which is itself a `book_rows x k_rows` grid plus `extra_dim`
market-level scalars:

    obs  = [ snapshot(t-n_hist+1), ..., snapshot(t) ]        <- oldest first

    snapshot = [ bid_price(0..k-1),      <- book_rows=4 fields, k_rows=10 levels,
                 bid_size (0..k-1),         laid out FIELD-major
                 ask_price(0..k-1),
                 ask_size (0..k-1),
                 log_mid, log1p_spread_ticks ]   <- extra_dim=2 scalars

The MLP encoder throws all of that away and sees `n_hist * snapshot_dim`
unrelated numbers. Every other encoder recovers it through this class, which is
the single place the layout is written down on the model side.

`from_obs_space` derives `n_hist` from the observation space rather than reading
it from config: `book_rows`, `k_rows` and `extra_dim` come from
`tunable_constants.json` (the same group `State_Helper` reads), and `n_hist` is
whatever makes the product match the space the env actually declared. A space
that is not a whole number of snapshots is a layout bug and raises, rather than
silently reshaping into garbage.
"""
from __future__ import annotations

from dataclasses import dataclass

import gymnasium as gym

from gym_continuousDoubleAuction.config_loader import group

#: Field order within a snapshot's book block, matching the `np.concatenate` in
#: `State_Helper.set_agg_LOB`. Named here so a token's channels can be
#: identified in a test or a debugger without counting offsets by hand.
BOOK_FIELDS = ("bid_price", "bid_size", "ask_price", "ask_size")

#: Scalar order within a snapshot's trailing block, same source.
EXTRA_FIELDS = ("log_mid", "log1p_spread_ticks")


@dataclass(frozen=True)
class ObsLayout:
    """How to read the flat observation vector as a (time, level, field) grid."""

    n_hist: int
    book_rows: int
    k_rows: int
    extra_dim: int

    @property
    def book_dim(self) -> int:
        """Floats in one snapshot's book block."""
        return self.book_rows * self.k_rows

    @property
    def snapshot_dim(self) -> int:
        """Floats in one snapshot."""
        return self.book_dim + self.extra_dim

    @property
    def flat_dim(self) -> int:
        """Floats in the whole observation."""
        return self.n_hist * self.snapshot_dim

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

        snapshot_dim = book_rows * k_rows + extra_dim
        flat_dim = int(obs_space.shape[0])
        n_hist, remainder = divmod(flat_dim, snapshot_dim)
        if remainder or n_hist < 1:
            raise ValueError(
                f"Observation space of {flat_dim} floats is not a whole number "
                f"of {snapshot_dim}-float snapshots (book_rows={book_rows} * "
                f"k_rows={k_rows} + extra_dim={extra_dim}). Either the env's "
                "observation changed without observation_layout in "
                "tunable_constants.json following it, or this space did not "
                "come from this env."
            )

        return cls(
            n_hist=n_hist,
            book_rows=book_rows,
            k_rows=k_rows,
            extra_dim=extra_dim,
        )
