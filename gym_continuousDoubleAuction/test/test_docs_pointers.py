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


from pathlib import Path

_HISTORY = {"16_verification_log.md", "17_changelog.md", "27_agent_skills.md"}


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
