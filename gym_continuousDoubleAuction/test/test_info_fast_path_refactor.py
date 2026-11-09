"""Tests for info fast path refactor.

Moved from `test_refactors.py` by issue #361; the class docstrings keep the
original issue numbers.
"""

import ast

import inspect

import os
from typing import ClassVar

import numpy as np

import pytest


from gym_continuousDoubleAuction.envs.exchg import info_helper

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


class TestPlainConvertsWithoutTheNeedlessCalls:
    """#258: `_plain` made 127,200 calls per 300 steps, nearly all on values that were plain."""

    @staticmethod
    def _reference(value):
        """The conversion as it was written before: recursion into every element."""
        if isinstance(value, np.ndarray):
            if value.ndim == 0:
                return value.item()
            return [TestPlainConvertsWithoutTheNeedlessCalls._reference(v) for v in value.tolist()]
        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, dict):
            return {
                k: TestPlainConvertsWithoutTheNeedlessCalls._reference(v) for k, v in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [TestPlainConvertsWithoutTheNeedlessCalls._reference(v) for v in value]
        return value

    CASES: ClassVar[list] = [
        np.arange(6, dtype=np.float32).reshape(2, 3),
        np.array(3),
        np.array([1.5]),
        np.int64(4),
        np.float32(2.5),
        np.bool_(True),
        (np.int32(1), np.array([0.25], dtype=np.float32), 7),
        {"a": np.int64(2), "b": [np.float64(1.0), np.array([1, 2])], "c": {"d": np.array(5)}},
        {"s": "x", "n": None, "t": True, "i": 3, "f": 0.5, "l": [], "e": {}},
        [],
    ]

    @pytest.mark.parametrize("case", range(len(CASES)))
    def test_same_output_as_the_recursive_version(self, case):
        value = self.CASES[case]
        got, want = info_helper._plain(value), self._reference(value)
        assert got == want and type(got) is type(want)

    def test_a_dict_of_plain_fields_costs_one_call(self, monkeypatch):
        calls = []
        real = info_helper._plain
        monkeypatch.setattr(info_helper, "_plain", lambda v: (calls.append(1), real(v))[1])
        info_helper._plain({f"k{i}": i for i in range(40)})
        assert len(calls) == 1

    def test_an_array_is_one_tolist_with_no_recursion(self, monkeypatch):
        calls = []
        real = info_helper._plain
        monkeypatch.setattr(info_helper, "_plain", lambda v: (calls.append(1), real(v))[1])
        info_helper._plain(np.zeros((4, 5)))
        assert len(calls) == 1

    def test_a_numpy_value_inside_a_dict_is_still_converted(self):
        out = info_helper._plain({"a": np.int64(1), "b": np.array([2.0])})
        assert type(out["a"]) is int and out["b"] == [2.0]
