"""Tests for ci configuration.

Moved from `test_s4_docs_and_tooling.py` by issue #361; the class docstrings keep the
original issue numbers.
"""

import re


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


class TestCiSmokeRunIsDescribedAsCiRunsIt:
    """#266: CLAUDE.md and doc 27 called `CDA_rand --steps 200 --agents 4` the CI smoke run;
    the workflow runs it with no arguments."""

    @staticmethod
    def _ci_command():
        lines = Path(".github/workflows/tests.yml").read_text(encoding="utf-8").splitlines()
        at = next(i for i, line in enumerate(lines) if "Random-agent env smoke run" in line)
        return next(l.split("run:", 1)[1].strip() for l in lines[at:] if "run:" in l)

    def test_the_workflow_runs_the_defaults(self):
        assert self._ci_command() == "python gym_continuousDoubleAuction/CDA_rand.py"

    def test_claude_md_quotes_the_command_ci_runs(self):
        assert self._ci_command() in Path("CLAUDE.md").read_text(encoding="utf-8")


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


class TestThe20261108ReviewHardening:
    """#357/#362-#365: the security items that are configuration and prose."""

    @staticmethod
    def _workflow():
        return Path(".github/workflows/tests.yml").read_text(encoding="utf-8")

    def test_the_token_is_read_only_and_every_action_is_sha_pinned(self):
        workflow = self._workflow()
        assert re.search(r"^permissions:\n  contents: read$", workflow, re.M)
        uses = re.findall(r"^ +- uses: +(\S+)(.*)$", workflow, re.M)
        assert uses, "no `uses:` steps found"
        for action, tail in uses:
            assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", action), action
            assert re.search(r"#\s*v\d+", tail), f"{action} has no tag comment"

    def test_dependabot_keeps_the_action_pins_current(self):
        dependabot = Path(".github/dependabot.yml").read_text(encoding="utf-8")
        assert "github-actions" in dependabot
        assert re.search(r"interval:\s*\"?weekly", dependabot)

    def test_ci_audits_the_lockfile(self):
        workflow = self._workflow()
        assert "pip-audit -r requirements-lock.txt --no-deps --disable-pip" in workflow

    def test_the_docker_usage_keeps_jupyter_local_and_warns_about_the_socket(self):
        ml = Path("docker/ml/dockerfile_ray_torch").read_text(encoding="utf-8")
        assert "-p 127.0.0.1:8888:8888" in ml
        assert "root-equivalent" in ml or "loopback" in ml
        gemini = Path("docker/gemini/dockerfile").read_text(encoding="utf-8")
        assert "root-equivalent" in gemini
        docs = Path("docs/19_docker.md").read_text(encoding="utf-8")
        assert "-p 127.0.0.1:8888:8888" in docs

    def test_every_checkpoint_loader_warns_that_it_unpickles_code(self):
        for relative in (
            "gym_continuousDoubleAuction/train/cli.py",
            "gym_continuousDoubleAuction/train/evaluate.py",
            "gym_continuousDoubleAuction/train/export.py",
            "gym_continuousDoubleAuction/train/probe/__main__.py",
        ):
            source = Path(relative).read_text(encoding="utf-8")
            assert "produced or trust" in source, relative
        for relative in ("docs/18_configuration.md", "docs/26_runbook.md"):
            text = Path(relative).read_text(encoding="utf-8")
            assert "weights_only=True" in text, relative
