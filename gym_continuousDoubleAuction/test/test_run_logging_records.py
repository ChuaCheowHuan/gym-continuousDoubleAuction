"""Tests for run logging records.

Moved from `test_open_bug_fixes.py` by issue #361; the class docstrings keep the
original issue numbers.
"""

import logging


from gym_continuousDoubleAuction import logging_setup

from gym_continuousDoubleAuction.train.train import TrainConfig, configure_run_logging


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
