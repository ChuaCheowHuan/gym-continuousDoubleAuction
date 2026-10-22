"""The papers' tuned Adam, as a Learner mixin independent of Continual Backprop.

Split out of `cbp_learner.py` so that it does not depend on Continual Backprop:
the two are separate interventions (see `TunedAdamMixin`), and tuned Adam stays
in this repository whatever happens to CBP. `cbp_learner` re-exports both names,
because checkpoints written before the split pickle their Learner class with a
reference to `cbp_learner.TunedAdamMixin` (test_learner_class_compat.py).
"""

from __future__ import annotations

from typing import Any, Dict

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
        settings = adam_settings(getattr(self.config, "learner_config_dict", None))
        if not settings:
            # Nothing configured - defer, so the optimiser is bit-for-bit the
            # one RLlib builds. This is the path every existing run takes.
            super().configure_optimizers_for_module(module_id, config=config)
            return

        params = self.get_parameters(self.module[module_id])
        optimizer = torch.optim.Adam(params, **settings)
        self.register_optimizer(
            module_id=module_id,
            optimizer=optimizer,
            params=params,
            lr_or_lr_schedule=config.lr,
        )


def adam_settings(learner_config_dict) -> Dict[str, Any]:
    """Adam keyword arguments from the `optimizer` group: only the ones it sets.

    A setting left unset (or at zero) is not passed, so the optimiser's own
    default applies and an empty dict means Adam exactly as RLlib builds it.
    The one reader of the group: `TunedAdamMixin` builds torch's Adam from it,
    and the cda-cbp extension builds the authors' `AdamGnT` from it.
    """
    values = (learner_config_dict or {}).get(OPTIMIZER_CONFIG_KEY) or {}
    settings: Dict[str, Any] = {}
    if values.get("adam_betas"):
        settings["betas"] = tuple(values["adam_betas"])
    if values.get("adam_weight_decay"):
        settings["weight_decay"] = float(values["adam_weight_decay"])
    return settings


def with_tuned_adam(base):
    """Compose only the optimiser mixin, for a run using it without CBP."""
    return type(f"TunedAdam{base.__name__}", (TunedAdamMixin, base), {})
