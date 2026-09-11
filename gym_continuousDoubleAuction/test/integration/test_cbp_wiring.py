"""Integration tests for the Continual Backprop wiring.

The claims that only hold once a real `Algorithm` exists:

  1. **Composition preserves the encoder's learner.** CBP is an update rule, not
     an architecture, so it is composed *over* whatever `learner_class_for`
     returned rather than competing for RLlib's single Learner slot. If that
     went wrong, selecting `jepa` with continual backprop on would silently drop
     the latent-prediction loss.
  2. **Off is off.** With both switches false the resolved learner class is the
     one a run would have had before any of this existed - not a subclass that
     happens to do nothing.
  3. **It runs inside a real PPO update**, replacing units and logging metrics,
     without breaking sampling, the league, or NAV conservation.
  4. **The state survives a checkpoint**, and a checkpoint written before CBP
     existed still restores.

`TestOtherEncodersAreUnaffectedByJEPA` in `test_encoder_wiring.py` is the model
for the isolation tests here.
"""
import shutil
import tempfile
from dataclasses import replace

import pytest
import ray
import torch

from gym_continuousDoubleAuction.train.model.cbp_learner import (
    CBP_STATE,
    CBPLearnerMixin,
    TunedAdamMixin,
    with_continual_backprop,
    with_tuned_adam,
)
from gym_continuousDoubleAuction.train.model.jepa_learner import CDAJEPALearner
from gym_continuousDoubleAuction.train.model.moe_learner import CDAPPOTorchLearner
from gym_continuousDoubleAuction.train.train import (
    TrainConfig,
    _learner_class,
    _learner_config_dict,
    build_config,
)

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

#: The shipped replacement rate fires roughly once per 39 optimiser steps over
#: 256 units, and a test-length run performs a handful - so at the real value
#: nothing would be replaced and every assertion below would pass vacuously.
#: Forced high here, which is exactly the manoeuvre doc/25's Finding 2 warns a
#: real run cannot make.
FIRING_CFG = dict(
    cbp_enabled=True,
    cbp_replacement_rate=0.05,
    cbp_maturity_threshold=1,
    cbp_metrics_every_n_updates=1,
)


class TestCompositionPreservesTheEncodersLearner:
    """CBP subclasses the encoder's Learner instead of replacing it."""

    def test_off_resolves_to_exactly_the_base_learner(self):
        """Not a subclass that does nothing - the same class object."""
        cfg = TrainConfig(**TEST_CFG)
        assert _learner_class(cfg) is CDAPPOTorchLearner

    def test_off_resolves_to_the_encoders_learner_for_jepa(self):
        cfg = TrainConfig(**TEST_CFG)
        cfg.encoder_type = "jepa"
        assert _learner_class(cfg) is CDAJEPALearner

    @pytest.mark.parametrize(
        "base", [CDAPPOTorchLearner, CDAJEPALearner], ids=["moe", "jepa"]
    )
    def test_the_loss_still_comes_from_the_base(self, base):
        """The MoE and JEPA terms must survive the composition.

        `compute_loss_for_module` is where both live; the mixin overrides the
        update path and the checkpoint, and must leave the loss alone.
        """
        composed = with_continual_backprop(base)
        assert composed.compute_loss_for_module is base.compute_loss_for_module
        assert CBPLearnerMixin in composed.__mro__
        assert composed.__mro__.index(CBPLearnerMixin) < composed.__mro__.index(base)

    def test_cbp_on_with_jepa_keeps_the_jepa_learner(self):
        cfg = TrainConfig(**TEST_CFG, **FIRING_CFG)
        cfg.encoder_type = "jepa"
        composed = _learner_class(cfg)
        assert CDAJEPALearner in composed.__mro__
        assert (composed.compute_loss_for_module
                is CDAJEPALearner.compute_loss_for_module)


class TestTunedAdamIsIndependentOfCBP:
    """The optimiser knobs must be usable without continual backprop.

    The papers treat them as separate interventions that happen to be used
    together. Composing the optimiser change only alongside CBP would make
    every CBP-vs-baseline comparison a comparison of both at once - the exact
    confound the two config groups exist to avoid.
    """

    def test_defaults_compose_nothing(self):
        assert _learner_class(TrainConfig(**TEST_CFG)) is CDAPPOTorchLearner

    def test_tuned_adam_alone_composes_only_the_optimiser_mixin(self):
        cfg = TrainConfig(**TEST_CFG, adam_betas=[0.99, 0.99],
                          adam_weight_decay=1e-4)
        composed = _learner_class(cfg)
        assert TunedAdamMixin in composed.__mro__
        assert CBPLearnerMixin not in composed.__mro__

    def test_both_compose_together(self):
        cfg = TrainConfig(**TEST_CFG, **FIRING_CFG,
                          adam_betas=[0.99, 0.99], adam_weight_decay=1e-4)
        composed = _learner_class(cfg)
        assert CBPLearnerMixin in composed.__mro__
        assert TunedAdamMixin in composed.__mro__

    def test_weight_decay_alone_is_enough_to_compose(self):
        """L2 is half the papers' RL recipe and must be reachable on its own."""
        cfg = TrainConfig(**TEST_CFG, adam_weight_decay=1e-4)
        assert TunedAdamMixin in _learner_class(cfg).__mro__

    def test_the_config_dict_carries_both_groups(self):
        values = _learner_config_dict(TrainConfig(**TEST_CFG))
        assert set(values) == {"optimizer", "continual_backprop"}
        assert values["optimizer"]["adam_betas"] == [0.9, 0.999]


class TestTunedAdamReachesTheOptimiser:
    """The betas and weight decay actually land on the built optimiser."""

    @classmethod
    def setup_class(cls):
        ray.init(ignore_reinit_error=True, include_dashboard=False,
                 log_to_driver=False, num_cpus=2)
        cfg = TrainConfig(**TEST_CFG, adam_betas=[0.99, 0.99],
                          adam_weight_decay=1e-4)
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


class TestCBPRunsInsideARealUpdate:
    """One real training iteration, with the mechanism firing."""

    @classmethod
    def setup_class(cls):
        ray.init(ignore_reinit_error=True, include_dashboard=False,
                 log_to_driver=False, num_cpus=2)
        cls.cfg = TrainConfig(**TEST_CFG, **FIRING_CFG)
        ppo_config, _cb = build_config(cls.cfg)
        cls.algo = ppo_config.build_algo()
        cls.result = cls.algo.train()
        cls.learner = cls.algo.learner_group._learner

    @classmethod
    def teardown_class(cls):
        cls.algo.stop()
        ray.shutdown()

    def test_the_learner_is_the_composed_class(self):
        assert isinstance(self.learner, CBPLearnerMixin)

    def test_every_trainable_module_got_four_layers(self):
        """Two hidden layers each for the policy and the value network.

        The frozen `RandomRLModule` baselines have no network and must not
        appear here at all.
        """
        assert set(self.learner._cbp_layers) == {"policy_0", "policy_1"}
        for layers in self.learner._cbp_layers.values():
            assert len(layers) == 4

    def test_only_trainable_modules_are_attached(self):
        """Nothing frozen may be attached, champions included.

        A champion is a snapshot kept fixed so the opponent it represents does
        not drift. It shares the `MultiRLModule` with the trainable policies, so
        it is reachable from `self.module` - and replacing a unit in one would
        silently mutate an opponent that is supposed to be constant, with no
        gradient to undo it. This surfaced on a real restore, where champions
        are present from `build()` rather than added mid-run.
        """
        for module_id in self.learner._cbp_layers:
            assert self.learner.should_module_be_updated(module_id)

    def test_units_were_actually_replaced(self):
        """The assertion the whole test would otherwise pass vacuously without."""
        total = sum(
            state.replacements
            for layers in self.learner._cbp_state.values()
            for state in layers.values()
        )
        assert total > 0

    def test_at_most_one_replacement_per_layer_per_step(self):
        """The `if c > 1` cap, observed through a real update.

        `_cbp_updates` counts optimiser steps; no layer may have replaced more
        units than there were steps.
        """
        steps = self.learner._cbp_updates
        assert steps > 0
        for layers in self.learner._cbp_state.values():
            for state in layers.values():
                assert state.replacements <= steps

    def test_the_metrics_are_logged_per_module(self):
        learners = self.result["learners"]
        for module_id in ("policy_0", "policy_1"):
            metrics = {
                key: value for key, value in learners[module_id].items()
                if key.startswith("cbp_")
            }
            assert {
                "cbp_dead_unit_frac",
                "cbp_saturated_unit_frac",
                "cbp_mean_weight_magnitude",
                "cbp_effective_rank",
                "cbp_mature_unit_frac",
                "cbp_replacements",
            } <= set(metrics)
            assert metrics["cbp_effective_rank"] > 0

    def test_training_still_produced_a_result(self):
        """Replacement must not break sampling, the league, or the update."""
        assert self.result["learners"]["policy_0"]
        assert not torch.isnan(
            torch.tensor(float(self.result["learners"]["policy_0"]["total_loss"]))
        )

    def test_no_activation_is_retained_between_forwards(self):
        """The hook must not pin the autograd graph until the next forward."""
        for stats in self.learner._cbp_stats.values():
            assert not any(value.requires_grad for value in stats.values())


class TestMetricsOnlyChangesNothing:
    """doc/25 Proposal A: measure without touching the trajectory."""

    @classmethod
    def setup_class(cls):
        ray.init(ignore_reinit_error=True, include_dashboard=False,
                 log_to_driver=False, num_cpus=2)
        cfg = TrainConfig(
            **TEST_CFG, cbp_enabled=True, cbp_metrics_only=True,
            cbp_replacement_rate=0.5, cbp_maturity_threshold=0,
            cbp_metrics_every_n_updates=1,
        )
        ppo_config, _cb = build_config(cfg)
        cls.algo = ppo_config.build_algo()
        cls.result = cls.algo.train()
        cls.learner = cls.algo.learner_group._learner

    @classmethod
    def teardown_class(cls):
        cls.algo.stop()
        ray.shutdown()

    def test_nothing_was_replaced_despite_an_absurd_rate(self):
        total = sum(
            state.replacements
            for layers in self.learner._cbp_state.values()
            for state in layers.values()
        )
        assert total == 0

    def test_the_correlates_are_still_logged(self):
        metrics = self.result["learners"]["policy_0"]
        assert "cbp_effective_rank" in metrics
        assert "cbp_dead_unit_frac" in metrics

    def test_the_utility_is_still_accumulated(self):
        """Most of the mechanism runs; only the replacement is withheld."""
        for layers in self.learner._cbp_state.values():
            for state in layers.values():
                assert torch.any(state.age > 0)


class TestCBPStateSurvivesACheckpoint:
    """Utility and ages are learned quantities and must be restored.

    A resume that dropped them would put every unit back at age 0, so the
    maturity threshold would protect all of them and the first sweep afterwards
    would rank by an estimate built from almost no data - silent, and on a
    project whose `chkpt_freq` is 2, frequent.
    """

    @classmethod
    def setup_class(cls):
        ray.init(ignore_reinit_error=True, include_dashboard=False,
                 log_to_driver=False, num_cpus=2)
        cls.tmp = tempfile.mkdtemp()
        cfg = TrainConfig(**TEST_CFG, **FIRING_CFG)
        ppo_config, _cb = build_config(cfg)
        cls.algo = ppo_config.build_algo()
        cls.algo.train()
        cls.learner = cls.algo.learner_group._learner

    @classmethod
    def teardown_class(cls):
        cls.algo.stop()
        ray.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_get_state_carries_the_cbp_block(self):
        state = self.learner.get_state()
        assert CBP_STATE in state
        assert set(state[CBP_STATE]) == {"policy_0", "policy_1"}

    def test_state_round_trips_through_set_state(self):
        state = self.learner.get_state()
        saved = {
            module_id: {
                name: (layer.utility.clone(), layer.age.clone(),
                       layer.accumulator, layer.replacements)
                for name, layer in layers.items()
            }
            for module_id, layers in self.learner._cbp_state.items()
        }

        # Clobber the live state, then restore it.
        for layers in self.learner._cbp_state.values():
            for layer in layers.values():
                layer.utility.fill_(0.0)
                layer.age.fill_(0)
                layer.accumulator = 0.0
                layer.replacements = 0

        self.learner.set_state(state)

        for module_id, layers in self.learner._cbp_state.items():
            for name, layer in layers.items():
                utility, age, accumulator, replacements = saved[module_id][name]
                torch.testing.assert_close(layer.utility, utility)
                torch.testing.assert_close(layer.age, age)
                assert layer.accumulator == pytest.approx(accumulator)
                assert layer.replacements == replacements

    def test_a_checkpoint_without_cbp_state_still_restores(self):
        """Every checkpoint this project has already written lacks the key."""
        state = self.learner.get_state()
        state.pop(CBP_STATE)
        self.learner.set_state(state)  # must not raise

    def test_a_state_missing_one_layer_leaves_that_layer_alone(self):
        """A newly enabled CBP, or a layer added by an encoder change."""
        state = self.learner.get_state()
        module_id = "policy_0"
        dropped = sorted(state[CBP_STATE][module_id])[0]
        del state[CBP_STATE][module_id][dropped]
        self.learner.set_state(state)
        assert dropped in self.learner._cbp_state[module_id]


class TestCBPSurvivesARealSaveAndRestore:
    """A real `save_to_path` and `build_algo(is_restore=True)`.

    `get_state` / `set_state` never leave the process, so they cannot show that
    the state actually serialises - RLlib writes the learner's state through its
    own `Checkpointable` machinery, and a tensor that round-trips in memory can
    still fail to survive that. This is the same gap
    `integration/test_checkpoint_roundtrip.py` exists to close for weights.
    """

    @classmethod
    def setup_class(cls):
        import dataclasses

        from gym_continuousDoubleAuction.train.train import build_algo, save_checkpoint

        ray.init(ignore_reinit_error=True, include_dashboard=False,
                 log_to_driver=False, num_cpus=2)
        cls.tmpdir = tempfile.mkdtemp(prefix="cda_cbp_ckpt_")
        cls.cfg = TrainConfig(
            log_base_dir=cls.tmpdir, chkpt_keep=0, **TEST_CFG, **FIRING_CFG
        )

        ppo_config, _cb = build_config(cls.cfg)
        original = ppo_config.build_algo()
        original.train()

        learner = original.learner_group._learner
        cls.saved = {
            module_id: {
                name: (state.utility.clone(), state.age.clone(),
                       state.replacements)
                for name, state in layers.items()
            }
            for module_id, layers in learner._cbp_state.items()
        }
        save_checkpoint(original, cls.cfg, int(original.iteration))
        original.stop()

        cls.restored, _cb2 = build_algo(
            dataclasses.replace(cls.cfg, is_restore=True)
        )

    @classmethod
    def teardown_class(cls):
        cls.restored.stop()
        ray.shutdown()
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_the_restored_learner_still_has_cbp(self):
        assert isinstance(self.restored.learner_group._learner, CBPLearnerMixin)

    def test_champions_in_the_restored_league_are_not_attached(self):
        """The restore is where this bites: champions exist from `build()`.

        On a fresh run the league is empty when the learner is built, so only
        the trainable policies are attached. On a restore the champions come
        back with the checkpoint and are present immediately - which is how an
        attached, and therefore replaceable, frozen champion first appeared.
        """
        learner = self.restored.learner_group._learner
        assert any(m.startswith("champion") for m in learner.module.keys()), (
            "the restored league should carry a champion, or this proves nothing"
        )
        assert not any(
            module_id.startswith("champion") for module_id in learner._cbp_layers
        )

    def test_utility_and_ages_come_back(self):
        """Without this, every unit restarts at age 0 and utility 0.

        The maturity threshold would then protect all of them, and the first
        sweep afterwards would rank by an estimate built from almost no data -
        silent, and on a project whose `chkpt_freq` is 2, frequent.
        """
        live = self.restored.learner_group._learner._cbp_state
        assert set(live) == set(self.saved)
        for module_id, layers in self.saved.items():
            for name, (utility, age, replacements) in layers.items():
                torch.testing.assert_close(live[module_id][name].utility, utility)
                torch.testing.assert_close(live[module_id][name].age, age)
                assert live[module_id][name].replacements == replacements

    def test_something_was_actually_carried(self):
        """Guards against the assertion above passing on two zeroed states."""
        assert any(
            int(age.max()) > 0
            for layers in self.saved.values()
            for _utility, age, _r in layers.values()
        )
