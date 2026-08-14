"""The package's logging configuration.

What matters here is not that logging works - the standard library's does -
but the three properties this package needs from it:

* the level is resolvable without an explicit argument, so a module that just
  calls `get_logger` in a Ray worker still comes up configured;
* the level travels through the environment, which is the only channel a
  remote EnvRunner shares with the driver;
* no module holds a literal - the format, the default level and the variable
  name all come out of `config/tunable_constants.json`.

See doc/11_logging_and_observability.md.
"""
import importlib
import json
import logging
import shutil

import pytest

from gym_continuousDoubleAuction import config_loader, logging_setup


@pytest.fixture(autouse=True)
def restore_logging():
    """Undo whatever a test did to the package logger and the environment."""
    root = logging.getLogger(logging_setup.ROOT_NAME)
    saved_handlers = list(root.handlers)
    saved_level = root.level
    saved_configured = logging_setup._configured

    yield

    root.handlers = saved_handlers
    root.setLevel(saved_level)
    logging_setup._configured = saved_configured
    config_loader.reload()


@pytest.fixture
def config_tree(tmp_path, monkeypatch):
    """A writable copy of `config/`, installed as the active config dir."""
    target = tmp_path / "config"
    shutil.copytree(config_loader.config_dir(), target)
    monkeypatch.setenv(config_loader.CONFIG_DIR_ENV_VAR, str(target))
    config_loader.reload()

    def edit(filename, mutate):
        path = target / filename
        with open(path) as fh:
            raw = json.load(fh)
        mutate(raw)
        with open(path, "w") as fh:
            json.dump(raw, fh)
        config_loader.reload()

    return edit


class TestLevelResolution:

    def test_explicit_argument_wins(self, monkeypatch):
        monkeypatch.setenv(logging_setup.level_env_var(), "ERROR")
        assert logging_setup.resolve_level("debug") == "DEBUG"

    def test_environment_beats_the_configured_default(self, monkeypatch):
        monkeypatch.setenv(logging_setup.level_env_var(), "warning")
        assert logging_setup.resolve_level() == "WARNING"

    def test_falls_back_to_the_config_file(self, monkeypatch, config_tree):
        monkeypatch.delenv(logging_setup.level_env_var(), raising=False)
        config_tree(
            "tunable_constants.json",
            lambda raw: raw["logging"].update(level="CRITICAL"),
        )
        assert logging_setup.resolve_level() == "CRITICAL"


class TestConfigure:

    def test_applies_the_level_to_the_package_logger(self, monkeypatch):
        monkeypatch.delenv(logging_setup.level_env_var(), raising=False)
        logging_setup.configure("WARNING", force=True)
        assert logging.getLogger(logging_setup.ROOT_NAME).level == logging.WARNING

    def test_exports_the_level_for_worker_processes(self, monkeypatch):
        """A remote EnvRunner never runs main(); the variable is how it learns."""
        monkeypatch.delenv(logging_setup.level_env_var(), raising=False)
        logging_setup.configure("DEBUG", force=True)

        import os
        assert os.environ[logging_setup.level_env_var()] == "DEBUG"

    def test_does_not_stack_handlers_when_reconfigured(self):
        logging_setup.configure("INFO", force=True)
        before = len(logging.getLogger(logging_setup.ROOT_NAME).handlers)
        logging_setup.configure("DEBUG", force=True)
        after = len(logging.getLogger(logging_setup.ROOT_NAME).handlers)
        assert before == after == 1

    def test_child_loggers_inherit_the_package_level(self, caplog):
        logging_setup.configure("INFO", force=True)
        logger = logging_setup.get_logger(
            f"{logging_setup.ROOT_NAME}.test_child"
        )

        with caplog.at_level(logging.INFO, logger=logging_setup.ROOT_NAME):
            logger.debug("dropped")
            logger.info("kept")

        assert "kept" in caplog.text
        assert "dropped" not in caplog.text


class TestNoLiteralsOfItsOwn:

    def test_format_comes_from_the_file(self, config_tree):
        config_tree(
            "tunable_constants.json",
            lambda raw: raw["logging"].update(format="CUSTOM %(message)s"),
        )
        logging_setup.configure("INFO", force=True)
        handler = logging.getLogger(logging_setup.ROOT_NAME).handlers[0]
        assert handler.formatter.format(
            logging.LogRecord("n", logging.INFO, "p", 1, "hello", None, None)
        ) == "CUSTOM hello"

    def test_env_var_name_comes_from_the_file(self, config_tree):
        config_tree(
            "tunable_constants.json",
            lambda raw: raw["logging"].update(env_var="CDA_OTHER_LEVEL"),
        )
        assert logging_setup.level_env_var() == "CDA_OTHER_LEVEL"


class TestPackageModulesUseIt:

    def test_no_module_calls_print(self):
        """envs/ and train/ report through the logger, not stdout.

        visualize/ is deliberately exempt: those are one-shot terminal tools
        whose output *is* the product. orderbook/test/ holds demo scripts.
        """
        import pathlib
        import re

        # A bare `print(` call: not `pprint(`, not `_config_fingerprint(`, not
        # `self.print_table(`, which are names that merely contain it.
        call = re.compile(r"(?<![\w.])print\s*\(")

        root = pathlib.Path(logging_setup.__file__).parent
        offenders = []
        for path in list((root / "envs").rglob("*.py")) + \
                list((root / "train").rglob("*.py")):
            if "orderbook/test" in path.as_posix():
                continue
            for number, line in enumerate(path.read_text().splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if call.search(stripped):
                    offenders.append(f"{path.relative_to(root)}:{number}")
        assert offenders == []
