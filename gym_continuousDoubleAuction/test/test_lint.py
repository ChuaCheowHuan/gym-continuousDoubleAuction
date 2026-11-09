"""The package, `tools/` and the skill scripts are ruff-clean, and stay that way.

docs/29 S4-6 asked for a linter. It runs as a test: CI already installs the
`dev` extra and runs this directory, and a finding fails the same job a broken
test would. Issue #360 extended it from pyflakes to the curated rule set in
`pyproject.toml` - bugbear, unclosed files, mutable class attributes and
implicit `Optional` - because pyflakes alone missed every one of those.

The rule set is `[tool.ruff.lint] select`; `ruff format --check` is separate
(`test_types.py`). Every message is a failure here: there is no allowlist,
because an allowlist is where the next real finding goes to be ignored.
"""

import pathlib
import subprocess
import sys

import gym_continuousDoubleAuction

PACKAGE_DIR = pathlib.Path(gym_continuousDoubleAuction.__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent


def _lint(targets):
    """Run `ruff check` over `targets` from the repository root, so it reads pyproject.toml."""
    return subprocess.run(
        [sys.executable, "-m", "ruff", "check", *[str(t) for t in targets]],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )


def _assert_clean(result):
    assert result.returncode == 0, (
        "ruff reported findings (run `ruff check .`; install the dev extra if ruff is "
        f"missing: pip install -e '.[dev]'):\n{result.stdout[-4000:]}{result.stderr[-1000:]}"
    )


def test_the_package_is_ruff_clean():
    _assert_clean(_lint([PACKAGE_DIR]))


def test_tools_and_skill_scripts_are_ruff_clean():
    """`tools/` and the skills' scripts are outside the package but run by contributors
    and agents, and an unused import there failed nothing (issue #268). Skipped where
    they are absent, as in an installed wheel."""
    import pytest

    targets = [p for p in (REPO_ROOT / "tools", REPO_ROOT / ".claude" / "skills") if p.is_dir()]
    if not targets:
        pytest.skip("tools/ and .claude/skills are not part of an installed package")
    _assert_clean(_lint(targets))


def test_the_lint_reaches_the_directories_it_claims_to():
    """A target list that silently resolved to nothing would make the test above pass."""
    assert (REPO_ROOT / "tools" / "check_links.py").is_file() or not (REPO_ROOT / "tools").exists()
    assert (
        list((REPO_ROOT / ".claude" / "skills").glob("*/scripts/*.py"))
        or not (REPO_ROOT / ".claude" / "skills").exists()
    )


def test_no_test_puts_a_working_directory_relative_path_on_sys_path():
    """`sys.path.append("../")` is relative to where pytest runs, not to the file:
    from the repository root it adds the repository's parent folder, where a
    sibling `cda_cbp` checkout then shadows the installed extension as a
    namespace package (issue #341). The package is installed, so a test needs
    no path of its own."""
    import ast

    found = []
    for path in sorted((PACKAGE_DIR / "test").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("append", "insert")
                and ast.unparse(node.func.value) == "sys.path"
            ):
                continue
            literals = [a.value for a in node.args if isinstance(a, ast.Constant)]
            if any(isinstance(v, str) and not v.startswith("/") for v in literals):
                found.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    assert not found, "relative sys.path entries:\n" + "\n".join(found)
