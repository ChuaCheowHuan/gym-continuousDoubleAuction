"""Transformer building blocks, shared by the `transformer` and MoE encoders.

Written here rather than using `nn.TransformerEncoderLayer` for one reason: the
MoE encoder is the same stack with each block's feed-forward replaced by a
gated mixture of experts. A block that takes its feed-forward as a factory makes
that a one-line substitution; the stock layer would have to be reimplemented
anyway to get inside it.

Pre-norm, not post-norm
-----------------------
`TransformerBlock` normalises *before* each sublayer and adds the residual
after. Post-norm transformers need a learning-rate warmup to train stably,
because early gradients through the residual path are large. Nothing in this
project's PPO config does warmup, and RL runs are not usually restarted for a
schedule bug that looks like "the architecture doesn't work", so pre-norm is the
safer default here.

Dropout
-------
Defaults to 0, and should stay there for PPO. The ratio `exp(logp_new -
logp_old)` compares a log-prob recorded during rollout against one recomputed on
the learner. Dropout is active for the second and not the first, so a non-zero
value feeds mask noise straight into the policy-gradient ratio rather than
regularising anything. The knob exists because it is standard on this component,
not because it is advisable.
"""
from __future__ import annotations

from typing import Callable, Optional

import torch
import torch.nn as nn


def feedforward(d_model: int, ff_dim: int, dropout: float = 0.0) -> nn.Module:
    """The standard two-layer feed-forward sublayer. The default factory."""
    return nn.Sequential(
        nn.Linear(d_model, ff_dim),
        nn.GELU(),
        nn.Dropout(dropout),
        nn.Linear(ff_dim, d_model),
    )


class TransformerBlock(nn.Module):
    """Pre-norm self-attention + feed-forward, both residual.

    Args:
        d_model: Token width.
        num_heads: Attention heads. Must divide `d_model`.
        dropout: Applied to attention weights and inside the feed-forward.
        ff_factory: Builds the feed-forward sublayer. Defaults to
            `feedforward`; the MoE encoder passes its own.
    """

    def __init__(
        self,
        d_model: int,
        num_heads: int,
        ff_dim: int,
        dropout: float = 0.0,
        ff_factory: Optional[Callable[[], nn.Module]] = None,
    ) -> None:
        super().__init__()
        if d_model % num_heads:
            raise ValueError(
                f"d_model={d_model} must be divisible by num_heads={num_heads}."
            )

        self.norm_attn = nn.LayerNorm(d_model)
        self.attn = nn.MultiheadAttention(
            embed_dim=d_model,
            num_heads=num_heads,
            dropout=dropout,
            batch_first=True,
        )
        self.norm_ff = nn.LayerNorm(d_model)
        self.ff = (
            ff_factory() if ff_factory is not None
            else feedforward(d_model, ff_dim, dropout)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """`(B, T, d_model)` in, same out.

        No attention mask: every token is a real observation - the sequence is
        a fixed-size grid, not a padded batch of variable-length inputs - so
        there is nothing to mask out.
        """
        normed = self.norm_attn(x)
        attended, _ = self.attn(normed, normed, normed, need_weights=False)
        x = x + attended

        ff_out = self.ff(self.norm_ff(x))
        # An MoE feed-forward returns (output, aux_loss); a plain one returns a
        # tensor. Unpacking here keeps the block agnostic to which it holds.
        if isinstance(ff_out, tuple):
            ff_out, aux = ff_out
        else:
            aux = None
        return x + ff_out if aux is None else (x + ff_out, aux)


class AttentionPool(nn.Module):
    """Pool `(B, T, d_model)` to `(B, d_model)` with a learned query.

    Mean-pooling weights every token equally, which for this env means a level
    with no resting size counts as much as the touch. This lets the network
    decide where to read from instead.
    """

    def __init__(self, d_model: int, num_heads: int, dropout: float = 0.0) -> None:
        super().__init__()
        self.query = nn.Parameter(torch.zeros(1, 1, d_model))
        nn.init.normal_(self.query, std=0.02)
        self.attn = nn.MultiheadAttention(
            embed_dim=d_model,
            num_heads=num_heads,
            dropout=dropout,
            batch_first=True,
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        query = self.query.expand(x.shape[0], -1, -1)
        pooled, _ = self.attn(query, x, x, need_weights=False)
        return pooled.squeeze(-2)


class PrivateToken(nn.Module):
    """Project the per-agent private block into one extra token.

    The observation is a shared book prefix plus a `private_dim` per-agent tail
    (see `obs_layout`). The tail is not tokenised with the book: token width is
    `max(book_rows, extra_dim)`, so folding it in would widen every book token
    to `private_dim` channels and right-pad each with zeros - attention over
    padding on every level of every snapshot, to carry nine numbers that belong
    to none of them.

    So it gets its own projection and joins the sequence as a single token.
    Every encoder that tokenises uses this rather than its own copy, which is
    what keeps them comparable: two architectures reading private state through
    differently-shaped heads would differ by the head as much as by the
    architecture.

    No positional embedding is added to it, deliberately. The two axes are time
    and book level, and the private block belongs to neither - it is the
    agent's own state as of now.

    LayerNorm for the same reason the book projection has one: the fields are
    bounded and O(1) by construction in `set_private_state`, but they are not
    on the *same* scale as each other (a NAV ratio near 1.0 beside a drawdown
    near 0.0), and this token shares a softmax with the book's.
    """

    def __init__(self, private_dim: int, d_model: int) -> None:
        super().__init__()
        if private_dim < 1:
            raise ValueError(
                f"PrivateToken needs private_dim >= 1; got {private_dim}. "
                "Build it only when the layout has a private block."
            )
        self.project = nn.Linear(private_dim, d_model)
        self.norm = nn.LayerNorm(d_model)

    def forward(self, private: torch.Tensor) -> torch.Tensor:
        """`(B, private_dim)` -> `(B, 1, d_model)`, ready to concatenate."""
        return self.norm(self.project(private)).unsqueeze(-2)
