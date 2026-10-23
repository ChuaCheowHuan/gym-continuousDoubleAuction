"""Encoders an installed package provides, and the pretrained-weights format.

An extension package (docs/30) can bring an encoder: it lists a module under the
`gym_cda.encoders` entry-point group, and that module registers the encoder when
imported. Three claims are pinned with a stand-in for such a package:

  1. **Lazy and automatic.** Listing an encoder imports nothing; the first lookup
     of its name imports the module, in whatever process asks, so env runners and
     learners need no setup of their own.
  2. **Enabling stays explicit.** A config may select the encoder only with its
     extension in `extensions_enabled`: installing a package changes no run.
  3. **The encoder answers for itself** whether it needs `Columns.NEXT_OBS`.

Then the checkpoint format for pretrained encoder weights, which lives in
`encoders.pretrained` so that loading weights does not depend on the trainer that
produced them.
"""

from types import SimpleNamespace

import pytest

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.train.model import encoders
from gym_continuousDoubleAuction.train.model.encoders import (
    ENCODER_DEFAULTS,
    ENCODER_EXTENSIONS,
    ENCODER_NEXT_OBS,
    ENCODER_REGISTRY,
    encoder_extension,
    ensure_registered,
    known_encoder_type,
    needs_next_obs,
    register,
    selectable_encoder_types,
    validate_encoder_type,
)
from gym_continuousDoubleAuction.train.model.encoders import pretrained
from gym_continuousDoubleAuction.train.model.encoders.passthrough import (
    PASSTHROUGH_DEFAULTS,
    PassthroughEncoderConfig,
)
from gym_continuousDoubleAuction.train.model.model_handler import (
    build_trainable_module_spec,
)

PLUGIN = "plugenc"
EXTENSION = "plugext"

#: The registry's tables, which the stand-in's registration is removed from.
REGISTRY_TABLES = (ENCODER_REGISTRY, ENCODER_DEFAULTS, ENCODER_EXTENSIONS, ENCODER_NEXT_OBS)


class _FakeEntryPoint:
    """What `importlib.metadata` hands back for a listed encoder module."""

    value = "plugin_package.encoder"
    dist = SimpleNamespace(name="plugin-package")

    def __init__(self, registers=True, fails=None):
        self.registers = registers
        self.fails = fails
        self.loads = 0

    def load(self):
        self.loads += 1
        if self.fails is not None:
            raise self.fails
        if not self.registers:
            return

        @register(
            PLUGIN,
            defaults={**PASSTHROUGH_DEFAULTS, "next_obs": False},
            extension=EXTENSION,
            needs_next_obs=lambda settings: settings["next_obs"],
        )
        def build(layout, spec, input_dims):
            settings = encoders.encoder_settings(PLUGIN, spec)
            settings.pop("next_obs")
            return PassthroughEncoderConfig(input_dims=input_dims, layout=layout, **settings)


@pytest.fixture
def plugin(monkeypatch):
    entry = _FakeEntryPoint()
    monkeypatch.setattr(encoders, "installed_encoders", lambda: {PLUGIN: entry})
    yield entry
    for table in REGISTRY_TABLES:
        table.pop(PLUGIN, None)


@pytest.fixture(scope="module")
def spaces():
    env = continuousDoubleAuctionEnv({})
    agent_id = env.agents[0]
    return env.get_observation_space(agent_id), env.get_action_space(agent_id)


class TestAnInstalledEncoderLoadsOnFirstUse:
    def test_listing_it_imports_nothing(self, plugin):
        assert PLUGIN in selectable_encoder_types()
        assert plugin.loads == 0
        assert PLUGIN not in ENCODER_REGISTRY

    def test_the_first_lookup_imports_it_once(self, plugin):
        assert known_encoder_type(PLUGIN) == PLUGIN
        known_encoder_type(PLUGIN)
        assert plugin.loads == 1
        assert PLUGIN in ENCODER_REGISTRY

    def test_it_records_its_extension(self, plugin):
        assert encoder_extension(PLUGIN) == EXTENSION

    def test_a_module_that_registers_nothing_is_an_error(self, monkeypatch):
        entry = _FakeEntryPoint(registers=False)
        monkeypatch.setattr(encoders, "installed_encoders", lambda: {PLUGIN: entry})
        with pytest.raises(ValueError, match="registered no such encoder"):
            ensure_registered(PLUGIN)

    def test_an_unlisted_name_is_still_unknown(self, plugin):
        with pytest.raises(ValueError, match="Unknown encoder_type 'nosuch'"):
            known_encoder_type("nosuch")

    def test_a_module_spec_builds_from_it(self, plugin, spaces):
        """The route an env runner takes: nothing imported the plugin first."""
        spec = build_trainable_module_spec(*spaces, encoder_type=PLUGIN, encoder_specs={})
        module = spec.build()
        assert module.encoder is not None
        assert plugin.loads == 1


class TestAPackageThatFailsToImport:
    """An installed package whose own import breaks, as cda-jepa does without scipy.

    The error names the package and its module, and keeps the real ImportError as
    its cause, at startup and when a checkpoint is restored: the bare
    `No module named 'scipy'` alone does not say which package needs it.
    """

    CAUSE = ModuleNotFoundError("No module named 'scipy'")

    @pytest.fixture
    def broken(self, monkeypatch):
        entry = _FakeEntryPoint(fails=self.CAUSE)
        monkeypatch.setattr(encoders, "installed_encoders", lambda: {PLUGIN: entry})
        yield entry
        for table in REGISTRY_TABLES:
            table.pop(PLUGIN, None)

    def _check(self, error):
        message = str(error.value)
        assert "plugin-package" in message
        assert "plugin_package.encoder" in message
        assert "No module named 'scipy'" in message
        assert error.value.__cause__ is self.CAUSE

    def test_at_startup_the_error_names_the_package(self, broken):
        with pytest.raises(ImportError) as error:
            validate_encoder_type(PLUGIN, [EXTENSION])
        self._check(error)

    def test_on_restore_the_error_names_the_package(self, broken, monkeypatch):
        from gym_continuousDoubleAuction.train import checkpoint

        monkeypatch.setattr(
            checkpoint, "_encoder_fingerprint", lambda config: {"encoder_type": PLUGIN}
        )
        with pytest.raises(ImportError) as error:
            checkpoint._config_fingerprint(SimpleNamespace(learner_config_dict={}))
        self._check(error)

    def test_an_entry_point_without_a_distribution_still_names_its_module(self, broken):
        broken.dist = None
        with pytest.raises(ImportError, match="plugin_package.encoder") as error:
            ensure_registered(PLUGIN)
        assert error.value.__cause__ is self.CAUSE


class TestSelectingItNeedsTheExtensionEnabled:
    def test_refused_when_its_extension_is_not_enabled(self, plugin):
        with pytest.raises(ValueError, match="provided by the 'plugext' extension"):
            validate_encoder_type(PLUGIN, [])

    def test_accepted_when_it_is(self, plugin):
        assert validate_encoder_type(PLUGIN, [EXTENSION]) == PLUGIN

    def test_not_checked_without_a_run_config(self, plugin):
        """`model_handler` reads the encoder group alone; `TrainConfig` checks."""
        assert validate_encoder_type(PLUGIN) == PLUGIN

    def test_this_repositorys_encoders_need_no_extension(self):
        assert validate_encoder_type("transformer", []) == "transformer"


class TestTheEncoderSaysWhetherItNeedsNextObs:
    def test_from_its_merged_settings(self, plugin):
        assert needs_next_obs(PLUGIN, {}) is False
        assert needs_next_obs(PLUGIN, {"next_obs": True}) is True

    def test_an_encoder_that_registered_no_answer_never_does(self):
        assert needs_next_obs("transformer", {}) is False
        assert needs_next_obs("mlp", {}) is False


class TestThePretrainedWeightsFormat:
    def test_an_encoder_without_a_pretrained_path_field_cannot_load_weights(self, spaces):
        module = build_trainable_module_spec(
            *spaces, encoder_type="transformer", encoder_specs={}
        ).build()
        with pytest.raises(ValueError, match="pretrained_path"):
            pretrained.pretrainable_encoder(module)

    def test_loads_pretrained_reads_the_config_field(self):
        class Holder:
            pass

        with_field, without = Holder(), Holder()
        with_field.config = type("C", (), {"pretrained_path": None})()
        without.config = object()
        assert pretrained.loads_pretrained(with_field)
        assert not pretrained.loads_pretrained(without)

    def test_a_missing_checkpoint_names_what_is_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="is not a pretrain checkpoint"):
            pretrained.verify_fingerprint(str(tmp_path), "transformer", {})
