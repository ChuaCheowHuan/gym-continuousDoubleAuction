"""The `jepa` encoder moved to the cda-jepa package; what is left here for it.

gym-CDA no longer ships `jepa`, its Learner or its pretrainer. Four things stay,
so that nothing written before the move breaks silently:

  1. **A config that selects it** names the package, rather than listing the
     encoders that are available as if `jepa` were a typo.
  2. **An old checkpoint** pickled `train.model.jepa_learner.CDAJEPALearner` and
     `JEPARLModule` by module path. That module forwards to the package, and
     without the package it fails naming it (`fixtures/jepa_classes_98c4900.pkl`
     holds the classes pickled on the last commit that shipped them).
  3. **The restore guard.** The config that resumes such a checkpoint must list
     `"jepa"` in `extensions_enabled`, and the checkpoint lists no extension. An
     encoder an extension provides implies that extension, so the two compare
     equal (`checkpoint._config_fingerprint`).
  4. **The old pretrainer command** says where the pretrainer went.

The checks that need the package are skipped without it, and the ones that need
its absence are skipped with it: gym-CDA's CI installs no extension.
"""

import importlib.util
import os
import pickle
import sys
from types import SimpleNamespace

import pytest

from gym_continuousDoubleAuction.config_loader import cli_default, group
from gym_continuousDoubleAuction.train import checkpoint
from gym_continuousDoubleAuction.train.model import encoders
from gym_continuousDoubleAuction.train.model.encoders import (
    known_encoder_type,
    selectable_encoder_types,
)
from gym_continuousDoubleAuction.test import test_encoder_plugins as plugins

#: Whether cda-jepa is installed, so `jepa` resolves.
HAVE_CDA_JEPA = importlib.util.find_spec("cda_jepa") is not None
needs_package = pytest.mark.skipif(not HAVE_CDA_JEPA, reason="needs the cda-jepa package")
needs_no_package = pytest.mark.skipif(HAVE_CDA_JEPA, reason="cda-jepa is installed")

PLUGIN, EXTENSION = plugins.PLUGIN, plugins.EXTENSION


@pytest.fixture
def plugin(monkeypatch):
    """The stand-in encoder package of test_encoder_plugins.py."""
    entry = plugins._FakeEntryPoint()
    monkeypatch.setattr(plugins.encoders, "installed_encoders", lambda: {PLUGIN: entry})
    yield entry
    for table in plugins.REGISTRY_TABLES:
        table.pop(PLUGIN, None)


FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "jepa_classes_98c4900.pkl")


def _load(name):
    with open(FIXTURE, "rb") as fh:
        return pickle.loads(pickle.load(fh)["classes"][name])


@needs_no_package
class TestAConfigSelectingItNamesThePackage:
    def test_the_lookup_names_cda_jepa(self):
        with pytest.raises(ValueError, match="moved to the cda-jepa"):
            known_encoder_type("jepa")

    def test_a_train_config_names_cda_jepa(self):
        from gym_continuousDoubleAuction.train.config import TrainConfig

        with pytest.raises(ValueError, match="cda-jepa"):
            TrainConfig(encoder_type="jepa", extensions_enabled=["jepa"])

    def test_it_is_not_offered(self):
        assert "jepa" not in selectable_encoder_types()
        assert {"mlp", "lstm", "transformer", "moe_transformer"} <= set(selectable_encoder_types())

    def test_every_moved_encoder_names_where_it_went(self):
        moved = getattr(encoders, "MOVED_ENCODERS", {})
        assert set(moved) == {"jepa"}
        assert "github.com/ChuaCheowHuan/cda_jepa" in moved["jepa"]


class TestNothingOfItShipsHere:
    def test_the_config_has_no_jepa_block(self):
        assert "jepa" not in group("train_config.json", "encoder")["encoder_specs"]

    def test_the_cli_defaults_have_no_pretrainer_block(self):
        with pytest.raises(KeyError):
            cli_default("cda_pretrain", "steps")

    def test_the_encoder_module_is_gone(self):
        assert (
            importlib.util.find_spec("gym_continuousDoubleAuction.train.model.encoders.jepa")
            is None
        )


class TestOldCheckpointClassesResolve:
    def test_the_fixture_covers_the_learner_module_and_tuned_adam(self):
        with open(FIXTURE, "rb") as fh:
            assert set(pickle.load(fh)["classes"]) == {"jepa", "jepa_tuned_adam", "jepa_module"}

    @needs_package
    def test_they_resolve_to_the_packages_classes(self):
        from cda_jepa.learner import CDAJEPALearner, JEPARLModule

        assert _load("jepa") is CDAJEPALearner
        assert _load("jepa_module") is JEPARLModule
        assert CDAJEPALearner in _load("jepa_tuned_adam").__mro__

    @pytest.mark.parametrize("name", ["jepa", "jepa_tuned_adam", "jepa_module"])
    def test_without_the_package_they_fail_naming_it(self, name, monkeypatch):
        monkeypatch.setitem(sys.modules, "cda_jepa", None)
        monkeypatch.setitem(sys.modules, "cda_jepa.learner", None)
        with pytest.raises(ImportError, match="cda-jepa"):
            _load(name)

    def test_the_shim_serves_nothing_else(self):
        from gym_continuousDoubleAuction.train.model import jepa_learner

        with pytest.raises(AttributeError):
            jepa_learner.TorchJEPAEncoder


class TestAnEncodersExtensionCountsAsEnabled:
    """`plugenc` stands in for `jepa`: an encoder the `plugext` extension provides."""

    @staticmethod
    def _fingerprint(monkeypatch, extensions_enabled):
        monkeypatch.setattr(
            checkpoint, "_encoder_fingerprint", lambda config: {"encoder_type": PLUGIN}
        )
        groups = {}
        if extensions_enabled is not None:
            groups["extensions"] = {"extensions_enabled": extensions_enabled}
        return checkpoint._config_fingerprint(SimpleNamespace(learner_config_dict=groups))

    def test_a_checkpoint_listing_no_extension_lists_the_encoders(self, plugin, monkeypatch):
        assert self._fingerprint(monkeypatch, None)["extensions_enabled"] == (EXTENSION,)

    def test_one_listing_it_already_is_unchanged(self, plugin, monkeypatch):
        assert self._fingerprint(monkeypatch, [EXTENSION])["extensions_enabled"] == (EXTENSION,)

    def test_other_extensions_are_kept(self, plugin, monkeypatch):
        assert self._fingerprint(monkeypatch, ["cbp"])["extensions_enabled"] == ("cbp", EXTENSION)

    def test_a_built_in_encoder_adds_nothing(self, monkeypatch):
        monkeypatch.setattr(
            checkpoint, "_encoder_fingerprint", lambda config: {"encoder_type": "transformer"}
        )
        fingerprint = checkpoint._config_fingerprint(SimpleNamespace(learner_config_dict={}))
        assert "extensions_enabled" not in fingerprint


class TestTheOldPretrainerCommand:
    def test_it_says_where_the_pretrainer_went(self, caplog):
        import logging

        from gym_continuousDoubleAuction.train.pretrain import __main__ as cli

        with caplog.at_level(logging.ERROR, logger="gym_continuousDoubleAuction.train.pretrain"):
            assert cli.main([]) == 2
        assert "python -m cda_jepa.pretrain" in caplog.text
