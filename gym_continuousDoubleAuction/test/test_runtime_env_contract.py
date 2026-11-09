"""Tests for runtime env contract.

Moved from `test_open_bug_fixes.py` by issue #361; the class docstrings keep the
original issue numbers.
"""

import pytest


class TestEnvVarsContractIsRayInit:
    """#244: `runtime` said `apply_env_vars()` had to run before ray is imported,
    while the entry points import ray at module scope and call it in `main()`.

    The only variable configured is read when Ray's memory monitor is
    constructed, not at import, so the contract that holds - and that is pinned
    here - is the order that matters: exported before `ray.init`, in every entry
    point that starts Ray.
    """

    @pytest.mark.parametrize(
        "module",
        [
            "gym_continuousDoubleAuction.train.train",
            "gym_continuousDoubleAuction.train.evaluate",
            "gym_continuousDoubleAuction.train.compare",
        ],
    )
    def test_the_entry_point_exports_before_it_starts_ray(self, module):
        import importlib
        import inspect

        source = inspect.getsource(importlib.import_module(module).main)
        assert "apply_env_vars()" in source and "ray.init(" in source
        assert source.index("apply_env_vars()") < source.index("ray.init(")

    def test_the_configured_variable_is_not_read_at_ray_import(self):
        """The fact the corrected contract rests on, checked against the installed
        Ray: if a Ray upgrade starts reading it at import, this fails and the
        call has to move ahead of the imports."""
        import inspect
        from ray._private import memory_monitor

        source = inspect.getsource(memory_monitor)
        first_function = source.index("\n    def ")
        assert "RAY_DEBUG_DISABLE_MEMORY_MONITOR" in source
        assert "RAY_DEBUG_DISABLE_MEMORY_MONITOR" not in source[:first_function]
        from gym_continuousDoubleAuction.config_loader import constants

        assert set(constants("runtime_env_vars")) - {"_source", "_note"} == {
            "RAY_DEBUG_DISABLE_MEMORY_MONITOR"
        }
