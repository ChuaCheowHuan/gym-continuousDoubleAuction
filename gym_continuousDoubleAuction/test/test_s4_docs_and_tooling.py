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


class TestCiRunsTheIntegrationSuiteOnce:
    """CI's first step runs `pytest gym_continuousDoubleAuction/test` and its third runs
    `pytest gym_continuousDoubleAuction/test/integration`. Without a default ignore the first
    step collected the integration suite as well, so CI built every real Algorithm twice."""

    INTEGRATION = "gym_continuousDoubleAuction/test/integration"

    @staticmethod
    def _collected(*args):
        import subprocess
        import sys

        out = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", *args],
            capture_output=True,
            text=True,
            timeout=300,
        ).stdout
        return [line for line in out.splitlines() if "::" in line]

    def test_the_default_run_leaves_the_integration_suite_out(self):
        collected = self._collected("gym_continuousDoubleAuction/test")
        assert collected, "nothing collected"
        assert not [t for t in collected if t.startswith(self.INTEGRATION)]


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
    """#251: three texts that contradicted the code they describe.

    The third, CBP's bias comment, moved to cda-cbp with the code
    (tests/test_moved_checks.py there).
    """

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

    def test_the_mark_price_notes_give_the_fallback_order_mark_price_uses(self):
        """Both notes said a one-sided quote came before the last print. `mark_price` tries the
        last print first and takes a one-sided quote only when nothing has printed, because a
        lone quote as the mark is the manipulation S2-5 removed (`test_self_match.py`)."""
        import json
        from gym_continuousDoubleAuction.config_loader import config_dir

        for name in ("env_defaults.json", "train_config.json"):
            note = json.load(open(config_dir() / name))["environment"]["_note_mark_price_source"]
            last, quote = note.index("last tape print"), note.index("one-sided quote")
            assert last < quote, name


import glob  # noqa: E402
import json  # noqa: E402

#: Documents that describe the present. The history files are excluded on purpose.
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


class TestThePr308ReviewFindings:
    """#309-#312, from the review of PR #308: text that said something the code or the other
    documents do not."""

    def test_every_group_moved_into_docs29_says_whose_sections_it_cites(self):
        """#310: bare section numbers in moved text mean the source document's sections."""
        lines = open("docs/29_fixed_issues.md", encoding="utf-8").read().split("\n")
        groups = [i for i, line in enumerate(lines) if line.startswith("### From ")]
        assert len(groups) > 10
        for i in groups:
            head = " ".join(lines[i : i + 6])
            assert "section numbers" in head and "this document" in head, lines[i]


class TestThe20261108ReviewHardening:
    """#357/#362-#365: the security items that are configuration and prose."""

    @staticmethod
    def _workflow():
        return open(".github/workflows/tests.yml", encoding="utf-8").read()

    def test_the_token_is_read_only_and_every_action_is_sha_pinned(self):
        workflow = self._workflow()
        assert re.search(r"^permissions:\n  contents: read$", workflow, re.M)
        uses = re.findall(r"^ +- uses: +(\S+)(.*)$", workflow, re.M)
        assert uses, "no `uses:` steps found"
        for action, tail in uses:
            assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", action), action
            assert re.search(r"#\s*v\d+", tail), f"{action} has no tag comment"

    def test_dependabot_keeps_the_action_pins_current(self):
        dependabot = open(".github/dependabot.yml", encoding="utf-8").read()
        assert "github-actions" in dependabot
        assert re.search(r"interval:\s*\"?weekly", dependabot)

    def test_ci_audits_the_lockfile(self):
        workflow = self._workflow()
        assert "pip-audit -r requirements-lock.txt --no-deps --disable-pip" in workflow

    def test_the_docker_usage_keeps_jupyter_local_and_warns_about_the_socket(self):
        ml = open("docker/ml/dockerfile_ray_torch", encoding="utf-8").read()
        assert "-p 127.0.0.1:8888:8888" in ml
        assert "root-equivalent" in ml or "loopback" in ml
        gemini = open("docker/gemini/dockerfile", encoding="utf-8").read()
        assert "root-equivalent" in gemini
        docs = open("docs/19_docker.md", encoding="utf-8").read()
        assert "-p 127.0.0.1:8888:8888" in docs

    def test_every_checkpoint_loader_warns_that_it_unpickles_code(self):
        for relative in (
            "gym_continuousDoubleAuction/train/cli.py",
            "gym_continuousDoubleAuction/train/evaluate.py",
            "gym_continuousDoubleAuction/train/export.py",
            "gym_continuousDoubleAuction/train/probe/__main__.py",
        ):
            source = open(relative, encoding="utf-8").read()
            assert "produced or trust" in source, relative
        for relative in ("docs/18_configuration.md", "docs/26_runbook.md"):
            text = open(relative, encoding="utf-8").read()
            assert "weights_only=True" in text, relative
