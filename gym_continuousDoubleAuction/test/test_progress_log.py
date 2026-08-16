"""The per-iteration `progress.jsonl` record, and what it does with awkward values.

`algo.train()` returns a full metrics dict every iteration. The driver loop used
to pull two keys out of it for a log line and drop the rest, so a finished run
left behind checkpoints, a scrollback of log lines, and no machine-readable
record of how it got there - there was no `results/progress.jsonl` and no Tune
`progress.csv`, because the loop calls `algo.train()` directly rather than going
through a Tuner. These tests pin the record.

The awkward values matter as much as the happy path. RLlib results carry numpy
scalars and arrays, occasionally an object with no JSON form, and NaNs early in
a run; a logger that raised on any of those would take down a training run that
was otherwise fine. See doc/11 2.1.
"""
import dataclasses
import json
import logging
import os
from types import SimpleNamespace

import numpy as np
import pytest

from gym_continuousDoubleAuction import logging_setup
from gym_continuousDoubleAuction.logging_setup import ROOT_NAME as LOGGER
from gym_continuousDoubleAuction.train import train as train_mod
from gym_continuousDoubleAuction.train.train import (
    PROGRESS_FILE,
    TrainConfig,
    VF_EXPLAINED_VAR_KEY,
    _append_progress,
    _json_safe,
    train,
    vf_explained_var,
)


def _learner_block(**per_module):
    """A result's `learners` block, keyed the way RLlib keys it."""
    from ray.rllib.utils.metrics import LEARNER_RESULTS

    return {LEARNER_RESULTS: dict(per_module)}


class FakeAlgo:
    """Enough of an Algorithm to drive the loop, returning a realistic result.

    The result deliberately carries numpy types and a learner block: a fake that
    returned only plain floats would pass a JSON writer that cannot actually
    survive an RLlib result.
    """

    def __init__(self, start_iteration=0, vf_values=(0.42, 0.31)):
        self.iteration = start_iteration
        self.callbacks = []
        self.vf_values = vf_values

    def train(self):
        self.iteration += 1
        result = {
            "training_iteration": self.iteration,
            "env_runners": {
                "num_env_steps_sampled": np.int64(256),
                "module_episode_returns_mean": {"policy_0": np.float32(1.5)},
            },
        }
        result.update(_learner_block(**{
            f"policy_{i}": {VF_EXPLAINED_VAR_KEY: np.float32(v)}
            for i, v in enumerate(self.vf_values)
        }))
        return result

    def save(self, path):
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, "rllib_checkpoint.json"), "w") as fh:
            json.dump({"marker": str(self.iteration)}, fh)
        return path


@pytest.fixture
def cfg(tmp_path):
    return TrainConfig(
        log_base_dir=str(tmp_path / "results"),
        num_trained_agents=2,
        num_agents=4,
        chkpt_freq=0,
    )


@pytest.fixture
def looped(cfg, monkeypatch):
    """`train()` with the algorithm build stubbed out, for a given iteration count."""

    def run(num_iters, algo=None):
        algo = algo if algo is not None else FakeAlgo()
        monkeypatch.setattr(train_mod, "build_algo", lambda _cfg: (algo, None))
        train(dataclasses.replace(cfg, num_iters=num_iters))
        return algo

    return run


def _lines(cfg):
    with open(cfg.progress_path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


class TestProgressFile:
    """Where the file lands and what a run writes into it."""

    def test_it_sits_in_the_run_directory(self, cfg):
        """Under log_base_dir, so a runtime profile that redirects results moves
        it - but in this run's own directory beneath it, so two runs sharing a
        log_base_dir cannot interleave writes into one file."""
        assert cfg.progress_path == os.path.join(
            os.path.abspath(cfg.log_base_dir), cfg.run_id, PROGRESS_FILE
        )
        assert os.path.dirname(cfg.progress_path) == cfg.run_dir
        assert cfg.run_dir.startswith(os.path.abspath(cfg.log_base_dir))

    def test_the_checkpoint_tree_is_not_run_scoped(self, cfg):
        """The one thing deliberately shared across runs.

        Restoring from a disconnect means finding the newest `iter_*` written by
        an *earlier* run. A per-run checkpoint tree would hide it and every
        resumed run would start from nothing.
        """
        assert cfg.checkpoint_dir == os.path.join(
            os.path.abspath(cfg.log_base_dir), "chkpt"
        )
        assert not cfg.checkpoint_dir.startswith(cfg.run_dir)

    def test_one_line_per_iteration(self, cfg, looped):
        looped(4)

        lines = _lines(cfg)
        assert len(lines) == 4
        assert [line["training_iteration"] for line in lines] == [1, 2, 3, 4]

    def test_a_second_run_appends_rather_than_truncating(self, cfg, looped):
        """A resumed run must not erase the history it is resuming from."""
        looped(2)
        looped(4, algo=FakeAlgo(start_iteration=2))

        assert [line["training_iteration"] for line in _lines(cfg)] == [1, 2, 3, 4]

    def test_the_whole_result_is_kept_not_just_the_logged_keys(self, cfg, looped):
        """The point of the file: the metrics the log line does not print.

        `_log_iteration` shows returns and vf_explained_var. Everything else
        RLlib computed - loss terms, KL, entropy, timers - is only ever in here.
        """
        looped(1)

        line = _lines(cfg)[0]
        assert line["env_runners"]["num_env_steps_sampled"] == 256
        assert line["learners"]["policy_0"][VF_EXPLAINED_VAR_KEY] == pytest.approx(0.42)

    def test_numbers_survive_as_numbers(self, cfg, looped):
        """numpy scalars must not arrive as quoted strings.

        A bare `json.dump(..., default=str)` would write "256" and "1.5", and
        every consumer would have to parse them back.
        """
        looped(1)

        env_runners = _lines(cfg)[0]["env_runners"]
        assert isinstance(env_runners["num_env_steps_sampled"], int)
        assert isinstance(env_runners["module_episode_returns_mean"]["policy_0"], float)


class TestAwkwardValues:
    """What `_json_safe` does with the things RLlib actually puts in a result."""

    def test_numpy_scalars_and_arrays(self):
        assert _json_safe(np.float32(1.5)) == 1.5
        assert _json_safe(np.int64(7)) == 7
        assert _json_safe(np.bool_(True)) is True
        assert _json_safe(np.array([1.0, 2.0])) == [1.0, 2.0]

    def test_non_finite_floats_become_null(self):
        """NaN and Infinity are not valid JSON, however happily Python emits them.

        An untrained critic's vf_explained_var is legitimately NaN, so this is a
        normal early-iteration value, not a corrupt one.
        """
        assert _json_safe(float("nan")) is None
        assert _json_safe(float("inf")) is None
        assert _json_safe({"vf": np.float32("nan")}) == {"vf": None}

    def test_an_object_with_no_json_form_is_stringified(self):
        assert _json_safe(SimpleNamespace(a=1)).startswith("namespace(")

    def test_non_string_dict_keys_are_coerced(self):
        assert _json_safe({1: "a"}) == {"1": "a"}

    def test_the_output_is_strictly_parseable(self, cfg):
        """The whole contract: whatever went in, strict JSON comes out.

        `parse_constant` fires on NaN/Infinity/-Infinity, which a plain
        `json.dump` would happily emit and a strict reader would reject.
        """
        _append_progress(
            {
                "arr": np.arange(3),
                "nan": float("nan"),
                "obj": SimpleNamespace(a=1),
                "nested": {"tup": (np.float64(1.0), None, True)},
            },
            cfg,
        )

        with open(cfg.progress_path) as fh:
            written = fh.read()

        parsed = json.loads(written, parse_constant=_reject)
        assert parsed["arr"] == [0, 1, 2]
        assert parsed["nan"] is None
        assert parsed["nested"]["tup"] == [1.0, None, True]
        assert isinstance(parsed["obj"], str)


def _reject(constant):
    raise AssertionError(f"non-JSON constant {constant!r} was written")


class TestFailuresDoNotStopTraining:
    """Instrumentation must never be the thing that kills a run."""

    def test_an_unwritable_path_warns_and_carries_on(self, cfg, caplog, monkeypatch):
        def explode(*_args, **_kwargs):
            raise OSError("No space left on device")

        monkeypatch.setattr(train_mod, "open", explode, raising=False)

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            _append_progress({"training_iteration": 1}, cfg)

        assert "could not append" in caplog.text

    def test_the_loop_finishes_even_when_every_write_fails(self, cfg, monkeypatch, looped):
        monkeypatch.setattr(
            train_mod, "_json_safe",
            lambda _r: (_ for _ in ()).throw(RuntimeError("unserialisable")),
        )

        algo = looped(3)

        assert algo.iteration == 3, "a logging failure stopped the training loop"


class TestVfExplainedVar:
    """The critic-health metric pulled out of the learner block."""

    def test_read_for_every_trainable_module(self, cfg):
        result = _learner_block(
            policy_0={VF_EXPLAINED_VAR_KEY: 0.5},
            policy_1={VF_EXPLAINED_VAR_KEY: 0.25},
        )

        assert vf_explained_var(result, cfg) == {"policy_0": 0.5, "policy_1": 0.25}

    def test_frozen_modules_are_not_expected(self, cfg):
        """Champions and random baselines never appear in the learner block.

        They are not in `policies_to_train`, so RLlib computes no learner stats
        for them. Asking for them would be asking for a KeyError.
        """
        result = _learner_block(
            policy_0={VF_EXPLAINED_VAR_KEY: 0.5},
            policy_1={VF_EXPLAINED_VAR_KEY: 0.25},
            policy_2={VF_EXPLAINED_VAR_KEY: 0.0},
            champion_v1={VF_EXPLAINED_VAR_KEY: 0.0},
        )

        assert sorted(vf_explained_var(result, cfg)) == ["policy_0", "policy_1"]

    def test_a_missing_module_is_omitted_not_zeroed(self, cfg):
        """Absent and "explains nothing" are different, and 0.0 is the alarm."""
        result = _learner_block(policy_0={VF_EXPLAINED_VAR_KEY: 0.5})

        assert vf_explained_var(result, cfg) == {"policy_0": 0.5}

    def test_a_result_without_a_learner_block_is_empty_not_an_error(self, cfg):
        assert vf_explained_var({}, cfg) == {}
        assert vf_explained_var({"learners": None}, cfg) == {}

    def test_it_reaches_the_iteration_log_line(self, cfg, caplog, looped):
        with caplog.at_level(logging.INFO, logger=LOGGER):
            looped(1)

        assert "vf_explained_var" in caplog.text
        assert "policy_0=0.42" in caplog.text

    def test_the_log_line_does_not_round_a_dead_critic_to_zero(self, cfg, caplog, looped):
        """3 significant figures, not 3 decimals.

        The values this metric takes on a broken run are ~1e-5 (see doc/17
        17.3), and `round(3.8e-05, 3)` is `0.0` - which prints identically to a
        module that reported nothing, losing the distinction the metric exists
        to draw.
        """
        with caplog.at_level(logging.INFO, logger=LOGGER):
            looped(1, algo=FakeAlgo(vf_values=(3.82e-05, -1.25e-05)))

        assert "policy_0=3.82e-05" in caplog.text
        assert "policy_0=0.0" not in caplog.text

    def test_a_result_with_no_learner_stats_says_so(self, cfg, caplog, looped):
        """An empty dict in the log line reads as "all zero"; "n/a" does not."""
        with caplog.at_level(logging.INFO, logger=LOGGER):
            looped(1, algo=FakeAlgo(vf_values=()))

        assert "vf_explained_var: n/a" in caplog.text


class TestRunDirectoryIsolation:
    """Two runs must not write into each other's files.

    The per-worker log name keeps the processes of one run apart, but nothing
    kept two *runs* apart: `log_base_dir` defaulted to a fixed "results", so two
    drivers - concurrent runs, or a notebook alongside a CLI run - both took the
    un-suffixed `run.log` and both appended to one `progress.jsonl`. The first
    is the cross-process RotatingFileHandler race; the second interleaves two
    writers inside a single JSON line, because `json.dump` writes incrementally
    and an RLlib result dict is larger than the stream buffer.
    """

    def test_each_config_gets_its_own_run_id(self):
        assert TrainConfig().run_id != TrainConfig().run_id

    def test_a_generated_id_is_a_readable_timestamp(self):
        import re

        assert re.fullmatch(r"run_\d{8}_\d{6}_[0-9a-f]{4}", TrainConfig().run_id)

    def test_replace_keeps_the_id(self, cfg):
        """The runtime profiles and half the tests build configs with
        `dataclasses.replace`; re-rolling the id there would move the run's
        output directory partway through a run."""
        assert dataclasses.replace(cfg, num_iters=99).run_id == cfg.run_id

    def test_the_id_is_not_part_of_the_configuration(self, cfg):
        """It names the run, it does not configure it. In __eq__ it would make
        no two TrainConfigs equal - including the checked-in file against its
        own defaults, and a restored checkpoint's config against the current
        one."""
        assert dataclasses.replace(cfg, run_id="something-else") == cfg

    def test_a_pinned_id_is_honoured(self, tmp_path):
        """Which is how a restored run extends the progress history it left."""
        pinned = TrainConfig(log_base_dir=str(tmp_path), run_id="pinned")
        assert pinned.run_dir == os.path.join(str(tmp_path), "pinned")

    def test_two_runs_write_separate_progress_files(self, cfg, monkeypatch):
        first = dataclasses.replace(cfg, num_iters=2)
        second = dataclasses.replace(cfg, num_iters=2, run_id="second")

        for config in (first, second):
            monkeypatch.setattr(
                train_mod, "build_algo", lambda _cfg: (FakeAlgo(), None)
            )
            train(config)

        assert first.progress_path != second.progress_path
        assert len(_lines(first)) == 2
        assert len(_lines(second)) == 2

    def test_a_pinned_id_extends_rather_than_starting_over(self, cfg, monkeypatch):
        """The append-mode property, still true inside a run directory."""
        config = dataclasses.replace(cfg, run_id="resumed", num_iters=2)
        monkeypatch.setattr(
            train_mod, "build_algo", lambda _cfg: (FakeAlgo(), None)
        )
        train(config)
        monkeypatch.setattr(
            train_mod,
            "build_algo",
            lambda _cfg: (FakeAlgo(start_iteration=2), None),
        )
        train(dataclasses.replace(config, num_iters=4))

        assert [line["training_iteration"] for line in _lines(config)] == [
            1, 2, 3, 4
        ]


class TestIterationReachesTheEnvRunners:
    """`iter=` on a worker's log lines.

    The episode callbacks run on the env runners, so with `num_env_runners > 0`
    the per-episode NAV tables and the conservation ERROR are emitted there and
    nowhere else - and every one of those lines read `iter=-`, leaving them
    joinable to a progress.jsonl row only by wall-clock order. The driver knew
    the number the whole time; it just never sent it.
    """

    class FakeGroup:
        def __init__(self, fail=False):
            self.applied = []
            self.fail = fail
            self.local_flags = []

        def foreach_env_runner(self, func, local_env_runner=True, **kwargs):
            if self.fail:
                raise RuntimeError("runner is restarting")
            self.local_flags.append(local_env_runner)
            runner = object()
            func(runner)
            self.applied.append(logging_setup.current_iteration())
            return [True]

    def test_every_iteration_is_broadcast_before_sampling(self, cfg, monkeypatch):
        algo = FakeAlgo()
        group = self.FakeGroup()
        algo.env_runner_group = group
        monkeypatch.setattr(train_mod, "build_algo", lambda _cfg: (algo, None))

        train(dataclasses.replace(cfg, num_iters=3))

        assert group.applied == [1, 2, 3]

    def test_the_local_runner_is_skipped(self, cfg, monkeypatch):
        """It shares this process, and set_iteration has already tagged it."""
        algo = FakeAlgo()
        group = self.FakeGroup()
        algo.env_runner_group = group
        monkeypatch.setattr(train_mod, "build_algo", lambda _cfg: (algo, None))

        train(dataclasses.replace(cfg, num_iters=1))

        assert group.local_flags == [False]

    def test_a_failing_broadcast_does_not_stop_training(self, cfg, monkeypatch):
        """Instrumentation. A runner that is restarting must cost `iter=-` on
        its lines, not the run."""
        algo = FakeAlgo()
        algo.env_runner_group = self.FakeGroup(fail=True)
        monkeypatch.setattr(train_mod, "build_algo", lambda _cfg: (algo, None))

        train(dataclasses.replace(cfg, num_iters=2))

        assert [line["training_iteration"] for line in _lines(cfg)] == [1, 2]

    def test_an_algorithm_without_runners_is_fine(self, cfg, monkeypatch):
        """The FakeAlgo everywhere else in this file has no env_runner_group."""
        algo = FakeAlgo()
        monkeypatch.setattr(train_mod, "build_algo", lambda _cfg: (algo, None))

        train(dataclasses.replace(cfg, num_iters=1))

        assert len(_lines(cfg)) == 1


class TestIterationBroadcastReportsPartialDelivery:
    """A runner that does not answer keeps the *previous* iteration.

    `foreach_env_runner` defaults to `healthy_only=True` and silently skips a
    runner that is restarting or slower than the 10s timeout. That runner is
    still alive and still sampling, and `set_iteration` has left the last value
    it was told in place - so its NAV tables and its recorded rows are labelled
    with the wrong iteration rather than with `-`.

    A stale but plausible number is worse than a missing one: nothing about it
    looks wrong. Blocking sampling until every runner acknowledges a *log field*
    is not the trade to make, so the broadcast stays best-effort and says when
    it fell short.
    """

    class _Group:
        def __init__(self, acked, healthy):
            self._acked = acked
            self._healthy = healthy
            self.calls = 0

        def foreach_env_runner(self, func, **kwargs):
            self.calls += 1
            return [True] * self._acked

        def num_healthy_remote_env_runners(self):
            return self._healthy

    def _algo(self, acked, healthy):
        group = self._Group(acked, healthy)
        return SimpleNamespace(env_runner_group=group), group

    def test_full_delivery_is_quiet(self, caplog):
        algo, group = self._algo(acked=2, healthy=2)

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            train_mod._broadcast_iteration(algo, 7)

        assert group.calls == 1
        assert caplog.text == ""

    def test_partial_delivery_is_reported(self, caplog):
        algo, _ = self._algo(acked=1, healthy=3)

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            train_mod._broadcast_iteration(algo, 7)

        assert "reached only 1 of 3 env runners" in caplog.text
        assert "iteration 7" in caplog.text

    def test_a_group_that_cannot_be_counted_stays_quiet(self, caplog):
        """The count is itself best-effort - an RLlib rename here must not turn
        a working broadcast into a warning on every iteration."""
        class NoCount(self._Group):
            def num_healthy_remote_env_runners(self):
                raise AttributeError("renamed in this Ray")

        algo = SimpleNamespace(env_runner_group=NoCount(1, 3))

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            train_mod._broadcast_iteration(algo, 7)

        assert caplog.text == ""

    def test_a_failed_broadcast_still_degrades_quietly(self, caplog):
        """The pre-existing contract: a runner that is restarting must cost
        `iter=-`, never the run."""
        class Broken:
            def foreach_env_runner(self, func, **kwargs):
                raise RuntimeError("actor unreachable")

        algo = SimpleNamespace(env_runner_group=Broken())

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            train_mod._broadcast_iteration(algo, 7)

        assert caplog.text == ""
