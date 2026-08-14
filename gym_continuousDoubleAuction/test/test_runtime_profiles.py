"""`config/runtime_profiles.json` reaching a TrainConfig and a ray.init().

The same property `test_config_sources.py` asserts for the training values,
asserted for the runtime ones: no literal copy of a profile lives in Python,
so editing the file changes what a run asks for. The method is the same -
point `$CDA_CONFIG_DIR` at a modified copy of `config/` and check the change
comes out the other end.

The hardware sets are also checked against the stated ceiling and floor: at
most 2 CPUs with 1 GPU, at least 1 CPU with 0 GPUs.
"""
import dataclasses
import json
import shutil

import pytest

from gym_continuousDoubleAuction import config_loader
from gym_continuousDoubleAuction.train import runtime
from gym_continuousDoubleAuction.train.train import TrainConfig

MAX_CPUS = 2
MAX_GPUS = 1
MIN_CPUS = 1


@pytest.fixture
def config_tree(tmp_path, monkeypatch):
    """A writable copy of `config/`, installed as the active config directory."""
    target = tmp_path / "config"
    shutil.copytree(config_loader.config_dir(), target)
    monkeypatch.setenv(config_loader.CONFIG_DIR_ENV_VAR, str(target))
    config_loader.reload()

    def edit(filename, mutate):
        path = target / filename
        with open(path) as fh:
            raw = json.load(fh)
        mutate(raw)
        with open(path, "w") as fh:
            json.dump(raw, fh)
        config_loader.reload()

    yield edit

    config_loader.reload()


@pytest.fixture
def no_cuda(monkeypatch):
    """Force the CPU path, so these tests do not depend on the test machine."""
    monkeypatch.setattr(runtime, "cuda_available", lambda: False)


@pytest.fixture
def with_cuda(monkeypatch):
    """Force the GPU path on a machine that has no GPU."""
    monkeypatch.setattr(runtime, "cuda_available", lambda: True)


class TestHardwareProfiles:

    def test_both_sets_exist(self):
        profiles = config_loader.group(runtime.PROFILES_FILE, "hardware")
        assert set(profiles) == {"gpu", "cpu"}

    @pytest.mark.parametrize("name", ["gpu", "cpu"])
    def test_within_the_stated_hardware_bounds(self, name):
        ray_init = config_loader.group(runtime.PROFILES_FILE, "hardware")[name]["ray_init"]
        assert MIN_CPUS <= ray_init["num_cpus"] <= MAX_CPUS
        assert 0 <= ray_init["num_gpus"] <= MAX_GPUS

    def test_gpu_set_asks_for_a_gpu_and_the_cpu_set_does_not(self):
        profiles = config_loader.group(runtime.PROFILES_FILE, "hardware")
        assert profiles["gpu"]["ray_init"]["num_gpus"] == 1
        assert profiles["gpu"]["train_config"]["num_gpus_per_learner"] > 0
        assert profiles["cpu"]["ray_init"]["num_gpus"] == 0
        assert profiles["cpu"]["train_config"]["num_gpus_per_learner"] == 0

    def test_env_runners_fit_the_cpu_budget(self):
        """Runners are actors: they must fit in what ray.init() is given."""
        for name, profile in config_loader.group(runtime.PROFILES_FILE, "hardware").items():
            tc, ray_init = profile["train_config"], profile["ray_init"]
            demand = tc["num_env_runners"] * tc["num_cpus_per_env_runner"]
            assert demand <= ray_init["num_cpus"], (
                f"{name}: {tc['num_env_runners']} runners x "
                f"{tc['num_cpus_per_env_runner']} CPUs exceeds num_cpus="
                f"{ray_init['num_cpus']}; the actors would stay pending."
            )

    def test_every_override_names_a_real_trainconfig_field(self):
        known = {f.name for f in dataclasses.fields(TrainConfig)}
        for profile in config_loader.group(runtime.PROFILES_FILE, "hardware").values():
            assert set(profile["train_config"]) <= known

    def test_an_unknown_override_key_raises(self, config_tree, no_cuda):
        config_tree(
            "runtime_profiles.json",
            lambda raw: raw["hardware"]["cpu"]["train_config"].update(no_such_field=1),
        )
        with pytest.raises(ValueError, match="not TrainConfig fields"):
            runtime.resolve(platform="local", use_gpu=False)


class TestResolution:

    def test_gpu_toggle_off_selects_the_cpu_set(self, with_cuda):
        assert runtime.resolve(platform="local", use_gpu=False).hardware == "cpu"

    def test_gpu_toggle_on_without_cuda_falls_back_and_says_so(self, no_cuda):
        rt = runtime.resolve(platform="local", use_gpu=True)
        assert rt.hardware == "cpu"
        assert rt.gpu_unavailable is True

    def test_auto_follows_cuda(self, with_cuda):
        assert runtime.resolve(platform="local", use_gpu="auto").hardware == "gpu"

    def test_env_var_pins_the_platform(self, monkeypatch, no_cuda):
        monkeypatch.setenv(runtime.PLATFORM_ENV_VAR, "docker")
        assert runtime.resolve().platform == "docker"

    def test_env_var_pins_the_gpu_toggle(self, monkeypatch, with_cuda):
        monkeypatch.setenv(runtime.USE_GPU_ENV_VAR, "false")
        assert runtime.resolve(platform="local").hardware == "cpu"

    def test_unknown_platform_raises_naming_the_valid_ones(self, no_cuda):
        with pytest.raises(KeyError, match="no platform"):
            runtime.resolve(platform="no_such_platform")

    def test_ray_init_merges_the_common_settings(self, no_cuda):
        kwargs = runtime.resolve(platform="local", use_gpu=False).ray_init_kwargs
        assert kwargs["include_dashboard"] is False
        assert kwargs["num_cpus"] == 1

    def test_editing_the_file_changes_what_ray_is_asked_for(self, config_tree, no_cuda):
        """The no-literal-in-Python property, for the resource counts."""
        config_tree(
            "runtime_profiles.json",
            lambda raw: raw["hardware"]["cpu"]["ray_init"].update(num_cpus=7),
        )
        assert runtime.resolve(platform="local", use_gpu=False).ray_init_kwargs["num_cpus"] == 7

    def test_a_platform_missing_a_required_key_raises(self, config_tree, no_cuda):
        config_tree(
            "runtime_profiles.json",
            lambda raw: raw["platforms"]["local"].pop("results_root"),
        )
        with pytest.raises(KeyError, match="results_root"):
            runtime.resolve(platform="local", use_gpu=False)


class TestApply:

    def test_profile_fields_land_on_the_config(self, no_cuda):
        rt = runtime.resolve(platform="local", use_gpu=False)
        cfg = runtime.apply(TrainConfig(), rt)
        for field, expected in rt.overrides.items():
            assert getattr(cfg, field) == expected

    def test_training_values_are_untouched(self, no_cuda):
        """A profile moves resources and paths, never the learning problem."""
        base = TrainConfig()
        cfg = runtime.apply(base, runtime.resolve(platform="local", use_gpu=False))
        moved = set(runtime.changed_fields(base, cfg))
        assert not moved & {
            "num_agents", "num_trained_agents", "max_step", "num_iters", "lr",
            "num_epochs", "minibatch_size",
            "order_penalty", "trade_penalty", "drawdown_penalty",
            "passive_bonus", "loss_multiplier", "seed",
        }

    def test_output_roots_are_applied(self, config_tree, no_cuda):
        config_tree(
            "runtime_profiles.json",
            lambda raw: raw["platforms"]["local"].update(
                results_root="/tmp/cda_results",
                episode_data_root="/tmp/cda_eps",
            ),
        )
        cfg = runtime.apply(TrainConfig(), runtime.resolve(platform="local", use_gpu=False))
        assert cfg.log_base_dir == "/tmp/cda_results"
        assert cfg.checkpoint_dir == "/tmp/cda_results/chkpt"
        assert cfg.episode_data_dir == "/tmp/cda_eps"

    def test_null_roots_leave_the_configured_paths_alone(self, no_cuda):
        base = TrainConfig()
        cfg = runtime.apply(base, runtime.resolve(platform="local", use_gpu=False))
        assert cfg.log_base_dir == base.log_base_dir
        assert cfg.episode_data_dir == base.episode_data_dir

    def test_disabled_episode_data_is_not_re_enabled_by_a_root(
        self, config_tree, no_cuda
    ):
        """Relocating a disabled output would silently turn it back on."""
        config_tree(
            "runtime_profiles.json",
            lambda raw: raw["platforms"]["local"].update(episode_data_root="/tmp/cda_eps"),
        )
        base = dataclasses.replace(TrainConfig(), episode_data_dir=None)
        cfg = runtime.apply(base, runtime.resolve(platform="local", use_gpu=False))
        assert cfg.episode_data_dir is None


class TestEnvVars:

    def test_exports_the_configured_names(self, monkeypatch):
        monkeypatch.delenv("RAY_DEBUG_DISABLE_MEMORY_MONITOR", raising=False)
        assert runtime.apply_env_vars()["RAY_DEBUG_DISABLE_MEMORY_MONITOR"] == "True"

    def test_an_exported_value_wins_over_the_file(self, monkeypatch):
        monkeypatch.setenv("RAY_DEBUG_DISABLE_MEMORY_MONITOR", "False")
        assert runtime.apply_env_vars()["RAY_DEBUG_DISABLE_MEMORY_MONITOR"] == "False"
