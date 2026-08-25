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
import pytest
import ray
import torch
from ray.rllib.core.rl_module.rl_module import RLModuleSpec

from gym_continuousDoubleAuction.train.model.encoders import MLP_ENCODER_TYPE
from gym_continuousDoubleAuction.train.model.encoders.passthrough import (
    TorchPassthroughEncoder,
)
from gym_continuousDoubleAuction.train.model.model_handler import CDACatalog
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
