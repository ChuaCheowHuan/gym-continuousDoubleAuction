"""The pretrained-encoder checkpoint format, for any encoder that can load one.

A pretrained encoder is a directory of three things: the encoder's weights, the
fingerprint of the architecture they belong to, and an RLlib module checkpoint.
This module reads and writes that format and nothing more. *Producing* the
weights is a trainer's job - `train.pretrain` for the encoders that ship a
self-supervised objective - and an encoder opts in by giving its config a
`pretrained_path` field, the same test `build_encoder_config` applies.

It lives here rather than in `train.pretrain` because three callers need it and
only one of them trains anything: `model_handler` verifies the fingerprint before
a run starts from pretrained weights, the probe loads them to score them, and an
encoder loads them at construction. None of those should depend on a trainer, or
on which encoder the trainer happens to know.

The fingerprint is the point of the format. `train.py` already refuses a restore
whose `encoder_type` or `encoder_spec` differs from the checkpoint's, because the
weights are that architecture's weights; a pretrained encoder needs exactly the
same guard, and gets it from the same `encoder_fingerprint`.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from gym_continuousDoubleAuction.config_loader import group
from gym_continuousDoubleAuction.logging_setup import get_logger
from gym_continuousDoubleAuction.train.model.encoders import (
    encoder_fingerprint,
    fingerprints_match,
)

logger = get_logger(__name__)

#: Files a pretrain checkpoint is made of.
WEIGHTS_FILE = "encoder.pt"
FINGERPRINT_FILE = "encoder_fingerprint.json"

#: An RLlib module checkpoint, written beside the two above.
#:
#: Two formats for two consumers, and they are not redundant. `encoder.pt` is
#: just the encoder, so the probe can load it into a module it built itself and
#: score it - and it is what the fingerprint guards. `rl_module/` is what
#: `RLModuleSpec.load_state_path` consumes, which is how a training run picks
#: the weights up through RLlib's own mechanism rather than a bespoke one.
#: The fingerprint is checked before that path is ever handed to RLlib; see
#: `verify_fingerprint`.
MODULE_SUBDIR = "rl_module"

#: Where a loadable encoder may sit inside an `ActorCriticEncoder`, in the order
#: they are tried. `encoder` is the shared trunk under `vf_share_layers: true`.
_SUB_ENCODERS = ("encoder", "actor_encoder", "critic_encoder")


def loads_pretrained(sub_encoder) -> bool:
    """Whether an encoder instance can take pretrained weights.

    The same test `build_encoder_config` applies to the encoder's config, made on
    the built encoder: its config has a `pretrained_path` field.
    """
    return hasattr(getattr(sub_encoder, "config", None), "pretrained_path")


def resolve_spec(encoder_type: str, encoder_spec: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """`encoder_spec`, with None meaning "the config file's block".

    One definition because a trainer and `save` must agree: the fingerprint
    written beside the weights has to describe the architecture the weights are
    *of*. They did not. `None` reached `build_module`, which turns a falsy spec
    into `{}` and so resolved to the *registry* defaults, while `save` wrote
    `encoder_fingerprint(encoder_type, None)` - so a pretrained encoder was
    built from whatever the code shipped rather than from what the run would be
    configured with, and the weights would not load into a training run built
    from the config block. See docs/29 S3-22.
    """
    if encoder_spec is not None:
        return encoder_spec
    return group("train_config.json", "encoder")["encoder_specs"].get(encoder_type, {})


def pretrainable_encoder(module):
    """The sub-encoder whose weights a pretrain checkpoint holds.

    The actor's (or the shared one), not both: with `vf_share_layers` false the
    critic has its own instance, and it is loaded from the same weights by
    `load_into` rather than trained a second time.

    Raises:
        ValueError: if the module has no encoder that can take pretrained weights.
    """
    for name in _SUB_ENCODERS[:2]:
        sub = getattr(module.encoder, name, None)
        if sub is not None and loads_pretrained(sub):
            return sub
    raise ValueError(
        "The built module has no encoder that can take pretrained weights: only an "
        "encoder whose config has a `pretrained_path` field can."
    )


def save(module, path: str, encoder_type: str, encoder_spec: Optional[Dict[str, Any]]) -> None:
    """Write the trained encoder's weights and the fingerprint that guards them."""
    import torch

    os.makedirs(path, exist_ok=True)
    encoder = pretrainable_encoder(module)

    torch.save(encoder.state_dict(), os.path.join(path, WEIGHTS_FILE))
    # Ray reads a bare relative path as a URI with no scheme and raises (#316).
    module.save_to_path(os.path.abspath(os.path.join(path, MODULE_SUBDIR)))
    with open(os.path.join(path, FINGERPRINT_FILE), "w") as handle:
        fingerprint = encoder_fingerprint(encoder_type, encoder_spec)
        # The tuple of pairs becomes a list of lists here; `fingerprints_match`
        # normalises both sides rather than relying on the round trip.
        json.dump(
            {
                "encoder_type": fingerprint["encoder_type"],
                "encoder_spec": dict(fingerprint["encoder_spec"]),
            },
            handle,
            indent=2,
        )
    logger.info("wrote %s and %s to %s", WEIGHTS_FILE, FINGERPRINT_FILE, path)


def verify_fingerprint(
    path: str, encoder_type: str, encoder_spec: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Check a pretrain checkpoint describes the encoder about to be built.

    Run at *spec-build* time, before any weights are handed to RLlib. That is
    the same point `_check_restored_config` guards a restore, and for the same
    reason: the weights are that architecture's weights, so a `d_model: 128`
    checkpoint meeting a `d_model: 256` encoder must fail loudly here rather
    than as a shape error several frames away - or, worse, as a partial load.

    Returns:
        The stored fingerprint.

    Raises:
        FileNotFoundError: if `path` is not a pretrain checkpoint.
        ValueError: on a mismatch.
    """
    # Resolved the same way a trainer and `save` resolve it, so all three
    # agree on what `None` means.
    encoder_spec = resolve_spec(encoder_type, encoder_spec)

    fingerprint_path = os.path.join(path, FINGERPRINT_FILE)
    for required in (os.path.join(path, WEIGHTS_FILE), fingerprint_path):
        if not os.path.isfile(required):
            raise FileNotFoundError(
                f"{path!r} is not a pretrain checkpoint: {required} is missing. "
                f"One is a directory holding {WEIGHTS_FILE}, "
                f"{FINGERPRINT_FILE} and {MODULE_SUBDIR}/."
            )

    with open(fingerprint_path) as handle:
        stored = json.load(handle)

    wanted = encoder_fingerprint(encoder_type, encoder_spec)
    if not fingerprints_match(stored, wanted):
        raise ValueError(
            f"The pretrained encoder in {path!r} does not match the one being "
            f"built.\n  checkpoint: {stored}\n  requested : "
            f"{{'encoder_type': {wanted['encoder_type']!r}, 'encoder_spec': "
            f"{dict(wanted['encoder_spec'])}}}\n"
            "The weights are that architecture's weights. Rebuild the "
            "pretrained encoder against this config, or point at the "
            "checkpoint that matches it."
        )
    return stored


def module_state_path(path: str, encoder_type: str, encoder_spec: Optional[Dict[str, Any]]) -> str:
    """The `RLModuleSpec.load_state_path` for a verified pretrain checkpoint.

    The fingerprint is checked first, so a mismatched checkpoint never reaches
    RLlib's loader - which would either fail with a shape error carrying no
    hint about why, or silently load what happened to line up.
    """
    verify_fingerprint(path, encoder_type, encoder_spec)
    module_path = os.path.join(path, MODULE_SUBDIR)
    if not os.path.isdir(module_path):
        raise FileNotFoundError(
            f"{path!r} carries no {MODULE_SUBDIR}/ directory, so a training run "
            "cannot load it. It was written by an older pretrainer; pretrain it again."
        )
    return module_path


def load_state(path: str):
    """The encoder weights stored in a pretrain checkpoint, on the CPU."""
    import torch

    return torch.load(os.path.join(path, WEIGHTS_FILE), map_location="cpu", weights_only=True)


def load_into(
    module, path: str, encoder_type: str, encoder_spec: Optional[Dict[str, Any]]
) -> List[str]:
    """Load pretrained weights into every encoder of `module`.

    Both the actor's encoder and, when `vf_share_layers` is false, the critic's
    get the same weights. They diverge during PPO; starting them from the same
    representation is the point of having pretrained one.

    Returns:
        The names of the sub-encoders that were loaded.

    Raises:
        FileNotFoundError: if `path` holds no pretrain checkpoint.
        ValueError: if the checkpoint's fingerprint does not match the encoder
            being loaded into, or the module has no encoder that can load one.
    """
    verify_fingerprint(path, encoder_type, encoder_spec)
    state = load_state(path)

    loaded = []
    for name in _SUB_ENCODERS:
        sub = getattr(module.encoder, name, None)
        if sub is not None and loads_pretrained(sub):
            sub.load_state_dict(state)
            loaded.append(name)

    if not loaded:
        raise ValueError(
            "The module has no encoder that can take pretrained weights. Pretrained "
            "weights only fit the encoder they were trained for."
        )
    logger.info("loaded pretrained weights into %s", ", ".join(loaded))
    return loaded
