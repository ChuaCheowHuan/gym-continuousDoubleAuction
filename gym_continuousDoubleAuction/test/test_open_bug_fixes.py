"""The three remaining open `bug` issues (#238, #244, #246).

Each test fails on the source the issue was filed against.
"""

import logging

import pytest

from gym_continuousDoubleAuction import config_loader, logging_setup
from gym_continuousDoubleAuction.train.train import TrainConfig, configure_run_logging


@pytest.fixture(autouse=True)
def _restore_logging():
    """`configure_run_logging` attaches a file handler and exports the log
    directory; put the process back as found (the same isolation
    `test_logging_setup.py` uses)."""
    import os

    root = logging.getLogger(logging_setup.ROOT_NAME)
    saved = (
        list(root.handlers),
        root.level,
        root.propagate,
        logging_setup._configured,
        logging_setup._log_file_path,
        os.environ.get(logging_setup.log_dir_env_var()),
    )
    yield
    for handler in list(root.handlers):
        if handler not in saved[0]:
            handler.close()
    root.handlers, root.level, root.propagate = saved[0], saved[1], saved[2]
    logging_setup._configured, logging_setup._log_file_path = saved[3], saved[4]
    logging_setup.set_iteration(None)
    if saved[5] is None:
        os.environ.pop(logging_setup.log_dir_env_var(), None)
    else:
        os.environ[logging_setup.log_dir_env_var()] = saved[5]
    config_loader.reload()


class TestRunLoggingRestoresPropagation:
    """#238: an earlier run with `ray_log_encoding` set left `propagate=False`
    for a later run without one."""

    @staticmethod
    def _configure(tmp_path, encoding):
        configure_run_logging(
            TrainConfig(
                log_base_dir=str(tmp_path), episode_data_dir=None, ray_log_encoding=encoding
            )
        )
        return logging.getLogger(logging_setup.ROOT_NAME).propagate

    def test_an_encoding_turns_it_off(self, tmp_path):
        assert self._configure(tmp_path, "JSON") is False

    def test_no_encoding_turns_it_on(self, tmp_path):
        assert self._configure(tmp_path, "") is True

    def test_a_later_run_without_an_encoding_gets_it_back(self, tmp_path):
        assert self._configure(tmp_path / "a", "JSON") is False
        assert self._configure(tmp_path / "b", "") is True

    def test_root_handlers_see_the_package_again(self, tmp_path, caplog):
        self._configure(tmp_path / "a", "JSON")
        self._configure(tmp_path / "b", "")
        with caplog.at_level(logging.INFO, logger=logging_setup.ROOT_NAME):
            logging_setup.get_logger("gym_continuousDoubleAuction.t238").info("seen")
        assert "seen" in caplog.text


class TestTheByteCapKeepsTheNewestFile:
    """#246: when a single file was larger than `episode_max_bytes` the cap
    removed every file, the newest included, and nothing said so."""

    @staticmethod
    def _record(tmp_path, episodes=3, **kwargs):
        import glob
        import os
        from gym_continuousDoubleAuction.test.test_episode_record import _run
        from gym_continuousDoubleAuction.train.episode_record import EpisodeRecorder

        recorder = EpisodeRecorder(str(tmp_path), rows_per_file=1, **kwargs)
        for i in range(episodes):
            _run(recorder, episode_id=f"ep_{i}", steps=2)
        recorder.close()
        return sorted(glob.glob(os.path.join(str(tmp_path), "*.parquet"))), recorder

    def test_a_cap_smaller_than_one_file_keeps_exactly_the_newest(self, tmp_path):
        import pyarrow.parquet as pq

        files, recorder = self._record(tmp_path, max_bytes=1)
        assert len(files) == 1
        # The newest episode, not an older one that happened to survive.
        assert set(pq.read_table(files[0]).to_pandas()["episode_id"]) == {"ep_2"}

    def test_the_rows_counted_as_written_are_on_disk(self, tmp_path):
        files, recorder = self._record(tmp_path, max_bytes=1)
        assert files and recorder._written_rows > 0

    def test_it_warns_once_that_the_cap_is_too_small(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING, logger=logging_setup.ROOT_NAME):
            self._record(tmp_path, episodes=4, max_bytes=1)
        warnings = [r for r in caplog.records if "larger than episode_max_bytes" in r.getMessage()]
        assert len(warnings) == 1

    def test_a_cap_that_fits_several_files_still_trims_the_oldest(self, tmp_path):
        import os

        files, _ = self._record(tmp_path, episodes=1, max_bytes=0)
        one = os.path.getsize(files[0])
        import shutil

        shutil.rmtree(tmp_path)
        tmp_path.mkdir()
        files, _ = self._record(tmp_path, episodes=6, max_bytes=int(one * 2.5))
        assert 1 < len(files) < 6

    def test_no_cap_warns_about_nothing(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING, logger=logging_setup.ROOT_NAME):
            self._record(tmp_path, max_bytes=0)
        assert not [r for r in caplog.records if "episode_max_bytes" in r.getMessage()]


class TestEnvVarsContractIsRayInit:
    """#244: `runtime` said `apply_env_vars()` had to run before ray is imported,
    while the entry points import ray at module scope and call it in `main()`.

    The only variable configured is read when Ray's memory monitor is
    constructed, not at import, so the contract that holds - and that is pinned
    here - is the order that matters: exported before `ray.init`, in every entry
    point that starts Ray.
    """

    @pytest.mark.parametrize(
        "module",
        [
            "gym_continuousDoubleAuction.train.train",
            "gym_continuousDoubleAuction.train.evaluate",
            "gym_continuousDoubleAuction.train.compare",
        ],
    )
    def test_the_entry_point_exports_before_it_starts_ray(self, module):
        import importlib
        import inspect

        source = inspect.getsource(importlib.import_module(module).main)
        assert "apply_env_vars()" in source and "ray.init(" in source
        assert source.index("apply_env_vars()") < source.index("ray.init(")

    def test_the_docs_no_longer_claim_an_import_order_ray_does_not_need(self):
        from gym_continuousDoubleAuction.train import runtime

        text = (runtime.__doc__ or "") + (runtime.apply_env_vars.__doc__ or "")
        assert "before ray is first imported" not in text
        assert "before `ray.init`" in text

    def test_the_configured_variable_is_not_read_at_ray_import(self):
        """The fact the corrected contract rests on, checked against the installed
        Ray: if a Ray upgrade starts reading it at import, this fails and the
        call has to move ahead of the imports."""
        import inspect
        from ray._private import memory_monitor

        source = inspect.getsource(memory_monitor)
        first_function = source.index("\n    def ")
        assert "RAY_DEBUG_DISABLE_MEMORY_MONITOR" in source
        assert "RAY_DEBUG_DISABLE_MEMORY_MONITOR" not in source[:first_function]
        from gym_continuousDoubleAuction.config_loader import constants

        assert set(constants("runtime_env_vars")) - {"_source", "_note"} == {
            "RAY_DEBUG_DISABLE_MEMORY_MONITOR"
        }
