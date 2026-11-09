"""Tests for train module split.

Moved from `test_refactors.py` by issue #361; the class docstrings keep the
original issue numbers.
"""

import ast

import inspect

import os

import sys


import pytest


_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _stored(function):
    """The attribute names a function assigns on `self`."""
    tree = ast.parse(inspect.getsource(function).lstrip())
    return {
        n.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Attribute)
        and isinstance(n.ctx, ast.Store)
        and isinstance(n.value, ast.Name)
        and n.value.id == "self"
    }


def _depth(node, d=0):
    """Deepest control-flow nesting under `node`."""
    deepest = d
    for child in ast.iter_child_nodes(node):
        step = d + 1 if isinstance(child, (ast.If, ast.For, ast.While, ast.Try, ast.With)) else d
        deepest = max(deepest, _depth(child, step))
    return deepest


def _function(module, qualname):
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == qualname:
            return node
    raise AssertionError(qualname)


_MOVED = {
    "config": "generate_run_id _default TrainConfig ENV_NAME TRAIN_CONFIG_FILE PROGRESS_FILE "
    "_BROADCAST_TIMEOUT_S VF_EXPLAINED_VAR_KEY",
    "build": "register_env make_spaces _next_obs_connector OPTIMIZER_CONFIG_KEY "
    "_learner_class _learner_config_dict build_config build_algo log_module_sizes",
    "checkpoint": "CHECKPOINT_PREFIX CHECKPOINT_TMP_SUFFIX LEAGUE_STATE_FILE _is_checkpoint "
    "list_checkpoints save_checkpoint _prune_checkpoints warn_about_foreign_checkpoints "
    "algo_callback _write_league_state _read_league_state _reconcile_league_state "
    "STRUCTURAL_CONFIG_KEYS UNRESTORABLE_CONFIG_KEYS "
    "PRE_FEATURE_BEHAVIOUR _config_fingerprint _check_restored_config restore_candidates "
    "_fix_checkpoint_optimizer_betas",
    "progress": "NavConservationError nav_violations _check_nav_conservation _apply_iteration "
    "_broadcast_iteration _json_safe _append_progress vf_explained_var _log_iteration",
    "cli": "_parse_args configure_run_logging ray_logging_config main",
}


class TestTrainModuleIsSplit:
    """#254: `train/train.py` was 2,224 lines holding config, build, checkpointing, progress and CLI."""

    @pytest.mark.parametrize("module", sorted(_MOVED))
    def test_every_name_is_still_importable_from_train_train(self, module):
        import importlib

        train_mod = importlib.import_module("gym_continuousDoubleAuction.train.train")
        owner = importlib.import_module(f"gym_continuousDoubleAuction.train.{module}")
        for name in _MOVED[module].split():
            assert getattr(train_mod, name) is getattr(owner, name), name

    @pytest.mark.parametrize("module", sorted(set(_MOVED) - {"cli"}))
    def test_a_moved_definition_lives_in_its_new_module(self, module):
        import importlib

        owner = importlib.import_module(f"gym_continuousDoubleAuction.train.{module}")
        for name in _MOVED[module].split():
            obj = getattr(owner, name)
            if inspect.isfunction(obj) or inspect.isclass(obj):
                assert obj.__module__ == owner.__name__, name

    def test_train_py_holds_the_loop_and_the_re_exports_only(self):
        from gym_continuousDoubleAuction.train import train as train_mod

        tree = ast.parse(inspect.getsource(train_mod))
        defined = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        assert defined == {"train", "__getattr__"}

    def test_the_command_line_names_resolve_lazily_to_cli(self):
        from gym_continuousDoubleAuction.train import cli
        from gym_continuousDoubleAuction.train import train as train_mod

        assert train_mod.main is cli.main and train_mod._parse_args is cli._parse_args
        with pytest.raises(AttributeError, match="no attribute 'nope'"):
            _ = train_mod.nope

    @pytest.mark.parametrize("first", ["cli", "checkpoint", "progress"])
    def test_any_module_can_be_imported_first(self, first):
        """No import cycle: a fresh interpreter importing the module alone succeeds."""
        import subprocess

        result = subprocess.run(
            [sys.executable, "-I", "-c", f"import gym_continuousDoubleAuction.train.{first}"],
            capture_output=True,
            text=True,
            timeout=240,
            cwd=_REPO,
        )
        assert result.returncode == 0, result.stderr[-600:]

    def test_the_documented_command_still_runs(self):
        import subprocess

        result = subprocess.run(
            [sys.executable, "-m", "gym_continuousDoubleAuction.train.train", "--help"],
            capture_output=True,
            text=True,
            timeout=240,
            cwd=_REPO,
        )
        assert result.returncode == 0 and "--iters" in result.stdout

    def test_log_lines_keep_the_logger_name_they_always_had(self):
        from gym_continuousDoubleAuction.train import build, checkpoint, cli, progress

        for module in (build, checkpoint, cli, progress):
            assert module.logger.name == "gym_continuousDoubleAuction.train.train"
