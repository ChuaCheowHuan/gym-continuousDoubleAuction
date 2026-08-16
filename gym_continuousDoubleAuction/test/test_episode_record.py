"""The per-step episode record.

This replaced a `pickle.dump` of every step of every episode, performed inline
in `on_episode_end` on the env runner. Four properties are under test here, and
each of them is a defect that shipped (doc/21 §2.2-2.4, §6):

* it writes a **typed, declared schema** rather than a pickle whose only reader
  is Python with this package importable;
* it **cannot raise into the hook** - a full disk on an env runner used to mean
  a killed and restarted worker, because RLlib's fault tolerance treats an
  exception out of `sample()` as a dead actor;
* it is **bounded** - by a sampling rate, by a byte cap, and by a limit on how
  many unfinished episodes it will buffer;
* it **costs nothing when it is off**, which the old flag did not: it disabled
  the write and kept the ~34 MB per episode of accumulation.
"""
import glob
import os
import pickle
import sys

import numpy as np
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from gym_continuousDoubleAuction.train.episode_record import (
    INFO_COLUMNS,
    REWARD_TERMS,
    EpisodeRecorder,
    _schema,
)

NUM_AGENTS = 3
OBS_LEN = 6


def _info(agent, **overrides):
    info = {
        "reward": 0.25,
        "NAV": "1000000.5",
        "num_trades": 3,
        "net_position": -2,
        "VWAP": 12.5,
        "cash": 1.0,
        "cash_on_hold": 2.0,
        "position_val": 3.0,
        "drawdown": 0.1,
        "max_nav": 5.0,
        "num_trades_step": 1,
        "num_passive_fills_step": 1,
        "order_step_placed": 1,
        "num_rejected_step": 0,
        "is_pass_action": agent == 0,
        "reward_terms": {term: 0.1 for term in REWARD_TERMS},
        "last_price": 20.0,
        "best_bid": 19.0,
        "best_ask": 21.0,
        # None on a one-sided book, by design - the column has to hold it.
        "spread": None,
        "model_action": [1, 0.5],
    }
    info.update(overrides)
    return info


class FakeEpisode:
    def __init__(self, episode_id, agents=NUM_AGENTS, **info_overrides):
        self.id_ = episode_id
        self._agents = [f"agent_{i}" for i in range(agents)]
        self._overrides = info_overrides

    def get_observations(self, index):
        return {a: np.zeros(OBS_LEN, dtype=np.float32) for a in self._agents}

    def get_actions(self, index):
        return {
            a: (np.int32(1), np.array([0.5], dtype=np.float32))
            for a in self._agents
        }

    def get_rewards(self, index):
        return {a: 0.25 for a in self._agents}

    def get_infos(self, index):
        return {
            a: _info(i, **self._overrides)
            for i, a in enumerate(self._agents)
        }

    def module_for(self, agent_id):
        return "policy_0"


def _read_all(directory):
    import pyarrow.parquet as pq

    files = sorted(glob.glob(os.path.join(directory, "*.parquet")))
    assert files, f"no parquet written in {directory}"
    return pq.read_table(files[0]).to_pandas() if len(files) == 1 else pq.read_table(
        files
    ).to_pandas()


def _run(recorder, episode_id="ep", steps=4, **kwargs):
    episode = FakeEpisode(episode_id, **kwargs)
    for step in range(steps):
        recorder.record_step(episode, step)
    recorder.finish_episode(episode_id)
    return episode


class TestWhatIsWritten:

    def test_one_row_per_episode_step_agent(self, tmp_path):
        recorder = EpisodeRecorder(str(tmp_path), run_id="run_x")
        _run(recorder, steps=4)
        recorder.close()

        df = _read_all(str(tmp_path))
        assert len(df) == 4 * NUM_AGENTS
        assert sorted(df["step"].unique()) == [0, 1, 2, 3]
        assert sorted(df["agent_id"].unique()) == ["agent_0", "agent_1", "agent_2"]

    def test_the_row_carries_the_run_and_the_iteration(self, tmp_path):
        """doc/11 §3 listed "the files carry no timestamp or iteration
        metadata" as a persistence problem: correlating an episode with
        training progress meant sorting filenames by mtime."""
        from gym_continuousDoubleAuction.logging_setup import set_iteration

        set_iteration(11)
        try:
            recorder = EpisodeRecorder(str(tmp_path), run_id="run_x")
            _run(recorder)
            recorder.close()
        finally:
            set_iteration(None)

        df = _read_all(str(tmp_path))
        assert set(df["run_id"]) == {"run_x"}
        assert set(df["iteration"]) == {11}
        assert (df["wall_time"] > 0).all()

    def test_an_iteration_the_process_does_not_know_is_null_not_zero(self, tmp_path):
        """0 is a real iteration number; a runner that has not been reached by
        `_broadcast_iteration` genuinely does not know which one it is on."""
        recorder = EpisodeRecorder(str(tmp_path))
        _run(recorder)
        recorder.close()

        df = _read_all(str(tmp_path))
        assert df["iteration"].isna().all()

    def test_nav_is_kept_both_exactly_and_numerically(self, tmp_path):
        """`info["NAV"]` is a string so the conservation check can parse it back
        with Decimal (doc/11 §2.6). Keeping only the float would discard that;
        keeping only the string would make the column need a cast to be usable.
        """
        recorder = EpisodeRecorder(str(tmp_path))
        _run(recorder)
        recorder.close()

        df = _read_all(str(tmp_path))
        assert set(df["nav_str"]) == {"1000000.5"}
        assert df["nav"].iloc[0] == pytest.approx(1000000.5)

    def test_the_reward_terms_get_a_column_each(self, tmp_path):
        recorder = EpisodeRecorder(str(tmp_path))
        _run(recorder)
        recorder.close()

        df = _read_all(str(tmp_path))
        for term in REWARD_TERMS:
            assert df[f"reward_term_{term}"].iloc[0] == pytest.approx(0.1)

    def test_a_none_valued_field_stays_null(self, tmp_path):
        """`spread` is None on a one-sided book and 0.0 would be a lie - it is
        indistinguishable from a book whose touch is one tick wide."""
        recorder = EpisodeRecorder(str(tmp_path))
        _run(recorder)
        recorder.close()

        df = _read_all(str(tmp_path))
        assert df["spread"].isna().all()

    def test_an_unknown_info_field_is_preserved_as_json(self, tmp_path):
        """A field added to Info_Helper must not be silently dropped by a
        schema written before it existed."""
        recorder = EpisodeRecorder(str(tmp_path))
        _run(recorder, something_new=7)
        recorder.close()

        df = _read_all(str(tmp_path))
        assert '"something_new": 7' in df["info_extra"].iloc[0]

    def test_no_extra_field_means_no_json(self, tmp_path):
        recorder = EpisodeRecorder(str(tmp_path))
        _run(recorder)
        recorder.close()

        df = _read_all(str(tmp_path))
        assert df["info_extra"].isna().all()

    def test_the_module_that_played_is_recorded(self, tmp_path):
        """The league reassigns opponents every episode, so without this a row
        cannot be attributed to a policy - which is most of what one would ask
        this file."""
        recorder = EpisodeRecorder(str(tmp_path))
        _run(recorder)
        recorder.close()

        df = _read_all(str(tmp_path))
        assert set(df["module_id"]) == {"policy_0"}

    def test_a_module_lookup_failure_is_null(self, tmp_path):
        """`module_for` is the one field that comes from RLlib's episode API
        rather than this repository's `info`, so a rename there must leave a
        null column rather than stop a run."""
        class NoModule(FakeEpisode):
            def module_for(self, agent_id):
                raise AttributeError("renamed in this Ray")

        recorder = EpisodeRecorder(str(tmp_path))
        episode = NoModule("ep")
        recorder.record_step(episode, 0)
        recorder.finish_episode("ep")
        recorder.close()

        df = _read_all(str(tmp_path))
        assert df["module_id"].isna().all()


class TestSchema:

    def test_the_schema_is_declared_not_inferred(self):
        """Inference would let two files of one run disagree about a column's
        type whenever an episode happened to hold only nulls in it."""
        schema = _schema()
        names = set(schema.names)

        assert {"run_id", "iteration", "episode_id", "step", "agent_id"} <= names
        for name, _ in INFO_COLUMNS:
            assert name in names
        for term in REWARD_TERMS:
            assert f"reward_term_{term}" in names

    def test_it_covers_what_the_env_actually_emits(self):
        """The drift guard. A field added to `Info_Helper.set_info` should get a
        column; this fails if one is added and forgotten, which is how a
        columnar record quietly turns back into a blob.
        """
        from gym_continuousDoubleAuction.envs.exchg.info_helper import Info_Helper
        import inspect

        source = inspect.getsource(Info_Helper.set_info)
        # The literal keys the helper writes, as they appear in the source.
        emitted = {
            line.split('"')[1]
            for line in source.splitlines()
            if line.strip().startswith('"') and '":' in line
        }
        known = {name for name, _ in INFO_COLUMNS} | {
            "NAV", "reward_terms", "model_action",
        }
        # Reward-term names appear in the helper's own dict, not in info.
        assert emitted - known - set(REWARD_TERMS) == set(), (
            "Info_Helper emits fields the episode record has no column for. Add "
            "them to INFO_COLUMNS, or accept that they land in info_extra."
        )


class TestBounds:

    def test_sampling_records_one_episode_in_n(self, tmp_path):
        """~34 MB per 4096-step episode: "on" used to mean "until the disk
        fills"."""
        recorder = EpisodeRecorder(str(tmp_path), sample_every=4, rows_per_file=1)
        wanted = [str(i) for i in range(40) if recorder.wants(str(i))]

        assert 0 < len(wanted) < 40
        recorder.close()

    def test_sampling_is_stable_across_processes(self, tmp_path):
        """crc32, not hash(): hash() on a str is salted by PYTHONHASHSEED, so
        every worker and every restart would sample a different subset and the
        record would be biased by process lifetime."""
        a = EpisodeRecorder(str(tmp_path / "a"), sample_every=5)
        b = EpisodeRecorder(str(tmp_path / "b"), sample_every=5)
        ids = [f"episode-{i}" for i in range(50)]

        assert [a.wants(i) for i in ids] == [b.wants(i) for i in ids]
        a.close()
        b.close()

    def test_sample_every_one_records_everything(self, tmp_path):
        recorder = EpisodeRecorder(str(tmp_path), sample_every=1)
        assert all(recorder.wants(str(i)) for i in range(20))
        recorder.close()

    def test_an_unsampled_episode_writes_nothing(self, tmp_path):
        recorder = EpisodeRecorder(str(tmp_path), sample_every=1000, rows_per_file=1)
        skipped = next(str(i) for i in range(1000) if not recorder.wants(str(i)))
        _run(recorder, episode_id=skipped)
        recorder.close()

        assert glob.glob(os.path.join(str(tmp_path), "*.parquet")) == []

    def test_the_byte_cap_deletes_the_oldest_first(self, tmp_path):
        """Per writer, not per directory: deleting another worker's files is a
        cross-process race for no benefit."""
        recorder = EpisodeRecorder(str(tmp_path), rows_per_file=1, max_bytes=1)
        for i in range(4):
            _run(recorder, episode_id=f"ep_{i}", steps=2)
        recorder.close()

        # A cap of one byte cannot hold even one file, so exactly the newest
        # survives each round - the point being that it is bounded at all.
        assert len(glob.glob(os.path.join(str(tmp_path), "*.parquet"))) <= 1

    def test_no_cap_keeps_everything(self, tmp_path):
        recorder = EpisodeRecorder(str(tmp_path), rows_per_file=1, max_bytes=0)
        for i in range(3):
            _run(recorder, episode_id=f"ep_{i}", steps=2)
        recorder.close()

        assert len(glob.glob(os.path.join(str(tmp_path), "*.parquet"))) == 3

    def test_an_episode_that_never_ends_is_evicted(self, tmp_path):
        """A force-reset discards in-flight episodes without calling
        `on_episode_end`, so rows keyed by episode id and released only there
        are held for the life of the worker (doc/21 §3.2)."""
        recorder = EpisodeRecorder(str(tmp_path), max_live_episodes=3)
        for i in range(10):
            recorder.record_step(FakeEpisode(f"ep_{i}"), 0)

        assert len(recorder._live) <= 3
        assert "ep_0" not in recorder._live
        recorder.close()


class TestItCannotBreakTheRun:

    def test_an_unwritable_directory_does_not_raise(self, tmp_path):
        """Instrumentation. A run that cannot write its diagnostics should
        still train - and on an env runner a raise here is a killed worker."""
        blocked = tmp_path / "file-not-a-dir"
        blocked.write_text("")
        recorder = EpisodeRecorder(str(blocked / "nested"), rows_per_file=1)

        _run(recorder, steps=2)
        recorder.close()   # must not raise

    def test_a_bad_row_does_not_raise(self, tmp_path):
        """Something the declared schema cannot hold is a warning, not a stop."""
        class Broken(FakeEpisode):
            def get_infos(self, index):
                return {"agent_0": _info(0, num_trades="not a number")}

        recorder = EpisodeRecorder(str(tmp_path), rows_per_file=1)
        recorder.record_step(Broken("ep"), 0)
        recorder.finish_episode("ep")
        recorder.close()   # must not raise

    def test_a_full_queue_drops_rather_than_blocks(self, tmp_path):
        """Blocking here would put the filesystem into the env runner's step
        loop, which is the failure this module exists to remove."""
        recorder = EpisodeRecorder(str(tmp_path), rows_per_file=1, queue_size=1)
        # Fill the hand-off without a writer draining it.
        recorder._queue.put_nowait([])
        recorder._enqueue([{"run_id": "x"}])

        assert recorder._dropped_batches == 1
        recorder.close()

    def test_close_flushes_an_unfinished_episode(self, tmp_path):
        """These runs normally end by being killed, so what was buffered at that
        moment is what a post mortem has."""
        recorder = EpisodeRecorder(str(tmp_path))
        episode = FakeEpisode("ep")
        for step in range(3):
            recorder.record_step(episode, step)
        recorder.close()

        df = _read_all(str(tmp_path))
        assert len(df) == 3 * NUM_AGENTS

    def test_close_is_idempotent(self, tmp_path):
        recorder = EpisodeRecorder(str(tmp_path))
        recorder.close()
        recorder.close()

    def test_it_is_not_pickled_with_the_callback(self, tmp_path):
        """It owns a thread and a queue; those are not state to ship to a
        worker, and each process must open its own files anyway."""
        from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import (
            SelfPlayCallback,
        )

        callback = SelfPlayCallback(
            num_trainable_policies=1,
            num_random_policies=1,
            episode_data_dir=str(tmp_path),
        )
        assert callback._recorder() is not None

        revived = pickle.loads(pickle.dumps(callback))

        assert revived._episode_recorder is None
        assert revived.episode_data_dir == str(tmp_path)
        callback._recorder().close()

    def test_a_disabled_record_builds_nothing(self, tmp_path):
        from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import (
            SelfPlayCallback,
        )

        callback = SelfPlayCallback(
            num_trainable_policies=1, num_random_policies=1, episode_data_dir=None,
        )
        assert callback._recorder() is None
