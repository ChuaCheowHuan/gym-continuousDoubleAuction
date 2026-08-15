"""A real short run, checked for the two things a run used to leave no trace of.

`test_progress_log.py` covers the writer and the metric extraction against a
FakeAlgo whose results are hand-built. That leaves the assumption underneath
both untested: that a *real* PPO iteration on this env actually produces a
`learners` block containing `vf_explained_var` for each trainable module, and
that a real result dict survives the JSON round trip. A rename in RLlib, or a
result carrying something `_json_safe` cannot handle, would sail past the unit
tests and leave the run logging nothing.

So this builds an actual PPO and trains it, sized for speed rather than
learning.

What it asserts about the *value* of vf_explained_var is split in two, and the
split is the point. `!= 0.0` looks like the obvious guard against a critic that
never received a gradient, and it is worthless here: a run of this suite reports
values around 1e-5 - the S1-1 signature doc/17 17.3 records from two real GPU
runs as "0.0 to 1.8e-07" - and every one of them is nonzero, so the assertion
passes on a critic that is comprehensively dead. Floating-point noise is not
evidence of learning.

So the unconditional assertions are only that the metric is present and finite
(a diverged value loss really does show up as NaN, and that is worth catching),
and the substantive claim - that the critic explains a non-trivial share of
return variance - is a separate strict xfail. It fails today because S1-1 is
open and unfixed. When S1-1 is fixed it will XPASS, which under strict xfail
fails the build: that is deliberate, and the fix is to delete the marker,
turning this into the live regression guard it cannot be while the defect is
still there.
"""
import json
import math
import os
import shutil
import tempfile

import pytest
import ray

from gym_continuousDoubleAuction.train.train import (
    TrainConfig,
    VF_EXPLAINED_VAR_KEY,
    train,
    vf_explained_var,
)
from gym_continuousDoubleAuction.train.policy.policy_handler import (
    trainable_policy_ids,
)

NUM_ITERS = 3

# Matches test_checkpoint_roundtrip.py: the smallest run that still exercises
# the real learner path.
TEST_CFG = dict(
    num_agents=4,
    num_trained_agents=2,
    max_step=64,
    num_episodes_per_iter=4,
    num_epochs=1,
    minibatch_size=64,
    num_env_runners=0,
    num_learners=0,
    num_gpus_per_learner=0,
    episode_data_dir=None,
    log_level="ERROR",
)


class TestProgressAndCriticHealth:
    """One real training run of a few iterations, then read what it left behind."""

    @classmethod
    def setup_class(cls):
        ray.init(
            ignore_reinit_error=True,
            include_dashboard=False,
            log_to_driver=False,
            num_cpus=2,
        )
        cls.tmpdir = tempfile.mkdtemp(prefix="cda_progress_")
        cls.cfg = TrainConfig(
            log_base_dir=cls.tmpdir,
            num_iters=NUM_ITERS,
            chkpt_freq=0,
            chkpt_keep=0,
            **TEST_CFG,
        )
        cls.algo, cls.last_result = train(cls.cfg)

        with open(cls.cfg.progress_path) as fh:
            cls.lines = [json.loads(line) for line in fh if line.strip()]

    @classmethod
    def teardown_class(cls):
        cls.algo.stop()
        ray.shutdown()
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_one_line_per_iteration(self):
        assert os.path.isfile(self.cfg.progress_path)
        assert len(self.lines) == NUM_ITERS
        assert [line["training_iteration"] for line in self.lines] == list(
            range(1, NUM_ITERS + 1)
        )

    def test_a_real_result_survives_the_json_round_trip(self):
        """Parsing above already proved it; this pins what has to be *in* it.

        A writer that silently dropped the nested blocks would still produce
        parseable lines, so the assertion is that the metrics are there, not
        merely that the file is valid JSON.
        """
        last = self.lines[-1]
        assert last["env_runners"]["num_env_steps_sampled"] > 0
        assert last["learners"], "the result carried no learner block"

    def test_vf_explained_var_is_reported_for_every_trainable_module(self):
        """The metric RLlib really emits, under the key this code really reads."""
        expected = trainable_policy_ids(self.cfg.num_trained_agents)
        reported = vf_explained_var(self.last_result, self.cfg)

        assert sorted(reported) == sorted(expected), (
            f"expected {VF_EXPLAINED_VAR_KEY} for {expected}, got "
            f"{sorted(reported)}. If this is empty, RLlib has moved or renamed "
            f"the key and the critic is no longer observable."
        )

    def test_the_metric_is_finite(self):
        """A NaN here is a diverged value loss, which is a real regression.

        This is the whole unconditional claim about the value - see the module
        docstring, and `test_the_critic_actually_explains_something` below for
        the claim that would mean the critic works.
        """
        for pid, value in vf_explained_var(self.last_result, self.cfg).items():
            assert math.isfinite(value), (
                f"{pid} reported a non-finite {VF_EXPLAINED_VAR_KEY} ({value}); "
                f"the value loss has diverged"
            )

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "S1-1: the critic receives no gradient, so vf_explained_var sits in "
            "the 1e-5 noise floor. Fixing S1-1 makes this XPASS and fails the "
            "build - remove the marker at that point, which turns this into the "
            "regression guard it cannot be while the defect is open."
        ),
    )
    def test_the_critic_actually_explains_something(self):
        """The assertion that would have caught S1-1, pinned as a known failure.

        The threshold is loose on purpose. `NUM_ITERS` iterations at this size
        teach a *working* critic very little, so this is not a measure of how
        well it learns - it is the line between "explains a share of the
        variance" and "is indistinguishable from noise", which is the only
        distinction a run this short can support.
        """
        reported = vf_explained_var(self.last_result, self.cfg)

        noise = {
            pid: value for pid, value in reported.items() if abs(value) < 1e-3
        }
        assert not noise, (
            f"{VF_EXPLAINED_VAR_KEY} is in the noise floor for {sorted(noise)} "
            f"after {NUM_ITERS} iterations ({noise}): the critic took no useful "
            f"gradient, PPO degenerates to REINFORCE, and every advantage this "
            f"run computes is noise. See doc/15 S1-1."
        )

    def test_the_file_carries_it_too(self):
        """Not just the returned result: the on-disk record is the durable one."""
        for pid in trainable_policy_ids(self.cfg.num_trained_agents):
            values = [
                line["learners"][pid][VF_EXPLAINED_VAR_KEY] for line in self.lines
            ]
            assert len(values) == NUM_ITERS
            assert all(v is None or isinstance(v, float) for v in values), values
