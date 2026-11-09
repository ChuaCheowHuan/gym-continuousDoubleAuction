"""Tests for docs coverage.

Moved from `test_s4_docs_and_tooling.py` by issue #361; the class docstrings keep the
original issue numbers.
"""

import re


def _section_title(doc, number):
    for line in Path(doc).read_text(encoding="utf-8").splitlines():
        match = re.match(rf"^## {number}\. (.+)$", line)
        if match:
            return match.group(1)
    return None


import os  # noqa: E402

import glob  # noqa: E402

import json  # noqa: E402
from pathlib import Path

_HISTORY = {"16_verification_log.md", "17_changelog.md", "27_agent_skills.md"}

_ENTRY_POINTS = (
    "CDA_rand.py",
    "train/train.py",
    "train/probe/__main__.py",
    "train/compare.py",
    "train/evaluate.py",
    "train/export.py",
    "visualize/run_all.py",
)


def _docs_text():
    paths = ["README.md"] + sorted(
        p for p in glob.glob("docs/*.md") if os.path.basename(p) not in _HISTORY
    )
    return "\n".join(Path(p).read_text(encoding="utf-8") for p in paths)


def _leaves(tree, prefix=""):
    for key, value in tree.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict) and value:
            yield from _leaves(value, prefix + key + ".")
        else:
            yield prefix + key


class TestEveryConfigKeyAndFlagIsDocumented:
    """#249 and #250: 18 config keys and 9 CLI flags appeared in no document, and nothing
    would have said so when the next one was added. Both are static, so they cost nothing."""

    def test_every_config_key_is_mentioned_in_some_document(self):
        text = _docs_text()
        missing = []
        for path in sorted(glob.glob("config/*.json")):
            for key in _leaves(json.loads(Path(path)).read_text(encoding="utf-8")):
                leaf = key.split(".")[-1]
                if not re.search(r"(?<![\w-])" + re.escape(leaf) + r"(?![\w])", text):
                    missing.append(f"{os.path.basename(path)}:{key}")
        assert not missing, (
            "config keys no document mentions (add them to docs/18 or the doc that owns "
            f"them): {missing}"
        )

    def test_every_cli_flag_is_mentioned_in_some_document(self):
        text = _docs_text()
        package = "gym_continuousDoubleAuction"
        missing = []
        for relative in _ENTRY_POINTS:
            source = Path(os.path.join(package, relative)).read_text(encoding="utf-8")
            for flag in re.findall(
                r"add_argument\(\s*(?:\"-\w\",\s*)?\"(--[a-z][a-z0-9-]*)\"", source
            ):
                if not re.search(re.escape(flag) + r"(?![\w-])", text):
                    missing.append(f"{relative}:{flag}")
        assert not missing, f"CLI flags no document mentions (add them to docs/26): {missing}"

    def test_the_flag_scan_finds_flags_at_all(self):
        """A regex that silently matched nothing would make the check above vacuous."""
        source = Path("gym_continuousDoubleAuction/train/compare.py").read_text(encoding="utf-8")
        found = re.findall(r"add_argument\(\s*(?:\"-\w\",\s*)?\"(--[a-z][a-z0-9-]*)\"", source)
        assert "--no-probe" in found and "--probe-seed" in found and len(found) > 10

    def test_an_undocumented_key_would_be_caught(self):
        assert not re.search(r"(?<![\w-])zz_not_a_real_key(?![\w])", _docs_text())
