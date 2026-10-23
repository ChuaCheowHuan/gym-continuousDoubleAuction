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

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import torch
from ray.rllib.core.columns import Columns

from gym_continuousDoubleAuction.logging_setup import get_logger
from gym_continuousDoubleAuction.train.model.encoders import encoder_settings
from gym_continuousDoubleAuction.train.model.encoders.pretrained import (
    FINGERPRINT_FILE,
    MODULE_SUBDIR,
    WEIGHTS_FILE,
    load_into,
    module_state_path,
    resolve_spec,
    save,
    verify_fingerprint,
)
from gym_continuousDoubleAuction.train.probe import features as features_module
from gym_continuousDoubleAuction.train.probe import probe as probe_module
from gym_continuousDoubleAuction.train.probe.corpus import ProbeCorpus

logger = get_logger(__name__)

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
        """Whether the weights must not be used: the latent spread fell far
        enough to call it a collapse, or the run diverged (see `diverged`).

        The check that matters, and the reason `latent_std` is recorded at all:
        a collapsed JEPA drives its *loss* to zero, so a run that reports only
        the loss cannot distinguish "learned everything" from "learned nothing
        and says so in the most flattering way available".
        """
        return not self.usable

    @property
    def diverged(self) -> bool:
        """Whether nothing trustworthy was measured: no reading at all, or a
        loss or latent spread that is NaN or infinite.

        `latent_std < 0.1` is False for NaN, so a run that blew up (or whose
        validation batches all returned no stats) used to pass as healthy and
        be saved under a valid fingerprint.
        """
        readings = (self.latent_std, self.train_loss, self.validation_loss)
        return not self.latent_std or not all(
            math.isfinite(v) for series in readings for v in series
        )

    @property
    def usable(self) -> bool:
        """Measured, finite and spread out: the weights are worth saving."""
        return not self.diverged and self.latent_std[-1] >= 0.1

    def summary(self) -> str:
        lines = [
            f"steps            : {self.steps}",
            f"train loss       : {self._first_last(self.train_loss)}",
            f"validation loss  : {self._first_last(self.validation_loss)}",
            f"latent std       : {self._first_last(self.latent_std)}",
        ]
        if self.diverged:
            lines.append(
                "DIVERGED: the loss or latent_std is NaN or infinite, or was "
                "never measured, so nothing here can be vouched for - do not "
                "use these weights."
            )
        elif self.collapsed:
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


def _batches(
    rows: np.ndarray, corpus: ProbeCorpus, batch_size: int, generator: np.random.Generator
):
    """Shuffled minibatches of observation rows.

    Shuffling is safe here and is *not* safe in the probe: there the split
    decides what a score means, and adjacent rows are near-duplicates. Here the
    split has already been made by episode, and within a split the order a
    self-supervised objective sees its rows in carries no information.
    """
    order = generator.permutation(len(rows))
    for start in range(0, len(order), batch_size):
        chunk = rows[order[start : start + batch_size]]
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
        chunk = rows[start : start + batch_size]
        encoder({Columns.OBS: torch.from_numpy(corpus.obs[chunk])})
        stats = encoder.take_jepa_stats()
        if stats is None:
            continue
        losses.append(float(stats["predict_loss"]))
        # A one-row chunk reports NaN (the spread of one row is undefined); it
        # is "not measured", not a datapoint to average in (issue #242).
        std = float(stats["latent_std"])
        if math.isfinite(std):
            stds.append(std)
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
        encoder_spec: Its `encoder_specs` block; None reads the config
            file's, which is what makes the pretrained architecture the
            one a training run will build.
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

    # `None` means "the config file's block", as the docstring says - it did
    # not. `build_module` turns a falsy spec into `{}`, which
    # `build_trainable_module_spec` then resolves to the *registry* defaults, so
    # a pretrained encoder was built from whatever the code shipped rather than
    # from what the run would be configured with. `save` then wrote
    # `encoder_fingerprint(encoder_type, None)` beside the weights, and a
    # training run built from the config block could not load them. See
    # docs/29 S3-22.
    encoder_spec = resolve_spec(encoder_type, encoder_spec)

    torch.manual_seed(seed)
    generator = np.random.default_rng(seed)

    module = features_module.build_module(
        obs_space, act_space, encoder_type, encoder_spec, book_mode=corpus.layout.book_mode
    )
    encoder = _jepa_encoder(module)

    # The world model has no optimiser here and no data to train on: the loop
    # feeds `encoder({Columns.OBS: batch})` with no NEXT_OBS and no ACTIONS, so
    # the term short-circuits and never runs. Saving a randomly initialised
    # world model into a checkpoint that `strict` load then pulls into a
    # training run is silent, which is the only reason this is loud.
    if encoder_settings(encoder_type, encoder_spec).get("world_model"):
        raise ValueError(
            f"encoder_spec has world_model=True, but {__name__} trains only "
            "the trunk and the predictor: the corpus carries observations "
            "alone, so the action-conditioned term never runs and its "
            "parameters would be saved untrained. Pretrain with "
            "world_model=False and enable it for the training run."
        )

    # The test fifth is held out deliberately, not wasted. The probe scores a
    # pretrained encoder "on identical rows with an identical split"
    # (docs/23 section 16), so these are exactly the episodes its test score is
    # read on; training on them here would leak them into that score.
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
                evaluated = _evaluate(encoder, module, validation_rows, corpus, batch_size)
                report.train_loss.append(float(stats["predict_loss"]))
                report.validation_loss.append(evaluated["loss"])
                report.latent_std.append(evaluated["latent_std"])
                logger.info(
                    "step %s/%s  train %.5f  val %.5f  latent_std %.4f",
                    step,
                    steps,
                    report.train_loss[-1],
                    report.validation_loss[-1],
                    report.latent_std[-1],
                )

    return module, report


#: The checkpoint format lives in `encoders.pretrained` and is re-exported here, where
#: it was first defined, so code importing it from the trainer keeps working.
__all__ = [
    "FINGERPRINT_FILE",
    "MODULE_SUBDIR",
    "PRETRAINABLE",
    "WEIGHTS_FILE",
    "PretrainReport",
    "load_into",
    "module_state_path",
    "pretrain",
    "resolve_spec",
    "save",
    "verify_fingerprint",
]
