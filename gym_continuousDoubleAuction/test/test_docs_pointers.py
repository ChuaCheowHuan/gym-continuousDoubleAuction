"""Tests for docs pointers.

Moved from `test_s4_docs_and_tooling.py` by issue #361; the class docstrings keep the
original issue numbers.
"""

import re

from gym_continuousDoubleAuction.envs.layout_version import check_layout_stamp, layout_stamp


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


class TestTheLayoutMismatchPointer:
    """#273: the refusal pointed at docs/05 section 1 ("Shape at a glance"); the text about
    checkpoints and layout stamps is section 10."""

    @staticmethod
    def _message():
        stamp = layout_stamp()
        stamp["observation_version"] = 1
        try:
            check_layout_stamp({"layout": stamp}, "ckpt")
        except ValueError as error:
            return str(error)
        raise AssertionError("a v1 stamp was accepted")

    def test_it_names_section_10(self):
        assert "docs/05 section 10" in self._message()

    def test_that_section_is_the_compatibility_one(self):
        number = re.search(r"docs/05 section (\d+)", self._message()).group(1)
        assert _section_title("docs/05_observation_space.md", number) == "Compatibility"


class TestDoc27DoesNotDescribeBuiltThingsAsMissing:
    """#267: doc 27 said the repository has no CLAUDE.md and kept full entries, with steps
    that differ from the skill, for skills that are built."""

    DOC = "docs/27_agent_skills.md"

    @staticmethod
    def _built_skills():
        return sorted(
            d
            for d in os.listdir(".claude/skills")
            if os.path.isfile(f".claude/skills/{d}/SKILL.md")
        )

    @staticmethod
    def _entry(text, name):
        start = text.index(f"### `{name}`")
        end = text.find("\n### ", start + 1)
        return text[start : end if end != -1 else None]

    def test_a_built_skill_links_to_its_skill_file(self):
        text = Path(self.DOC).read_text(encoding="utf-8")
        skills = self._built_skills()
        assert skills
        for name in skills:
            assert f".claude/skills/{name}/SKILL.md" in self._entry(text, name), name

    def test_and_carries_no_second_copy_of_its_steps(self):
        text = Path(self.DOC).read_text(encoding="utf-8")
        for name in self._built_skills():
            assert "**Steps.**" not in self._entry(text, name), name


class TestStaleCommentsAndNotes:
    """#251: three texts that contradicted the code they describe.

    The third, CBP's bias comment, moved to cda-cbp with the code
    (tests/test_moved_checks.py there).
    """

    def test_the_probe_note_describes_the_split_the_probe_makes(self):
        from gym_continuousDoubleAuction.config_loader import config_dir
        from gym_continuousDoubleAuction.train.probe.probe import MIN_GROUPS_TO_SPLIT_BY_GROUP

        note = json.loads(Path(config_dir() / "cli_defaults.json").read_text(encoding="utf-8"))[
            "cda_probe"
        ]["_note_corpus"]
        assert "the split is contiguous, so" not in note
        assert "by episode" in note and "contiguous" in note
        assert str(MIN_GROUPS_TO_SPLIT_BY_GROUP) in note or "three" in note

    def test_the_file_source_names_every_command_it_drives(self):
        from gym_continuousDoubleAuction.config_loader import config_dir

        data = json.loads(Path(config_dir() / "cli_defaults.json").read_text(encoding="utf-8"))
        for block in data.values():
            if isinstance(block, dict) and "_module" in block:
                command = block["_module"].split(".")[-1]
                assert command in data["_source"], command

    def test_the_mark_price_notes_give_the_fallback_order_mark_price_uses(self):
        """Both notes said a one-sided quote came before the last print. `mark_price` tries the
        last print first and takes a one-sided quote only when nothing has printed, because a
        lone quote as the mark is the manipulation S2-5 removed (`test_self_match.py`)."""
        from gym_continuousDoubleAuction.config_loader import config_dir

        for name in ("env_defaults.json", "train_config.json"):
            note = json.loads(Path(config_dir() / name).read_text(encoding="utf-8"))["environment"][
                "_note_mark_price_source"
            ]
            last, quote = note.index("last tape print"), note.index("one-sided quote")
            assert last < quote, name


class TestThePr308ReviewFindings:
    """#309-#312, from the review of PR #308: text that said something the code or the other
    documents do not."""

    def test_every_group_moved_into_docs29_says_whose_sections_it_cites(self):
        """#310: bare section numbers in moved text mean the source document's sections."""
        lines = Path("docs/29_fixed_issues.md").read_text(encoding="utf-8").split("\n")
        groups = [i for i, line in enumerate(lines) if line.startswith("### From ")]
        assert len(groups) > 10
        for i in groups:
            head = " ".join(lines[i : i + 6])
            assert "section numbers" in head and "this document" in head, lines[i]
