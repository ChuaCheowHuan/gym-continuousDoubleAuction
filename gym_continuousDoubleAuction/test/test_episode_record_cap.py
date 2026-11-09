"""Tests for episode record cap.

Moved from `test_open_bug_fixes.py` by issue #361; the class docstrings keep the
original issue numbers.
"""

import logging


from gym_continuousDoubleAuction import logging_setup


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
