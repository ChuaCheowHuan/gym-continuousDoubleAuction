"""The package is pyflakes-clean, and stays that way.

doc/15 S4-6 asked for a linter. The CI workflow cannot be changed from the
sessions that maintain this repository (the push credential has no `workflow`
scope - doc/17 §37.6), so the linter runs as a test: CI already installs the
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
