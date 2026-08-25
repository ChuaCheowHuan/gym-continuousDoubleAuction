"""The transformer encoder with each block's feed-forward replaced by an MoE.

Everything else - tokenisation, the two-axis positional encoding, pre-norm
blocks, pooling, the mandatory input LayerNorm - is inherited unchanged from
`transformer`, which is why `TransformerBlock` takes its feed-forward as a
factory.

What is different is that this encoder produces a *second* loss term. See `moe`
for why the load-balancing loss is needed and how it is defined; the chain that
carries it to the optimiser is:

    MoEFeedForward.forward   returns (output, stats)
    TransformerBlock.forward passes the tuple through
    this encoder            collects per-block stats into `_moe_stats`
    CDAPPOTorchRLModule      takes them and puts MOE_AUX_LOSS in `fwd_out`
    CDAPPOTorchLearner       adds aux_loss_coeff * aux to the total loss

The hop through the module is unavoidable: `ActorCriticEncoder._forward` keeps
only `ENCODER_OUT` from whatever an encoder returns, so an extra dict key would
be dropped before anything could read it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from ray.rllib.core.models.base import Encoder

from gym_continuousDoubleAuction.train.model.encoders import (
    encoder_settings,
    register,
)
from gym_continuousDoubleAuction.train.model.encoders.blocks import TransformerBlock
from gym_continuousDoubleAuction.train.model.encoders.moe import moe_factory
from gym_continuousDoubleAuction.train.model.encoders.obs_layout import ObsLayout
from gym_continuousDoubleAuction.train.model.encoders.transformer import (
    TorchTransformerEncoder,
    TransformerEncoderConfig,
)

#: Defaults for the `moe_transformer` block of `encoder_specs`. The transformer
#: keys mean exactly what they do there; `ff_dim` is now each *expert's* width,
#: so the dense-equivalent parameter count is roughly `num_experts` times it.
MOE_TRANSFORMER_DEFAULTS = {
    "tokenization": "both",
    "d_model": 128,
    "num_heads": 4,
    "num_layers": 2,
    "ff_dim": 256,
    "dropout": 0.0,
    "pool": "attention",
    "num_experts": 4,
    "top_k": 2,
    "aux_loss_coeff": 0.01,
}


@dataclass
class MoETransformerEncoderConfig(TransformerEncoderConfig):
    """`TransformerEncoderConfig` plus the mixture's own knobs."""

    num_experts: int = MOE_TRANSFORMER_DEFAULTS["num_experts"]
    top_k: int = MOE_TRANSFORMER_DEFAULTS["top_k"]
    #: Weight on the load-balancing term. Read by the Learner, not here.
    aux_loss_coeff: float = MOE_TRANSFORMER_DEFAULTS["aux_loss_coeff"]

    def build(self, framework: str = "torch") -> Encoder:
        if framework != "torch":
            raise ValueError(
                f"{type(self).__name__} is torch-only; got framework={framework!r}."
            )
        return TorchMoETransformerEncoder(self)


class TorchMoETransformerEncoder(TorchTransformerEncoder):
    """The transformer stack, with mixture-of-experts feed-forwards."""

    def _make_block(self, config: MoETransformerEncoderConfig) -> TransformerBlock:
        return TransformerBlock(
            d_model=config.d_model,
            num_heads=config.num_heads,
            ff_dim=config.ff_dim,
            dropout=config.dropout,
            ff_factory=moe_factory(
                d_model=config.d_model,
                ff_dim=config.ff_dim,
                num_experts=config.num_experts,
                top_k=config.top_k,
                dropout=config.dropout,
            ),
        )


@register("moe_transformer", defaults=MOE_TRANSFORMER_DEFAULTS)
def build_moe_transformer_config(
    layout: ObsLayout,
    spec: Dict[str, Any],
    input_dims: List[int],
) -> MoETransformerEncoderConfig:
    settings = encoder_settings("moe_transformer", spec)
    return MoETransformerEncoderConfig(
        input_dims=input_dims, layout=layout, **settings
    )
