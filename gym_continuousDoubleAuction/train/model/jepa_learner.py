"""Carrying the JEPA latent-prediction loss from the encoder to the optimiser.

Two classes, mirroring `moe_learner` rather than merging with it:

  JEPARLModule    - takes the stats the JEPA encoder left behind and puts them
                    in `fwd_out`, which is the only channel from a module's
                    forward pass to the Learner's loss. Also declares the
                    encoder's training-only submodules.
  CDAJEPALearner  - adds `aux_loss_coeff * aux` to PPO's total loss and logs
                    the two collapse metrics.

Why the encoder cannot simply return the loss: `ActorCriticEncoder._forward`
keeps only `{ENCODER_OUT: {ACTOR, CRITIC}}` and discards every other key its
inner encoders produced. See `TorchJEPAEncoder.take_jepa_stats`.

Why this file rather than an addition to `moe_learner`
------------------------------------------------------
Both classes here *subclass* the ones there. Generalising `moe_learner` into a
shared auxiliary-loss seam would be the better design in the abstract - two
consumers is the point at which that usually pays - but it would edit code on
the path of every custom encoder, and `jepa` is meant to be addable without
touching any of them. Subclassing gets the same behaviour with a diff that
reaches nothing already shipped, and `CDAJEPALearner` inherits the MoE term
rather than replacing it, so a league mixing the two still works.

The actor branch only
---------------------
`vf_share_layers` is false by default, which builds two independent encoder
instances. Both would compute a JEPA loss, and adding them would double the
term - silently, and only under that setting. `moe_learner` hit exactly this
and had to average over blocks rather than sum. Here the collector takes the
*first* sub-encoder that has stats, actor before critic, and stops.
"""
from __future__ import annotations

from typing import Any, Dict, List

from ray.rllib.utils.annotations import override

from gym_continuousDoubleAuction.train.model.moe_learner import (
    CDAPPOTorchLearner,
    CDAPPOTorchRLModule,
)

#: `fwd_out` key holding the latent-prediction loss (plus its variance hinge).
JEPA_AUX_LOSS = "jepa_aux_loss"

#: `fwd_out` keys holding the collapse metrics.
JEPA_LATENT_STD = "jepa_latent_std"
JEPA_OFFDIAG_COV = "jepa_offdiag_cov"
JEPA_PREDICT_LOSS = "jepa_predict_loss"

#: Metric names, logged per module by the Learner.
JEPA_AUX_LOSS_KEY = "jepa_aux_loss"
JEPA_LATENT_STD_KEY = "jepa_latent_std"
JEPA_OFFDIAG_COV_KEY = "jepa_offdiag_cov"
JEPA_PREDICT_LOSS_KEY = "jepa_predict_loss"

#: Where a JEPA encoder may sit inside an `ActorCriticEncoder`, in the order
#: they are tried. `encoder` is the shared trunk under `vf_share_layers: true`;
#: otherwise the actor's is the one the policy acts through.
_SUB_ENCODERS = ("encoder", "actor_encoder", "critic_encoder")

#: Submodules of a JEPA encoder that exist only to train it.
_TRAINING_ONLY = ("target_trunk", "predictor")


def _jepa_sub_encoder(encoder):
    """The first sub-encoder carrying JEPA machinery, or None.

    First, not all of them: see the module docstring on double-counting.
    """
    for name in _SUB_ENCODERS:
        sub = getattr(encoder, name, None)
        if sub is not None and hasattr(sub, "take_jepa_stats"):
            return name, sub
    return None, None


class JEPARLModule(CDAPPOTorchRLModule):
    """The CDA PPO module, plus the JEPA loss forwarded to the Learner.

    Identical to its base for any encoder that produces no JEPA stats, so a
    checkpoint written by one and restored into the other differs only in the
    class name.
    """

    @override(CDAPPOTorchRLModule)
    def _forward_train(self, batch: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        out = super()._forward_train(batch, **kwargs)

        # Immediately after the encoder ran, so the stats are this batch's.
        _name, sub = _jepa_sub_encoder(self.encoder)
        stats = sub.take_jepa_stats() if sub is not None else None
        if stats:
            out[JEPA_AUX_LOSS] = stats["aux_loss"]
            out[JEPA_LATENT_STD] = stats["latent_std"]
            out[JEPA_OFFDIAG_COV] = stats["offdiag_cov"]
            out[JEPA_PREDICT_LOSS] = stats["predict_loss"]
        return out

    @override(CDAPPOTorchRLModule)
    def get_non_inference_attributes(self) -> List[str]:
        """The base list, plus the JEPA encoder's training-only submodules.

        The EMA target trunk and the predictor are needed only to compute the
        auxiliary loss. Left undeclared, every champion snapshot and every
        inference-only copy would carry a second full encoder it never runs.

        Built from what is actually present rather than from a fixed string, so
        this returns exactly the base list when the encoder is not a JEPA one -
        which is what keeps `test_non_inference_attributes_contract` true for
        every other architecture.
        """
        attributes = super().get_non_inference_attributes()

        name, sub = _jepa_sub_encoder(self.encoder)
        if sub is None:
            return attributes

        return attributes + [
            f"encoder.{name}.{part}"
            for part in _TRAINING_ONLY
            if hasattr(sub, part)
        ]


class CDAJEPALearner(CDAPPOTorchLearner):
    """PPO's loss, the MoE term it inherits, and the JEPA term."""

    @override(CDAPPOTorchLearner)
    def compute_loss_for_module(self, *, module_id, config, batch, fwd_out):
        total_loss = super().compute_loss_for_module(
            module_id=module_id, config=config, batch=batch, fwd_out=fwd_out
        )

        aux_loss = fwd_out.get(JEPA_AUX_LOSS)
        if aux_loss is None:
            return total_loss

        self.metrics.log_dict(
            {
                JEPA_AUX_LOSS_KEY: aux_loss,
                JEPA_PREDICT_LOSS_KEY: fwd_out[JEPA_PREDICT_LOSS],
                # The metric that matters. A collapsed JEPA drives its
                # prediction loss to ZERO, which reads as success - the loss
                # alone cannot tell a working encoder from a dead one. This
                # goes to 0 exactly when every observation maps to the same
                # latent, and should sit near 1.0, the scale LayerNormed
                # targets already have.
                JEPA_LATENT_STD_KEY: fwd_out[JEPA_LATENT_STD],
                # Dimensional collapse: variance held up while the dimensions
                # become redundant, which `latent_std` alone would miss.
                JEPA_OFFDIAG_COV_KEY: fwd_out[JEPA_OFFDIAG_COV],
            },
            key=module_id,
            window=1,
        )
        return total_loss + self._jepa_aux_loss_coeff(module_id) * aux_loss

    def _jepa_aux_loss_coeff(self, module_id) -> float:
        """The module's own `aux_loss_coeff`, read off its encoder config.

        Off the module rather than the algorithm config because it is an
        encoder-level knob, and because in a league different modules could in
        principle carry different encoders.
        """
        _name, sub = _jepa_sub_encoder(
            getattr(self.module[module_id], "encoder", None)
        )
        coeff = getattr(getattr(sub, "config", None), "aux_loss_coeff", None)
        if coeff is None:
            raise ValueError(
                f"Module {module_id!r} produced a JEPA auxiliary loss but no "
                "encoder config carrying `aux_loss_coeff`. The loss term would "
                "be silently unweighted."
            )
        return coeff
