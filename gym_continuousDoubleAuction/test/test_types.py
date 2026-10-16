"""The env package type-checks clean (issue #148, #152).

Most of what mypy used to report on `envs/` was one finding: a mixin reading an attribute that
another class creates. Those are declared now (`SharedState`, `AccountState`), so what is left
is real, and the package is held at zero.
"""

import subprocess
import sys

from gym_continuousDoubleAuction.test.test_lint import REPO_ROOT


def test_envs_is_mypy_clean():
    result = subprocess.run(
        [sys.executable, "-m", "mypy"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=300
    )
    assert result.returncode == 0, (
        "mypy found problems in gym_continuousDoubleAuction/envs "
        "(install the dev extra: pip install -e '.[dev]'):\n"
        + result.stdout[-3000:]
        + result.stderr[-500:]
    )


def test_the_coverage_floor_is_configured():
    """`pytest --cov` fails below `fail_under` (issue #148); keep the floor from being dropped."""
    import tomllib

    with open(REPO_ROOT / "pyproject.toml", "rb") as fh:
        config = tomllib.load(fh)
    floor = config["tool"]["coverage"]["report"]["fail_under"]
    assert 80 <= floor < 100
    assert config["tool"]["coverage"]["run"]["branch"] is True


def test_the_tree_is_formatted():
    """`ruff format --check` finds nothing to change (issue #148).

    The tree was formatted in one pass; this keeps it from drifting back. The ruff version is
    pinned in the dev extra because formatter output can change between releases.
    """
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--check", "."],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, (
        "ruff would reformat these files (run `ruff format .`; install the dev extra if "
        "ruff is missing: pip install -e '.[dev]'):\n"
        + result.stdout[-2000:]
        + result.stderr[-500:]
    )
