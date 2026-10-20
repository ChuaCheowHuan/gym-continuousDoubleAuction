"""Integration tests for the papers' tuned Adam (`optim_learner.TunedAdamMixin`).

Tuned Adam is independent of Continual Backprop: the papers treat them as
separate interventions that happen to be used together, and composing the
optimiser change only alongside CBP would make every CBP-vs-baseline comparison
a comparison of both at once. These tests use no CBP setting, so they hold
whether or not CBP is part of this repository.
"""

import pytest
import ray

from gym_continuousDoubleAuction.train.model.moe_learner import CDAPPOTorchLearner
from gym_continuousDoubleAuction.train.model.optim_learner import TunedAdamMixin
from gym_continuousDoubleAuction.train.train import TrainConfig, _learner_class, build_config

TEST_CFG = dict(
    num_agents=4,
    num_trained_agents=2,
    max_step=64,
    num_episodes_per_iter=2,
    num_epochs=1,
    minibatch_size=64,
    num_env_runners=0,
    num_learners=0,
    num_gpus_per_learner=0,
    episode_data_dir=None,
    log_level="ERROR",
    seed=7,
)


class TestTunedAdamComposesOnItsOwn:
    def test_defaults_compose_nothing(self):
        assert _learner_class(TrainConfig(**TEST_CFG)) is CDAPPOTorchLearner

    def test_tuned_adam_alone_composes_only_the_optimiser_mixin(self):
        cfg = TrainConfig(**TEST_CFG, adam_betas=[0.99, 0.99], adam_weight_decay=1e-4)
        composed = _learner_class(cfg)
        assert composed.__mro__[1:3] == (TunedAdamMixin, CDAPPOTorchLearner)

    def test_weight_decay_alone_is_enough_to_compose(self):
        """L2 is half the papers' RL recipe and must be reachable on its own."""
        cfg = TrainConfig(**TEST_CFG, adam_weight_decay=1e-4)
        assert TunedAdamMixin in _learner_class(cfg).__mro__


class TestTunedAdamReachesTheOptimiser:
    """The betas and weight decay actually land on the built optimiser."""

    @classmethod
    def setup_class(cls):
        ray.init(ignore_reinit_error=True, include_dashboard=False, log_to_driver=False, num_cpus=2)
        cfg = TrainConfig(**TEST_CFG, adam_betas=[0.99, 0.99], adam_weight_decay=1e-4)
        ppo_config, _cb = build_config(cfg)
        cls.algo = ppo_config.build_algo()

    @classmethod
    def teardown_class(cls):
        cls.algo.stop()
        ray.shutdown()

    def test_the_optimiser_carries_the_configured_values(self):
        learner = self.algo.learner_group._learner
        optimizer = learner.get_optimizer(module_id="policy_0")
        group = optimizer.param_groups[0]
        assert tuple(group["betas"]) == (0.99, 0.99)
        assert group["weight_decay"] == pytest.approx(1e-4)
