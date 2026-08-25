"""A per-step embedding of one observation's order-book grid.

Tokenise, project, LayerNorm, pool - the same front end the transformer has,
minus the attention stack, reduced to a single vector per observation.

On its own this is not a registered encoder. It exists to be the LSTM's
*tokenizer*: `RecurrentEncoderConfig` takes a `tokenizer_config`, and
`TorchLSTMEncoder` folds its `(B, T, obs)` input to `(B * T, obs)`, runs the
tokenizer, unfolds back to `(B, T, latent)` and recurs over T. So this is what
turns "an LSTM over the raw 168-float observation" into "an LSTM over a
structured per-step embedding of the book" - the difference between the two
LSTM designs, and the reason the tokenizer is worth writing.

The two time axes
-----------------
Do not confuse them. `T` is the *rollout* axis - consecutive env steps, what the
LSTM's memory runs along. `n_hist` is a window *inside a single observation*,
already stacked by the env. This module collapses `n_hist`; the LSTM handles T.
That also means the two overlap: with `n_hist` 4 the LSTM re-reads the last four
snapshots at every step. Setting `n_hist` to 1 for a recurrent run removes the
redundancy, at the cost of invalidating checkpoints (it is structural).
"""
from __future__ import annotations

from dataclasses import dataclass

import torch.nn as nn
from ray.rllib.core.columns import Columns
from ray.rllib.core.models.base import ENCODER_OUT, Encoder, Model
from ray.rllib.core.models.configs import ModelConfig
from ray.rllib.core.models.torch.base import TorchModel
from ray.rllib.utils.annotations import override

from gym_continuousDoubleAuction.train.model.encoders.blocks import AttentionPool
from gym_continuousDoubleAuction.train.model.encoders.obs_layout import ObsLayout
from gym_continuousDoubleAuction.train.model.encoders.tokenize import (
    token_shape,
    tokenize,
)

#: How the token sequence is reduced to one vector per observation.
POOLINGS = ("mean", "attention")


@dataclass
class TokenEmbedConfig(ModelConfig):
    """Config for `TorchTokenEmbedEncoder`."""

    layout: ObsLayout = None
    tokenization: str = "both"
    d_model: int = 128
    pool: str = "mean"
    #: Heads for `pool="attention"`. Unused otherwise.
    num_heads: int = 4

    @property
    def output_dims(self):
        return (self.d_model,)

    def build(self, framework: str = "torch") -> Encoder:
        if framework != "torch":
            raise ValueError(
                f"{type(self).__name__} is torch-only; got framework={framework!r}."
            )
        return TorchTokenEmbedEncoder(self)


class TorchTokenEmbedEncoder(TorchModel, Encoder):
    """`(B, obs)` -> `(B, d_model)`. Stateless; the recurrence is its caller's."""

    def __init__(self, config: TokenEmbedConfig) -> None:
        TorchModel.__init__(self, config)
        Encoder.__init__(self, config)

        if config.pool not in POOLINGS:
            raise ValueError(
                f"Unknown pool {config.pool!r}. Available: {', '.join(POOLINGS)}."
            )

        self.layout = config.layout
        self.tokenization = config.tokenization
        _, token_dim = token_shape(self.layout, self.tokenization)

        self.project = nn.Linear(token_dim, config.d_model)
        # Not a knob. The size channels run ~200x the price channels and share
        # a token with them - see the scale note in `tokenize`.
        self.norm = nn.LayerNorm(config.d_model)
        self.pool = (
            AttentionPool(config.d_model, config.num_heads)
            if config.pool == "attention"
            else None
        )

    @override(Model)
    def _forward(self, inputs: dict, **kwargs) -> dict:
        tokens = tokenize(inputs[Columns.OBS], self.layout, self.tokenization)
        embedded = self.norm(self.project(tokens))
        latent = self.pool(embedded) if self.pool is not None else embedded.mean(dim=-2)
        return {ENCODER_OUT: latent}
