"""Training a JEPA encoder on observations alone, before any PPO runs.

The loop is small because everything it needs already exists: the corpus reader
is the probe harness's, the encoder is whatever `build_trainable_module_spec`
would give a real run, and the objective is the one the encoder already computes
for itself during training. What is added here is the optimiser, the split, and
the checkpoint format.

Why the module rather than the encoder
--------------------------------------
This builds the whole `RLModuleSpec` and trains the encoder inside it, rather
than instantiating a `TorchJEPAEncoder` directly. That is deliberate: it
guarantees the pretrained architecture is *the one training will use* - same
catalog, same `vf_share_layers`, same `ActorCriticEncoder` wrapper - and it is
the same reasoning `probe.features.build_module` gives. An encoder built by hand
here could drift from the configured one without anything failing until the
weights refused to load.

The pi and vf heads are built and never touched. They cost a few hundred
kilobytes and remove a whole class of "the pretrained thing was subtly not the
trained thing" bug.

What is held out, and why it is held out by episode
---------------------------------------------------
The objective is self-supervised, so nothing stops it training on every row.
A validation split is still worth having: it is the only way to tell "the loss
went down" from "the loss went down on rows it had memorised", and a collapse
shows up there first. It is split by episode, reusing `probe.probe.split_masks`
- consecutive observations share three of their four snapshots, so a row-level
split puts near-duplicates of a validation row in training.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import torch
from ray.rllib.core.columns import Columns

from gym_continuousDoubleAuction.logging_setup import get_logger
from gym_continuousDoubleAuction.train.model.encoders import (
    encoder_fingerprint,
    fingerprints_match,
)
from gym_continuousDoubleAuction.train.probe import features as features_module
from gym_continuousDoubleAuction.train.probe import probe as probe_module
from gym_continuousDoubleAuction.train.probe.corpus import ProbeCorpus

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

#: The encoder this trains. Nothing else defines a JEPA objective, and
#: pretraining an encoder that has none would run happily and produce nothing.
PRETRAINABLE = ("jepa",)


@dataclass
class PretrainReport:
    """What one pretraining run did, for the CLI to print and a test to assert."""

    steps: int
    train_loss: List[float] = field(default_factory=list)
    validation_loss: List[float] = field(default_factory=list)
    latent_std: List[float] = field(default_factory=list)

    @property
    def collapsed(self) -> bool:
        """Whether the latent spread fell far enough to call it a collapse.

        The check that matters, and the reason `latent_std` is recorded at all:
        a collapsed JEPA drives its *loss* to zero, so a run that reports only
        the loss cannot distinguish "learned everything" from "learned nothing
        and says so in the most flattering way available".
        """
        return bool(self.latent_std) and self.latent_std[-1] < 0.1

    def summary(self) -> str:
        lines = [
            f"steps            : {self.steps}",
            f"train loss       : {self._first_last(self.train_loss)}",
            f"validation loss  : {self._first_last(self.validation_loss)}",
            f"latent std       : {self._first_last(self.latent_std)}",
        ]
        if self.collapsed:
            lines.append(
                "COLLAPSED: latent_std fell below 0.1, so the encoder maps every "
                "observation to nearly the same vector. The prediction loss "
                "looks excellent precisely because of it - do not use these "
                "weights."
            )
        return "\n".join(lines)

    @staticmethod
    def _first_last(values) -> str:
        if not values:
            return "-"
        return f"{values[0]:.5f} -> {values[-1]:.5f}"


def _jepa_encoder(module):
    """The sub-encoder carrying the JEPA machinery.

    The actor's, not both: with `vf_share_layers` false the critic has its own
    instance, and training both would double the objective on the same data -
    the confound `moe_learner` had to average over blocks to avoid.
    """
    encoder = module.encoder
    for name in ("encoder", "actor_encoder"):
        sub = getattr(encoder, name, None)
        if sub is not None and hasattr(sub, "take_jepa_stats"):
            return sub
    raise ValueError(
        "The built module has no JEPA encoder. Pretraining trains a "
        f"self-supervised objective, so encoder_type must be one of "
        f"{', '.join(PRETRAINABLE)}."
    )


def _batches(rows: np.ndarray, corpus: ProbeCorpus, batch_size: int,
             generator: np.random.Generator):
    """Shuffled minibatches of observation rows.

    Shuffling is safe here and is *not* safe in the probe: there the split
    decides what a score means, and adjacent rows are near-duplicates. Here the
    split has already been made by episode, and within a split the order a
    self-supervised objective sees its rows in carries no information.
    """
    order = generator.permutation(len(rows))
    for start in range(0, len(order), batch_size):
        chunk = rows[order[start:start + batch_size]]
        yield torch.from_numpy(corpus.obs[chunk])


@torch.no_grad()
def _evaluate(encoder, module, rows, corpus, batch_size) -> Dict[str, float]:
    """Objective on held-out episodes.

    Runs with the module in *train* mode, because the objective only exists
    there - masking is off in eval, by design, so an eval-mode pass would
    report nothing at all. `no_grad` is what makes it an evaluation.
    """
    losses, stds = [], []
    for start in range(0, len(rows), batch_size):
        chunk = rows[start:start + batch_size]
        encoder({Columns.OBS: torch.from_numpy(corpus.obs[chunk])})
        stats = encoder.take_jepa_stats()
        if stats is None:
            continue
        losses.append(float(stats["predict_loss"]))
        stds.append(float(stats["latent_std"]))
    return {
        "loss": float(np.mean(losses)) if losses else float("nan"),
        "latent_std": float(np.mean(stds)) if stds else float("nan"),
    }


def pretrain(
    corpus: ProbeCorpus,
    obs_space,
    act_space,
    encoder_type: str = "jepa",
    encoder_spec: Optional[Dict[str, Any]] = None,
    steps: int = 200,
    batch_size: int = 128,
    lr: float = 3e-4,
    seed: int = 0,
    log_every: int = 20,
):
    """Train a JEPA encoder on `corpus`, returning the module and a report.

    Args:
        corpus: Observations to train on. Built by `probe.corpus`.
        obs_space: Single-agent observation space, for building the module.
        act_space: Single-agent action space, same.
        encoder_type: Must name an encoder with a JEPA objective.
        encoder_spec: Its `encoder_specs` block; None reads the config file's.
        steps: Optimiser steps.
        batch_size: Rows per step.
        lr: Adam learning rate.
        seed: Seeds the shuffle and torch, so a run is reproducible.
        log_every: How often to evaluate and log.

    Returns:
        `(module, report)`. The module carries the trained encoder; `report`
        carries the loss curves and - the one worth reading - `latent_std`.

    Raises:
        ValueError: if `encoder_type` names an encoder with no JEPA objective,
            or the corpus is too small to split.
    """
    if encoder_type not in PRETRAINABLE:
        raise ValueError(
            f"Cannot pretrain encoder_type {encoder_type!r}: it defines no "
            f"self-supervised objective. Available: {', '.join(PRETRAINABLE)}."
        )

    torch.manual_seed(seed)
    generator = np.random.default_rng(seed)

    module = features_module.build_module(
        obs_space, act_space, encoder_type, encoder_spec
    )
    encoder = _jepa_encoder(module)

    train_mask, validation_mask, _test_mask = probe_module.split_masks(
        corpus.episode_index, len(corpus)
    )
    train_rows = np.flatnonzero(train_mask)
    validation_rows = np.flatnonzero(validation_mask)
    if not len(train_rows) or not len(validation_rows):
        raise ValueError(
            f"A corpus of {len(corpus)} rows over {corpus.num_episodes} "
            "episode(s) does not divide into a train and validation split. "
            "Collect more episodes."
        )

    # Only the parts the objective trains. The pi and vf heads have no gradient
    # here at all, and the target trunk must never be trained by one - it moves
    # by EMA, and that asymmetry is what discourages collapse.
    trained = list(encoder.trunk.parameters()) + list(encoder.predictor.parameters())
    optimiser = torch.optim.Adam(trained, lr=lr)

    module.train()
    report = PretrainReport(steps=steps)
    step = 0
    while step < steps:
        for batch in _batches(train_rows, corpus, batch_size, generator):
            if step >= steps:
                break

            encoder({Columns.OBS: batch})
            stats = encoder.take_jepa_stats()
            if stats is None:
                raise RuntimeError(
                    "The encoder produced no JEPA stats in train mode. Its "
                    "objective is not running, so this loop would report a "
                    "falling loss while training nothing."
                )

            optimiser.zero_grad(set_to_none=True)
            stats["aux_loss"].backward()
            optimiser.step()
            step += 1

            if step % log_every == 0 or step == steps:
                evaluated = _evaluate(
                    encoder, module, validation_rows, corpus, batch_size
                )
                report.train_loss.append(float(stats["predict_loss"]))
                report.validation_loss.append(evaluated["loss"])
                report.latent_std.append(evaluated["latent_std"])
                logger.info(
                    "step %s/%s  train %.5f  val %.5f  latent_std %.4f",
                    step, steps, report.train_loss[-1],
                    report.validation_loss[-1], report.latent_std[-1],
                )

    return module, report


def save(module, path: str, encoder_type: str,
         encoder_spec: Optional[Dict[str, Any]]) -> None:
    """Write the trained encoder's weights and the fingerprint that guards them.

    The fingerprint is the whole point of the format. `train.py` already refuses
    a restore whose `encoder_type` or `encoder_spec` differs from the
    checkpoint's, because the weights are that architecture's weights; a
    pretrained encoder needs exactly the same guard, and gets it from the same
    `encoder_fingerprint`.
    """
    os.makedirs(path, exist_ok=True)
    encoder = _jepa_encoder(module)

    torch.save(encoder.state_dict(), os.path.join(path, WEIGHTS_FILE))
    module.save_to_path(os.path.join(path, MODULE_SUBDIR))
    with open(os.path.join(path, FINGERPRINT_FILE), "w") as handle:
        fingerprint = encoder_fingerprint(encoder_type, encoder_spec)
        # The tuple of pairs becomes a list of lists here; `fingerprints_match`
        # normalises both sides rather than relying on the round trip.
        json.dump(
            {"encoder_type": fingerprint["encoder_type"],
             "encoder_spec": dict(fingerprint["encoder_spec"])},
            handle,
            indent=2,
        )
    logger.info("wrote %s and %s to %s", WEIGHTS_FILE, FINGERPRINT_FILE, path)


def verify_fingerprint(path: str, encoder_type: str,
                      encoder_spec: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Check a pretrain checkpoint describes the encoder about to be built.

    Extracted so it can run at *spec-build* time, before any weights are handed
    to RLlib. That is the same point `_check_restored_config` guards a restore,
    and for the same reason: the weights are that architecture's weights, so a
    `d_model: 128` checkpoint meeting a `d_model: 256` encoder must fail loudly
    here rather than as a shape error several frames away - or, worse, as a
    partial load.

    Returns:
        The stored fingerprint.

    Raises:
        FileNotFoundError: if `path` is not a pretrain checkpoint.
        ValueError: on a mismatch.
    """
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


def module_state_path(path: str, encoder_type: str,
                      encoder_spec: Optional[Dict[str, Any]]) -> str:
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
            "cannot load it. It was written by an older pretrainer; re-run "
            "`python -m gym_continuousDoubleAuction.train.pretrain`."
        )
    return module_path


def load_into(module, path: str, encoder_type: str,
              encoder_spec: Optional[Dict[str, Any]]) -> List[str]:
    """Load pretrained weights into every encoder of `module`.

    Both the actor's encoder and, when `vf_share_layers` is false, the critic's
    get the same trunk. They diverge during PPO; starting them from the same
    representation is the point of having pretrained one.

    Returns:
        The names of the sub-encoders that were loaded.

    Raises:
        FileNotFoundError: if `path` holds no pretrain checkpoint.
        ValueError: if the checkpoint's fingerprint does not match the encoder
            being loaded into. Loading a `d_model: 128` checkpoint into a
            `d_model: 256` encoder must be a hard error - the alternative is a
            shape mismatch several frames away, or worse, a partial load.
    """
    verify_fingerprint(path, encoder_type, encoder_spec)
    state = torch.load(
        os.path.join(path, WEIGHTS_FILE), map_location="cpu", weights_only=True
    )

    loaded = []
    for name in ("encoder", "actor_encoder", "critic_encoder"):
        sub = getattr(module.encoder, name, None)
        if sub is not None and hasattr(sub, "take_jepa_stats"):
            sub.load_state_dict(state)
            loaded.append(name)

    if not loaded:
        raise ValueError(
            "The module has no JEPA encoder to load into. Pretrained weights "
            "only fit the encoder they were trained for."
        )
    logger.info("loaded pretrained weights into %s", ", ".join(loaded))
    return loaded
