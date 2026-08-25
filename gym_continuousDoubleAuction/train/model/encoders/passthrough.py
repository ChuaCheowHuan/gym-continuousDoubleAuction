"""The smallest possible encoder, for testing the custom-encoder path.

Registered as `_passthrough`, which `validate_encoder_type` refuses, so it can
never be selected from `config/train_config.json`. It exists only so tests can
send something down the whole custom route - `CDAModelConfig` -> `CDACatalog`
-> `build_encoder_config` -> `ActorCriticEncoderConfig` -> the pi/vf heads ->
checkpoint round-trip - with an architecture too simple to be the cause of a
failure.

That matters because the shipped default, `mlp`, is a *pass-through*: it uses
the stock RLlib catalog and touches none of this. It can pass while every line
of the custom path is broken. This fixture is what closes that gap, and it
tokenises the observation so `ObsLayout` and `tokenize` are covered too.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

import torch.nn as nn
from ray.rllib.core.columns import Columns
from ray.rllib.core.models.base import ENCODER_OUT, Encoder, Model
from ray.rllib.core.models.configs import ModelConfig
from ray.rllib.core.models.torch.base import TorchModel
from ray.rllib.utils.annotations import override

from gym_continuousDoubleAuction.train.model.encoders import (
    encoder_settings,
    register,
)
from gym_continuousDoubleAuction.train.model.encoders.obs_layout import ObsLayout
from gym_continuousDoubleAuction.train.model.encoders.tokenize import (
    token_shape,
    tokenize,
)

#: Latent width of the fixture. Small - it is never trained for real.
_PASSTHROUGH_LATENT = 32


@dataclass
class PassthroughEncoderConfig(ModelConfig):
    """Config for `TorchPassthroughEncoder`."""

    layout: ObsLayout = None
    tokenization: str = "both"
    latent_dim: int = _PASSTHROUGH_LATENT

    @property
    def output_dims(self):
        """Becomes `Catalog.latent_dims`, which sizes the pi and vf heads."""
        return (self.latent_dim,)

    def build(self, framework: str = "torch") -> Encoder:
        if framework != "torch":
            raise ValueError(
                f"{type(self).__name__} is torch-only; got framework={framework!r}."
            )
        return TorchPassthroughEncoder(self)


class TorchPassthroughEncoder(TorchModel, Encoder):
    """Tokenise, project, LayerNorm, mean-pool. No attention, no recurrence."""

    def __init__(self, config: PassthroughEncoderConfig) -> None:
        TorchModel.__init__(self, config)
        Encoder.__init__(self, config)

        self.layout = config.layout
        self.tokenization = config.tokenization
        _, token_dim = token_shape(self.layout, self.tokenization)

        self.project = nn.Linear(token_dim, config.latent_dim)
        # Not a knob. See the scale discussion in `tokenize`: without this the
        # sqrt-volume channel dominates every downstream dot product.
        self.norm = nn.LayerNorm(config.latent_dim)

    @override(Model)
    def _forward(self, inputs: dict, **kwargs) -> dict:
        tokens = tokenize(inputs[Columns.OBS], self.layout, self.tokenization)
        latent = self.norm(self.project(tokens))
        return {ENCODER_OUT: latent.mean(dim=-2)}


#: Full spec schema for the fixture.
PASSTHROUGH_DEFAULTS = {
    "tokenization": "both",
    "latent_dim": _PASSTHROUGH_LATENT,
}


@register("_passthrough", defaults=PASSTHROUGH_DEFAULTS)
def build_passthrough_config(
    layout: ObsLayout,
    spec: Dict[str, Any],
    input_dims: List[int],
) -> PassthroughEncoderConfig:
    settings = encoder_settings("_passthrough", spec)
    return PassthroughEncoderConfig(input_dims=input_dims, layout=layout, **settings)
