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

    def test_it_sits_beside_the_checkpoints(self, cfg):
        """Under log_base_dir, so a runtime profile that redirects results moves it."""
        assert cfg.progress_path == os.path.join(
            os.path.abspath(cfg.log_base_dir), PROGRESS_FILE
        )
        assert os.path.dirname(cfg.progress_path) == os.path.dirname(
            cfg.checkpoint_dir
        )

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
