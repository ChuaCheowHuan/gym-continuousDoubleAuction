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
    saved = (list(root.handlers), root.level, root.propagate,
             logging_setup._configured, logging_setup._log_file_path,
             os.environ.get(logging_setup.log_dir_env_var()))
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
        configure_run_logging(TrainConfig(
            log_base_dir=str(tmp_path), episode_data_dir=None,
            ray_log_encoding=encoding))
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
