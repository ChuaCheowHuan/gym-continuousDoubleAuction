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
        [sys.executable, "-m", "mypy"], cwd=REPO_ROOT,
        capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, (
        "mypy found problems in gym_continuousDoubleAuction/envs "
        "(install the dev extra: pip install -e '.[dev]'):\n" + result.stdout[-3000:]
        + result.stderr[-500:])
