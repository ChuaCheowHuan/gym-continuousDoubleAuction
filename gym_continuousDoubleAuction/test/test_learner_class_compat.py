"""Learner classes pickled into existing checkpoints must keep loading.

`Algorithm.from_checkpoint` rebuilds from the config stored in the checkpoint,
and that config holds the composed Learner class. The class itself is made with
`type()` and pickled by value, but its mixins are pickled *by module path*: a
checkpoint that ran tuned Adam or Continual Backprop names
`gym_continuousDoubleAuction.train.model.cbp_learner.TunedAdamMixin` or
`...CBPLearnerMixin`. Moving either class without leaving that name behind makes
every such checkpoint fail to unpickle.

`fixtures/learner_classes_f7c1353.pkl` holds `_learner_class(...)` cloudpickled
on master at f7c1353, before any of the code moved, for five configs.
"""

import os
import pickle

import pytest

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "learner_classes_f7c1353.pkl")


def _classes():
    with open(FIXTURE, "rb") as fh:
        return pickle.load(fh)["classes"]


def _load(name):
    return pickle.loads(_classes()[name])


class TestOldPickledLearnerClassesLoad:
    def test_the_fixture_covers_every_composition(self):
        assert set(_classes()) == {
            "default",
            "tuned_adam",
            "cbp",
            "cbp_tuned_adam",
            "cbp_metrics_only",
        }

    def test_the_default_learner_is_the_plain_ppo_learner(self):
        from gym_continuousDoubleAuction.train.model.moe_learner import CDAPPOTorchLearner

        assert _load("default") is CDAPPOTorchLearner

    def test_a_tuned_adam_learner_loads_with_the_current_mixin(self):
        from gym_continuousDoubleAuction.train.model.optim_learner import TunedAdamMixin

        cls = _load("tuned_adam")
        assert cls.__mro__[1] is TunedAdamMixin
        assert cls.configure_optimizers_for_module is TunedAdamMixin.configure_optimizers_for_module

    @pytest.mark.parametrize("name", ["cbp", "cbp_tuned_adam", "cbp_metrics_only"])
    def test_a_continual_backprop_learner_loads(self, name):
        from gym_continuousDoubleAuction.train.model.cbp_learner import CBPLearnerMixin

        assert CBPLearnerMixin in _load(name).__mro__

    def test_tuned_adam_rides_along_with_continual_backprop(self):
        from gym_continuousDoubleAuction.train.model.optim_learner import TunedAdamMixin

        assert TunedAdamMixin in _load("cbp_tuned_adam").__mro__
