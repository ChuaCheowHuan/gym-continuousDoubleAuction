"""Integration tests for the extension point (docs/30).

The claims that only hold once a real `Algorithm` exists:

  1. **An installed, enabled extension runs inside a real PPO update**: its
     Learner mixin replaces PPO's loss through `_policy_value_loss`, its module
     mixin is on the module it selected and not the other, and its env wrapper
     wrapped the env the runner sampled from.
  2. **The composed classes survive a checkpoint**: `Algorithm.save` pickles
     the dynamically built Learner and module classes, and the restore builds
     them back.
  3. **The sidecar records the extension**, so a later restore without it is
     refused by name.

The dummy package is installed for the module's lifetime as a `*.dist-info`
directory on `sys.path`, the same way `test_extensions.py` does it, so
discovery goes through real entry points.
"""

import shutil
import sys
import tempfile
import textwrap
from pathlib import Path

import ray
import torch
from ray.rllib.algorithms.algorithm import Algorithm

from gym_continuousDoubleAuction.train import extensions
from gym_continuousDoubleAuction.train.checkpoint import _read_league_state, save_checkpoint
from gym_continuousDoubleAuction.train.train import TrainConfig, build_config

DUMMY_MODULE = textwrap.dedent(
    '''
    from gym_continuousDoubleAuction.train.extensions import Extension, settings_for


    class LearnerMixin:
        """Scales PPO's own loss: a stand-in for an update rule that replaces it."""

        def _policy_value_loss(self, *, module_id, config, batch, fwd_out):
            loss = super()._policy_value_loss(
                module_id=module_id, config=config, batch=batch, fwd_out=fwd_out
            )
            scale = settings_for(self.config.learner_config_dict, "wiring_dummy")["loss_scale"]
            self.metrics.log_value((module_id, "wiring_dummy_scale"), scale, window=1)
            return loss * scale


    class ModuleMixin:
        pass


    def wrap(env, settings):
        env.wiring_dummy_tag = settings["tag"]
        return env


    EXTENSION = Extension(
        name="wiring_dummy",
        version="0.0.1",
        defaults={"loss_scale": 0.5, "tag": "wrapped", "modules": ["policy_0"]},
        learner_mixin=LearnerMixin,
        module_mixin=ModuleMixin,
        module_ids=lambda settings, ids: [m for m in ids if m in settings["modules"]],
        env_wrapper=wrap,
    )
    '''
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
    extensions_enabled=["wiring_dummy"],
)


def _install(root: Path) -> None:
    (root / "cda_wiring_dummy.py").write_text(DUMMY_MODULE)
    dist = root / "cda_wiring_dummy-0.0.1.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: cda_wiring_dummy\nVersion: 0.0.1\n"
    )
    (dist / "entry_points.txt").write_text(
        f"[{extensions.ENTRY_POINT_GROUP}]\nwiring_dummy = cda_wiring_dummy:EXTENSION\n"
    )


class TestAnEnabledExtensionInARealRun:
    @classmethod
    def setup_class(cls):
        cls.site = Path(tempfile.mkdtemp())
        _install(cls.site)
        sys.path.insert(0, str(cls.site))
        extensions.discover.cache_clear()

        ray.init(ignore_reinit_error=True, include_dashboard=False, log_to_driver=False, num_cpus=2)
        cls.log_dir = tempfile.mkdtemp()
        cls.cfg = TrainConfig(**TEST_CFG, log_base_dir=cls.log_dir)
        ppo_config, _cb = build_config(cls.cfg)
        cls.algo = ppo_config.build_algo()
        cls.result = cls.algo.train()
        cls.learner = cls.algo.learner_group._learner

    @classmethod
    def teardown_class(cls):
        cls.algo.stop()
        ray.shutdown()
        sys.path.remove(str(cls.site))
        sys.modules.pop("cda_wiring_dummy", None)
        extensions.discover.cache_clear()
        shutil.rmtree(cls.site, ignore_errors=True)
        shutil.rmtree(cls.log_dir, ignore_errors=True)

    def test_the_learner_is_the_composed_class(self):
        mixin = extensions.discover()["wiring_dummy"].learner_mixin
        assert isinstance(self.learner, mixin)

    def test_the_replaced_loss_ran_for_every_trainable_module(self):
        for module_id in ("policy_0", "policy_1"):
            metrics = self.result["learners"][module_id]
            assert metrics["wiring_dummy_scale"] == 0.5
            assert torch.isfinite(torch.tensor(float(metrics["total_loss"])))

    def test_the_module_mixin_is_only_on_the_module_it_selected(self):
        mixin = extensions.discover()["wiring_dummy"].module_mixin
        modules = self.algo.env_runner.module
        assert isinstance(modules["policy_0"], mixin)
        assert not isinstance(modules["policy_1"], mixin)
        assert type(modules["policy_0"]).extension_settings["wiring_dummy"]["tag"] == "wrapped"

    def test_the_sampled_env_was_wrapped(self):
        # The runner holds a vector env of gymnasium-wrapped envs; ours is innermost.
        (env,) = self.algo.env_runner.env.envs
        assert env.unwrapped.wiring_dummy_tag == "wrapped"

    def test_the_checkpoint_round_trips_and_records_the_extension(self):
        path = save_checkpoint(self.algo, self.cfg, 1)
        assert _read_league_state(path)[extensions.EXTENSIONS_STATE_KEY] == {
            "wiring_dummy": "0.0.1"
        }

        restored = Algorithm.from_checkpoint(path)
        try:
            mixin = extensions.discover()["wiring_dummy"].learner_mixin
            assert isinstance(restored.learner_group._learner, mixin)
            assert restored.config.learner_config_dict["extensions"]["extensions_enabled"] == [
                "wiring_dummy"
            ]
        finally:
            restored.stop()
