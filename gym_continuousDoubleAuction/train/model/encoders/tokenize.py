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

from gym_continuousDoubleAuction.train.model.encoders.obs_layout import (
    ObsLayout,
    split_private,
)

#: Valid values for an encoder spec's `tokenization` key.
TOKENIZATIONS = ("time", "level", "both")


def token_width(layout: ObsLayout) -> int:
    """Channels in a level/global token: wide enough for either kind.

    A level token needs `book_rows` channels and a global token needs
    `extra_dim`, and both share one sequence, so the width is the larger of the
    two and the shorter kind is right-padded with zeros.

    `max`, not `book_rows`: at the shipped layout (4 fields, 2 scalars) they are
    the same number, but `extra_dim` is a `tunable_constants.json` knob whose
    note anticipates more market features being added. Sizing to `book_rows`
    would silently truncate the scalars past the fourth - and only for the
    encoders that tokenise, so `mlp` would keep seeing a feature the transformer
    and LSTM no longer received, which is a difference between architectures
    that nothing would report.
    """
    return max(layout.book_rows, layout.extra_dim)


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
        return layout.k_rows + 1, token_width(layout)
    # "both": every (snapshot, level) cell, + 1 global token per snapshot.
    return layout.n_hist * (layout.k_rows + 1), token_width(layout)


def tokenize(obs: torch.Tensor, layout: ObsLayout, tokenization: str) -> torch.Tensor:
    """Reshape a flat observation batch into `(B, num_tokens, token_dim)`.

    Args:
        obs: `(B, layout.flat_dim)` float tensor - the whole observation; the
            private tail is split off and discarded here.
        layout: the grid to read `obs` as.
        tokenization: one of `TOKENIZATIONS`.

    Returns:
        `(B, num_tokens, token_dim)` matching `token_shape(layout, tokenization)`.
    """
    _check(tokenization)
    batch = obs.shape[0]

    # The book part only. A full observation carries `private_dim` per-agent
    # floats after the stack, and they are deliberately not tokenised - see
    # `obs_layout`. Slicing here rather than demanding a pre-split input keeps
    # every caller's contract "pass the observation".
    book, _private = split_private(obs, layout)

    # (B, n_hist, snapshot_dim) - snapshots are stacked oldest-first by
    # State_Helper's obs_history deque, so this axis is time ascending.
    snapshots = book.reshape(batch, layout.n_hist, layout.snapshot_dim)

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

    # One zero-filled sequence per snapshot, `token_width` channels wide, into
    # which both kinds of token are written at their own width. Whichever kind
    # is narrower keeps trailing zeros; neither is ever truncated.
    width = token_width(layout)
    tokens = torch.zeros(
        batch, layout.n_hist, layout.k_rows + 1, width,
        dtype=book.dtype, device=book.device,
    )
    tokens[..., : layout.k_rows, : layout.book_rows] = book
    tokens[..., layout.k_rows, : layout.extra_dim] = extras

    if tokenization == "level":
        # Newest snapshot only.
        return tokens[:, -1]

    # "both": flatten (time, level) into one sequence, time-major so a token's
    # index is `t * (k_rows + 1) + level`.
    return tokens.reshape(batch, layout.n_hist * (layout.k_rows + 1), width)


def _check(tokenization: str) -> None:
    if tokenization not in TOKENIZATIONS:
        raise ValueError(
            f"Unknown tokenization {tokenization!r}. "
            f"Available: {', '.join(TOKENIZATIONS)}."
        )
