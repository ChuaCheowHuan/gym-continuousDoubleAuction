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
from typing import Any, Callable, Dict, List, Optional

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

#: `encoder_type` -> that encoder's full spec schema and its default values.
#: Also populated by `@register`; it is what `encoder_settings` validates against.
ENCODER_DEFAULTS: Dict[str, Dict[str, Any]] = {}

#: `encoder_type` -> `(module path, attribute)` for an RLModule class that
#: encoder needs instead of the default, or absent if it needs none.
#:
#: A *path* rather than the class, resolved on demand by `module_class_for`.
#: The classes live in `train/model/`, which imports this package, so importing
#: one here would be circular. Deferring the import is what lets an encoder
#: name its own module class without inverting that dependency.
ENCODER_MODULE_CLASSES: Dict[str, tuple] = {}

#: `encoder_type` -> `(module path, attribute)` for a Learner class, same rules.
#: The learner is algorithm-wide rather than per-module, so `train.py` resolves
#: this once from the configured encoder; see `learner_class_for`.
ENCODER_LEARNER_CLASSES: Dict[str, tuple] = {}

#: Spec keys applied to the top-level model config rather than to the encoder,
#: because RLlib reads them itself. See `model_config_overrides`.
MODEL_CONFIG_SPEC_KEYS = ("max_seq_len",)

#: Keys accepted in *every* encoder's spec block and handled centrally rather
#: than by the encoder. Null means "inherit", so an encoder that says nothing
#: about one of these gets the `ppo` group's value.
#:
#: They exist because the `ppo` group's `lr` and `vf_share_layers` were both
#: chosen for the MLP. Holding a transformer to a learning rate tuned for a
#: 2x256 tanh net measures the learning rate, not the architecture; and
#: `vf_share_layers: false` doubles an attention stack, which is a real cost
#: rather than the small one it is for an MLP.
COMMON_SPEC_KEYS = {
    "lr": None,
    "vf_share_layers": None,
}


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

    #: A `train.pretrain` checkpoint whose weights the encoder starts from.
    #:
    #: A field of its own rather than a key inside `encoder_spec`, deliberately:
    #: `encoder_spec` is what `encoder_fingerprint` hashes, and a fingerprint
    #: that depended on *where the weights came from* could never match the one
    #: stored beside those weights. It is also not an architecture knob - it
    #: changes where training starts, not what shape anything is.
    pretrained_path: Optional[str] = None


def register(
    name: str,
    defaults: Optional[Dict[str, Any]] = None,
    module_class_path: Optional[tuple] = None,
    learner_class_path: Optional[tuple] = None,
) -> Callable[[EncoderConfigBuilder], EncoderConfigBuilder]:
    """Register an encoder config builder under an `encoder_type`.

    Args:
        name: The `encoder_type` config selects on. A name starting with `_` is
            a test fixture: registered and buildable, but `validate_encoder_type`
            rejects it, so it cannot be named in a config file. That is how the
            plumbing gets an end-to-end test without shipping an architecture
            nobody asked for.
        defaults: The encoder's full spec schema. Declaring it here rather than
            inside each builder is what lets `encoder_settings` do the merge and
            the unknown-key check once, and lets `model_config_overrides` see a
            default the config file happened to omit.
        module_class_path: `(module, attribute)` naming an RLModule class this
            encoder needs instead of the default. Omit it and the encoder gets
            whatever `build_trainable_module_spec` uses for everyone - which is
            why adding this parameter changed nothing for the encoders that
            were already registered.
        learner_class_path: `(module, attribute)` naming a Learner class, same
            rules. Resolved by `train.py`, once, from the configured encoder.

    Both paths are strings resolved on demand rather than imported classes:
    those classes live in `train/model/`, which imports this package, so an
    import here would be circular.
    """

    def decorate(builder: EncoderConfigBuilder) -> EncoderConfigBuilder:
        if name in ENCODER_REGISTRY:
            raise ValueError(
                f"Encoder {name!r} is already registered, by "
                f"{ENCODER_REGISTRY[name].__module__}. Encoder names must be "
                "unique - the registry is what config selects on."
            )
        ENCODER_REGISTRY[name] = builder
        ENCODER_DEFAULTS[name] = dict(defaults or {})
        if module_class_path is not None:
            ENCODER_MODULE_CLASSES[name] = module_class_path
        if learner_class_path is not None:
            ENCODER_LEARNER_CLASSES[name] = learner_class_path
        return builder

    return decorate


def _resolve(path: tuple):
    """Import `(module, attribute)` and return the attribute."""
    import importlib

    module_name, attribute = path
    return getattr(importlib.import_module(module_name), attribute)


def module_class_for(encoder_type: str, default):
    """The RLModule class an encoder needs, or `default` if it needs none.

    `default` is what every encoder resolved to before any of them declared one,
    so an encoder that says nothing is unaffected by this mechanism existing.
    """
    path = ENCODER_MODULE_CLASSES.get(encoder_type)
    return _resolve(path) if path else default


def learner_class_for(encoder_type: str, default):
    """The Learner class an encoder needs, or `default` if it needs none.

    Unlike the module class this is algorithm-wide - RLlib takes one Learner for
    the whole run - so it is resolved from the *configured* encoder. A league
    whose modules carried different encoders would need the union of their
    learners, which is why every Learner registered here subclasses the default
    rather than replacing it.
    """
    path = ENCODER_LEARNER_CLASSES.get(encoder_type)
    return _resolve(path) if path else default


def model_config_get(model_config, key, default):
    """Read one key from a module spec's model config, dataclass or dict.

    Both forms occur and the caller does not get to choose: a freshly built
    spec holds a `CDAModelConfig`, but `add_module` - which every champion
    snapshot calls - normalises every spec's model config to a plain dict.
    Reading with `getattr` alone silently returns the default from that point
    on, which is how the structural check on `encoder_type` came to be disabled
    for the whole of a run once its first champion appeared.

    A config with no such key is a stock `DefaultModelConfig`, i.e. the mlp
    pass-through, so the caller's default is the right answer for it - including
    for a checkpoint written before the encoder group existed.
    """
    if isinstance(model_config, dict):
        return model_config.get(key, default)
    return getattr(model_config, key, default)


def _valid_keys(encoder_type: str) -> set:
    return set(ENCODER_DEFAULTS.get(encoder_type, {})) | set(COMMON_SPEC_KEYS)


def _check_keys(encoder_type: str, spec: Dict[str, Any]) -> None:
    """A misspelled knob resolving to its default silently is exactly the
    failure `config_loader` exists to prevent, so it raises here too."""
    unknown = sorted(set(spec) - _valid_keys(encoder_type))
    if unknown:
        raise ValueError(
            f"Unknown key(s) {unknown} in the {encoder_type!r} encoder spec. "
            f"Valid keys: {sorted(_valid_keys(encoder_type))}."
        )


def encoder_settings(encoder_type: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    """An encoder's *own* settings: its spec merged over its declared defaults.

    Excludes `COMMON_SPEC_KEYS`, which every encoder accepts but none consumes,
    so a builder can splat this straight into its config dataclass.
    """
    _check_keys(encoder_type, spec)
    defaults = ENCODER_DEFAULTS.get(encoder_type, {})
    return {**defaults, **{k: v for k, v in spec.items() if k in defaults}}


def common_settings(encoder_type: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    """The `COMMON_SPEC_KEYS` an encoder spec set, dropping the ones left null.

    Null means "inherit", so an encoder that says nothing about `lr` gets the
    `ppo` group's value rather than overriding it with a None.
    """
    _check_keys(encoder_type, spec)
    given = {k: v for k, v in spec.items() if k in COMMON_SPEC_KEYS}
    merged = {**COMMON_SPEC_KEYS, **given}
    return {k: v for k, v in merged.items() if v is not None}


def model_config_overrides(encoder_type: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    """Settings that belong on the top-level model config, not on the encoder.

    Two sources. `MODEL_CONFIG_SPEC_KEYS` are the encoder's own knobs that RLlib
    reads itself - `max_seq_len` is the only one, and the connectors read it to
    cut a recurrent module's batch into sequences long before any encoder is
    called. `vf_share_layers` is a common key, overriding the `ppo` group only
    when an encoder explicitly sets it.

    Merged against declared defaults rather than read raw from `spec`, so a
    config file that omits `max_seq_len` still gets the encoder's intended value
    instead of `DefaultModelConfig`'s unrelated one.
    """
    own = encoder_settings(encoder_type, spec)
    common = common_settings(encoder_type, spec)
    overrides = {k: own[k] for k in MODEL_CONFIG_SPEC_KEYS if k in own}
    if "vf_share_layers" in common:
        overrides["vf_share_layers"] = common["vf_share_layers"]
    return overrides


def training_overrides(encoder_type: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    """Settings for `AlgorithmConfig.training`, i.e. `lr`.

    `lr = 5e-05` in the `ppo` group was tuned for a 2x256 tanh MLP. A
    transformer generally wants a different one, and comparing architectures at
    a learning rate that suits only one of them measures the learning rate.
    """
    common = common_settings(encoder_type, spec)
    return {k: common[k] for k in ("lr",) if k in common}


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


def needs_next_obs(encoder_type: str, encoder_spec: Optional[Dict[str, Any]]) -> bool:
    """Whether this encoder's train batch must carry `Columns.NEXT_OBS`.

    PPO does not add it, so an encoder that predicts the next observation needs
    a learner connector attached - and attaching one unconditionally would make
    every other architecture pay for a column it never reads.

    True only for a `jepa` encoder with `world_model` on. Read from the merged
    settings rather than the raw spec block, so a config file that omits the key
    still gets the registered default.
    """
    if encoder_type not in ENCODER_DEFAULTS:
        return False
    return bool(
        encoder_settings(encoder_type, encoder_spec or {}).get("world_model")
    )


def encoder_fingerprint(encoder_type: str, encoder_spec: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The encoder's identity, as something two callers can compare with `!=`.

    One definition, because there are now two places that need it and they must
    agree exactly: `train._encoder_fingerprint`, which digs it out of an
    `AlgorithmConfig` so a restore cannot silently change the architecture, and
    the offline pretrainer, which writes it beside the weights so loading a
    `d_model: 128` checkpoint into a `d_model: 256` encoder is a hard error
    rather than a shape mismatch several frames later.

    `encoder_spec` is normalised to sorted items rather than kept as a dict:
    the fingerprint is compared with `!=`, and two dicts differing only in key
    order would otherwise read as a change. Round-tripping through JSON turns
    those tuples into lists, so `fingerprints_match` compares the normalised
    form of both sides rather than the raw values.

    **The spec is merged against the registry's defaults before it is hashed**,
    which is doc/15 S3-22. Hashing the raw spec got it wrong in both
    directions, and the two failures are opposites:

    * A false mismatch. A config that states a value equal to its registered
      default, and one that omits it, describe the *identical* architecture and
      fingerprinted differently - a hard error at `pretrain.verify_fingerprint`
      and at `train._check_restored_config` over nothing at all. That is not
      hypothetical: `pretrain(encoder_spec=None)` resolves to registry defaults
      and wrote an *empty* spec, so pretrained weights could not be loaded into
      a training run built from the config block they were trained from.
    * A false match, which is worse. A checkpoint whose spec omitted a key kept
      the same fingerprint when the value in `*_DEFAULTS` was later edited - so
      the architecture changed and the guard said nothing, which is exactly the
      silent shape mismatch this function exists to prevent.

    `encoder_settings` is the canonical merged form and is what the encoder is
    actually built from, so it is what identifies it. `mlp` has no registry
    entry and is passed through unmerged.
    """
    try:
        # `or {}` because None means "the encoder's own defaults", which is
        # exactly what merging an empty spec produces - and `encoder_settings`
        # validates keys, so it takes a mapping rather than None.
        settings = encoder_settings(encoder_type, encoder_spec or {})
    except (KeyError, ValueError):
        # `mlp` has no registry entry, and a spec carrying another encoder's
        # keys does not validate against this one. Neither is this function's
        # business: it reports an identity, and a caller comparing two of them
        # wants "these differ", not an exception from the comparison itself.
        # The un-merged spec cannot collide with a merged one, so a mismatch is
        # still what comes out.
        settings = dict(encoder_spec or {})

    return {
        "encoder_type": encoder_type,
        "encoder_spec": tuple(sorted(settings.items())),
    }


def fingerprints_match(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    """Whether two fingerprints describe the same encoder, across JSON.

    `json.dump` turns the spec's tuple of pairs into a list of lists, so a
    naive `==` between a freshly built fingerprint and one read back from disk
    is always False. Both sides are re-normalised here.
    """
    def normalise(fingerprint):
        spec = fingerprint.get("encoder_spec") or ()
        return (
            fingerprint.get("encoder_type"),
            tuple(sorted((str(k), v) for k, v in dict(spec).items())),
        )

    return normalise(left) == normalise(right)


def build_encoder_config(
    obs_space: gym.Space,
    model_config_dict: Dict[str, Any],
    action_space: Optional[gym.Space] = None,
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
    config = ENCODER_REGISTRY[encoder_type](layout, spec, [layout.flat_dim])

    # Set after building rather than passed to the builder: the builder's
    # signature is `(layout, spec, input_dims)` for every encoder, and this is
    # not part of any encoder's spec. An encoder with no `pretrained_path`
    # field simply never sees it.
    # Only an encoder that asks for it - the world model needs the action
    # space to size its action embedding, and nothing else does.
    if action_space is not None and hasattr(config, "action_space"):
        config.action_space = action_space

    pretrained = model_config_dict.get("pretrained_path")
    if pretrained:
        if not hasattr(config, "pretrained_path"):
            raise ValueError(
                f"encoder_type {encoder_type!r} was given a pretrained "
                f"checkpoint but has no `pretrained_path` field, so it cannot "
                "load one. Only encoders with a self-supervised objective can."
            )
        config.pretrained_path = pretrained
    return config


# Encoder modules are imported for their `@register` side effect, at the bottom
# so they can import the registry above without a cycle.
from gym_continuousDoubleAuction.train.model.encoders import (  # noqa: E402
    jepa,
    lstm,
    moe_transformer,
    passthrough,
    transformer,
)

#: The registered encoder modules, named so the side-effect imports above read
#: as the deliberate re-exports they are rather than as unused imports.
REGISTERED_ENCODER_MODULES = (jepa, lstm, moe_transformer, passthrough, transformer)

