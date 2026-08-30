"""Integration tests for the selectable-encoder wiring.

Two claims that only hold once a real `Algorithm` exists, and that the unit
tests in `test_encoder_registry.py` cannot make:

  1. **Champions inherit the encoder.** `SelfPlayCallback` snapshots a champion
     with `RLModuleSpec.from_module(...)`, which is supposed to clone the source
     module's class, catalog and model config. If it did not, a league running a
     custom encoder would quietly fill up with stock-MLP champions, and the
     trainable modules would be playing a different architecture than the one
     under test.

  2. **A restore cannot change the encoder.** `encoder_type` and `encoder_spec`
     are `STRUCTURAL_CONFIG_KEYS`, so editing them in the same pass as
     `is_restore` must be a hard error rather than a silent no-op. This is the
     same failure `n_hist` is already guarded against.

`_passthrough` is the registered test fixture; it is not selectable from a
config file, which is why these build a `TrainConfig` and then override the
field directly.
"""
import shutil
import tempfile

import pytest
import ray
import torch
from ray.rllib.algorithms.algorithm import Algorithm
from ray.rllib.core import COMPONENT_LEARNER, COMPONENT_RL_MODULE
from ray.rllib.core.rl_module.rl_module import RLModuleSpec

from gym_continuousDoubleAuction.train.model.encoders import MLP_ENCODER_TYPE
from gym_continuousDoubleAuction.train.model.encoders.passthrough import (
    TorchPassthroughEncoder,
)
from gym_continuousDoubleAuction.train.model.encoders.transformer import (
    TorchTransformerEncoder,
)
from gym_continuousDoubleAuction.train.model.model_handler import CDACatalog
from gym_continuousDoubleAuction.train.model.encoders import (
    ENCODER_LEARNER_CLASSES,
    ENCODER_MODULE_CLASSES,
    learner_class_for,
    module_class_for,
    needs_next_obs,
)
from gym_continuousDoubleAuction.train.model.jepa_learner import (
    CDAJEPALearner,
    JEPARLModule,
    JEPA_AUX_LOSS_KEY,
    JEPA_LATENT_STD_KEY,
    JEPA_OFFDIAG_COV_KEY,
    JEPA_PREDICT_LOSS_KEY,
    JEPA_WORLD_LOSS_KEY,
)
from gym_continuousDoubleAuction.train.model.moe_learner import (
    CDAPPOTorchRLModule,
    MOE_AUX_LOSS_KEY,
    MOE_MAX_EXPERT_SHARE_KEY,
    MOE_MIN_EXPERT_SHARE_KEY,
    CDAPPOTorchLearner,
)
from gym_continuousDoubleAuction.train.policy.policy_handler import (
    trainable_policy_ids,
)
from gym_continuousDoubleAuction.train.train import (
    TrainConfig,
    _check_restored_config,
    _encoder_fingerprint,
    _model_config_get,
    build_config,
)

FIXTURE = "_passthrough"


def _learner_module_state(algo, module_id):
    """Full module state from the LearnerGroup, local or remote.

    Deliberately not `learner_group._learner.module[...]`: that private
    attribute is None whenever num_learners > 0.
    """
    return algo.learner_group.get_state(
        components=f"{COMPONENT_LEARNER}/{COMPONENT_RL_MODULE}/{module_id}",
    )[COMPONENT_LEARNER][COMPONENT_RL_MODULE][module_id]

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
)


def config_with_encoder(encoder_type, encoder_specs=None, **overrides):
    """A TrainConfig for `encoder_type`, fixture names included.

    `TrainConfig.__post_init__` runs `validate_encoder_type`, which refuses a
    fixture - that is the point of the strict check, and `dataclasses.replace`
    re-runs it. Assigning after construction is how a test opts past a guard
    aimed at config files.
    """
    cfg = TrainConfig(**{**TEST_CFG, **overrides})
    cfg.encoder_type = encoder_type
    if encoder_specs is not None:
        cfg.encoder_specs = encoder_specs
    return cfg


class TestChampionsInheritTheEncoder:
    """A champion snapshot must be the same architecture as its source."""

    @classmethod
    def setup_class(cls):
        ray.init(
            ignore_reinit_error=True,
            include_dashboard=False,
            log_to_driver=False,
            num_cpus=2,
        )
        cls.cfg = config_with_encoder(FIXTURE)
        ppo_config, cls.callback = build_config(cls.cfg)
        cls.algo = ppo_config.build_algo()
        cls.source_pid = trainable_policy_ids(cls.cfg.num_trained_agents)[0]

        cls.callback._create_champion_snapshot_from_policy(
            cls.algo, cls.source_pid, return_value=0.0, iteration=1
        )
        cls.champion_id = cls.callback.champion_history[-1]["id"]

    @classmethod
    def teardown_class(cls):
        cls.algo.stop()
        ray.shutdown()

    def test_trainable_modules_use_the_custom_encoder(self):
        """The spec's model config may be a dataclass or a dict - see below."""
        spec = self.algo.config.rl_module_spec.rl_module_specs[self.source_pid]

        assert spec.catalog_class is CDACatalog
        assert _model_config_get(spec.model_config, "encoder_type", None) == FIXTURE

    def test_the_built_encoder_is_the_custom_one(self):
        """What the module actually runs, past every layer of config plumbing."""
        encoder = self.algo.env_runner.module[self.source_pid].encoder
        base = getattr(encoder, "actor_encoder", None) or encoder.encoder

        assert isinstance(base, TorchPassthroughEncoder)

    def test_champion_is_the_same_architecture_as_its_source(self):
        """`RLModuleSpec.from_module` must carry the catalog and model config."""
        modules = self.algo.env_runner.module
        champion = modules[self.champion_id]
        source = modules[self.source_pid]

        assert type(champion) is type(source)

        cloned = RLModuleSpec.from_module(champion)
        assert cloned.catalog_class is CDACatalog
        assert _model_config_get(cloned.model_config, "encoder_type", None) == FIXTURE

    def test_champion_weights_match_the_source(self):
        """A cloned architecture is no use if the state did not load into it."""
        modules = self.algo.env_runner.module
        champion = dict(modules[self.champion_id].named_parameters())
        source = dict(modules[self.source_pid].named_parameters())

        assert set(champion) == set(source)
        for name, tensor in source.items():
            assert champion[name].shape == tensor.shape

    def test_the_fingerprint_survives_a_champion_snapshot(self):
        """Regression: `add_module` turns every model_config into a plain dict.

        `_encoder_fingerprint` read it with `getattr` alone, so from the first
        champion onwards it reported the `mlp` default no matter which encoder
        was running - silently disabling the structural restore check for the
        rest of the run, which is exactly the failure that check exists to
        prevent. Every real run creates champions, so this was the normal path.
        """
        assert self.callback.champion_history, "no champion was created"

        assert _encoder_fingerprint(self.algo.config)["encoder_type"] == FIXTURE


class TestRestoreCannotChangeTheEncoder:
    """`encoder_type` / `encoder_spec` are structural, so a change must raise."""

    def test_changing_the_encoder_type_raises(self):
        restored, _ = build_config(config_with_encoder(MLP_ENCODER_TYPE))
        desired, _ = build_config(config_with_encoder(FIXTURE, run_id="other"))

        with pytest.raises(ValueError, match="encoder_type"):
            _check_restored_config(restored, desired)

    def test_changing_the_encoder_spec_raises(self):
        """A same-named encoder reshaped by its spec is still a different net."""
        restored, _ = build_config(config_with_encoder(FIXTURE))
        desired, _ = build_config(
            config_with_encoder(
                FIXTURE,
                encoder_specs={FIXTURE: {"latent_dim": 8}},
                run_id="other",
            )
        )

        with pytest.raises(ValueError, match="encoder_spec"):
            _check_restored_config(restored, desired)

    def test_an_unchanged_encoder_restores_cleanly(self):
        restored, _ = build_config(config_with_encoder(FIXTURE))
        desired, _ = build_config(config_with_encoder(FIXTURE, run_id="other"))

        _check_restored_config(restored, desired)

    def test_the_default_mlp_run_restores_cleanly(self):
        """The shipped config must not trip its own new guard."""
        restored, _ = build_config(TrainConfig(**TEST_CFG))
        desired, _ = build_config(TrainConfig(**TEST_CFG, run_id="other"))

        _check_restored_config(restored, desired)


class TestRecurrentEncoderTrainsEndToEnd:
    """The stateful path, which only exists once a real Algorithm samples.

    Everything about a recurrent module that can break lives outside the module:
    the connectors adding a time dimension, the states being carried between
    steps, the env receiving actions shaped differently from the stateless case.
    None of it is reachable from a unit test that calls `forward_train` by hand,
    and the first thing it broke was the *info dict* - `_plain` could not handle
    the 0-d arrays the time-dimension connectors produce, so every env step
    failed with `'int' object is not iterable`.
    """

    @classmethod
    def setup_class(cls):
        ray.init(
            ignore_reinit_error=True,
            include_dashboard=False,
            log_to_driver=False,
            num_cpus=2,
        )
        cls.cfg = config_with_encoder("lstm")
        ppo_config, cls.callback = build_config(cls.cfg)
        cls.algo = ppo_config.build_algo()
        cls.pid = trainable_policy_ids(cls.cfg.num_trained_agents)[0]
        cls.before = {
            k: v.detach().clone()
            for k, v in cls.algo.env_runner.module[cls.pid].named_parameters()
        }
        cls.result = cls.algo.train()

    @classmethod
    def teardown_class(cls):
        cls.algo.stop()
        ray.shutdown()

    def test_the_module_is_stateful(self):
        assert self.algo.env_runner.module[self.pid].is_stateful()

    def test_an_iteration_completes(self):
        """Sampling, the env steps, and the learner update all survived."""
        assert self.result["learners"][self.pid]["policy_loss"] is not None

    def test_the_recurrent_weights_are_trained(self):
        after = dict(self.algo.env_runner.module[self.pid].named_parameters())
        changed = {
            k for k, v in after.items() if not torch.equal(self.before[k], v)
        }

        assert any("lstm" in k for k in changed), "the LSTM itself did not update"
        assert any("tokenizer" in k for k in changed), "the tokenizer did not update"

    def test_a_champion_snapshot_of_a_recurrent_module_works(self):
        """Champions are cloned with `RLModuleSpec.from_module`, which has to
        carry statefulness across as well as the architecture."""
        self.callback._create_champion_snapshot_from_policy(
            self.algo, self.pid, return_value=0.0, iteration=1
        )
        champion_id = self.callback.champion_history[-1]["id"]
        champion = self.algo.env_runner.module[champion_id]

        assert champion.is_stateful()
        assert type(champion) is type(self.algo.env_runner.module[self.pid])


class TestMoEAuxLossReachesTheOptimiser:
    """The load-balancing term is computed three layers away from the loss.

    `MoEFeedForward` returns it, the block passes it up, the encoder stages it,
    `CDAPPOTorchRLModule` moves it into `fwd_out`, and `CDAPPOTorchLearner` adds
    it to PPO's total. Every link is invisible from either end - a break
    anywhere leaves training running normally with a gate nothing pushes towards
    balance, which is a silent regression to a very expensive dense layer.
    """

    @classmethod
    def setup_class(cls):
        ray.init(
            ignore_reinit_error=True,
            include_dashboard=False,
            log_to_driver=False,
            num_cpus=2,
        )
        cls.cfg = config_with_encoder("moe_transformer")
        ppo_config, cls.callback = build_config(cls.cfg)
        cls.algo = ppo_config.build_algo()
        cls.pid = trainable_policy_ids(cls.cfg.num_trained_agents)[0]
        cls.before = {
            k: v.detach().clone()
            for k, v in cls.algo.env_runner.module[cls.pid].named_parameters()
        }
        cls.result = cls.algo.train()

    @classmethod
    def teardown_class(cls):
        cls.algo.stop()
        ray.shutdown()

    def test_the_custom_learner_is_in_use(self):
        assert self.algo.config.learner_class is CDAPPOTorchLearner

    def test_the_aux_loss_is_logged(self):
        """If the module stopped forwarding it, the learner would add nothing
        and this metric would simply be absent."""
        learner_results = self.result["learners"][self.pid]

        assert MOE_AUX_LOSS_KEY in learner_results
        assert learner_results[MOE_AUX_LOSS_KEY] > 0

    def test_expert_utilisation_is_reported(self):
        """A collapsed mixture and a healthy one have identical losses and
        identical throughput. These two numbers are the only difference."""
        learner_results = self.result["learners"][self.pid]

        assert MOE_MAX_EXPERT_SHARE_KEY in learner_results
        assert MOE_MIN_EXPERT_SHARE_KEY in learner_results
        assert (
            learner_results[MOE_MIN_EXPERT_SHARE_KEY]
            <= learner_results[MOE_MAX_EXPERT_SHARE_KEY]
        )

    def test_the_gates_are_trained(self):
        """Nothing but the auxiliary loss trains a gate towards balance."""
        after = dict(self.algo.env_runner.module[self.pid].named_parameters())
        changed = {
            k for k, v in after.items() if not torch.equal(self.before[k], v)
        }

        assert any(".gate." in k for k in changed), "no gate was updated"
        assert any(".experts." in k for k in changed), "no expert was updated"

    def test_a_non_moe_encoder_logs_no_moe_metrics(self):
        """The module and learner are wired unconditionally, so they have to be
        inert for the other encoders rather than merely harmless."""
        cfg = config_with_encoder(MLP_ENCODER_TYPE, run_id="mlp-moe-check")
        ppo_config, _ = build_config(cfg)
        algo = ppo_config.build_algo()
        try:
            results = algo.train()["learners"][self.pid]
        finally:
            algo.stop()

        assert MOE_AUX_LOSS_KEY not in results


class TestCustomEncoderCheckpointRoundTrip:
    """A checkpoint has to carry the custom classes, not just the weights.

    `Algorithm.from_checkpoint` rebuilds from the config stored in the
    checkpoint, so the module class, the catalog class and the encoder spec all
    have to survive serialisation and re-import. A unit test's `get_state` /
    `set_state` cannot show that: it never leaves the process, and both ends
    were constructed by the same code path.
    """

    ENCODER = "transformer"

    @classmethod
    def setup_class(cls):
        ray.init(
            ignore_reinit_error=True,
            include_dashboard=False,
            log_to_driver=False,
            num_cpus=2,
        )
        cls.tmp = tempfile.mkdtemp()
        cfg = config_with_encoder(cls.ENCODER, run_id="ckpt-roundtrip")
        ppo_config, _ = build_config(cfg)
        cls.algo = ppo_config.build_algo()
        cls.pid = trainable_policy_ids(cfg.num_trained_agents)[0]

        cls.algo.save(cls.tmp)
        cls.restored = Algorithm.from_checkpoint(cls.tmp)

    @classmethod
    def teardown_class(cls):
        cls.restored.stop()
        cls.algo.stop()
        ray.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_restored_module_is_the_custom_class(self):
        restored = self.restored.env_runner.module[self.pid]

        assert type(restored) is type(self.algo.env_runner.module[self.pid])
        assert isinstance(
            restored.encoder.actor_encoder, TorchTransformerEncoder
        )

    def test_the_encoder_spec_survives(self):
        spec = self.restored.config.rl_module_spec.rl_module_specs[self.pid]

        assert _model_config_get(spec.model_config, "encoder_type", None) == (
            self.ENCODER
        )

    def test_the_weights_are_identical(self):
        """Compared on the Learner, which is where the authoritative weights
        live and what the checkpoint actually persists.

        Not on the EnvRunner: `get_non_inference_attributes` marks `vf` and
        `encoder.critic_encoder` as training-only, so they are never synced out
        and each runner's copy keeps its own random initialisation. Comparing
        those would be asserting something that is not true by design.
        """
        original = _learner_module_state(self.algo, self.pid)
        restored = _learner_module_state(self.restored, self.pid)

        assert set(original) == set(restored)
        for name, tensor in original.items():
            assert torch.equal(
                torch.as_tensor(tensor), torch.as_tensor(restored[name])
            ), f"{name} differs"

    def test_the_actor_side_weights_reach_the_env_runner(self):
        """What actually acts in the environment after a restore."""
        original = dict(self.algo.env_runner.module[self.pid].named_parameters())
        restored = dict(self.restored.env_runner.module[self.pid].named_parameters())

        acting = [n for n in original if "critic" not in n and not n.startswith("vf.")]
        assert acting
        for name in acting:
            assert torch.equal(original[name], restored[name]), f"{name} differs"

    def test_the_restore_guard_accepts_its_own_checkpoint(self):
        """The structural check must not fire on an unchanged config - that
        would make every custom-encoder run unresumable."""
        desired, _ = build_config(
            config_with_encoder(self.ENCODER, run_id="ckpt-roundtrip-2")
        )

        _check_restored_config(self.restored.config, desired)


class TestJEPAAuxLossReachesTheOptimiser:
    """The latent-prediction term, end to end through a real Algorithm.

    Same shape of claim as `TestMoEAuxLossReachesTheOptimiser` and for the same
    reason: the term is computed several layers from the loss - the encoder
    stages it, `JEPARLModule` moves it into `fwd_out`, `CDAJEPALearner` adds it
    to PPO's total - and a break anywhere leaves training running normally with
    an encoder nothing is teaching, which looks exactly like a working run.

    It also pins the isolation claim at the algorithm level: selecting `jepa`
    must swap in *both* the module and the learner class, and selecting
    anything else must leave both at what they were.
    """

    @classmethod
    def setup_class(cls):
        ray.init(
            ignore_reinit_error=True,
            include_dashboard=False,
            log_to_driver=False,
            num_cpus=2,
        )
        cls.cfg = config_with_encoder("jepa")
        ppo_config, cls.callback = build_config(cls.cfg)
        cls.algo = ppo_config.build_algo()
        cls.pid = trainable_policy_ids(cls.cfg.num_trained_agents)[0]
        cls.before = {
            k: v.detach().clone()
            for k, v in cls.algo.env_runner.module[cls.pid].named_parameters()
        }
        cls.result = cls.algo.train()

    @classmethod
    def teardown_class(cls):
        cls.algo.stop()
        ray.shutdown()

    def test_the_jepa_learner_is_in_use(self):
        assert self.algo.config.learner_class is CDAJEPALearner

    def test_the_module_class_is_the_jepa_one(self):
        assert isinstance(self.algo.env_runner.module[self.pid], JEPARLModule)

    def test_the_aux_loss_is_logged(self):
        """Absent if the module stopped forwarding it - the learner would then
        add nothing and training would look entirely normal."""
        learner_results = self.result["learners"][self.pid]

        assert JEPA_AUX_LOSS_KEY in learner_results
        assert learner_results[JEPA_AUX_LOSS_KEY] > 0
        assert JEPA_PREDICT_LOSS_KEY in learner_results

    def test_the_collapse_metrics_are_reported(self):
        """A collapsed JEPA drives its prediction loss to zero, which reads as
        success: loss and throughput look identical to a working encoder. These
        two numbers are the only difference."""
        learner_results = self.result["learners"][self.pid]

        assert JEPA_LATENT_STD_KEY in learner_results
        assert JEPA_OFFDIAG_COV_KEY in learner_results
        # LayerNormed targets sit near unit scale; anywhere near 0 is a
        # collapse, and this run is far too short to be in one.
        assert learner_results[JEPA_LATENT_STD_KEY] > 0.1

    def test_the_encoder_is_trained(self):
        after = dict(self.algo.env_runner.module[self.pid].named_parameters())
        changed = {
            k for k, v in after.items() if not torch.equal(self.before[k], v)
        }
        assert any("actor_encoder.trunk" in k for k in changed), (
            "the online trunk took no gradient at all"
        )

    def test_the_predictor_is_trained_but_the_target_is_not(self):
        """The target moves by EMA, never by gradient - that asymmetry is the
        anti-collapse mechanism. The predictor moves by gradient."""
        module = self.algo.env_runner.module[self.pid]
        encoder = module.encoder.actor_encoder

        assert all(not p.requires_grad for p in encoder.target_trunk.parameters())
        assert any(p.requires_grad for p in encoder.predictor.parameters())

    def test_the_training_only_parts_are_declared(self):
        """Or every champion snapshot carries a second encoder it never runs."""
        module = self.algo.env_runner.module[self.pid]
        declared = module.get_non_inference_attributes()

        assert "encoder.actor_encoder.target_trunk" in declared
        assert "encoder.actor_encoder.predictor" in declared


class TestOtherEncodersAreUnaffectedByJEPA:
    """Selecting anything else must resolve exactly as it did before `jepa`.

    The registry gained an optional module class and an optional learner class.
    Neither is set for any encoder that existed first, so each must still get
    the defaults - this is the mechanical form of the isolation claim.
    """

    @pytest.mark.parametrize(
        "encoder_type", ["mlp", "transformer", "lstm", "moe_transformer"]
    )
    def test_the_learner_is_still_the_default(self, encoder_type):
        assert learner_class_for(encoder_type, CDAPPOTorchLearner) is (
            CDAPPOTorchLearner
        )

    @pytest.mark.parametrize(
        "encoder_type", ["transformer", "lstm", "moe_transformer"]
    )
    def test_the_module_class_is_still_the_default(self, encoder_type):
        assert module_class_for(encoder_type, CDAPPOTorchRLModule) is (
            CDAPPOTorchRLModule
        )

    def test_jepa_is_the_only_encoder_that_overrides_either(self):
        assert set(ENCODER_MODULE_CLASSES) == {"jepa"}
        assert set(ENCODER_LEARNER_CLASSES) == {"jepa"}


class TestJEPAWorldModelReachesTheOptimiser:
    """The action-conditioned term, end to end through a real Algorithm.

    It needs `Columns.NEXT_OBS`, which PPO's train batch does not carry, so this
    also pins the conditional connector: it must be attached when the world
    model is on, and the term must actually arrive at the loss. Attached but
    unread, or read but never added, both look exactly like a working run.
    """

    @classmethod
    def setup_class(cls):
        ray.init(
            ignore_reinit_error=True,
            include_dashboard=False,
            log_to_driver=False,
            num_cpus=2,
        )
        cls.cfg = config_with_encoder(
            "jepa", encoder_specs={"jepa": {"world_model": True}}
        )
        ppo_config, cls.callback = build_config(cls.cfg)
        cls.algo = ppo_config.build_algo()
        cls.pid = trainable_policy_ids(cls.cfg.num_trained_agents)[0]
        cls.result = cls.algo.train()

    @classmethod
    def teardown_class(cls):
        cls.algo.stop()
        ray.shutdown()

    def test_the_world_loss_is_logged(self):
        """Absent if the connector did not run, or if the encoder never saw
        NEXT_OBS - neither of which raises anywhere."""
        learner_results = self.result["learners"][self.pid]

        assert JEPA_WORLD_LOSS_KEY in learner_results
        assert learner_results[JEPA_WORLD_LOSS_KEY] > 0

    def test_the_masked_objective_still_runs_alongside_it(self):
        """The world model is an addition, not a replacement."""
        learner_results = self.result["learners"][self.pid]

        assert JEPA_AUX_LOSS_KEY in learner_results
        assert JEPA_LATENT_STD_KEY in learner_results

    def test_the_action_embedding_is_trained(self):
        module = self.algo.env_runner.module[self.pid]
        world = module.encoder.actor_encoder.world_model

        assert world is not None
        assert any(p.requires_grad for p in world.action_embed.parameters())


class TestTheNextObsConnectorIsConditional:
    """Attached for the world model and for nothing else.

    Every other architecture would otherwise pay for a column it never reads -
    an extra observation-sized tensor per row of every train batch.
    """

    @pytest.mark.parametrize(
        "encoder_type", ["mlp", "transformer", "lstm", "moe_transformer"]
    )
    def test_other_encoders_do_not_ask_for_it(self, encoder_type):
        assert not needs_next_obs(encoder_type, None)

    def test_jepa_without_the_world_model_does_not_ask_for_it(self):
        assert not needs_next_obs("jepa", {"world_model": False})

    def test_jepa_with_the_world_model_does(self):
        assert needs_next_obs("jepa", {"world_model": True})

    def test_the_default_is_read_when_the_spec_omits_it(self):
        """A config file that never mentions `world_model` must resolve to the
        registered default, not to a missing key."""
        assert not needs_next_obs("jepa", {})
        assert not needs_next_obs("jepa", None)
