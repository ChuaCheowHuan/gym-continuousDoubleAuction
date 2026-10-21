"""The papers' tuned Adam, as a Learner mixin independent of Continual Backprop.

Split out of `cbp_learner.py` so that it does not depend on Continual Backprop:
the two are separate interventions (see `TunedAdamMixin`), and tuned Adam stays
in this repository whatever happens to CBP. `cbp_learner` re-exports both names,
because checkpoints written before the split pickle their Learner class with a
reference to `cbp_learner.TunedAdamMixin` (test_learner_class_compat.py).
"""

from __future__ import annotations

import torch

#: Key under which the optimiser group rides on `learner_config_dict`.
OPTIMIZER_CONFIG_KEY = "optimizer"


class TunedAdamMixin:
    """Adam's betas and weight decay, from config instead of torch's defaults.

    A mixin of its own rather than part of `CBPLearnerMixin`, because the two
    interventions are independent and the papers treat them that way. Both
    papers run every algorithm *except* the standard-PPO baseline with
    `beta_1 = beta_2 = 0.99`, on the grounds that the usual (0.9, 0.999)
    mismatch is itself a cause of plasticity loss: the squared-gradient
    estimate in the denominator updates far more slowly than the gradient
    estimate in the numerator, so one large gradient produces one very large,
    destabilising update. The Nature paper separately applies continual
    backprop together with L2 in every reinforcement-learning experiment, and
    reports that the pair is insensitive to the replacement rate where CBP
    alone is not.

    Keeping them separable is the point: composing this only when CBP is on
    would make every CBP-vs-baseline comparison a comparison of CBP *and* a
    retuned optimiser, which is exactly the confound to avoid.
    """

    def configure_optimizers_for_module(self, module_id, config=None) -> None:
        values = (getattr(self.config, "learner_config_dict", None) or {}).get(
            OPTIMIZER_CONFIG_KEY
        ) or {}
        betas = values.get("adam_betas")
        weight_decay = values.get("adam_weight_decay")
        if not betas and not weight_decay:
            # Nothing configured - defer, so the optimiser is bit-for-bit the
            # one RLlib builds. This is the path every existing run takes.
            super().configure_optimizers_for_module(module_id, config=config)
            return

        params = self.get_parameters(self.module[module_id])
        optimizer = torch.optim.Adam(
            params,
            betas=tuple(betas) if betas else (0.9, 0.999),
            weight_decay=float(weight_decay or 0.0),
        )
        self.register_optimizer(
            module_id=module_id,
            optimizer=optimizer,
            params=params,
            lr_or_lr_schedule=config.lr,
        )


def with_tuned_adam(base):
    """Compose only the optimiser mixin, for a run using it without CBP."""
    return type(f"TunedAdam{base.__name__}", (TunedAdamMixin, base), {})
