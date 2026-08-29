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

#: `fwd_out` key holding the action-conditioned world-model loss, present only
#: when that is enabled AND the batch carried `Columns.NEXT_OBS`.
JEPA_WORLD_LOSS = "jepa_world_loss"

#: `fwd_out` keys holding the collapse metrics.
JEPA_LATENT_STD = "jepa_latent_std"
JEPA_OFFDIAG_COV = "jepa_offdiag_cov"
JEPA_PREDICT_LOSS = "jepa_predict_loss"

#: Metric names, logged per module by the Learner.
JEPA_AUX_LOSS_KEY = "jepa_aux_loss"
JEPA_LATENT_STD_KEY = "jepa_latent_std"
JEPA_OFFDIAG_COV_KEY = "jepa_offdiag_cov"
JEPA_PREDICT_LOSS_KEY = "jepa_predict_loss"
JEPA_WORLD_LOSS_KEY = "jepa_world_loss"

#: Where a JEPA encoder may sit inside an `ActorCriticEncoder`, in the order
#: they are tried. `encoder` is the shared trunk under `vf_share_layers: true`;
#: otherwise the actor's is the one the policy acts through.
_SUB_ENCODERS = ("encoder", "actor_encoder", "critic_encoder")

#: Submodules of a JEPA encoder that exist only to train it. `world_model` is
#: here for the same reason as the other two: it computes an auxiliary loss and
#: is never read on the inference path, so an inference-only copy or a champion
#: snapshot carrying it is carrying dead weight.
_TRAINING_ONLY = ("target_trunk", "predictor", "world_model")


def _jepa_sub_encoder(encoder):
    """The first sub-encoder carrying JEPA machinery, or None.

    First, not all of them: see the module docstring on double-counting.

    Accepts None, because callers may run before `setup()` has built the
    encoder - `get_non_inference_attributes` does.
    """
    if encoder is None:
        return None, None
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
            # Absent unless the world model is on and the batch carried
            # NEXT_OBS, which only the learner connector supplies.
            if "world_loss" in stats:
                out[JEPA_WORLD_LOSS] = stats["world_loss"]
        return out

    @override(CDAPPOTorchRLModule)
    def setup(self):
        """Build the module, then drop the training-only parts if inference-only.

        Dropping them *here* rather than leaving it to RLlib is not a
        preference. `TorchRLModule.__init__` deletes the names
        `get_non_inference_attributes` returns, but for a dotted path it
        traverses to the leaf and then calls `delattr(self, leaf_name)` - on the
        *module*, not on the leaf's parent - so a nested attribute that actually
        exists raises `AttributeError` instead of being removed. PPO's own
        `encoder.critic_encoder` escapes that only because inference-only setup
        never creates it, so the loop's "absent, skip" branch runs first.

        So this makes ours absent by the same route. Once these are gone the
        loop skips them exactly as it skips the critic encoder, and the dotted
        paths stay in `get_non_inference_attributes` where they are still needed
        - `get_state` filters the state dict by those prefixes, and that part
        handles dots correctly.

        Without this, building an inference-only `jepa` module raises, and
        champions are inference-only copies: a `jepa` league failed on its first
        champion snapshot.
        """
        super().setup()

        # Only the first JEPA sub-encoder's stats are ever collected, so any
        # other copy would compute the whole objective - mask pass, target
        # pass, predictor, world model - and have it discarded, keeping the
        # autograd graph alive in `_jepa_stats` until the next forward. With
        # `vf_share_layers` false, which is the shipped default, that is the
        # critic's copy on every single training forward.
        collected, _sub = _jepa_sub_encoder(getattr(self, "encoder", None))
        for name in _SUB_ENCODERS:
            other = getattr(getattr(self, "encoder", None), name, None)
            if (name != collected and other is not None
                    and hasattr(other, "objective_enabled")):
                other.objective_enabled = False

        if not self.inference_only:
            return

        for name in _SUB_ENCODERS:
            sub = getattr(getattr(self, "encoder", None), name, None)
            if sub is None or not hasattr(sub, "take_jepa_stats"):
                continue
            for part in _TRAINING_ONLY:
                if getattr(sub, part, None) is not None:
                    delattr(sub, part)

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

        # `getattr`, not `self.encoder`: RLlib calls this from `TorchRLModule
        # .__init__`, which runs BEFORE `setup()` has created the encoder. An
        # unguarded read raises AttributeError there, and `RLModuleSpec.build`
        # catches AttributeError to fall back to a deprecated constructor - so
        # the real error is swallowed and resurfaces as a confusing complaint
        # about `RLModuleConfig`. Champions are inference-only copies, so this
        # made a `jepa` league fail on its first snapshot.
        name, sub = _jepa_sub_encoder(getattr(self, "encoder", None))
        if sub is None:
            return attributes

        # `getattr(...) is not None`, matching `setup`'s deletion condition:
        # `world_model` is an attribute set to None when it is off, so `hasattr`
        # alone would declare a submodule that does not exist.
        return attributes + [
            f"encoder.{name}.{part}"
            for part in _TRAINING_ONLY
            if getattr(sub, part, None) is not None
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
        total_loss = total_loss + self._jepa_aux_loss_coeff(module_id) * aux_loss

        world_loss = fwd_out.get(JEPA_WORLD_LOSS)
        if world_loss is not None:
            self.metrics.log_dict(
                {JEPA_WORLD_LOSS_KEY: world_loss}, key=module_id, window=1
            )
            total_loss = total_loss + (
                self._encoder_setting(module_id, "world_model_coeff")
                * world_loss
            )
        return total_loss

    def _jepa_aux_loss_coeff(self, module_id) -> float:
        return self._encoder_setting(module_id, "aux_loss_coeff")

    def _encoder_setting(self, module_id, name: str) -> float:
        """One coefficient, read off the module's own encoder config.

        Off the module rather than the algorithm config because these are
        encoder-level knobs, and because in a league different modules could in
        principle carry different encoders.

        Raises rather than defaulting: a term that reached the loss but found no
        coefficient would be added unweighted, which is a silent change to what
        is being optimised.
        """
        _name, sub = _jepa_sub_encoder(
            getattr(self.module[module_id], "encoder", None)
        )
        value = getattr(getattr(sub, "config", None), name, None)
        if value is None:
            raise ValueError(
                f"Module {module_id!r} produced a JEPA loss term but its "
                f"encoder config carries no `{name}`. The term would be "
                "silently unweighted."
            )
        return value
