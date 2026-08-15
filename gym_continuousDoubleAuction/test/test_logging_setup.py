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
    saved_log_file = logging_setup._log_file_path
    # configure(log_dir=...) exports the directory for worker processes. Left
    # set, the next test to call configure() would resolve it from the
    # environment and write a file into a tmp_path that no longer exists.
    import os as _os
    saved_dir_var = _os.environ.get(logging_setup.log_dir_env_var())

    yield

    for handler in list(root.handlers):
        if handler not in saved_handlers:
            handler.close()   # release the run log before tmp_path is removed
    root.handlers = saved_handlers
    root.setLevel(saved_level)
    logging_setup._configured = saved_configured
    logging_setup._log_file_path = saved_log_file
    logging_setup.set_iteration(None)
    if saved_dir_var is None:
        _os.environ.pop(logging_setup.log_dir_env_var(), None)
    else:
        _os.environ[logging_setup.log_dir_env_var()] = saved_dir_var
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


class TestRunLogFile:
    """The log survives the terminal it was printed in.

    Until this existed the package logged only to stdout, so the narrative a
    run is diagnosed from - the per-episode NAV tables, the ERROR preceding a
    strict_nav_check raise - lived in scrollback, while progress.jsonl kept the
    numbers. doc/17 17 records two GPU runs diagnosed exactly that way.
    """

    def test_a_run_log_is_written_beside_the_metrics(self, tmp_path):
        logging_setup.configure("INFO", log_dir=str(tmp_path), force=True)
        logging_setup.get_logger("gym_continuousDoubleAuction.t").info("hello")

        path = tmp_path / "run.log"
        assert path.exists()
        assert "hello" in path.read_text()
        assert logging_setup.log_file_path() == str(path)

    def test_the_file_gets_what_stdout_gets(self, tmp_path, capsys):
        logging_setup.configure("INFO", log_dir=str(tmp_path), force=True)
        logging_setup.get_logger("gym_continuousDoubleAuction.t").warning("both")

        assert "both" in capsys.readouterr().err
        assert "both" in (tmp_path / "run.log").read_text()

    def test_no_file_without_a_log_dir(self, tmp_path):
        """Every env runner takes this path: RotatingFileHandler is not safe
        across processes, so only the driver passes a directory."""
        logging_setup.configure("INFO", force=True)
        logging_setup.get_logger("gym_continuousDoubleAuction.t").info("stdout only")

        assert logging_setup.log_file_path() is None
        assert not list(tmp_path.glob("*.log*"))

    def test_rotation_bounds_the_file(self, tmp_path, config_tree):
        """doc/11 3 lists unbounded growth as a persistence problem; a run log
        that fills the disk would be a new instance of it."""
        config_tree("tunable_constants.json", lambda raw: raw["logging"].update(
            {"file_max_bytes": 2048, "file_backup_count": 2}
        ))
        logging_setup.configure("INFO", log_dir=str(tmp_path), force=True)
        logger = logging_setup.get_logger("gym_continuousDoubleAuction.t")

        for i in range(400):
            logger.info("filling the log with line %s of padding", i)

        logs = sorted(p.name for p in tmp_path.glob("run.log*"))
        assert logs, "nothing was written"
        # 1 live file + at most backup_count rotated ones, and none oversized
        assert len(logs) <= 3, logs
        for name in logs:
            assert (tmp_path / name).stat().st_size < 8192, name

    def test_an_empty_file_name_disables_it(self, tmp_path, config_tree):
        config_tree("tunable_constants.json",
                    lambda raw: raw["logging"].update({"file_name": ""}))
        logging_setup.configure("INFO", log_dir=str(tmp_path), force=True)
        logging_setup.get_logger("gym_continuousDoubleAuction.t").info("nowhere")

        assert logging_setup.log_file_path() is None
        assert not list(tmp_path.glob("*.log*"))

    def test_an_unwritable_destination_warns_and_keeps_training(self, tmp_path):
        """Instrumentation must not take down a run that is otherwise fine -
        the same rule _append_progress follows."""
        blocked = tmp_path / "not-a-dir"
        blocked.write_text("this is a file, so it cannot contain run.log")

        logging_setup.configure("INFO", log_dir=str(blocked), force=True)

        assert logging_setup.log_file_path() is None
        logging_setup.get_logger("gym_continuousDoubleAuction.t").info("still up")

    def test_the_file_name_and_bounds_come_from_the_file(self, tmp_path, config_tree):
        """No literal copy in Python - the property doc/18 claims."""
        config_tree("tunable_constants.json", lambda raw: raw["logging"].update(
            {"file_name": "renamed.log"}
        ))
        logging_setup.configure("INFO", log_dir=str(tmp_path), force=True)
        logging_setup.get_logger("gym_continuousDoubleAuction.t").info("x")

        assert (tmp_path / "renamed.log").exists()


class TestIterationTag:
    """A log line can be joined to its progress.jsonl row."""

    def test_lines_carry_the_iteration(self, tmp_path):
        logging_setup.configure("INFO", log_dir=str(tmp_path), force=True)
        logger = logging_setup.get_logger("gym_continuousDoubleAuction.t")

        logging_setup.set_iteration(12)
        logger.info("inside twelve")

        assert "iter=12" in (tmp_path / "run.log").read_text()

    def test_an_unknown_iteration_is_a_dash(self, tmp_path):
        """Every env runner is in this state. It must not be '0', which is a
        real iteration, and must not blow up formatting."""
        logging_setup.configure("INFO", log_dir=str(tmp_path), force=True)
        logging_setup.get_logger("gym_continuousDoubleAuction.t").info("no idea")

        assert "iter=-" in (tmp_path / "run.log").read_text()

    def test_clearing_it_stops_the_tagging(self, tmp_path):
        logging_setup.configure("INFO", log_dir=str(tmp_path), force=True)
        logger = logging_setup.get_logger("gym_continuousDoubleAuction.t")

        logging_setup.set_iteration(3)
        logger.info("during")
        logging_setup.set_iteration(None)
        logger.info("after")

        lines = (tmp_path / "run.log").read_text().splitlines()
        assert "iter=3" in lines[0]
        assert "iter=-" in lines[1]

    def test_a_child_module_logger_is_tagged_too(self, tmp_path):
        """The filter is on the handler, not the logger: a filter on the
        package logger would miss everything propagating up from a child."""
        logging_setup.configure("INFO", log_dir=str(tmp_path), force=True)
        logging_setup.set_iteration(5)

        logging_setup.get_logger(
            "gym_continuousDoubleAuction.envs.exchg.info_helper"
        ).info("from a child")

        assert "iter=5" in (tmp_path / "run.log").read_text()

    def test_current_iteration_reports_it(self):
        logging_setup.set_iteration(9)
        assert logging_setup.current_iteration() == 9
        logging_setup.set_iteration(None)
        assert logging_setup.current_iteration() is None


class TestTimestampsAreOrderable:

    def test_the_date_is_in_the_stamp(self, tmp_path):
        """A training run outlasts a day; a time-only stamp cannot be ordered
        across midnight, nor joined to anything dated."""
        import re

        logging_setup.configure("INFO", log_dir=str(tmp_path), force=True)
        logging_setup.get_logger("gym_continuousDoubleAuction.t").info("when")

        first = (tmp_path / "run.log").read_text().splitlines()[0]
        assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\b", first), first


class TestWorkerProcessesGetTheirOwn:
    """The episode callbacks run on the env runners, not the driver.

    With num_env_runners > 0 the NAV tables and the conservation ERROR are
    emitted in a worker. A driver-only file would miss exactly the lines this
    whole feature exists to keep. Verified against a real 2-runner training run:
    without this the worker's NAV tables reached no file at all.
    """

    def test_the_directory_is_exported_for_workers(self, tmp_path):
        import os

        logging_setup.configure("INFO", log_dir=str(tmp_path), force=True)

        assert os.environ[logging_setup.log_dir_env_var()] == str(tmp_path)

    def test_a_worker_resolves_the_directory_from_the_environment(
        self, tmp_path, monkeypatch
    ):
        """A worker never runs train.main, so this is the only channel it has -
        the same route the level takes."""
        monkeypatch.setenv(logging_setup.log_dir_env_var(), str(tmp_path))

        logging_setup.configure("INFO", force=True)   # no log_dir: a worker
        logging_setup.get_logger("gym_continuousDoubleAuction.t").info("worker line")

        written = list(tmp_path.glob("run.*.log"))
        assert len(written) == 1, [p.name for p in written]
        assert "worker line" in written[0].read_text()

    def test_a_worker_writes_its_own_pid_suffixed_file(self, tmp_path, monkeypatch):
        """Separate files, not one shared: RotatingFileHandler is not safe
        across processes, and two workers rotating together truncate each
        other's output."""
        import os

        monkeypatch.setenv(logging_setup.log_dir_env_var(), str(tmp_path))
        logging_setup.configure("INFO", force=True)
        logging_setup.get_logger("gym_continuousDoubleAuction.t").info("x")

        assert logging_setup.log_file_path() == str(
            tmp_path / f"run.{os.getpid()}.log"
        )
        assert not (tmp_path / "run.log").exists()

    def test_the_driver_keeps_the_plain_name(self, tmp_path):
        """Passing log_dir explicitly is what makes a process the driver."""
        logging_setup.configure("INFO", log_dir=str(tmp_path), force=True)
        logging_setup.get_logger("gym_continuousDoubleAuction.t").info("x")

        assert logging_setup.log_file_path() == str(tmp_path / "run.log")

    def test_the_variable_name_comes_from_the_file(self, config_tree):
        config_tree("tunable_constants.json", lambda raw: raw["logging"].update(
            {"dir_env_var": "CDA_OTHER_DIR"}
        ))
        assert logging_setup.log_dir_env_var() == "CDA_OTHER_DIR"

    def test_no_file_when_nothing_points_anywhere(self, tmp_path, monkeypatch):
        monkeypatch.delenv(logging_setup.log_dir_env_var(), raising=False)
        logging_setup.configure("INFO", force=True)
        logging_setup.get_logger("gym_continuousDoubleAuction.t").info("x")

        assert logging_setup.log_file_path() is None
        assert not list(tmp_path.glob("*.log*"))
