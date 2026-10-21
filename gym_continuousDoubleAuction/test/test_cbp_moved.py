"""Continual Backprop moved to the `cda-cbp` package; what stays behind here.

Three promises to people with configs and checkpoints from before the move:

* An old `cbp_*` key is an error that names the package, never silently
  ignored - a run that quietly dropped `cbp_enabled: true` would look exactly
  like one with CBP on.
* An old checkpoint's `continual_backprop` group reads as the extension's
  settings, so resuming it with `extensions_enabled: ["cbp"]` and the same
  settings passes the restore guard, and changing them is still refused.
* `cbp_learner.CBPLearnerMixin`, the name old checkpoints pickled, resolves to
  the package's mixin, or raises naming the package.
"""

import json
import sys
from types import SimpleNamespace

import pytest

from gym_continuousDoubleAuction.train import extensions
from gym_continuousDoubleAuction.train.checkpoint import (
    _check_restored_config,
    _config_fingerprint,
)
from gym_continuousDoubleAuction.train.compare import parse_overrides
from gym_continuousDoubleAuction.train.train import TrainConfig

#: The `continual_backprop` learner group as every checkpoint before the move
#: stored it.
LEGACY_GROUP = {
    "cbp_enabled": True,
    "cbp_metrics_only": False,
    "cbp_replacement_rate": 0.05,
    "cbp_maturity_threshold": 1,
    "cbp_utility_decay": 0.99,
    "cbp_utility": "contribution",
    "cbp_scope": "feedforward",
    "cbp_fire_on": "adam_step",
    "cbp_reset_optimizer_state": True,
    "cbp_compensate_mean": False,
    "cbp_dead_unit_threshold": 0.01,
    "cbp_metrics_every_n_updates": 1,
}


def _settings(group):
    return {k[len("cbp_") :]: v for k, v in group.items() if k != "cbp_enabled"}


def _legacy(**changes):
    return SimpleNamespace(learner_config_dict={"continual_backprop": {**LEGACY_GROUP, **changes}})


def _extension(settings, enabled=("cbp",)):
    return SimpleNamespace(
        learner_config_dict={
            extensions.EXTENSIONS_CONFIG_KEY: {
                "extensions_enabled": list(enabled),
                "extension_settings": {"cbp": settings} if enabled else {},
            }
        }
    )


class TestOldKeysNameThePackage:
    def test_a_config_file_with_the_old_group(self, tmp_path):
        path = tmp_path / "old.json"
        path.write_text(json.dumps({"continual_backprop": {"cbp_enabled": True}}))
        with pytest.raises(ValueError, match="cda-cbp"):
            TrainConfig.from_json(str(path))

    def test_a_set_override(self):
        with pytest.raises(SystemExit, match="cda-cbp"):
            parse_overrides(["cbp_enabled=true"])

    def test_the_config_has_no_cbp_fields(self):
        assert not [name for name in TrainConfig.__dataclass_fields__ if name.startswith("cbp_")]

    def test_a_config_dir_still_carrying_them(self, tmp_path, monkeypatch):
        from gym_continuousDoubleAuction import config_loader

        src = config_loader.config_dir()
        for other in src.glob("*.json"):
            (tmp_path / other.name).write_bytes(other.read_bytes())
        data = json.loads((src / "train_config.json").read_text())
        data["continual_backprop"] = {"cbp_enabled": True}
        (tmp_path / "train_config.json").write_text(json.dumps(data))
        monkeypatch.setenv(config_loader.CONFIG_DIR_ENV_VAR, str(tmp_path))
        config_loader.reload()
        try:
            with pytest.raises(ValueError, match="cda-cbp"):
                TrainConfig()
        finally:
            monkeypatch.delenv(config_loader.CONFIG_DIR_ENV_VAR)
            config_loader.reload()


class TestOldCheckpointsReadAsTheExtension:
    def test_an_enabled_group_becomes_the_extension(self):
        fp = _config_fingerprint(_legacy())
        assert fp["extensions_enabled"] == ("cbp",)
        assert fp["ext.cbp.utility"] == "contribution"
        assert fp["ext.cbp.metrics_only"] is False
        assert not any(key.startswith("cbp_") for key in fp)

    def test_a_metrics_only_group_becomes_the_extension(self):
        fp = _config_fingerprint(_legacy(cbp_enabled=False, cbp_metrics_only=True))
        assert fp["extensions_enabled"] == ("cbp",)
        assert fp["ext.cbp.metrics_only"] is True

    def test_a_disabled_group_is_nothing(self):
        fp = _config_fingerprint(_legacy(cbp_enabled=False))
        assert fp.get("extensions_enabled", ()) == ()
        assert not any(key.startswith(("cbp_", "ext.cbp.")) for key in fp)

    def test_resuming_with_the_same_settings_passes(self):
        _check_restored_config(_legacy(), _extension(_settings(LEGACY_GROUP)))

    def test_resuming_with_a_changed_setting_is_refused(self):
        settings = {**_settings(LEGACY_GROUP), "utility": "overall"}
        with pytest.raises(ValueError, match="ext.cbp.utility"):
            _check_restored_config(_legacy(), _extension(settings))

    def test_resuming_without_the_extension_is_refused(self):
        with pytest.raises(ValueError, match="extensions_enabled"):
            _check_restored_config(_legacy(), _extension({}, enabled=()))

    def test_resuming_with_a_default_config_is_refused(self):
        """A default run writes no extension group at all - the usual way to
        forget it - only the optimiser group. CBP would keep running from the
        checkpoint's own config while the config said nothing of it."""
        default = SimpleNamespace(
            learner_config_dict={
                "optimizer": {"adam_betas": [0.9, 0.999], "adam_weight_decay": 0.0}
            }
        )
        with pytest.raises(ValueError, match="extensions_enabled"):
            _check_restored_config(_legacy(), default)

    def test_a_disabled_group_resumes_without_it(self):
        _check_restored_config(_legacy(cbp_enabled=False), _extension({}, enabled=()))


class TestTheOldMixinName:
    def test_it_raises_naming_the_package_when_missing(self, monkeypatch):
        from gym_continuousDoubleAuction.train.model import cbp_learner

        monkeypatch.setitem(sys.modules, "cda_cbp", None)
        monkeypatch.setitem(sys.modules, "cda_cbp.learner", None)
        with pytest.raises(ImportError, match="cda-cbp"):
            cbp_learner.CBPLearnerMixin

    def test_it_is_the_packages_mixin_when_installed(self):
        learner = pytest.importorskip("cda_cbp.learner")
        from gym_continuousDoubleAuction.train.model import cbp_learner

        assert cbp_learner.CBPLearnerMixin is learner.CBPLearnerMixin

    def test_tuned_adam_needs_no_package(self, monkeypatch):
        from gym_continuousDoubleAuction.train.model import cbp_learner, optim_learner

        monkeypatch.setitem(sys.modules, "cda_cbp", None)
        assert cbp_learner.TunedAdamMixin is optim_learner.TunedAdamMixin


def _write_ctor_pickle(directory, payload: bytes):
    from ray.rllib.utils.checkpoints import Checkpointable

    (directory / Checkpointable.CLASS_AND_CTOR_ARGS_FILE_NAME).write_bytes(payload)
    return str(directory)


def _old_cbp_class_bytes():
    import os
    import pickle

    fixture = os.path.join(os.path.dirname(__file__), "fixtures", "learner_classes_f7c1353.pkl")
    with open(fixture, "rb") as fh:
        return pickle.load(fh)["classes"]["cbp"]


@pytest.fixture
def without_cda_cbp(monkeypatch):
    monkeypatch.setitem(sys.modules, "cda_cbp", None)
    monkeypatch.setitem(sys.modules, "cda_cbp.learner", None)


class TestAnOldCheckpointWithoutThePackageIsRefused:
    """RLlib's `from_checkpoint` swallows an unpickling error and builds with no
    config, failing later with "'NoneType' object has no attribute 'to_dict'";
    `build_algo` then took that for a truncated save and, unless the checkpoint
    was pinned, fell back to older ones and finally to a fresh run. A CBP
    checkpoint resumed without cda-cbp must stop instead, naming the package."""

    def test_the_check_names_the_package(self, tmp_path, without_cda_cbp):
        from gym_continuousDoubleAuction.train.checkpoint import check_pickled_classes_load

        path = _write_ctor_pickle(tmp_path, _old_cbp_class_bytes())
        with pytest.raises(ImportError, match="cda-cbp"):
            check_pickled_classes_load(path)

    def test_a_loadable_or_missing_file_passes(self, tmp_path):
        import pickle

        from gym_continuousDoubleAuction.train.checkpoint import check_pickled_classes_load

        check_pickled_classes_load(str(tmp_path))
        check_pickled_classes_load(_write_ctor_pickle(tmp_path, pickle.dumps({"a": 1})))

    def test_a_truncated_file_is_left_to_rllib(self, tmp_path):
        from gym_continuousDoubleAuction.train.checkpoint import check_pickled_classes_load

        check_pickled_classes_load(_write_ctor_pickle(tmp_path, b"\x80\x05trunc"))

    def test_build_algo_stops_before_falling_back(self, tmp_path, monkeypatch, without_cda_cbp):
        from gym_continuousDoubleAuction.train import build as build_mod

        path = _write_ctor_pickle(tmp_path, _old_cbp_class_bytes())
        loaded = []
        monkeypatch.setattr(build_mod, "restore_candidates", lambda _cfg: [(1, path)])
        monkeypatch.setattr(build_mod, "build_config", lambda _cfg: (None, None))
        monkeypatch.setattr(build_mod, "_read_league_state", lambda _p: {})
        monkeypatch.setattr(build_mod, "check_layout_stamp", lambda *_a, **_k: None)
        monkeypatch.setattr(build_mod, "Algorithm", SimpleNamespace(from_checkpoint=loaded.append))
        with pytest.raises(ImportError, match="cda-cbp"):
            build_mod.build_algo(TrainConfig(is_restore=True))
        assert loaded == []
