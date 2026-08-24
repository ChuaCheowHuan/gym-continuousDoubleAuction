"""Transformer encoder over the order-book grid.

Reads the flat observation as tokens (see `tokenize`), adds a positional
encoding, runs `num_layers` pre-norm self-attention blocks, and pools to a
single latent vector for the pi and vf heads.

Positional encoding
-------------------
Under `both` tokenisation the sequence is a *grid*, not a line: token index
`t * (k_rows + 1) + level` carries level `level` of snapshot `t`. A single flat
position embedding over those indices cannot express that "level 3 at t=0" and
"level 0 at t=3" differ along different axes - it would have to learn the
factorisation from scratch. So time and level get separate learned embeddings,
summed, and each axis is shared across the other. `time` and `level`
tokenisations are the degenerate cases with one axis of length 1.

Learned rather than sinusoidal on both axes: the level axis is short (11
positions including the global token) and its ordering is book depth, where
position 0 - the touch - is qualitatively different from position 9 rather than
merely earlier. There is nothing for a sinusoid's translation-invariance to buy.

Scale
-----
LayerNorm after the input projection is not configurable, and this is why.
Measured over 40 real steps of a 4-agent env, the per-channel standard
deviations of a `both` token - `[bid_price, bid_size, ask_price, ask_size]` -
are `[1.27, 8.17, 0.046, 9.52]`: the size channels, which are `sqrt(volume)`,
run some 200x the ask-price channel, and all four sit inside the *same* 4-wide
token. Pushed through an untrained projection, the resulting attention puts a
mean 47% of its mass on a single token (entropy 1.62 of a possible 3.78 over 44
tokens). With the LayerNorm that becomes 9.5% and 2.76. Removing it does not
degrade the transformer gracefully - it stops attending. See also the scale note
in `tokenize`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import torch
import torch.nn as nn
from ray.rllib.core.columns import Columns
from ray.rllib.core.models.base import ENCODER_OUT, Encoder, Model
from ray.rllib.core.models.configs import ModelConfig
from ray.rllib.core.models.torch.base import TorchModel
from ray.rllib.utils.annotations import override

from gym_continuousDoubleAuction.train.model.encoders import register
from gym_continuousDoubleAuction.train.model.encoders.blocks import (
    AttentionPool,
    TransformerBlock,
)
from gym_continuousDoubleAuction.train.model.encoders.obs_layout import ObsLayout
from gym_continuousDoubleAuction.train.model.encoders.tokenize import (
    token_shape,
    tokenize,
)

#: Defaults for the `transformer` block of `encoder_specs`. Every key here must
#: also appear in `config/train_config.json`; these are the fallbacks for a
#: config that omits one, and the single place a new key's default is written.
TRANSFORMER_DEFAULTS = {
    "tokenization": "both",
    "d_model": 128,
    "num_heads": 4,
    "num_layers": 2,
    "ff_dim": 256,
    "dropout": 0.0,
    "pool": "attention",
}

#: How a token sequence is reduced to one latent vector.
POOLINGS = ("mean", "attention")


def positional_index(layout: ObsLayout, tokenization: str):
    """(time index, level index) per token, for the two positional embeddings.

    Mirrors the token order `tokenize` produces. Returns tensors of length
    `num_tokens`, and the size each axis's embedding table needs.
    """
    num_tokens, _ = token_shape(layout, tokenization)

    if tokenization == "time":
        # One token per snapshot; no level axis.
        return torch.arange(num_tokens), torch.zeros(num_tokens, dtype=torch.long)

    # `level` and `both` both lay levels out as k_rows real levels plus one
    # global token, so the level axis is k_rows + 1 wide either way.
    stride = layout.k_rows + 1
    positions = torch.arange(num_tokens)
    if tokenization == "level":
        # Newest snapshot only; no time axis.
        return torch.zeros(num_tokens, dtype=torch.long), positions

    # "both" is time-major: index = t * stride + level.
    return positions // stride, positions % stride


@dataclass
class TransformerEncoderConfig(ModelConfig):
    """Config for `TorchTransformerEncoder`."""

    layout: ObsLayout = None
    tokenization: str = TRANSFORMER_DEFAULTS["tokenization"]
    d_model: int = TRANSFORMER_DEFAULTS["d_model"]
    num_heads: int = TRANSFORMER_DEFAULTS["num_heads"]
    num_layers: int = TRANSFORMER_DEFAULTS["num_layers"]
    ff_dim: int = TRANSFORMER_DEFAULTS["ff_dim"]
    dropout: float = TRANSFORMER_DEFAULTS["dropout"]
    pool: str = TRANSFORMER_DEFAULTS["pool"]

    @property
    def output_dims(self):
        """Becomes `Catalog.latent_dims`, which sizes the pi and vf heads."""
        return (self.d_model,)

    def build(self, framework: str = "torch") -> Encoder:
        if framework != "torch":
            raise ValueError(
                f"{type(self).__name__} is torch-only; got framework={framework!r}."
            )
        return TorchTransformerEncoder(self)


class TorchTransformerEncoder(TorchModel, Encoder):
    """Tokenise, project, add positions, attend, pool."""

    def __init__(self, config: TransformerEncoderConfig) -> None:
        TorchModel.__init__(self, config)
        Encoder.__init__(self, config)

        if config.pool not in POOLINGS:
            raise ValueError(
                f"Unknown pool {config.pool!r}. Available: {', '.join(POOLINGS)}."
            )
        if config.num_layers < 1:
            raise ValueError(f"num_layers must be >= 1; got {config.num_layers}.")

        self.layout = config.layout
        self.tokenization = config.tokenization
        _, token_dim = token_shape(self.layout, self.tokenization)

        self.project = nn.Linear(token_dim, config.d_model)
        # Not a knob - see the module docstring.
        self.norm_in = nn.LayerNorm(config.d_model)

        time_idx, level_idx = positional_index(self.layout, self.tokenization)
        # Buffers, not parameters: these are constant index tensors, but they
        # must follow the module across devices.
        self.register_buffer("time_idx", time_idx, persistent=False)
        self.register_buffer("level_idx", level_idx, persistent=False)
        self.time_embedding = nn.Embedding(
            int(time_idx.max()) + 1, config.d_model
        )
        self.level_embedding = nn.Embedding(
            int(level_idx.max()) + 1, config.d_model
        )

        self.blocks = nn.ModuleList(
            TransformerBlock(
                d_model=config.d_model,
                num_heads=config.num_heads,
                ff_dim=config.ff_dim,
                dropout=config.dropout,
            )
            for _ in range(config.num_layers)
        )
        self.norm_out = nn.LayerNorm(config.d_model)
        self.pool = (
            AttentionPool(config.d_model, config.num_heads, config.dropout)
            if config.pool == "attention"
            else None
        )

    @override(Model)
    def _forward(self, inputs: dict, **kwargs) -> dict:
        tokens = tokenize(inputs[Columns.OBS], self.layout, self.tokenization)

        x = self.norm_in(self.project(tokens))
        x = x + self.time_embedding(self.time_idx) + self.level_embedding(
            self.level_idx
        )

        for block in self.blocks:
            x = block(x)

        x = self.norm_out(x)
        latent = self.pool(x) if self.pool is not None else x.mean(dim=-2)
        return {ENCODER_OUT: latent}


@register("transformer")
def build_transformer_config(
    layout: ObsLayout,
    spec: Dict[str, Any],
    input_dims: List[int],
) -> TransformerEncoderConfig:
    settings = {**TRANSFORMER_DEFAULTS, **spec}
    unknown = sorted(set(settings) - set(TRANSFORMER_DEFAULTS))
    if unknown:
        raise ValueError(
            f"Unknown key(s) {unknown} in the 'transformer' encoder spec. "
            f"Valid keys: {sorted(TRANSFORMER_DEFAULTS)}."
        )
    return TransformerEncoderConfig(input_dims=input_dims, layout=layout, **settings)
