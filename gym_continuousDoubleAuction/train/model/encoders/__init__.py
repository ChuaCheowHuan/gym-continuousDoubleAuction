"""Selectable observation encoders for the trainable PPO modules.

What this package is for
------------------------
The trainable modules encode observations with RLlib's stock MLP. This package
lets `config/train_config.json`'s `encoder` group swap that for something else -
an LSTM, a transformer - without touching PPO, the league wiring, or the action
heads. The frozen `RandomRLModule` baselines have no network and are unaffected.

How the swap happens
--------------------
RLlib's `Catalog` already has the seam. `Catalog.__init__` merges the module's
`model_config` over `DefaultModelConfig()`'s defaults into `_model_config_dict`,
then `_determine_components_hook` calls the static `_get_encoder_config` to
decide the encoder and reads `latent_dims` off whatever that returns. So:

  * `CDAModelConfig` extends `DefaultModelConfig` with two extra fields. Because
    the catalog converts a dataclass with `dataclasses.asdict`, the extra fields
    survive into `_model_config_dict` where a catalog can read them.
  * `CDACatalog` (in `model_handler`) overrides `_get_encoder_config` to look the
    encoder up here instead of running RLlib's default decision tree.
  * `PPOCatalog.__init__` then wraps whatever came back in an
    `ActorCriticEncoderConfig`, which supplies the `ENCODER_OUT/{ACTOR, CRITIC}`
    contract, the `.critic_encoder` attribute `compute_values` looks for, the
    `inference_only` handling, and - for a config deriving from
    `RecurrentEncoderConfig` - the stateful wrapper. None of that has to be
    written here.

The consequence is that an encoder is *only* a `ModelConfig` plus an `Encoder`.
`DefaultPPOTorchRLModule` needs no subclass, and the pi/vf heads keep coming
from the stock catalog, sized off `latent_dims`.

`mlp` is deliberately not in this registry. It resolves to the stock
`DefaultModelConfig` path in `model_handler.default_model_config` and never
reaches `CDACatalog`, so a default run is bit-identical to one from before this
package existed and every checkpoint written by one still loads.

Adding an encoder
-----------------
Write a module here defining a `ModelConfig` (with `output_dims` set, since that
becomes `latent_dims`) and its `Encoder`, decorate a builder with `@register`,
import it at the bottom of this file, and add its block to `encoder_specs` in
`config/train_config.json`. A spec block existing is the signal that its encoder
is implemented.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List

import gymnasium as gym
from ray.rllib.core.models.configs import ModelConfig
from ray.rllib.core.rl_module.default_model_config import DefaultModelConfig

from gym_continuousDoubleAuction.train.model.encoders.obs_layout import ObsLayout

#: `encoder_type` that means "use the stock RLlib MLP". Handled before the
#: registry - see the module docstring.
MLP_ENCODER_TYPE = "mlp"

#: Builds one encoder's `ModelConfig`. Registered under an `encoder_type`.
EncoderConfigBuilder = Callable[[ObsLayout, Dict[str, Any], List[int]], ModelConfig]

#: `encoder_type` -> builder. Populated by `@register` at import time.
ENCODER_REGISTRY: Dict[str, EncoderConfigBuilder] = {}


@dataclass
class CDAModelConfig(DefaultModelConfig):
    """`DefaultModelConfig` plus the two fields `CDACatalog` dispatches on.

    Subclassing rather than replacing keeps every stock field meaningful - the
    pi/vf heads are still built from `head_fcnet_hiddens`, the actor/critic
    trunks are still shared or not per `vf_share_layers` - so a custom encoder
    only has to describe itself, not re-specify the rest of the network.
    """

    #: Key into `ENCODER_REGISTRY`. `MLP_ENCODER_TYPE` never reaches a catalog.
    encoder_type: str = MLP_ENCODER_TYPE

    #: That encoder's block from `encoder_specs`, passed through to its builder.
    encoder_spec: Dict[str, Any] = field(default_factory=dict)


def register(name: str) -> Callable[[EncoderConfigBuilder], EncoderConfigBuilder]:
    """Register an encoder config builder under an `encoder_type`.

    A name starting with `_` is a test fixture: it is registered and buildable,
    but `validate_encoder_type` rejects it, so it cannot be selected from
    config. That is how the plumbing gets an end-to-end test without shipping an
    architecture nobody asked for.
    """

    def decorate(builder: EncoderConfigBuilder) -> EncoderConfigBuilder:
        if name in ENCODER_REGISTRY:
            raise ValueError(
                f"Encoder {name!r} is already registered, by "
                f"{ENCODER_REGISTRY[name].__module__}. Encoder names must be "
                "unique - the registry is what config selects on."
            )
        ENCODER_REGISTRY[name] = builder
        return builder

    return decorate


def selectable_encoder_types() -> List[str]:
    """Every `encoder_type` a config file may name, sorted."""
    return sorted(
        [MLP_ENCODER_TYPE]
        + [name for name in ENCODER_REGISTRY if not name.startswith("_")]
    )


def known_encoder_type(encoder_type: str) -> str:
    """Check an `encoder_type` names something buildable, returning it unchanged.

    Permissive about test fixtures, so a test can drive one through the same
    code path a real encoder takes. Config values go through
    `validate_encoder_type` instead, which is the strict one.

    Raises:
        ValueError: if it names no registered encoder.
    """
    if encoder_type == MLP_ENCODER_TYPE or encoder_type in ENCODER_REGISTRY:
        return encoder_type

    raise ValueError(
        f"Unknown encoder_type {encoder_type!r}. Available: "
        f"{', '.join(selectable_encoder_types())}."
    )


def validate_encoder_type(encoder_type: str) -> str:
    """Check an `encoder_type` *read from config*, returning it unchanged.

    Stricter than `known_encoder_type`: it also refuses test fixtures, which
    are buildable but must not be selectable from a config file. Call this at
    the boundary where a config value is read - not on every build, or a test
    could never exercise a fixture.

    Raises:
        ValueError: if it names no registered encoder, or names a test fixture.
    """
    if encoder_type.startswith("_") and encoder_type in ENCODER_REGISTRY:
        raise ValueError(
            f"Encoder {encoder_type!r} is a test fixture and cannot be "
            "selected from config. Available: "
            f"{', '.join(selectable_encoder_types())}."
        )
    return known_encoder_type(encoder_type)


def build_encoder_config(
    obs_space: gym.Space,
    model_config_dict: Dict[str, Any],
) -> ModelConfig:
    """Build the encoder `ModelConfig` a `CDAModelConfig` asks for.

    Called from `CDACatalog._get_encoder_config`, so `model_config_dict` is the
    catalog's merged dict, carrying `CDAModelConfig`'s extra fields.

    Raises:
        ValueError: on an unknown or fixture-only `encoder_type`, or on
            `MLP_ENCODER_TYPE`, which must never reach a custom catalog.
    """
    encoder_type = model_config_dict["encoder_type"]

    if encoder_type == MLP_ENCODER_TYPE:
        raise ValueError(
            "CDACatalog was built for encoder_type 'mlp', which is the "
            "pass-through the stock RLlib catalog already handles. "
            "build_trainable_module_spec should not have routed it here."
        )
    if encoder_type not in ENCODER_REGISTRY:
        raise ValueError(
            f"Unknown encoder_type {encoder_type!r}. Available: "
            f"{', '.join(selectable_encoder_types())}."
        )

    layout = ObsLayout.from_obs_space(obs_space)
    spec = model_config_dict.get("encoder_spec") or {}
    return ENCODER_REGISTRY[encoder_type](layout, spec, [layout.flat_dim])


# Encoder modules are imported for their `@register` side effect, at the bottom
# so they can import the registry above without a cycle.
from gym_continuousDoubleAuction.train.model.encoders import (  # noqa: E402,F401
    passthrough,
    transformer,
)
