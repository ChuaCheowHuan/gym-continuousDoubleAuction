"""The documentation's links and anchors, as a test (issue #268).

CLAUDE.md rule 7 says `tools/check_links.py` must report 0 broken links, and nothing
ran it: a broken link or a renamed heading was caught by whoever remembered. The CI
workflow cannot be edited from the sessions that maintain this repository (no
`workflow` scope, docs/17 §37.6), so it runs here, in the job that already runs the
suite - the same arrangement as `test_lint.py`.
"""

import pathlib
import subprocess
import sys

import pytest

import gym_continuousDoubleAuction

REPO_ROOT = pathlib.Path(gym_continuousDoubleAuction.__file__).resolve().parent.parent
CHECKER = REPO_ROOT / "tools" / "check_links.py"

pytestmark = pytest.mark.skipif(
    not CHECKER.is_file(), reason="tools/check_links.py is not part of an installed package"
)


def _run(root):
    return subprocess.run([sys.executable, str(CHECKER), str(root)], capture_output=True, text=True)


def test_the_repository_has_no_broken_links():
    out = _run(REPO_ROOT)
    assert out.returncode == 0, f"broken links:\n{out.stdout}"
    assert "TOTAL 0" in out.stderr


class TestTheCheckerItself:
    """Both directions, on a throwaway tree, so a checker that reported nothing for
    every input could not pass the test above."""

    @staticmethod
    def _tree(tmp_path, readme, **extra):
        (tmp_path / "docs").mkdir()
        (tmp_path / "README.md").write_text(readme)
        (tmp_path / "docs" / "a.md").write_text("# Alpha\n\n## Beta section\n")
        for name, text in extra.items():
            (tmp_path / name.replace("__", "/")).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / name.replace("__", "/")).write_text(text)
        return tmp_path

    def test_a_good_link_and_anchor_pass(self, tmp_path):
        root = self._tree(tmp_path, "[a](docs/a.md) [b](docs/a.md#beta-section)\n")
        assert _run(root).returncode == 0

    def test_a_missing_file_is_reported(self, tmp_path):
        out = _run(self._tree(tmp_path, "[x](docs/nope.md)\n"))
        assert out.returncode == 1 and "missing docs/nope.md" in out.stdout

    def test_a_missing_anchor_is_reported(self, tmp_path):
        out = _run(self._tree(tmp_path, "[x](docs/a.md#gone)\n"))
        assert out.returncode == 1 and "anchor docs/a.md#gone" in out.stdout

    def test_claude_md_is_checked(self, tmp_path):
        root = self._tree(tmp_path, "ok\n", **{"CLAUDE.md": "[x](docs/nope.md)\n"})
        out = _run(root)
        assert out.returncode == 1 and "CLAUDE.md" in out.stdout

    def test_contributing_md_is_checked(self, tmp_path):
        root = self._tree(tmp_path, "ok\n", **{"CONTRIBUTING.md": "[x](docs/nope.md)\n"})
        assert "CONTRIBUTING.md" in _run(root).stdout

    def test_a_skill_file_is_checked(self, tmp_path):
        root = self._tree(
            tmp_path, "ok\n", **{".claude__skills__demo__SKILL.md": "[x](../../../docs/nope.md)\n"}
        )
        out = _run(root)
        assert out.returncode == 1 and "SKILL.md" in out.stdout

    def test_a_tree_without_the_optional_files_is_fine(self, tmp_path):
        assert _run(self._tree(tmp_path, "ok\n")).returncode == 0
