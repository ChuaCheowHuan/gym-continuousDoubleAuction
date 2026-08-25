"""Carrying the MoE load-balancing loss from the encoder to the optimiser.

Two pieces, because nothing between them can see both ends:

  CDAPPOTorchRLModule - takes the stats the MoE encoder left behind and puts
                        them in `fwd_out`, which is the only channel from a
                        module's forward pass to the Learner's loss.
  CDAPPOTorchLearner  - adds `aux_loss_coeff * aux` to PPO's total loss, and
                        logs the per-expert routing fractions.

Why the module has to be involved at all: `ActorCriticEncoder._forward` returns
only `{ENCODER_OUT: {ACTOR, CRITIC}}` and discards every other key its inner
encoders produced, so an auxiliary term cannot simply be returned from the
encoder. See `TorchTransformerEncoder.take_moe_stats`.

Both are inert for every non-MoE encoder: `take_moe_stats` returns `None`, no
key is written, and the Learner adds nothing. So they can be wired
unconditionally rather than only for `moe_transformer`, which keeps one code
path instead of two.
"""
from __future__ import annotations

from typing import Any, Dict

import torch
from ray.rllib.algorithms.ppo.torch.ppo_torch_learner import PPOTorchLearner
from ray.rllib.algorithms.ppo.torch.default_ppo_torch_rl_module import (
    DefaultPPOTorchRLModule,
)
from ray.rllib.utils.annotations import override

#: `fwd_out` key holding the summed load-balancing loss.
MOE_AUX_LOSS = "moe_aux_loss"

#: `fwd_out` key holding per-expert routing fractions, averaged over blocks.
MOE_EXPERT_FRACTIONS = "moe_expert_fractions"

#: Metric names, logged per module by the Learner.
MOE_AUX_LOSS_KEY = "moe_aux_loss"
MOE_MAX_EXPERT_SHARE_KEY = "moe_max_expert_share"
MOE_MIN_EXPERT_SHARE_KEY = "moe_min_expert_share"


def _collect(encoder) -> Dict[str, Any]:
    """Take the MoE stats from whichever sub-encoders have any.

    The actor and critic are separate encoder instances unless
    `vf_share_layers`, and both route independently, so both contribute.
    """
    candidates = [
        getattr(encoder, name, None)
        for name in ("encoder", "actor_encoder", "critic_encoder")
    ]

    aux_terms = []
    fraction_terms = []
    for sub in candidates:
        take = getattr(sub, "take_moe_stats", None)
        if take is None:
            continue
        for block_stats in take() or []:
            aux_terms.append(block_stats["aux_loss"])
            fraction_terms.append(block_stats["expert_fractions"])

    if not aux_terms:
        return {}
    return {
        MOE_AUX_LOSS: torch.stack(aux_terms).sum(),
        MOE_EXPERT_FRACTIONS: torch.stack(fraction_terms).mean(dim=0),
    }


class CDAPPOTorchRLModule(DefaultPPOTorchRLModule):
    """The stock PPO module, plus MoE stats forwarded to the Learner.

    Identical to its base for every encoder that produces no stats, which is all
    of them except `moe_transformer`.
    """

    @override(DefaultPPOTorchRLModule)
    def _forward_train(self, batch: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        out = super()._forward_train(batch, **kwargs)
        # Immediately after the encoder ran, so the stats are this batch's.
        out.update(_collect(self.encoder))
        return out


class CDAPPOTorchLearner(PPOTorchLearner):
    """PPO's loss plus the MoE load-balancing term."""

    @override(PPOTorchLearner)
    def compute_loss_for_module(self, *, module_id, config, batch, fwd_out):
        total_loss = super().compute_loss_for_module(
            module_id=module_id, config=config, batch=batch, fwd_out=fwd_out
        )

        aux_loss = fwd_out.get(MOE_AUX_LOSS)
        if aux_loss is None:
            return total_loss

        coeff = self._aux_loss_coeff(module_id)
        fractions = fwd_out[MOE_EXPERT_FRACTIONS]
        self.metrics.log_dict(
            {
                MOE_AUX_LOSS_KEY: aux_loss,
                # A healthy mixture keeps these near 1/num_experts. Max drifting
                # towards 1 and min towards 0 is expert collapse, which is
                # otherwise invisible: a collapsed MoE and a working one have
                # identical losses and identical throughput.
                MOE_MAX_EXPERT_SHARE_KEY: fractions.max(),
                MOE_MIN_EXPERT_SHARE_KEY: fractions.min(),
            },
            key=module_id,
            window=1,
        )
        return total_loss + coeff * aux_loss

    def _aux_loss_coeff(self, module_id) -> float:
        """The module's own `aux_loss_coeff`, read from its encoder config.

        Off the module rather than the algorithm config because it is an
        encoder-level knob, and because in a league different modules could in
        principle carry different encoders.
        """
        encoder = getattr(self.module[module_id], "encoder", None)
        for name in ("encoder", "actor_encoder", "critic_encoder"):
            sub = getattr(encoder, name, None)
            coeff = getattr(getattr(sub, "config", None), "aux_loss_coeff", None)
            if coeff is not None:
                return coeff
        raise ValueError(
            f"Module {module_id!r} produced an MoE auxiliary loss but no "
            "encoder config carrying `aux_loss_coeff`. The loss term would be "
            "silently unweighted."
        )
