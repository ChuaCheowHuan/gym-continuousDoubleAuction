"""The seam between PPO's own loss and the auxiliary terms (docs/30 section 4).

`CDAPPOTorchLearner.compute_loss_for_module` used to compute PPO's loss and add
the MoE load-balancing term in one method. An extension that replaces PPO's
loss (an update rule rather than an extra term) had to override that whole
method, and so dropped the MoE term and, through `CDAJEPALearner`'s `super()`
call, the JEPA one. `_policy_value_loss` is the part such an extension
overrides; the auxiliary terms are added around it whatever it returns.

No Algorithm is built here: the learner is constructed without `__init__` and
PPO's own loss is stubbed, because what is pinned is which method calls which,
not the value of PPO's loss.
"""

import pytest
import torch
from ray.rllib.algorithms.ppo.torch.ppo_torch_learner import PPOTorchLearner

from gym_continuousDoubleAuction.train.model.jepa_learner import CDAJEPALearner
from gym_continuousDoubleAuction.train.model.moe_learner import (
    MOE_AUX_LOSS,
    MOE_EXPERT_FRACTIONS,
    CDAPPOTorchLearner,
)


class _Metrics:
    def log_dict(self, *args, **kwargs):
        pass


PPO_LOSS = torch.tensor(1.5)
MOE_TERM = torch.tensor(0.25)
COEFF = 0.1


@pytest.fixture
def stub_ppo_loss(monkeypatch):
    """PPO's own loss returns a fixed tensor; anything else is the seam's doing."""
    monkeypatch.setattr(
        PPOTorchLearner,
        "compute_loss_for_module",
        lambda self, *, module_id, config, batch, fwd_out: PPO_LOSS.clone(),
    )


def _learner(cls):
    learner = cls.__new__(cls)
    learner.metrics = _Metrics()
    learner._aux_loss_coeff = lambda module_id: COEFF
    return learner


def _loss(learner, fwd_out):
    return learner.compute_loss_for_module(module_id="p", config=None, batch={}, fwd_out=fwd_out)


def _moe_out():
    return {MOE_AUX_LOSS: MOE_TERM, MOE_EXPERT_FRACTIONS: torch.tensor([0.5, 0.5])}


class _ReplacesPPO(CDAPPOTorchLearner):
    """What a loss-replacing extension looks like: it overrides the seam only."""

    def _policy_value_loss(self, *, module_id, config, batch, fwd_out):
        return torch.tensor(10.0)


@pytest.mark.usefixtures("stub_ppo_loss")
class TestPolicyValueLossSeam:
    def test_without_an_aux_term_the_loss_is_ppos_own(self):
        assert torch.equal(_loss(_learner(CDAPPOTorchLearner), {}), PPO_LOSS)

    def test_the_moe_term_is_added_to_ppos_loss(self):
        assert torch.equal(
            _loss(_learner(CDAPPOTorchLearner), _moe_out()), PPO_LOSS + COEFF * MOE_TERM
        )

    def test_the_seam_returns_ppos_loss(self):
        learner = _learner(CDAPPOTorchLearner)
        out = learner._policy_value_loss(module_id="p", config=None, batch={}, fwd_out={})
        assert torch.equal(out, PPO_LOSS)

    def test_replacing_the_seam_keeps_the_moe_term(self):
        """The reason the seam exists: the replacement does not drop MoE."""
        out = _loss(_learner(_ReplacesPPO), _moe_out())
        assert torch.equal(out, torch.tensor(10.0) + COEFF * MOE_TERM)

    def test_jepa_learner_reaches_the_seam_through_super(self):
        """`CDAJEPALearner` overrides the outer method and calls `super()`, so a
        replacement composed beneath it is still used."""
        replaced_jepa = type(
            "ReplacedJEPA",
            (CDAJEPALearner,),
            {"_policy_value_loss": _ReplacesPPO._policy_value_loss},
        )
        assert torch.equal(_loss(_learner(replaced_jepa), {}), torch.tensor(10.0))
