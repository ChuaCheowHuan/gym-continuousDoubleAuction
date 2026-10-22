"""The extension point: installable packages found through entry points (docs/30).

What an external package relies on, pinned here because that package's own
tests run against this repository rather than inside it:

  1. **Discovery is through real entry points.** The dummy extension below is
     installed for the duration of a test as a `*.dist-info` directory on
     `sys.path`, exactly as pip would leave it, and found by `discover()`.
  2. **Nothing enabled means nothing changes.** The Learner and module classes
     are the same objects as before, the env is not wrapped, and a default
     run's checkpoint sidecar gains no key.
  3. **Enabling is explicit and validated.** Installing changes no run; an
     enabled name that is not installed, or a setting the extension does not
     declare, raises when the TrainConfig is built.
  4. **Resumes are guarded.** The enabled set and every resolved setting are
     unrestorable, a structural setting fails as structural, and a checkpoint
     whose extension is missing is refused before RLlib unpickles it.
"""

import textwrap
from types import SimpleNamespace

import pytest

from gym_continuousDoubleAuction.train import extensions
from gym_continuousDoubleAuction.train.checkpoint import (
    PRE_FEATURE_BEHAVIOUR,
    UNRESTORABLE_CONFIG_KEYS,
    _check_restored_config,
    _config_fingerprint,
)
from gym_continuousDoubleAuction.train.model.moe_learner import CDAPPOTorchLearner
from gym_continuousDoubleAuction.train.build import _learner_config_dict
from gym_continuousDoubleAuction.train.train import TrainConfig, _learner_class

DUMMY_MODULE = textwrap.dedent(
    '''
    from gym_continuousDoubleAuction.train.extensions import Extension


    class LearnerMixin:
        pass


    class ModuleMixin:
        pass


    def validate(settings, cfg):
        if settings["width"] < 1:
            raise ValueError("width must be positive")


    def wrap(env, settings):
        env.wrapped_by = ("dummy", settings["width"])
        return env


    EXTENSION = Extension(
        name="dummy",
        version="0.1.0",
        defaults={"width": 4, "modules": ["policy_0"], "scale": 1.0},
        validate=validate,
        learner_mixin=LearnerMixin,
        module_mixin=ModuleMixin,
        module_ids=lambda settings, ids: [m for m in ids if m in settings["modules"]],
        env_wrapper=wrap,
        structural_keys=("width",),
    )

    NOT_AN_EXTENSION = object()
    '''
)


def _install(root, name, target, module_source=DUMMY_MODULE, module="cda_dummy_ext"):
    """Leave `root` looking like site-packages after `pip install` of one package."""
    (root / f"{module}.py").write_text(module_source)
    dist = root / f"{module}-0.1.0.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {module}\nVersion: 0.1.0\n")
    (dist / "entry_points.txt").write_text(
        f"[{extensions.ENTRY_POINT_GROUP}]\n{name} = {module}:{target}\n"
    )


@pytest.fixture
def fresh_discovery():
    extensions.discover.cache_clear()
    yield
    extensions.discover.cache_clear()


@pytest.fixture
def dummy(tmp_path, monkeypatch, fresh_discovery):
    _install(tmp_path, "dummy", "EXTENSION")
    monkeypatch.syspath_prepend(str(tmp_path))
    return extensions.discover()["dummy"]


BASE_CFG = dict(
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


def _cfg(**kwargs):
    return TrainConfig(**BASE_CFG, **kwargs)


class TestDiscovery:
    def test_an_installed_package_is_found_through_its_entry_point(self, dummy):
        assert dummy.name == "dummy"
        assert dummy.version == "0.1.0"

    def test_an_entry_point_that_is_not_an_extension_raises(
        self, tmp_path, monkeypatch, fresh_discovery
    ):
        _install(tmp_path, "dummy", "NOT_AN_EXTENSION")
        monkeypatch.syspath_prepend(str(tmp_path))
        with pytest.raises(TypeError, match="not an Extension"):
            extensions.discover()

    def test_an_entry_point_named_differently_from_its_extension_raises(
        self, tmp_path, monkeypatch, fresh_discovery
    ):
        _install(tmp_path, "other", "EXTENSION")
        monkeypatch.syspath_prepend(str(tmp_path))
        with pytest.raises(ValueError, match="must match"):
            extensions.discover()


class TestNothingEnabledChangesNothing:
    def test_the_shipped_config_enables_nothing(self):
        cfg = TrainConfig()
        assert cfg.extensions_enabled == []
        assert cfg.extension_settings == {}

    def test_the_learner_class_is_the_same_object(self, dummy):
        """Installed but not enabled: still not a subclass that does nothing."""
        assert _learner_class(_cfg()) is CDAPPOTorchLearner

    def test_the_env_is_not_wrapped(self, dummy):
        env = SimpleNamespace()
        assert extensions.wrap_env(env, [], {}) is env
        assert not hasattr(env, "wrapped_by")

    def test_module_specs_are_untouched(self, dummy):
        spec = SimpleNamespace(module_class=CDAPPOTorchLearner)
        multi = SimpleNamespace(rl_module_specs={"policy_0": spec})
        extensions.compose_module_specs(multi, ["policy_0"], _cfg())
        assert spec.module_class is CDAPPOTorchLearner

    def test_the_learner_config_dict_gains_no_group(self):
        from gym_continuousDoubleAuction.train.build import _learner_config_dict

        assert extensions.EXTENSIONS_CONFIG_KEY not in _learner_config_dict(_cfg())

    def test_the_env_registers_without_a_train_config(self):
        """`train.evaluate` registers the env before it has any TrainConfig."""
        from ray.tune.registry import ENV_CREATOR, _global_registry

        from gym_continuousDoubleAuction.train.build import ENV_NAME, register_env

        register_env(None)
        assert _global_registry.contains(ENV_CREATOR, ENV_NAME)

    def test_a_default_run_records_no_extension(self):
        assert extensions.versions({"extensions": extensions.learner_config(_cfg())}) == {}


class TestEnablingIsExplicitAndValidated:
    def test_defaults_are_filled_in(self, dummy):
        resolved = extensions.resolve(["dummy"], {"dummy": {"width": 8}})
        assert resolved == {"dummy": {"width": 8, "modules": ["policy_0"], "scale": 1.0}}

    def test_an_unknown_setting_raises(self, dummy):
        with pytest.raises(ValueError, match="unknown keys \\['widht'\\]"):
            _cfg(extensions_enabled=["dummy"], extension_settings={"dummy": {"widht": 8}})

    def test_the_extensions_own_validation_runs(self, dummy):
        with pytest.raises(ValueError, match="width must be positive"):
            _cfg(extensions_enabled=["dummy"], extension_settings={"dummy": {"width": 0}})

    def test_enabling_a_package_that_is_not_installed_raises(self, fresh_discovery):
        with pytest.raises(ValueError, match="not installed"):
            _cfg(extensions_enabled=["no_such_extension"])

    def test_listing_a_name_twice_raises(self, dummy):
        with pytest.raises(ValueError, match="more than once"):
            _cfg(extensions_enabled=["dummy", "dummy"])

    def test_settings_for_an_extension_that_is_not_enabled_are_ignored(self, fresh_discovery):
        """Uninstalling needs only the name removed from extensions_enabled."""
        cfg = _cfg(extension_settings={"discorl": {"anything": 1}})
        assert extensions.learner_config(cfg)["extension_settings"] == {}


class TestComposition:
    def test_the_learner_mixin_comes_first_and_the_base_is_kept(self, dummy):
        composed = _learner_class(_cfg(extensions_enabled=["dummy"]))
        assert composed.__mro__[1] is dummy.learner_mixin
        assert issubclass(composed, CDAPPOTorchLearner)
        assert composed._policy_value_loss is CDAPPOTorchLearner._policy_value_loss

    def test_extensions_wrap_tuned_adam(self, dummy):
        """An extension's optimiser setup runs before tuned Adam's (#335 review).

        TunedAdamMixin builds torch's Adam without calling `super()`, so outside
        an extension it silently replaced the extension's own optimiser (cda-cbp's
        AdamGnT) whenever `adam_betas` or `adam_weight_decay` was set.
        """
        from gym_continuousDoubleAuction.train.model.optim_learner import TunedAdamMixin

        composed = _learner_class(_cfg(extensions_enabled=["dummy"], adam_betas=[0.99, 0.99]))
        mro = composed.__mro__
        assert (
            mro.index(dummy.learner_mixin)
            < mro.index(TunedAdamMixin)
            < mro.index(CDAPPOTorchLearner)
        )

    def test_the_module_mixin_goes_only_on_the_modules_it_selects(self, dummy):
        specs = {
            pid: SimpleNamespace(module_class=CDAPPOTorchLearner)
            for pid in ("policy_0", "policy_1")
        }
        multi = SimpleNamespace(rl_module_specs=specs)
        cfg = _cfg(extensions_enabled=["dummy"], extension_settings={"dummy": {"width": 2}})
        extensions.compose_module_specs(multi, ["policy_0", "policy_1"], cfg)

        chosen = specs["policy_0"].module_class
        assert chosen.__mro__[1] is dummy.module_mixin
        assert chosen.extension_settings["dummy"]["width"] == 2
        assert specs["policy_1"].module_class is CDAPPOTorchLearner

    def test_the_env_wrapper_receives_resolved_settings(self, dummy):
        env = extensions.wrap_env(SimpleNamespace(), ["dummy"], {})
        assert env.wrapped_by == ("dummy", 4)

    def test_a_learner_reads_its_settings_off_the_learner_config(self, dummy):
        cfg = _cfg(extensions_enabled=["dummy"], extension_settings={"dummy": {"scale": 0.5}})
        group = {extensions.EXTENSIONS_CONFIG_KEY: extensions.learner_config(cfg)}
        assert extensions.settings_for(group, "dummy")["scale"] == 0.5
        assert extensions.versions(group) == {"dummy": "0.1.0"}


def _algo_config(enabled=(), settings=None):
    group = {
        "extensions_enabled": sorted(enabled),
        "extension_settings": settings or {},
    }
    return SimpleNamespace(learner_config_dict={extensions.EXTENSIONS_CONFIG_KEY: group})


class TestResumeIsGuarded:
    def test_enabled_extensions_are_unrestorable_and_default_to_none(self):
        assert "extensions_enabled" in UNRESTORABLE_CONFIG_KEYS
        assert PRE_FEATURE_BEHAVIOUR["extensions_enabled"] == ()

    def test_settings_are_fingerprinted_under_their_own_prefix(self, dummy):
        fp = _config_fingerprint(
            _algo_config(["dummy"], {"dummy": {"width": 4, "modules": ["policy_0"]}})
        )
        assert fp["extensions_enabled"] == ("dummy",)
        assert fp["ext.dummy.width"] == 4
        assert fp["ext.dummy.modules"] == ("policy_0",)

    def test_a_checkpoint_from_before_extensions_restores(self, dummy):
        _check_restored_config(SimpleNamespace(), _algo_config())

    def test_enabling_an_extension_on_resume_is_refused(self, dummy):
        with pytest.raises(ValueError, match="extensions_enabled"):
            _check_restored_config(
                _algo_config(), _algo_config(["dummy"], {"dummy": {"scale": 1.0}})
            )

    def test_disabling_an_extension_on_resume_is_refused(self, dummy):
        """A default run's config carries no extensions group at all, so the
        desired side must still read as "none enabled" rather than be skipped."""
        desired = SimpleNamespace(learner_config_dict=_learner_config_dict(_cfg()))
        assert extensions.EXTENSIONS_CONFIG_KEY not in desired.learner_config_dict
        with pytest.raises(ValueError, match="extensions_enabled"):
            _check_restored_config(_algo_config(["dummy"], {"dummy": {"scale": 1.0}}), desired)

    def test_changing_a_setting_on_resume_is_refused(self, dummy):
        with pytest.raises(ValueError, match="ext.dummy.scale"):
            _check_restored_config(
                _algo_config(["dummy"], {"dummy": {"scale": 1.0}}),
                _algo_config(["dummy"], {"dummy": {"scale": 2.0}}),
            )

    def test_changing_a_structural_setting_fails_as_structural(self, dummy):
        with pytest.raises(ValueError, match="shape of the problem"):
            _check_restored_config(
                _algo_config(["dummy"], {"dummy": {"width": 4}}),
                _algo_config(["dummy"], {"dummy": {"width": 8}}),
            )

    def test_a_checkpoint_whose_extension_is_missing_is_refused(self, fresh_discovery):
        with pytest.raises(ValueError, match="dummy 0.1.0.*not installed"):
            extensions.check_installed(
                {extensions.EXTENSIONS_STATE_KEY: {"dummy": "0.1.0"}}, "ckpt"
            )

    def test_a_sidecar_without_extensions_passes(self, fresh_discovery):
        extensions.check_installed({}, "ckpt")
        extensions.check_installed(None, "ckpt")


ORDERED_MODULE = textwrap.dedent(
    '''
    from gym_continuousDoubleAuction.train.extensions import Extension


    class LearnerMixin:
        pass


    EXTENSION = Extension(
        name="{name}", version="0.1.0", learner_mixin=LearnerMixin, learner_order={order}
    )
    '''
)


class TestLearnerOrder:
    """`learner_order` decides how far out a mixin wraps, not the extension's name."""

    @pytest.fixture
    def pair(self, tmp_path, monkeypatch, fresh_discovery):
        # Names sort opposite to the requested order: "aaa" must wrap outside "zzz".
        for name, order in (("aaa", 10), ("zzz", 0)):
            root = tmp_path / name
            root.mkdir()
            source = ORDERED_MODULE.replace("{name}", name).replace("{order}", str(order))
            _install(root, name, "EXTENSION", source, module=f"cda_{name}_ext")
            monkeypatch.syspath_prepend(str(root))
        return extensions.discover()

    def test_the_default_order_is_zero(self):
        assert extensions.Extension(name="x", version="0").learner_order == 0

    def test_a_higher_order_wraps_further_out_whatever_the_names(self, pair):
        composed = _learner_class(_cfg(extensions_enabled=["zzz", "aaa"]))
        mro = composed.__mro__
        assert mro.index(pair["aaa"].learner_mixin) < mro.index(pair["zzz"].learner_mixin)

    def test_equal_orders_fall_back_to_name_order(self, dummy):
        # The existing single-extension behaviour: the mixin sits directly over the base.
        composed = _learner_class(_cfg(extensions_enabled=["dummy"]))
        assert composed.__mro__[1] is dummy.learner_mixin
