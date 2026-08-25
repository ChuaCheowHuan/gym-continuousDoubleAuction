"""LSTM encoder: a structured per-step embedding, then recurrence over rollout.

This is the "structured" of the two ways to give this env an LSTM.

The other one is free: set `use_lstm=True` on `DefaultModelConfig` and RLlib
builds a recurrent encoder whose tokenizer is a stock MLP over the raw
168-float observation. The book's `(time, level, field)` structure is discarded
exactly as it is under `mlp`, and the LSTM's memory is layered on top of an
`n_hist`-step window that already carries most of the same information.

This one keeps the structure: the tokenizer is `TokenEmbedConfig`, which reads
the observation as the grid it is, and the LSTM runs over the *rollout* axis on
top of that embedding.

Why there is no custom Encoder class here
-----------------------------------------
`RecurrentEncoderConfig` already takes a `tokenizer_config`, and
`TorchLSTMEncoder` already does the fold / tokenize / unfold / recur dance,
`get_initial_state`, and the batch-first-to-layers-first state transposition. So
the whole encoder is a stock `RecurrentEncoderConfig` with our tokenizer in it -
the same shape RLlib's own `use_lstm` path builds, differing only in that
tokenizer.

Deriving from `RecurrentEncoderConfig` rather than wrapping it is also what
makes statefulness work end to end, and both mechanisms key off `isinstance`:

  * `DefaultPPORLModule.setup` forces `inference_only=False` for a recurrent
    base config, so the critic's states are collected during sampling. Without
    it `compute_values` has no states to run on.
  * `ActorCriticEncoderConfig.build` returns `TorchStatefulActorCriticEncoder`
    rather than the plain one, which is what routes STATE_IN/STATE_OUT to the
    actor and critic separately.

`max_seq_len`
-------------
Read by RLlib's connectors, not by this encoder, so it lives on the top-level
model config rather than in the encoder config. `build_trainable_module_spec`
lifts it out of this spec block for that reason - see the note there.
"""
from __future__ import annotations

from typing import Any, Dict, List

from ray.rllib.core.models.configs import RecurrentEncoderConfig

from gym_continuousDoubleAuction.train.model.encoders import (
    encoder_settings,
    register,
)
from gym_continuousDoubleAuction.train.model.encoders.obs_layout import ObsLayout
from gym_continuousDoubleAuction.train.model.encoders.token_embed import (
    TokenEmbedConfig,
)

#: Defaults for the `lstm` block of `encoder_specs`. `max_seq_len` is here
#: because it belongs to this encoder conceptually, but it is applied to the
#: top-level model config - see the module docstring.
LSTM_DEFAULTS = {
    "tokenization": "both",
    "d_model": 128,
    "pool": "mean",
    "num_heads": 4,
    "hidden_dim": 256,
    "num_layers": 1,
    "max_seq_len": 20,
}


@register("lstm", defaults=LSTM_DEFAULTS)
def build_lstm_config(
    layout: ObsLayout,
    spec: Dict[str, Any],
    input_dims: List[int],
) -> RecurrentEncoderConfig:
    settings = encoder_settings("lstm", spec)
    if settings["num_layers"] < 1:
        raise ValueError(
            f"lstm num_layers must be >= 1; got {settings['num_layers']}."
        )

    return RecurrentEncoderConfig(
        input_dims=input_dims,
        recurrent_layer_type="lstm",
        hidden_dim=settings["hidden_dim"],
        num_layers=settings["num_layers"],
        # RLlib's connectors hand the encoder batch-first (B, T, ...) tensors.
        batch_major=True,
        tokenizer_config=TokenEmbedConfig(
            input_dims=input_dims,
            layout=layout,
            tokenization=settings["tokenization"],
            d_model=settings["d_model"],
            pool=settings["pool"],
            num_heads=settings["num_heads"],
        ),
    )
