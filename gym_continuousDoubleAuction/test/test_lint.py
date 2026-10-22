"""The package is pyflakes-clean, and stays that way.

docs/29 S4-6 asked for a linter. The CI workflow cannot be changed from the
sessions that maintain this repository (the push credential has no `workflow`
scope - docs/17 §37.6), so the linter runs as a test: CI already installs the
`dev` extra and runs this directory, and a new unused import or undefined name
fails the same job a broken test would.

pyflakes rather than a style checker on purpose. Its findings are the ones that
are bugs or near-bugs - undefined names, unused imports and locals, redefined
names, `from x import *` hiding what is defined - and it has no opinion on line
length or quote style, so it can be made to pass once and kept passing without
a formatting pass over 18,000 lines. Every message it emits is a failure here;
there is no allowlist, because an allowlist is where the next real finding goes
to be ignored.
"""

import pathlib

from pyflakes import api as pyflakes_api
from pyflakes import reporter as pyflakes_reporter

import gym_continuousDoubleAuction

PACKAGE_DIR = pathlib.Path(gym_continuousDoubleAuction.__file__).resolve().parent


class _Collect:
    """A pyflakes reporter that keeps the messages instead of printing them."""

    def __init__(self):
        self.messages = []

    def unexpectedError(self, filename, msg):
        self.messages.append(f"{filename}: {msg}")

    def syntaxError(self, filename, msg, lineno, offset, text):
        self.messages.append(f"{filename}:{lineno}:{offset}: {msg}")

    def flake(self, message):
        self.messages.append(str(message))


def test_package_is_pyflakes_clean():
    collector = _Collect()
    # `Reporter` is the printing implementation; pyflakes only needs the three
    # methods above, so the collector stands in for it.
    assert isinstance(pyflakes_reporter.Reporter, type)
    count = pyflakes_api.checkRecursive([str(PACKAGE_DIR)], collector)
    assert count == 0, f"pyflakes reported {count} finding(s):\n" + "\n".join(collector.messages)


REPO_ROOT = PACKAGE_DIR.parent


def test_tools_and_skill_scripts_are_pyflakes_clean():
    """`tools/` and the skills' scripts are outside the package but run by contributors
    and agents, and an unused import there failed nothing (issue #268). Skipped where
    they are absent, as in an installed wheel."""
    import pytest

    targets = [
        str(p) for p in (REPO_ROOT / "tools", REPO_ROOT / ".claude" / "skills") if p.is_dir()
    ]
    if not targets:
        pytest.skip("tools/ and .claude/skills are not part of an installed package")
    collector = _Collect()
    count = pyflakes_api.checkRecursive(targets, collector)
    assert count == 0, f"pyflakes reported {count} finding(s):\n" + "\n".join(collector.messages)


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
