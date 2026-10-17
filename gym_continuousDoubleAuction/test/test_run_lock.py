"""One live run per checkpoint folder (issue #179).

All runs under one `log_base_dir` save into one folder, `chkpt/iter_NNNNN`; that sharing is
deliberate, since a new run resumes from an earlier run's newest save. But two runs going at
once overwrite each other's same-numbered save, and `chkpt_keep` pruning counts both runs'
saves against one limit, with neither run told. A lock file names the run holding the folder;
a second run on it is refused, and a lock whose process has gone is taken over.
"""

import json
import os
import socket
import subprocess
import sys
import threading

import pytest

from gym_continuousDoubleAuction.train.run_lock import LOCK_FILE, RunLock, RunLockedError


def _write_lock(directory, **fields):
    payload = {"run_id": "other_run", "pid": os.getppid(), "host": socket.gethostname()}
    payload.update(fields)
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, LOCK_FILE), "w") as fh:
        json.dump(payload, fh)


def _dead_pid():
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


class TestAcquireAndRelease:
    def test_it_writes_who_holds_the_folder(self, tmp_path):
        with RunLock(str(tmp_path), "run_a"):
            held = json.loads((tmp_path / LOCK_FILE).read_text())
            assert held["run_id"] == "run_a" and held["pid"] == os.getpid()
            assert held["host"] == socket.gethostname()

    def test_it_is_gone_after_the_with_block(self, tmp_path):
        with RunLock(str(tmp_path), "run_a"):
            pass
        assert not (tmp_path / LOCK_FILE).exists()

    def test_it_is_gone_after_an_error_too(self, tmp_path):
        with pytest.raises(RuntimeError):
            with RunLock(str(tmp_path), "run_a"):
                raise RuntimeError("the run failed")
        assert not (tmp_path / LOCK_FILE).exists()

    def test_the_folder_is_created_if_it_does_not_exist(self, tmp_path):
        with RunLock(str(tmp_path / "chkpt" / "deeper"), "run_a"):
            assert (tmp_path / "chkpt" / "deeper" / LOCK_FILE).exists()

    def test_releasing_never_removes_someone_elses_lock(self, tmp_path):
        lock = RunLock(str(tmp_path), "run_a")
        lock.acquire()
        _write_lock(tmp_path, run_id="taken_over")  # someone replaced it
        lock.release()
        assert json.loads((tmp_path / LOCK_FILE).read_text())["run_id"] == "taken_over"


class TestASecondRunIsRefused:
    def test_a_live_holder_refuses_by_name(self, tmp_path):
        _write_lock(tmp_path, run_id="the_first_run", pid=os.getppid())
        with pytest.raises(RunLockedError) as caught:
            RunLock(str(tmp_path), "run_b").acquire()
        message = str(caught.value)
        assert "the_first_run" in message and str(os.getppid()) in message
        assert "log_base_dir" in message, "it says what to do"
        assert (tmp_path / LOCK_FILE).exists(), "the holder's lock is untouched"

    def test_a_holder_on_another_machine_is_taken_to_be_live(self, tmp_path):
        _write_lock(tmp_path, host="some-other-machine", pid=_dead_pid())
        with pytest.raises(RunLockedError, match="some-other-machine"):
            RunLock(str(tmp_path), "run_b").acquire()

    def test_the_error_is_a_runtime_error(self):
        assert issubclass(RunLockedError, RuntimeError)


class TestAStaleLockIsTakenOver:
    def test_a_dead_process_on_this_machine_is_stale(self, tmp_path):
        _write_lock(tmp_path, pid=_dead_pid())
        with RunLock(str(tmp_path), "run_b"):
            assert json.loads((tmp_path / LOCK_FILE).read_text())["run_id"] == "run_b"

    def test_our_own_process_is_stale(self, tmp_path):
        """A notebook that re-runs `train` after a crash left the lock with its own pid."""
        _write_lock(tmp_path, pid=os.getpid())
        with RunLock(str(tmp_path), "run_b"):
            pass

    def test_an_unreadable_lock_is_stale(self, tmp_path):
        (tmp_path / LOCK_FILE).write_text("{ not json")
        with RunLock(str(tmp_path), "run_b"):
            pass


class TestTrainHoldsTheLock:
    @staticmethod
    def _cfg(tmp_path):
        from gym_continuousDoubleAuction.train.config import TrainConfig

        return TrainConfig(log_base_dir=str(tmp_path), episode_data_dir=None)

    def test_a_second_train_on_a_held_folder_is_refused_before_anything_is_built(
        self, tmp_path, monkeypatch
    ):
        from gym_continuousDoubleAuction.train import train as train_module

        cfg = self._cfg(tmp_path)
        _write_lock(cfg.checkpoint_dir, run_id="the_first_run")

        def build_algo(cfg):
            pytest.fail("build_algo ran although the folder was held")

        monkeypatch.setattr(train_module, "build_algo", build_algo)
        with pytest.raises(RunLockedError, match="the_first_run"):
            train_module.train(cfg)

    def test_the_lock_is_released_when_building_fails(self, tmp_path, monkeypatch):
        from gym_continuousDoubleAuction.train import train as train_module

        cfg = self._cfg(tmp_path)

        def build_algo(cfg):
            assert os.path.exists(os.path.join(cfg.checkpoint_dir, LOCK_FILE)), (
                "held while building"
            )
            raise RuntimeError("could not build")

        monkeypatch.setattr(train_module, "build_algo", build_algo)
        with pytest.raises(RuntimeError, match="could not build"):
            train_module.train(cfg)
        assert not os.path.exists(os.path.join(cfg.checkpoint_dir, LOCK_FILE))


class TestTwoRunsFindingTheSameStaleLock:
    """#296: the takeover of a stale lock is one step, so only one of two runs gets it."""

    def test_the_second_run_waits_for_the_first_and_is_then_refused(self, tmp_path):
        _write_lock(tmp_path, pid=_dead_pid())
        first, second = RunLock(str(tmp_path), "run_a"), RunLock(str(tmp_path), "run_b")
        # Both runs live in this process, so the first writes its parent's pid: a live pid that
        # is not this process's, which is what another running run looks like.
        real_payload = first._payload
        first._payload = lambda: {**real_payload(), "pid": os.getppid()}
        outcome = {}

        def second_acquire():
            try:
                second.acquire()
                outcome["result"] = "held"
            except RunLockedError:
                outcome["result"] = "refused"

        worker = threading.Thread(target=second_acquire)
        seen = {}
        real_read = first._read

        def read_then_let_the_other_run_try():
            held = real_read()  # the stale lock, as the first run sees it
            if "started" not in seen:
                seen["started"] = True
                worker.start()
                worker.join(timeout=0.5)
                seen["second_finished_early"] = not worker.is_alive()
            return held

        first._read = read_then_let_the_other_run_try
        try:
            first.acquire()
            worker.join(timeout=5)
            assert not seen["second_finished_early"], "the second run got in mid-takeover"
            assert outcome["result"] == "refused"
            assert first._held and not second._held
        finally:
            first.release()

    def test_the_guard_file_is_not_mistaken_for_a_lock(self, tmp_path):
        with RunLock(str(tmp_path), "run_a"):
            pass
        assert not (tmp_path / LOCK_FILE).exists()
        with RunLock(str(tmp_path), "run_b"):  # the guard left behind blocks nobody
            assert (tmp_path / LOCK_FILE).exists()
