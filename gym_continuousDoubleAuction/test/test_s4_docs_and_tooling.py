"""The S4-minor documentation and tooling issues (#249 #250 #251 #266 #267 #268 #273).

Where an issue is a pointer or a statement in prose, the test pins it against the thing it
points at, so it fails when either side moves.
"""
import re

from gym_continuousDoubleAuction.envs.layout_version import check_layout_stamp, layout_stamp


def _section_title(doc, number):
    for line in open(doc, encoding="utf-8"):
        match = re.match(rf"^## {number}\. (.+)$", line)
        if match:
            return match.group(1)
    return None


class TestTheLayoutMismatchPointer:
    """#273: the refusal pointed at doc/05 section 1 ("Shape at a glance"); the text about
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
        assert "doc/05 section 10" in self._message()

    def test_that_section_is_the_compatibility_one(self):
        number = re.search(r"doc/05 section (\d+)", self._message()).group(1)
        assert _section_title("doc/05_observation_space.md", number) == "Compatibility"


import os  # noqa: E402


class TestCiSmokeRunIsDescribedAsCiRunsIt:
    """#266: CLAUDE.md and doc 27 called `CDA_rand --steps 200 --agents 4` the CI smoke run;
    the workflow runs it with no arguments."""

    @staticmethod
    def _ci_command():
        lines = open(".github/workflows/tests.yml").read().splitlines()
        at = next(i for i, line in enumerate(lines) if "Random-agent env smoke run" in line)
        return next(l.split("run:", 1)[1].strip() for l in lines[at:] if "run:" in l)

    def test_the_workflow_runs_the_defaults(self):
        assert self._ci_command() == "python gym_continuousDoubleAuction/CDA_rand.py"

    def test_claude_md_quotes_the_command_ci_runs(self):
        assert self._ci_command() in open("CLAUDE.md").read()

    def test_doc_27_quotes_it_too(self):
        assert self._ci_command() in open("doc/27_agent_skills.md").read()

    def test_neither_calls_the_flagged_form_the_ci_run(self):
        for path in ("CLAUDE.md", "doc/27_agent_skills.md"):
            text = " ".join(open(path).read().split())
            assert "--steps 200 --agents 4` is the CI" not in text, path


class TestDoc27DoesNotDescribeBuiltThingsAsMissing:
    """#267: doc 27 said the repository has no CLAUDE.md and kept full entries, with steps
    that differ from the skill, for skills that are built."""

    DOC = "doc/27_agent_skills.md"

    def test_it_does_not_say_there_is_no_claude_md(self):
        assert "The repository has none" not in open(self.DOC).read()
        assert os.path.isfile("CLAUDE.md")

    @staticmethod
    def _built_skills():
        return sorted(d for d in os.listdir(".claude/skills")
                      if os.path.isfile(f".claude/skills/{d}/SKILL.md"))

    @staticmethod
    def _entry(text, name):
        start = text.index(f"### `{name}`")
        end = text.find("\n### ", start + 1)
        return text[start:end if end != -1 else None]

    def test_a_built_skill_links_to_its_skill_file(self):
        text = open(self.DOC).read()
        skills = self._built_skills()
        assert skills
        for name in skills:
            assert f".claude/skills/{name}/SKILL.md" in self._entry(text, name), name

    def test_and_carries_no_second_copy_of_its_steps(self):
        text = open(self.DOC).read()
        for name in self._built_skills():
            assert "**Steps.**" not in self._entry(text, name), name
