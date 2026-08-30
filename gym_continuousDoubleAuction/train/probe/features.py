"""The feature sets a probe is scored on: raw observations, and frozen latents.

Three kinds, and the comparison only means something with all three present:

  raw            The observation itself. The floor. Since every latent is a
                 function of this vector, a latent that does not beat it under
                 a linear readout has reorganised nothing.
  <encoder>      That architecture at initialisation, weights untrained. This
                 is the *inductive bias* term: a transformer that beats `raw`
                 before any training has done so through tokenisation, the
                 two-axis positional encoding and the input LayerNorm alone.
  <encoder> @ckpt  The same architecture with weights from a real checkpoint.
                 Trained minus untrained is what training actually taught it.

Reporting a trained encoder without its untrained twin is the mistake this
module is shaped to prevent. `doc/18` §5.5 already warns that comparing
architectures at one learning rate measures the learning rate; comparing a
trained encoder against only `raw` has the same shape, and credits the
architecture with whatever its initialisation was already worth.

Freezing
--------
Everything here runs under `eval()` and `torch.no_grad()`. `eval()` is not
cosmetic: dropout is a spec key on every tokenising encoder, and a live dropout
would make the latent - and therefore the score - nondeterministic, which is
the same failure `test_eval_forward_is_deterministic` exists to catch on the
policy path.

Statefulness
------------
The LSTM encoder is recurrent, so its latent at step `t` depends on the whole
episode before `t`. It is therefore run one episode at a time with the state
threaded through, and reset at each episode boundary. Batching its rows the way
the stateless encoders are batched would silently score it on a memory that was
re-initialised every row - which is not the encoder anyone configured.
"""
from __future__ import annotations

import os
from typing import Dict, Optional

import numpy as np
import torch
import tree
from ray.rllib.algorithms.ppo.torch.default_ppo_torch_rl_module import (
    DefaultPPOTorchRLModule,
)
from ray.rllib.core.columns import Columns
from ray.rllib.core.models.base import ACTOR, ENCODER_OUT
from ray.rllib.core.rl_module.rl_module import RLModule

from gym_continuousDoubleAuction.logging_setup import get_logger
from gym_continuousDoubleAuction.train.model.model_handler import (
    build_trainable_module_spec,
)
from gym_continuousDoubleAuction.train.probe.corpus import ProbeCorpus

logger = get_logger(__name__)

#: Name of the `raw` feature set, which has no encoder behind it.
RAW_FEATURES = "raw"

#: Rows per forward pass for a stateless encoder. Only a memory/throughput
#: knob - the latents do not depend on it.
BATCH_ROWS = 512

#: Where an RLlib algorithm checkpoint keeps one module's state.
_MODULE_SUBPATH = ("learner_group", "learner", "rl_module")

#: Written by `RLModule.save_to_path` beside the weights. Its presence is what
#: distinguishes a module directory from any other directory that happens to
#: exist - without that test, a `--module-id` naming a module the checkpoint
#: does not contain falls back to loading the checkpoint *root* as a module,
#: and the user gets a missing-file error about an internal pickle rather than
#: being told which module was not found.
_MODULE_MARKER = "module_state.pkl"


def raw(corpus: ProbeCorpus) -> np.ndarray:
    """The observation stream itself, as `(N, flat_dim)` float64."""
    return corpus.obs.astype(np.float64)


def build_module(
    obs_space,
    act_space,
    encoder_type: str,
    encoder_spec: Optional[Dict] = None,
) -> RLModule:
    """One trainable module, built exactly as training builds it.

    Going through `build_trainable_module_spec` rather than instantiating an
    encoder directly is what makes the probe score *the encoder training would
    use* - the same catalog, the same `vf_share_layers`, the same
    `ActorCriticEncoder` wrapper. An encoder built by hand here could drift
    from the configured one without anything failing.
    """
    spec = build_trainable_module_spec(
        obs_space,
        act_space,
        encoder_type=encoder_type,
        encoder_specs={encoder_type: encoder_spec} if encoder_spec else {},
    )
    # Only `mlp` leaves module_class None, for RLlib to fill from the
    # algorithm's default spec; there is no algorithm here to fill it.
    if spec.module_class is None:
        spec.module_class = DefaultPPOTorchRLModule
    return spec.build()


def load_module(checkpoint: str, module_id: str) -> RLModule:
    """Restore one module from a training checkpoint.

    Args:
        checkpoint: An `iter_<n>` directory as `train.py` writes, or the module
            directory inside one.
        module_id: Which module, e.g. `policy_0`. Ignored if `checkpoint`
            already points at a module directory.

    Returns:
        The restored `RLModule`, architecture and weights both - so the
        `encoder_type` scored is the one the run trained, not the one the
        current `train_config.json` happens to name.

    Raises:
        FileNotFoundError: if no module directory is found.
    """
    path = _module_path(checkpoint, module_id)
    logger.info("loading module from %s", path)
    return RLModule.from_checkpoint(path)


def _module_path(checkpoint: str, module_id: str) -> str:
    """Resolve `checkpoint` to the directory holding one module's state.

    Accepts either an `iter_<n>` checkpoint directory or a module directory
    passed straight in, and refuses anything else rather than handing an
    unrelated directory to the deserialiser.
    """
    direct = os.path.join(checkpoint, *_MODULE_SUBPATH, module_id)
    for candidate in (direct, checkpoint):
        if _is_module_dir(candidate):
            return candidate

    available = _available_modules(checkpoint)
    raise FileNotFoundError(
        f"No module {module_id!r} under {checkpoint!r}. Looked for {direct} "
        f"and for {checkpoint} itself as a module directory. "
        + (f"Modules present: {', '.join(available)}. " if available else "")
        + "`train.py` writes checkpoints as iter_<n>/ directories under "
        "checkpoint_dir."
    )


def _is_module_dir(path: str) -> bool:
    return os.path.isfile(os.path.join(path, _MODULE_MARKER))


def _available_modules(checkpoint: str) -> list:
    """Module ids in a checkpoint, so the error can name them."""
    root = os.path.join(checkpoint, *_MODULE_SUBPATH)
    if not os.path.isdir(root):
        return []
    return sorted(
        name for name in os.listdir(root)
        if _is_module_dir(os.path.join(root, name))
    )


def pretrained_module(obs_space, act_space, encoder_type: str,
                     path: str, encoder_spec: Optional[Dict] = None) -> RLModule:
    """A module of the configured architecture, carrying pretrained weights.

    The measurement offline pretraining exists to make: the same architecture
    appears twice in a report, once at initialisation and once after the
    self-supervised objective has trained it, on identical rows with an
    identical split. Everything between those two columns is what pretraining
    taught the encoder.

    Imported lazily because `train.pretrain` imports this module - the probe is
    the corpus reader pretraining reuses, so the dependency only runs one way
    at import time.

    Raises:
        FileNotFoundError: if `path` is not a pretrain checkpoint.
        ValueError: if its fingerprint does not match the encoder being built.
    """
    from gym_continuousDoubleAuction.train.pretrain import load_into

    module = build_module(obs_space, act_space, encoder_type, encoder_spec)
    load_into(module, path, encoder_type, encoder_spec)
    return module


def latents(module: RLModule, corpus: ProbeCorpus) -> np.ndarray:
    """Frozen encoder latents for every row of `corpus`, as `(N, d)` float64.

    The actor branch, not the critic: with `vf_share_layers` false they are two
    independently initialised encoders of the same shape, and the actor's is
    the one the policy acts on.
    """
    module.eval()
    with torch.no_grad():
        if module.is_stateful():
            return _stateful_latents(module, corpus)
        return _stateless_latents(module, corpus)


def _encode(module: RLModule, batch) -> torch.Tensor:
    return module.encoder(batch)[ENCODER_OUT][ACTOR]


def _stateless_latents(module: RLModule, corpus: ProbeCorpus) -> np.ndarray:
    out = []
    for start in range(0, len(corpus), BATCH_ROWS):
        obs = torch.from_numpy(corpus.obs[start:start + BATCH_ROWS])
        out.append(_encode(module, {Columns.OBS: obs}).numpy())
    return np.concatenate(out).astype(np.float64)


def _stateful_latents(module: RLModule, corpus: ProbeCorpus) -> np.ndarray:
    """One sequence per episode, state carried within and reset between.

    The whole episode goes through in a single forward pass. A recurrent
    encoder's state is carried inside the call, so chunking would need the
    returned `state_out` threaded back in - correct, but an extra moving part
    for no gain at episode lengths this env produces.
    """
    out = np.empty((len(corpus), _latent_width(module, corpus)), dtype=np.float64)

    for episode in np.unique(corpus.episode_index):
        rows = np.flatnonzero(corpus.episode_index == episode)
        # (1, T, obs): one sequence, the episode's full length.
        obs = torch.from_numpy(corpus.obs[rows]).unsqueeze(0)
        state_in = tree.map_structure(
            lambda s: s.unsqueeze(0).contiguous(), module.get_initial_state()
        )
        latent = _encode(module, {Columns.OBS: obs, Columns.STATE_IN: state_in})
        out[rows] = latent.squeeze(0).numpy().astype(np.float64)

    return out


def _latent_width(module: RLModule, corpus: ProbeCorpus) -> int:
    """Latent width, measured by encoding one row rather than read off config.

    `latent_dims` lives on the catalog and a stateful encoder's is reached
    through two wrappers; one forward pass answers the question without
    depending on either.
    """
    obs = torch.from_numpy(corpus.obs[:1]).unsqueeze(0)
    state_in = tree.map_structure(
        lambda s: s.unsqueeze(0).contiguous(), module.get_initial_state()
    )
    latent = _encode(module, {Columns.OBS: obs, Columns.STATE_IN: state_in})
    return int(latent.shape[-1])
