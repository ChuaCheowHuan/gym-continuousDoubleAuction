"""A per-step embedding of one observation's order-book grid.

Tokenise, project, LayerNorm, pool - the same front end the transformer has,
minus the attention stack, reduced to a single vector per observation.

On its own this is not a registered encoder. It exists to be the LSTM's
*tokenizer*: `RecurrentEncoderConfig` takes a `tokenizer_config`, and
`TorchLSTMEncoder` folds its `(B, T, obs)` input to `(B * T, obs)`, runs the
tokenizer, unfolds back to `(B, T, latent)` and recurs over T. So this is what
turns "an LSTM over the raw flat observation" into "an LSTM over a
structured per-step embedding of the book" - the difference between the two
LSTM designs, and the reason the tokenizer is worth writing.

Why the positional embeddings are not optional
----------------------------------------------
Tokenising is only half of "reads the observation as the grid it is". A mean
over per-token linear projections is a linear function of their sum, so without
a position signal this encoder is invariant to the order of both axes - the
grid goes in and its per-field mean comes out. It carries the same two
embeddings the transformer does, for that reason. See doc/15 S2-10.

The embeddings are necessary and not sufficient: under a linear projection and
a mean, `mean(W x_i + p_i)` is `W mean(x_i) + mean(p_i)`, so the position is an
input-independent constant and the invariance survives untouched. A token-wise
nonlinearity between the two is what makes the position bear on the result.

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

import torch
import torch.nn as nn
from ray.rllib.core.columns import Columns
from ray.rllib.core.models.base import ENCODER_OUT, Encoder, Model
from ray.rllib.core.models.configs import ModelConfig
from ray.rllib.core.models.torch.base import TorchModel
from ray.rllib.utils.annotations import override

from gym_continuousDoubleAuction.train.model.encoders.blocks import (
    AttentionPool,
    PrivateToken,
)
from gym_continuousDoubleAuction.train.model.encoders.obs_layout import (
    ObsLayout,
    split_private,
)
from gym_continuousDoubleAuction.train.model.encoders.tokenize import (
    positional_index,
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

        # Two positional embeddings, (time, level), exactly as the transformer
        # has - and for a stronger reason here, because nothing downstream can
        # make up for their absence.
        #
        # Without them this encoder was `tokenize -> Linear -> LayerNorm ->
        # mean`, and a mean of per-token linear projections is a linear
        # function of the token *sum*: permutation-invariant across both axes.
        # Measured on the real observation space, permuting the book levels
        # moved the latent by 1.8e-07 and reversing time by 1.2e-07 - float32
        # noise. The 44 book tokens collapsed to their per-field mean before
        # anything nonlinear, so the `lstm` encoder discarded exactly the grid
        # structure its own docstring says it preserves, and any
        # lstm-vs-transformer comparison was measuring something else. That is
        # doc/15 S2-10.
        #
        # `pool="attention"` would have masked this partially; `pool="mean"` is
        # the shipped default, so it did not.
        time_idx, level_idx = positional_index(self.layout, self.tokenization)
        self.register_buffer("time_idx", time_idx, persistent=False)
        self.register_buffer("level_idx", level_idx, persistent=False)
        self.time_embedding = nn.Embedding(
            int(time_idx.max()) + 1, config.d_model
        )
        self.level_embedding = nn.Embedding(
            int(level_idx.max()) + 1, config.d_model
        )

        # A token-wise nonlinearity, and it is what actually makes the position
        # count. Positional embeddings alone do not: `mean(W x_i + p_i)` is
        # `W mean(x_i) + mean(p_i)`, so under a linear projection and a mean the
        # position contributes an input-INDEPENDENT constant and the encoder
        # stays exactly as permutation-invariant as it was. Measured with the
        # embeddings added and nothing else: permuting the book levels still
        # moved the latent by 0.000000.
        #
        # With a nonlinearity between the two, `mean(f(W x_i + p_i))` depends on
        # which position each token sits at, which is the whole point. Residual
        # and re-normalised, the same shape the transformer's blocks use, so a
        # freshly initialised encoder still starts close to the projection it
        # had before.
        self.token_mlp = nn.Sequential(
            nn.Linear(config.d_model, config.d_model),
            nn.GELU(),
        )
        self.norm_tokens = nn.LayerNorm(config.d_model)
        # One extra token carrying this agent's private state; see PrivateToken.
        self.private_token = (
            PrivateToken(self.layout.private_dim, config.d_model)
            if self.layout.private_dim else None
        )
        self.pool = (
            AttentionPool(config.d_model, config.num_heads)
            if config.pool == "attention"
            else None
        )

    @override(Model)
    def _forward(self, inputs: dict, **kwargs) -> dict:
        obs = inputs[Columns.OBS]
        embedded = self.norm(self.project(tokenize(obs, self.layout, self.tokenization)))

        # Added after the LayerNorm, matching the transformer, so the
        # normalisation still does its job on the projected token and the
        # position is not rescaled away with it.
        embedded = embedded + self.time_embedding(self.time_idx) \
            + self.level_embedding(self.level_idx)

        # See the note on `token_mlp`: without this the positions above are an
        # additive constant and change nothing.
        embedded = self.norm_tokens(embedded + self.token_mlp(embedded))

        if self.private_token is not None:
            _book, private = split_private(obs, self.layout)
            embedded = torch.cat([embedded, self.private_token(private)], dim=-2)

        latent = self.pool(embedded) if self.pool is not None else embedded.mean(dim=-2)
        return {ENCODER_OUT: latent}
