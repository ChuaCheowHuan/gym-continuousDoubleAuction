"""The logging review's open issues under multiple env runners (#216 to #221).

Each test pins one behaviour of the fix; the shape of the problem is in docs/11 §5.
"""

import itertools
import json
import logging
import os
import shutil
import time
from types import SimpleNamespace

import pytest

from gym_continuousDoubleAuction import config_loader, logging_setup
from gym_continuousDoubleAuction.train import progress
from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import (
    SelfPlayCallback,
)

PKG = logging_setup.ROOT_NAME


@pytest.fixture(autouse=True)
def restore_logging(monkeypatch):
    """Undo what a test did to the package logger, Ray's logger, the environment and the driver's state."""
    root = logging.getLogger(PKG)
    ray_names = ["ray", "ray.rllib"]
    saved = (
        list(root.handlers),
        root.level,
        logging_setup._configured,
        logging_setup._log_file_path,
    )
    saved_ray = {n: list(logging.getLogger(n).handlers) for n in ray_names}
    saved_mirrored = list(logging_setup._ray_mirrored)
    saved_dir = os.environ.get(logging_setup.log_dir_env_var())
    saved_seen = set(progress._seen_runner_logs)
    saved_warned = progress._warned_missing_runner_log
    progress._seen_runner_logs.clear()
    progress._warned_missing_runner_log = False
    yield
    for handler in list(root.handlers):
        if handler not in saved[0]:
            handler.close()
    root.handlers, _level, logging_setup._configured, logging_setup._log_file_path = saved
    root.setLevel(saved[1])
    for name, handlers in saved_ray.items():
        logging.getLogger(name).handlers = handlers
    logging_setup._ray_mirrored[:] = saved_mirrored
    logging_setup.set_iteration(None)
    if saved_dir is None:
        os.environ.pop(logging_setup.log_dir_env_var(), None)
    else:
        os.environ[logging_setup.log_dir_env_var()] = saved_dir
    progress._seen_runner_logs.clear()
    progress._seen_runner_logs.update(saved_seen)
    progress._warned_missing_runner_log = saved_warned
    config_loader.reload()


@pytest.fixture
def edit_logging(tmp_path, monkeypatch):
    """Edit the `logging` group of a writable copy of `config/`."""
    target = tmp_path / "config"
    shutil.copytree(config_loader.config_dir(), target)
    monkeypatch.setenv(config_loader.CONFIG_DIR_ENV_VAR, str(target))
    config_loader.reload()

    def edit(**values):
        path = target / "tunable_constants.json"
        with open(path) as fh:
            raw = json.load(fh)
        raw["logging"].update(values)
        with open(path, "w") as fh:
            json.dump(raw, fh)
        config_loader.reload()

    return edit


def _fresh_ray_logger(parent):
    """A logger under `parent` that nothing has configured or disabled.

    Not a named Ray logger, and records are logged at ERROR: a test that ran Ray earlier in
    the process leaves `ray.rllib` at the level Ray's `LoggingConfig` gave it (ERROR), and
    capturing Ray's records does not change what Ray decides to emit.
    """
    return logging.getLogger(f"{parent}.cda_test_{next(_counter)}")


_counter = itertools.count()


def _logs(tmp_path):
    out = tmp_path / "logs"
    out.mkdir(exist_ok=True)
    return out


def _make_group(directory, tag, age, extras=("", ".1", ".head")):
    """A worker log run.<tag>.log with rotated backups and a head, `age` seconds old."""
    paths = []
    for extra in extras:
        path = directory / f"run.{tag}.log{extra}"
        path.write_text("x")
        stamp = time.time() - age
        os.utime(path, (stamp, stamp))
        paths.append(path)
    return paths


class TestTheStartOfARunIsKept:
    """#216: rotation discarded the start of a run, where divergence begins."""

    def test_the_first_file_survives_every_later_rotation(self, tmp_path, edit_logging):
        edit_logging(file_max_bytes=2048, file_backup_count=1, file_keep_head=True)
        logging_setup.configure("INFO", log_dir=str(tmp_path), force=True)
        logger = logging_setup.get_logger(f"{PKG}.t")
        logger.info("the-very-first-line")
        for i in range(600):
            logger.info("padding line %s to fill the file and force several rotations", i)

        head = tmp_path / "run.log.head"
        assert head.exists() and "the-very-first-line" in head.read_text()
        assert "the-very-first-line" not in (tmp_path / "run.log").read_text()
        assert not (tmp_path / "run.log.2").exists()  # backups still bounded

    def test_the_head_is_written_once(self, tmp_path, edit_logging):
        edit_logging(file_max_bytes=2048, file_backup_count=1, file_keep_head=True)
        logging_setup.configure("INFO", log_dir=str(tmp_path), force=True)
        logger = logging_setup.get_logger(f"{PKG}.t")
        for i in range(120):
            logger.info("padding line %s to fill the file and force a rotation", i)
        first = (tmp_path / "run.log.head").read_text()
        for i in range(400):
            logger.info("more padding line %s to fill the file and rotate again", i)
        assert (tmp_path / "run.log.head").read_text() == first

    def test_it_can_be_switched_off(self, tmp_path, edit_logging):
        edit_logging(file_max_bytes=2048, file_backup_count=1, file_keep_head=False)
        logging_setup.configure("INFO", log_dir=str(tmp_path), force=True)
        logger = logging_setup.get_logger(f"{PKG}.t")
        for i in range(300):
            logger.info("padding line %s to fill the file and force rotations", i)
        assert not (tmp_path / "run.log.head").exists()


class TestWorkerLogsAreBounded:
    """#216: each restarted env runner opened a new file set, without limit."""

    def test_only_the_newest_groups_are_kept_with_all_their_files(self, tmp_path):
        d = _logs(tmp_path)
        groups = {
            tag: _make_group(d, tag, age)
            for tag, age in [
                ("1.aaaa", 500),
                ("2.bbbb", 400),
                ("3.cccc", 300),
                ("4.dddd", 200),
                ("5.eeee", 100),
            ]
        }
        (d / "run.log").write_text("driver")

        removed = logging_setup.prune_worker_logs(str(d), "run.log", keep=2)

        assert removed == 3
        for tag in ("4.dddd", "5.eeee"):
            assert all(p.exists() for p in groups[tag])
        for tag in ("1.aaaa", "2.bbbb", "3.cccc"):
            assert not any(p.exists() for p in groups[tag])
        assert (d / "run.log").exists()  # the driver's file is not a worker log

    def test_a_group_counts_once_however_many_files_it_has(self, tmp_path):
        d = _logs(tmp_path)
        many = _make_group(d, "1.aaaa", 100, extras=("", ".1", ".2", ".3", ".head"))
        one = _make_group(d, "2.bbbb", 200, extras=("",))
        logging_setup.prune_worker_logs(str(d), "run.log", keep=2)
        assert all(p.exists() for p in many + one)

    def test_zero_turns_it_off(self, tmp_path):
        d = _logs(tmp_path)
        files = [p for t, a in [("1.a", 9), ("2.b", 8), ("3.c", 7)] for p in _make_group(d, t, a)]
        assert logging_setup.prune_worker_logs(str(d), "run.log", keep=0) == 0
        assert all(p.exists() for p in files)

    def test_the_protected_log_is_never_removed(self, tmp_path):
        d = _logs(tmp_path)
        old = _make_group(d, "1.old", 900)
        _make_group(d, "2.new", 10)
        logging_setup.prune_worker_logs(str(d), "run.log", keep=1, protect=str(d / "run.1.old.log"))
        assert all(p.exists() for p in old)

    def test_a_missing_directory_is_not_an_error(self, tmp_path):
        assert logging_setup.prune_worker_logs(str(tmp_path / "nope"), "run.log", keep=2) == 0

    def test_a_worker_prunes_when_it_opens_its_log(self, tmp_path, monkeypatch, edit_logging):
        edit_logging(file_max_worker_files=2)
        d = _logs(tmp_path)
        old = [_make_group(d, f"{n}.t{n}", 1000 - n) for n in range(1, 6)]
        monkeypatch.setenv(logging_setup.log_dir_env_var(), str(d))

        logging_setup.configure("INFO", force=True)  # no log_dir argument: a worker

        survivors = [g for g in old if all(p.exists() for p in g)]
        assert len(survivors) == 2
        assert survivors == old[-2:]

    def test_the_driver_never_prunes(self, tmp_path, edit_logging):
        edit_logging(file_max_worker_files=1)
        d = _logs(tmp_path)
        groups = [_make_group(d, f"{n}.t{n}", 100 - n) for n in range(1, 4)]
        logging_setup.configure("INFO", log_dir=str(d), force=True)
        assert all(p.exists() for g in groups for p in g)


class TestRaysOwnRecordsReachTheRunLog:
    """#218: RLlib's diagnostics were in a different stream from the narrative they explain."""

    def test_a_record_from_a_ray_logger_lands_in_the_file(self, tmp_path):
        logging_setup.configure("INFO", log_dir=str(tmp_path), force=True)
        ray_log = _fresh_ray_logger("ray.rllib.env.env_runner_group")
        ray_log.setLevel(logging.INFO)
        ray_log.warning("No samples returned from remote workers")
        for handler in logging.getLogger(PKG).handlers:
            handler.flush()
        text = (tmp_path / "run.log").read_text()
        assert "No samples returned from remote workers" in text
        assert "ray.rllib.env.env_runner_group" in text and "iter=" in text

    def test_a_record_from_rllib_whose_logger_does_not_propagate_is_still_captured(self, tmp_path):
        rllib = logging.getLogger("ray.rllib")
        was = rllib.propagate
        rllib.propagate = False  # what RLlib does once it has set itself up
        try:
            logging_setup.configure("INFO", log_dir=str(tmp_path), force=True)
            _fresh_ray_logger("ray.rllib.algorithms").error("restarting env runner 3")
            for handler in logging.getLogger(PKG).handlers:
                handler.flush()
        finally:
            rllib.propagate = was
        assert "restarting env runner 3" in (tmp_path / "run.log").read_text()

    def test_a_record_is_written_once_even_where_two_ray_loggers_carry_the_handler(self, tmp_path):
        rllib = logging.getLogger("ray.rllib")
        was = rllib.propagate
        rllib.propagate = True  # a process where RLlib has not configured itself yet
        try:
            logging_setup.configure("INFO", log_dir=str(tmp_path), force=True)
            _fresh_ray_logger("ray.rllib.env").error("only-once-marker")
            for handler in logging.getLogger(PKG).handlers:
                handler.flush()
        finally:
            rllib.propagate = was
        assert (tmp_path / "run.log").read_text().count("only-once-marker") == 1

    def test_it_is_the_file_handler_only(self, tmp_path):
        logging_setup.configure("INFO", log_dir=str(tmp_path), force=True)
        ray_handlers = [
            h for name in ("ray", "ray.rllib") for h in logging.getLogger(name).handlers
        ]
        stream = [h for h in logging.getLogger(PKG).handlers if type(h) is logging.StreamHandler]
        assert not any(h in ray_handlers for h in stream)
        assert any(isinstance(h, logging.handlers.RotatingFileHandler) for h in ray_handlers)

    def test_reconfiguring_does_not_stack_copies(self, tmp_path):
        for _ in range(3):
            logging_setup.configure("INFO", log_dir=str(tmp_path), force=True)
        mirrored = [
            h
            for h in logging.getLogger("ray").handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert len(mirrored) == 1
        ours = [
            h
            for h in logging.getLogger("ray.rllib").handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert len(ours) == 1

    def test_it_can_be_switched_off(self, tmp_path, edit_logging):
        edit_logging(capture_ray_logs=False)
        logging_setup.configure("INFO", log_dir=str(tmp_path), force=True)
        assert not any(
            isinstance(h, logging.handlers.RotatingFileHandler)
            for h in logging.getLogger("ray").handlers
        )

    def test_no_file_means_nothing_is_mirrored(self):
        logging_setup.configure("INFO", force=True)
        assert logging_setup._ray_mirrored == []


class TestADriverLearnsWhereEachProcessLogs:
    """#218: a worker that could not open its run log said so only on its own stdout."""

    def test_a_process_with_no_log_is_a_warning_in_the_drivers_log(self, monkeypatch, caplog):
        monkeypatch.setenv(logging_setup.log_dir_env_var(), "/shared/logs")
        with caplog.at_level(logging.INFO, logger=PKG):
            progress._report_runner_logs(["", "/shared/logs/run.1.a.log", ""], "env runner")
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "2 of 3 env runner processes have no run log" in warnings[0].getMessage()
        assert "/shared/logs" in warnings[0].getMessage()

    def test_it_warns_once(self, monkeypatch, caplog):
        monkeypatch.setenv(logging_setup.log_dir_env_var(), "/shared/logs")
        with caplog.at_level(logging.WARNING, logger=PKG):
            progress._report_runner_logs([""], "env runner")
            progress._report_runner_logs([""], "env runner")
        assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1

    def test_no_directory_configured_means_no_warning(self, monkeypatch, caplog):
        monkeypatch.delenv(logging_setup.log_dir_env_var(), raising=False)
        with caplog.at_level(logging.WARNING, logger=PKG):
            progress._report_runner_logs(["", ""], "env runner")
        assert not caplog.records

    def test_each_new_path_is_announced_once(self, monkeypatch, caplog):
        monkeypatch.delenv(logging_setup.log_dir_env_var(), raising=False)
        with caplog.at_level(logging.INFO, logger=PKG):
            progress._report_runner_logs(["/l/run.1.a.log"], "env runner")
            progress._report_runner_logs(["/l/run.1.a.log", "/l/run.2.b.log"], "env runner")
        lines = [r.getMessage() for r in caplog.records]
        assert lines == ["env runner log: /l/run.1.a.log", "env runner log: /l/run.2.b.log"]

    def test_the_applied_function_returns_this_processs_log_path(self, tmp_path):
        logging_setup.configure("INFO", log_dir=str(tmp_path), force=True)
        assert progress._apply_iteration(3)(None) == logging_setup.log_file_path()
        assert logging_setup.current_iteration() == 3
        logging_setup.configure("INFO", force=True)
        os.environ.pop(logging_setup.log_dir_env_var(), None)
        logging_setup.configure("INFO", force=True)
        assert progress._apply_iteration(4)(None) == ""


class _Result:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class _LearnerGroup:
    def __init__(self, n=2, local=False, raises=False):
        self.n, self.is_local, self.raises, self.calls = n, local, raises, []

    def foreach_learner(self, func, **kwargs):
        self.calls.append(kwargs)
        if self.raises:
            raise RuntimeError("learner group is gone")
        return [_Result(func(None)) for _ in range(self.n)]

    def __len__(self):
        return self.n


class TestLearnersGetTheIteration:
    """#217: remote learner actors never received the tag, so every line read `iter=-`."""

    def test_remote_learners_are_told(self):
        group = _LearnerGroup()
        progress._broadcast_to_learners(SimpleNamespace(learner_group=group), 7)
        assert len(group.calls) == 1 and group.calls[0]["timeout_seconds"] > 0
        assert logging_setup.current_iteration() == 7  # the fake runs the function in-process

    def test_a_local_learner_is_not_asked(self):
        group = _LearnerGroup(local=True)
        progress._broadcast_to_learners(SimpleNamespace(learner_group=group), 7)
        assert group.calls == []

    def test_no_learner_group_is_not_an_error(self):
        progress._broadcast_to_learners(SimpleNamespace(), 7)
        progress._broadcast_to_learners(SimpleNamespace(learner_group=None), 7)

    def test_a_failure_costs_the_tag_not_the_run(self, caplog):
        with caplog.at_level(logging.DEBUG, logger=PKG):
            progress._broadcast_to_learners(
                SimpleNamespace(learner_group=_LearnerGroup(raises=True)), 7
            )
        assert "could not broadcast iteration 7 to the learners" in caplog.text

    def test_learners_that_did_not_answer_are_a_warning(self, caplog):
        group = _LearnerGroup(n=3)
        group.foreach_learner = lambda func, **kw: [_Result(func(None))]
        with caplog.at_level(logging.WARNING, logger=PKG):
            progress._broadcast_to_learners(SimpleNamespace(learner_group=group), 7)
        assert "reached only 1 of 3 learners" in caplog.text

    def test_the_iteration_broadcast_includes_them_even_with_no_env_runner_group(self):
        group = _LearnerGroup()
        progress._broadcast_iteration(SimpleNamespace(learner_group=group), 9)
        assert len(group.calls) == 1

    def test_their_log_paths_are_reported(self, caplog):
        group = _LearnerGroup(n=1)
        with caplog.at_level(logging.INFO, logger=PKG):
            progress._broadcast_to_learners(SimpleNamespace(learner_group=group), 2)
        # The fake runs `_apply` in this process, which has no run log: nothing to announce,
        # and no warning when no directory is configured.
        assert "learner log:" not in caplog.text


def _callback():
    return SelfPlayCallback(num_trainable_policies=2, num_random_policies=6, episode_data_dir=None)


class TestAMissedBroadcastReadsAsADash:
    """#220: a runner the broadcast missed kept the previous iteration, a plausible wrong number."""

    def test_a_remote_runner_clears_the_tag_when_its_sample_ends(self):
        logging_setup.set_iteration(5)
        _callback().on_sample_end(env_runner=SimpleNamespace(worker_index=1))
        assert logging_setup.current_iteration() is None

    def test_the_local_runner_shares_the_drivers_tag_and_leaves_it(self):
        logging_setup.set_iteration(5)
        _callback().on_sample_end(env_runner=SimpleNamespace(worker_index=0))
        assert logging_setup.current_iteration() == 5

    def test_no_runner_at_all_leaves_it_too(self):
        logging_setup.set_iteration(5)
        _callback().on_sample_end()
        assert logging_setup.current_iteration() == 5

    def test_it_clears_even_if_the_record_flush_fails(self):
        class Boom:
            def flush_finished(self, wait):
                raise OSError("disk full")

        cb = _callback()
        cb._episode_recorder = Boom()
        logging_setup.set_iteration(5)
        cb.on_sample_end(env_runner=SimpleNamespace(worker_index=2))
        assert logging_setup.current_iteration() is None

    def test_a_fresh_broadcast_is_what_makes_the_next_sample_read_a_number(self):
        cb = _callback()
        logging_setup.set_iteration(1)
        cb.on_sample_end(env_runner=SimpleNamespace(worker_index=1))
        assert logging_setup.current_iteration() is None
        progress._apply_iteration(2)(None)
        assert logging_setup.current_iteration() == 2
        line = logging.LogRecord("x", logging.INFO, "f", 1, "m", (), None)
        logging_setup._IterationFilter().filter(line)
        assert line.iteration == 2


class TestAWorkersConsoleIsNotADuplicate:
    """#221: a worker's NAV table appeared in its file and again on the driver console."""

    @staticmethod
    def _worker(tmp_path, monkeypatch):
        monkeypatch.setenv(logging_setup.log_dir_env_var(), str(tmp_path))
        logging_setup.configure("INFO", force=True)
        return logging_setup.get_logger(f"{PKG}.t")

    def test_a_worker_with_a_file_echoes_only_warnings(self, tmp_path, monkeypatch, capsys):
        logger = self._worker(tmp_path, monkeypatch)
        logger.info("the NAV table")
        logger.warning("something surprising")
        for handler in logging.getLogger(PKG).handlers:
            handler.flush()
        out = capsys.readouterr().out
        assert "something surprising" in out and "the NAV table" not in out
        written = logging_setup.log_file_path()
        assert "the NAV table" in open(written).read()  # the file keeps everything

    def test_the_driver_echoes_everything(self, tmp_path, capsys):
        logging_setup.configure("INFO", log_dir=str(tmp_path), force=True)
        logging_setup.get_logger(f"{PKG}.t").info("driver narrative")
        assert "driver narrative" in capsys.readouterr().out

    def test_a_worker_with_no_file_echoes_everything(self, monkeypatch, capsys):
        monkeypatch.delenv(logging_setup.log_dir_env_var(), raising=False)
        logging_setup.configure("INFO", force=True)
        logging_setup.get_logger(f"{PKG}.t").info("no file, so the console is the record")
        assert "no file, so the console is the record" in capsys.readouterr().out

    def test_an_empty_setting_restores_the_old_behaviour(
        self, tmp_path, monkeypatch, capsys, edit_logging
    ):
        edit_logging(worker_console_level="")
        self._worker(tmp_path, monkeypatch).info("echoed as before")
        assert "echoed as before" in capsys.readouterr().out

    def test_the_level_is_configurable(self, tmp_path, monkeypatch, capsys, edit_logging):
        edit_logging(worker_console_level="INFO")
        self._worker(tmp_path, monkeypatch).info("echoed at INFO")
        assert "echoed at INFO" in capsys.readouterr().out

    def test_a_bad_level_name_is_refused_naming_the_key(self, tmp_path, monkeypatch, edit_logging):
        edit_logging(worker_console_level="LOUD")
        monkeypatch.setenv(logging_setup.log_dir_env_var(), str(tmp_path))
        with pytest.raises(ValueError, match="worker_console_level"):
            logging_setup.configure("INFO", force=True)
