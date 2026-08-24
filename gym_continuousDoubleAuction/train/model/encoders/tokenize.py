"""Turning the flat observation into a token sequence.

Three tokenisations, selected per encoder by its `tokenization` spec key:

    "time"   n_hist tokens of  (book_rows*k_rows + extra_dim)  floats
             One token per snapshot. The whole book at one instant is a single
             token, so attention can only relate *times*, never levels.

    "level"  k_rows tokens of  book_rows  floats
             One token per book level, from the newest snapshot only. Attention
             relates levels - where the depth is, how the sides differ - but
             sees no history.

    "both"   n_hist*k_rows tokens of  book_rows  floats
             One token per (snapshot, level) cell. Attention relates both axes.
             This is the default: the other two are each a projection of it,
             and are kept so an ablation can ask which axis is doing the work.

Under "level" and "both" a token is 4 floats `[bid_price, bid_size, ask_price,
ask_size]` for one level, and the 2 market-level scalars have nowhere to go -
they are per-snapshot, not per-level. They are carried instead on a separate
*global token* per snapshot, appended to the sequence, so they stay inside the
attention rather than being dropped or smeared across every level. Under "time"
they are already part of each token and no global token is added.

Scale
-----
These channels are on wildly different scales - see the normalisation in
`State_Helper.set_agg_LOB`: prices are a relative distance from the midpoint
(order 0.01), sizes are `sqrt(volume)` and unbounded (order 100 for a
10,000-lot level), `log_mid` is 2.3-4.6. A `tanh` MLP absorbs that. Attention
does not: the dot products that feed the softmax are dominated by the size
channel, the softmax saturates, and attention collapses onto a single token. So
every encoder built on these tokens applies LayerNorm immediately after the
input projection. That is not a tuning knob and is not configurable.
"""
from __future__ import annotations

from typing import Tuple

import torch

from gym_continuousDoubleAuction.train.model.encoders.obs_layout import ObsLayout

#: Valid values for an encoder spec's `tokenization` key.
TOKENIZATIONS = ("time", "level", "both")


def token_shape(layout: ObsLayout, tokenization: str) -> Tuple[int, int]:
    """(num_tokens, token_dim) a tokenisation produces, global token included.

    Raises:
        ValueError: on an unknown tokenisation.
    """
    _check(tokenization)
    if tokenization == "time":
        return layout.n_hist, layout.snapshot_dim
    if tokenization == "level":
        # k_rows level tokens + 1 global token carrying that snapshot's scalars.
        return layout.k_rows + 1, layout.book_rows
    # "both": every (snapshot, level) cell, + 1 global token per snapshot.
    return layout.n_hist * (layout.k_rows + 1), layout.book_rows


def tokenize(obs: torch.Tensor, layout: ObsLayout, tokenization: str) -> torch.Tensor:
    """Reshape a flat observation batch into `(B, num_tokens, token_dim)`.

    Args:
        obs: `(B, layout.flat_dim)` float tensor.
        layout: the grid to read `obs` as.
        tokenization: one of `TOKENIZATIONS`.

    Returns:
        `(B, num_tokens, token_dim)` matching `token_shape(layout, tokenization)`.
    """
    _check(tokenization)
    batch = obs.shape[0]

    # (B, n_hist, snapshot_dim) - snapshots are stacked oldest-first by
    # State_Helper's obs_history deque, so this axis is time ascending.
    snapshots = obs.reshape(batch, layout.n_hist, layout.snapshot_dim)

    if tokenization == "time":
        return snapshots

    # Split each snapshot into its book grid and its market-level scalars. The
    # book block is FIELD-major - all k bid_prices, then all k bid_sizes, ... -
    # so it reshapes to (field, level) and transposes to (level, field), which
    # is the token axis we want.
    book = snapshots[..., : layout.book_dim]
    extras = snapshots[..., layout.book_dim :]

    book = book.reshape(batch, layout.n_hist, layout.book_rows, layout.k_rows)
    book = book.transpose(-1, -2)  # (B, n_hist, k_rows, book_rows)

    # The global token is the snapshot's extra_dim scalars, right-padded to
    # book_rows so it can sit in the same sequence as the level tokens.
    global_token = torch.zeros(
        batch, layout.n_hist, 1, layout.book_rows,
        dtype=book.dtype, device=book.device,
    )
    width = min(layout.extra_dim, layout.book_rows)
    global_token[..., 0, :width] = extras[..., :width]

    # (B, n_hist, k_rows + 1, book_rows)
    tokens = torch.cat([book, global_token], dim=-2)

    if tokenization == "level":
        # Newest snapshot only.
        return tokens[:, -1]

    # "both": flatten (time, level) into one sequence, time-major so a token's
    # index is `t * (k_rows + 1) + level`.
    return tokens.reshape(batch, layout.n_hist * (layout.k_rows + 1), layout.book_rows)


def _check(tokenization: str) -> None:
    if tokenization not in TOKENIZATIONS:
        raise ValueError(
            f"Unknown tokenization {tokenization!r}. "
            f"Available: {', '.join(TOKENIZATIONS)}."
        )
