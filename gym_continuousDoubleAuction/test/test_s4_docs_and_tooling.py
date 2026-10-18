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
        assert self._ci_command() in open("docs/27_agent_skills.md").read()

    def test_neither_calls_the_flagged_form_the_ci_run(self):
        for path in ("CLAUDE.md", "docs/27_agent_skills.md"):
            text = " ".join(open(path).read().split())
            assert "--steps 200 --agents 4` is the CI" not in text, path


class TestDoc27DoesNotDescribeBuiltThingsAsMissing:
    """#267: doc 27 said the repository has no CLAUDE.md and kept full entries, with steps
    that differ from the skill, for skills that are built."""

    DOC = "docs/27_agent_skills.md"

    def test_it_does_not_say_there_is_no_claude_md(self):
        assert "The repository has none" not in open(self.DOC).read()
        assert os.path.isfile("CLAUDE.md")

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
        text = open(self.DOC).read()
        skills = self._built_skills()
        assert skills
        for name in skills:
            assert f".claude/skills/{name}/SKILL.md" in self._entry(text, name), name

    def test_and_carries_no_second_copy_of_its_steps(self):
        text = open(self.DOC).read()
        for name in self._built_skills():
            assert "**Steps.**" not in self._entry(text, name), name


class TestStaleCommentsAndNotes:
    """#251: three texts that contradicted the code they describe."""

    def test_the_cbp_comment_says_the_bias_is_zeroed_not_redrawn(self):
        import inspect
        from gym_continuousDoubleAuction.train.model import cbp

        source = inspect.getsource(cbp._reinitialise)
        assert "for weight and bias" not in source
        assert "bias is NOT drawn" in source

    def test_and_the_code_does_zero_it(self):
        import torch
        from gym_continuousDoubleAuction.train.model import cbp

        incoming, outgoing = torch.nn.Linear(4, 3), torch.nn.Linear(3, 2)
        with torch.no_grad():
            incoming.bias.fill_(7.0)
        layer = cbp.ReplaceableLayer(
            name="x", incoming=incoming, outgoing=[outgoing], activation=torch.nn.Tanh()
        )
        state = cbp.CBPLayerState.zeros(3)
        cbp._reinitialise(state, layer, 1, None, None, cbp.CBPConfig())
        assert float(incoming.bias[1]) == 0.0 and float(incoming.bias[0]) == 7.0

    def test_the_probe_note_describes_the_split_the_probe_makes(self):
        import json
        from gym_continuousDoubleAuction.config_loader import config_dir
        from gym_continuousDoubleAuction.train.probe.probe import MIN_GROUPS_TO_SPLIT_BY_GROUP

        note = json.load(open(config_dir() / "cli_defaults.json"))["cda_probe"]["_note_corpus"]
        assert "the split is contiguous, so" not in note
        assert "by episode" in note and "contiguous" in note
        assert str(MIN_GROUPS_TO_SPLIT_BY_GROUP) in note or "three" in note

    def test_the_file_source_names_every_command_it_drives(self):
        import json
        from gym_continuousDoubleAuction.config_loader import config_dir

        data = json.load(open(config_dir() / "cli_defaults.json"))
        for block in data.values():
            if isinstance(block, dict) and "_module" in block:
                command = block["_module"].split(".")[-1]
                assert command in data["_source"], command


import glob  # noqa: E402
import json  # noqa: E402

#: Documents that describe the present. The history files are excluded on purpose.
_HISTORY = {"16_verification_log.md", "17_changelog.md", "README_v1.md", "27_agent_skills.md"}
_ENTRY_POINTS = (
    "CDA_rand.py",
    "train/train.py",
    "train/probe/__main__.py",
    "train/pretrain/__main__.py",
    "train/compare.py",
    "train/evaluate.py",
    "train/export.py",
    "visualize/run_all.py",
)


def _docs_text():
    paths = ["README.md"] + sorted(
        p for p in glob.glob("docs/*.md") if os.path.basename(p) not in _HISTORY
    )
    return "\n".join(open(p, encoding="utf-8").read() for p in paths)


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
            for key in _leaves(json.load(open(path))):
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
            source = open(os.path.join(package, relative), encoding="utf-8").read()
            for flag in re.findall(
                r"add_argument\(\s*(?:\"-\w\",\s*)?\"(--[a-z][a-z0-9-]*)\"", source
            ):
                if not re.search(re.escape(flag) + r"(?![\w-])", text):
                    missing.append(f"{relative}:{flag}")
        assert not missing, f"CLI flags no document mentions (add them to docs/26): {missing}"

    def test_the_flag_scan_finds_flags_at_all(self):
        """A regex that silently matched nothing would make the check above vacuous."""
        source = open("gym_continuousDoubleAuction/train/compare.py", encoding="utf-8").read()
        found = re.findall(r"add_argument\(\s*(?:\"-\w\",\s*)?\"(--[a-z][a-z0-9-]*)\"", source)
        assert "--no-probe" in found and "--probe-seed" in found and len(found) > 10

    def test_an_undocumented_key_would_be_caught(self):
        assert not re.search(r"(?<![\w-])zz_not_a_real_key(?![\w])", _docs_text())
