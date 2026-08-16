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

        assert "both" in capsys.readouterr().out
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

    def test_a_worker_writes_its_own_tagged_file(self, tmp_path, monkeypatch):
        """Separate files, not one shared: RotatingFileHandler is not safe
        across processes, and two workers rotating together truncate each
        other's output."""
        import os

        monkeypatch.setenv(logging_setup.log_dir_env_var(), str(tmp_path))
        logging_setup.configure("INFO", force=True)
        logging_setup.get_logger("gym_continuousDoubleAuction.t").info("x")

        path = logging_setup.log_file_path()
        # The pid leads, because that is what the `pid=` field of every line
        # matches. Anything after it is the cluster-unique part - see
        # test_the_tag_is_unique_across_nodes_not_just_within_one.
        assert os.path.basename(path).startswith(f"run.{os.getpid()}")
        assert path.endswith(".log")
        assert not (tmp_path / "run.log").exists()

    def test_the_tag_is_unique_across_nodes_not_just_within_one(
        self, tmp_path, monkeypatch
    ):
        """A pid is unique per node, and `log_base_dir` can be a shared mount.

        Two nodes number processes independently, so with results on NFS or a
        Drive mount two workers can hold the same pid and open the same file -
        which is the cross-process rotation race the per-worker name exists to
        prevent. Ray's worker id is what actually separates them.
        """
        import sys
        from types import SimpleNamespace

        monkeypatch.setenv(logging_setup.log_dir_env_var(), str(tmp_path))

        def fake_ray(worker_id):
            return SimpleNamespace(
                get_runtime_context=lambda: SimpleNamespace(
                    get_worker_id=lambda: worker_id
                )
            )

        # Same pid, two workers: the names must still differ.
        monkeypatch.setitem(sys.modules, "ray", fake_ray("aaaaaaaabbbb"))
        logging_setup.configure("INFO", force=True)
        first = logging_setup.log_file_path()

        monkeypatch.setitem(sys.modules, "ray", fake_ray("ccccccccdddd"))
        logging_setup.configure("INFO", force=True)
        second = logging_setup.log_file_path()

        assert first != second
        assert first.endswith("aaaaaaaa.log")
        assert second.endswith("cccccccc.log")

    def test_the_tag_falls_back_to_the_pid_without_ray(
        self, tmp_path, monkeypatch
    ):
        """Ray is read from sys.modules, never imported: importing it here would
        break apply_env_vars(), which must run before ray is first imported."""
        import os
        import sys

        monkeypatch.setenv(logging_setup.log_dir_env_var(), str(tmp_path))
        monkeypatch.delitem(sys.modules, "ray", raising=False)

        logging_setup.configure("INFO", force=True)

        assert logging_setup.log_file_path() == str(
            tmp_path / f"run.{os.getpid()}.log"
        )

    def test_a_ray_without_a_worker_id_does_not_break_logging(
        self, tmp_path, monkeypatch
    ):
        """A renamed API degrades to the pid rather than losing the log."""
        import os
        import sys
        from types import SimpleNamespace

        monkeypatch.setenv(logging_setup.log_dir_env_var(), str(tmp_path))
        monkeypatch.setitem(sys.modules, "ray", SimpleNamespace(
            get_runtime_context=lambda: (_ for _ in ()).throw(RuntimeError())
        ))

        logging_setup.configure("INFO", force=True)

        assert logging_setup.log_file_path() == str(
            tmp_path / f"run.{os.getpid()}.log"
        )

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


class TestConcurrentConfiguration:
    """Setting logging up from several threads at once.

    The write path was already safe - `Handler.handle` takes the handler's lock
    around `emit`, so records cannot interleave. The *setup* path was not:
    `get_logger` checks `_configured` and then acts on it, and `configure`
    removes and closes the existing handlers before adding the replacements.
    Two threads inside that sequence produce either a duplicated handler or a
    handler closed while another thread is emitting through it. Nothing in this
    file exercised concurrency at all, which is why it went unnoticed.
    """

    def test_racing_get_logger_calls_leave_exactly_one_handler_set(self):
        import threading

        logging_setup._configured = False
        root = logging.getLogger(logging_setup.ROOT_NAME)
        root.handlers = []

        start = threading.Barrier(8)

        def configure_from_scratch():
            start.wait()
            logging_setup.get_logger("gym_continuousDoubleAuction.race")

        threads = [
            threading.Thread(target=configure_from_scratch) for _ in range(8)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # One stream handler, not eight, and not zero.
        assert len(root.handlers) == 1

    def test_a_racing_reconfigure_never_drops_a_line(self, tmp_path):
        """Lines logged while another thread is calling configure(force=True).

        The failure this pins is not a torn line - the handler lock prevents
        that - but a line written to a handler that a concurrent reconfigure
        had already closed and removed.
        """
        import threading

        logging_setup.configure("INFO", log_dir=str(tmp_path), force=True)
        logger = logging_setup.get_logger("gym_continuousDoubleAuction.race")

        errors = []
        stop = threading.Event()

        def reconfigure():
            while not stop.is_set():
                try:
                    logging_setup.configure(
                        "INFO", log_dir=str(tmp_path), force=True
                    )
                except Exception as exc:      # pragma: no cover - the failure
                    errors.append(exc)

        def emit():
            for i in range(200):
                try:
                    logger.info("line %s", i)
                except Exception as exc:      # pragma: no cover - the failure
                    errors.append(exc)

        spinner = threading.Thread(target=reconfigure)
        spinner.start()
        writers = [threading.Thread(target=emit) for _ in range(4)]
        for writer in writers:
            writer.start()
        for writer in writers:
            writer.join()
        stop.set()
        spinner.join()

        assert not errors, errors[:3]

    def test_concurrent_writers_do_not_tear_a_line(self, tmp_path):
        """Every record arrives whole. This already held - it is pinned so that
        a future handler change cannot quietly give it up."""
        import threading

        logging_setup.configure("INFO", log_dir=str(tmp_path), force=True)
        logger = logging_setup.get_logger("gym_continuousDoubleAuction.race")

        def emit(marker):
            for i in range(100):
                logger.info("%s-%03d-END", marker, i)

        threads = [
            threading.Thread(target=emit, args=(f"w{n}",)) for n in range(6)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        lines = [
            line for line in (tmp_path / "run.log").read_text().splitlines()
            if "-END" in line
        ]
        assert len(lines) == 600
        # A torn line would show a second record's text after the terminator.
        assert all(line.endswith("-END") for line in lines)


class TestSeparateProcesses:
    """What two OS processes do to one log directory.

    `RotatingFileHandler` has no cross-process interlock, so the design's answer
    is to stop them sharing a file rather than to make sharing safe. These run
    real subprocesses, because the thing being tested is precisely what threads
    cannot stand in for.
    """

    SCRIPT = """
import sys
sys.path.insert(0, {repo!r})
from gym_continuousDoubleAuction.logging_setup import configure, get_logger
configure("INFO", {kwargs}, force=True)
log = get_logger("gym_continuousDoubleAuction.proc")
for i in range(200):
    log.info("%s line %03d END", {marker!r}, i)
"""

    def _run(self, tmp_path, name, marker, kwargs):
        import subprocess
        import sys

        repo = str(
            __import__("pathlib").Path(__file__).resolve().parents[2]
        )
        script = tmp_path / f"{name}.py"
        script.write_text(self.SCRIPT.format(
            repo=repo, kwargs=kwargs, marker=marker
        ))
        return subprocess.Popen([sys.executable, str(script)])

    def test_two_workers_write_separate_files_and_lose_nothing(self, tmp_path):
        """The per-worker name, doing its job: both processes' output survives."""
        env_var = logging_setup.log_dir_env_var()
        kwargs = f"log_dir=None"

        import os
        import subprocess
        import sys

        repo = str(
            __import__("pathlib").Path(__file__).resolve().parents[2]
        )
        env = dict(os.environ, **{env_var: str(tmp_path)})
        script = tmp_path / "worker.py"
        script.write_text(self.SCRIPT.format(
            repo=repo, kwargs=kwargs, marker="W",
        ))

        procs = [
            subprocess.Popen([sys.executable, str(script)], env=env)
            for _ in range(2)
        ]
        for proc in procs:
            assert proc.wait(timeout=120) == 0

        files = sorted(tmp_path.glob("run.*.log"))
        assert len(files) == 2, [f.name for f in files]
        total = sum(
            len([l for l in f.read_text().splitlines() if "END" in l])
            for f in files
        )
        assert total == 400

    def test_two_runs_do_not_share_a_driver_log(self, tmp_path):
        """Why run_dir exists.

        Both processes are drivers, so both take the un-suffixed `run.log`. Given
        one directory they would rotate the same file underneath each other;
        given a directory each - which is what TrainConfig.run_dir hands them -
        they cannot interact at all.
        """
        first = tmp_path / "run_a"
        second = tmp_path / "run_b"

        procs = [
            self._run(tmp_path, "d1", "A", f"log_dir={str(first)!r}"),
            self._run(tmp_path, "d2", "B", f"log_dir={str(second)!r}"),
        ]
        for proc in procs:
            assert proc.wait(timeout=120) == 0

        for directory, marker in ((first, "A"), (second, "B")):
            lines = (directory / "run.log").read_text().splitlines()
            kept = [line for line in lines if "END" in line]
            assert len(kept) == 200, directory
            # Nothing from the other run reached this file.
            assert all(marker in line for line in kept)


class TestUnhandledExceptions:
    """The traceback belongs in the run log.

    Python's default hook writes it to stderr, outside logging entirely, so a
    run that died left its narrative in `run.log` and the reason for its death
    only in scrollback - the exact failure the run log was added to fix. It
    matters most for the `strict_nav_check` AssertionError, whose whole job is
    to stop a run loudly enough to be diagnosed afterwards.
    """

    SCRIPT = """
import sys
sys.path.insert(0, {repo!r})
from gym_continuousDoubleAuction.logging_setup import configure
configure("INFO", log_dir={log_dir!r}, force=True)
{body}
"""

    def _run(self, tmp_path, body):
        import subprocess
        import sys

        repo = str(
            __import__("pathlib").Path(__file__).resolve().parents[2]
        )
        script = tmp_path / "dies.py"
        script.write_text(self.SCRIPT.format(
            repo=repo, log_dir=str(tmp_path), body=body
        ))
        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=120,
        )
        return proc, (tmp_path / "run.log").read_text()

    def test_the_traceback_reaches_the_run_log(self, tmp_path):
        proc, log = self._run(
            tmp_path, "raise AssertionError('NAV conservation VIOLATED')"
        )

        assert proc.returncode != 0
        assert "NAV conservation VIOLATED" in log
        assert "Traceback (most recent call last)" in log
        assert "unhandled AssertionError" in log

    def test_stderr_still_gets_it_too(self, tmp_path):
        """The previous hook is chained, not replaced: anything reading stderr -
        a CI log, a terminal - sees what it always did."""
        proc, _ = self._run(tmp_path, "raise ValueError('boom')")

        assert "ValueError: boom" in proc.stderr

    def test_an_exception_in_a_thread_is_logged(self, tmp_path):
        """threading.excepthook, which no try/except around train() would reach."""
        _, log = self._run(tmp_path, (
            "import threading\n"
            "t = threading.Thread(target=lambda: 1 / 0, name='sampler')\n"
            "t.start(); t.join()\n"
        ))

        assert "unhandled ZeroDivisionError in thread sampler" in log

    def test_a_keyboard_interrupt_is_one_line_not_a_stack(self, tmp_path):
        """These runs normally end by being killed. A full stack for every
        intentional Ctrl-C is noise at the end of every session."""
        _, log = self._run(tmp_path, "raise KeyboardInterrupt")

        assert "interrupted" in log
        assert "Traceback" not in log


class TestWarningCapture:
    """`warnings.warn` goes through logging, not to a bare stderr write.

    A DeprecationWarning from Ray or gymnasium is the earliest signal that an
    upgrade is about to break this repository, and it used to go to stderr
    unrecorded and unrotated.

    In a subprocess, not in-process: pytest's warnings plugin wraps every test
    in `catch_warnings(record=True)`, which replaces `warnings.showwarning` -
    the exact hook `captureWarnings(True)` installs. In-process assertions here
    would be testing pytest's recorder rather than this package's routing.
    """

    SCRIPT = """
import sys
sys.path.insert(0, {repo!r})
import warnings
from gym_continuousDoubleAuction.logging_setup import configure
configure("INFO", log_dir={log_dir!r}, force=True)
warnings.simplefilter("always")
warnings.warn("ray is going to break this", DeprecationWarning)
"""

    def _run(self, tmp_path):
        import subprocess
        import sys

        repo = str(
            __import__("pathlib").Path(__file__).resolve().parents[2]
        )
        script = tmp_path / "warns.py"
        script.write_text(self.SCRIPT.format(repo=repo, log_dir=str(tmp_path)))
        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=120,
        )
        return proc, (tmp_path / "run.log").read_text()

    def test_a_deprecation_warning_lands_in_the_run_log(self, tmp_path):
        proc, log = self._run(tmp_path)

        assert proc.returncode == 0
        assert "ray is going to break this" in log
        assert "py.warnings" in log

    def test_it_does_not_reach_the_last_resort_handler(self, tmp_path):
        """`captureWarnings(True)` alone would not be enough: it logs to
        `py.warnings`, which is outside this package's namespace and so inherits
        none of its handlers, leaving the record to fall through to logging's
        last-resort handler - which writes to stderr, exactly what capturing it
        was meant to stop."""
        proc, _ = self._run(tmp_path)

        assert "ray is going to break this" in proc.stdout
        assert proc.stderr == ""


class TestWorkerEnvVars:
    """What `ray.init(runtime_env=...)` has to carry.

    The os.environ export reaches workers only when this process starts the
    cluster - the raylet inherits our environment. Against `ray.init(address=)`
    on a cluster that was already running, nothing exported here arrives, and
    since the episode callbacks run on the runners that is where the NAV tables
    and the conservation ERROR would be lost.
    """

    def test_it_carries_the_level_and_the_directory(self, tmp_path):
        logging_setup.configure("DEBUG", log_dir=str(tmp_path), force=True)

        env_vars = logging_setup.merge_runtime_env()["env_vars"]
        assert env_vars[logging_setup.level_env_var()] == "DEBUG"
        assert env_vars[logging_setup.log_dir_env_var()] == str(tmp_path)

    def test_an_unset_variable_stays_unset(self, monkeypatch):
        """Not an empty string, which resolve_level and the directory lookup
        would both have to special-case."""
        monkeypatch.delenv(logging_setup.log_dir_env_var(), raising=False)
        logging_setup.configure("INFO", force=True)

        assert logging_setup.log_dir_env_var() not in logging_setup.worker_env_vars()

    def test_an_explicit_caller_value_wins(self, tmp_path):
        logging_setup.configure("DEBUG", log_dir=str(tmp_path), force=True)

        merged = logging_setup.merge_runtime_env(
            {"env_vars": {logging_setup.level_env_var(): "ERROR"}}
        )
        assert merged["env_vars"][logging_setup.level_env_var()] == "ERROR"

    def test_the_rest_of_the_runtime_env_is_preserved(self, tmp_path):
        logging_setup.configure("INFO", log_dir=str(tmp_path), force=True)

        merged = logging_setup.merge_runtime_env({"pip": ["tabulate"]})
        assert merged["pip"] == ["tabulate"]


class TestIterationAcrossThreads:
    """The iteration tag is a property of the process, not of one thread.

    It was a ContextVar, chosen to be per-thread. A new thread starts from an
    empty context, so every line the driver logged from anywhere but the loop
    thread read `iter=-` while the process knew the answer perfectly well - and
    a value set inside a Ray actor task was not guaranteed to still be in
    context for the next task, which is what the broadcast to the env runners
    depends on.
    """

    def test_a_line_from_another_thread_carries_the_iteration(self, tmp_path):
        import threading

        logging_setup.configure("INFO", log_dir=str(tmp_path), force=True)
        logging_setup.set_iteration(7)

        def emit():
            logging_setup.get_logger("gym_continuousDoubleAuction.t").info("elsewhere")

        thread = threading.Thread(target=emit)
        thread.start()
        thread.join()

        line = [
            l for l in (tmp_path / "run.log").read_text().splitlines()
            if "elsewhere" in l
        ][0]
        assert "iter=7" in line

    def test_a_thread_can_set_it_for_the_process(self, tmp_path):
        """Which is what an env runner does when the driver broadcasts."""
        import threading

        logging_setup.configure("INFO", log_dir=str(tmp_path), force=True)
        logging_setup.set_iteration(None)

        thread = threading.Thread(target=logging_setup.set_iteration, args=(11,))
        thread.start()
        thread.join()

        assert logging_setup.current_iteration() == 11
