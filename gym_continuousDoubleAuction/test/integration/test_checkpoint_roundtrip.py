"""What a real RLlib save/restore actually brings back.

`test_checkpointing.py` covers the driver logic around checkpointing - naming,
retention, restore selection, iteration accounting - against a FakeAlgo whose
`save()` writes a one-key marker file and whose loader is monkeypatched out.
That leaves the thing the checkpoints exist for untested: whether a restored
run resumes with its learned weights, its optimizer, its league, and its
iteration count, or quietly starts over from a random initialisation.

This module does one real save and one real restore and checks all four. It
builds an actual PPO, so it is the slowest test in the suite; everything it
configures is sized for speed, not learning.

Weights are compared on the LearnerGroup, which is what the checkpoint holds
and what training continues from. The EnvRunner copy is deliberately not the
reference: RLlib syncs only the acting path to it, so a runner's critic tensors
sit at their initial values even in a run that never restarts, and comparing
them would fail against a perfectly good checkpoint. `ACTING_ONLY` names the
subset a runner is expected to keep current, and the champion test uses it to
check the weights that actually choose actions.
"""
import os
import shutil
import tempfile
from dataclasses import replace as dataclasses_replace

import numpy as np
import ray
import torch
from ray.rllib.core import COMPONENT_LEARNER, COMPONENT_RL_MODULE
from ray.rllib.utils.metrics import ENV_RUNNER_RESULTS

from gym_continuousDoubleAuction.train import train as train_mod
from gym_continuousDoubleAuction.train.train import (
    CHECKPOINT_PREFIX,
    LEAGUE_STATE_FILE,
    TrainConfig,
    build_algo,
    build_config,
    save_checkpoint,
)
from gym_continuousDoubleAuction.train.policy.policy_handler import (
    trainable_policy_ids,
)

# Small and short: this test is about the round trip, not learning.
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


def _acting_only(state):
    """The parameters inference uses, which are the ones EnvRunners are synced.

    The value function - `critic_encoder` and the `vf` head - is a training-time
    structure: it never runs on an EnvRunner, so its copy there is whatever the
    module was built with.
    """
    return {
        k: v for k, v in state.items()
        if "critic" not in k and not k.startswith("vf.")
    }


def _as_numpy(state):
    out = {}
    for key, value in state.items():
        out[key] = (
            value.detach().cpu().numpy() if torch.is_tensor(value)
            else np.asarray(value)
        ).astype(np.float64)
    return out


def _learner_weights(algo, module_id):
    """Full module state from the LearnerGroup, local or remote.

    Deliberately not `learner_group._learner.module[...]`: that private
    attribute is None whenever num_learners > 0.
    """
    state = algo.learner_group.get_state(
        components=f"{COMPONENT_LEARNER}/{COMPONENT_RL_MODULE}/{module_id}",
    )[COMPONENT_LEARNER][COMPONENT_RL_MODULE][module_id]
    return _as_numpy(state)


def _runner_weights(algo, module_id):
    return _as_numpy(algo.env_runner.module[module_id].get_state())


def _mismatched(expected, actual):
    assert sorted(expected) == sorted(actual), (
        f"different parameter sets: {sorted(set(expected) ^ set(actual))}"
    )
    return [k for k in expected if not np.allclose(expected[k], actual[k])]


class TestRealCheckpointRoundTrip:
    """One PPO, trained one iteration, saved, and restored through `build_algo`."""

    @classmethod
    def setup_class(cls):
        ray.init(
            ignore_reinit_error=True,
            include_dashboard=False,
            log_to_driver=False,
            num_cpus=2,
        )
        cls.tmpdir = tempfile.mkdtemp(prefix="cda_ckpt_roundtrip_")
        cls.cfg = TrainConfig(
            log_base_dir=cls.tmpdir, chkpt_keep=0, **TEST_CFG
        )

        ppo, callback = build_config(cls.cfg)
        original = ppo.build_algo()
        original.train()

        # A champion guarantees the league is non-empty, so the restore has
        # bookkeeping to bring back and not an initial state that happens to
        # match. The iteration above may well have created one of its own; both
        # are expected back, so record whatever is there rather than a count.
        cls.source_pid = trainable_policy_ids(cls.cfg.num_trained_agents)[0]
        callback._create_champion_snapshot_from_policy(
            original, cls.source_pid, return_value=0.0, iteration=1
        )
        cls.champion_ids = [c["id"] for c in callback.champion_history]
        cls.champion_id = cls.champion_ids[-1]
        cls.champion_id_counter = callback.champion_id_counter

        cls.saved_iteration = int(original.iteration)
        cls.checkpoint_path = save_checkpoint(
            original, cls.cfg, cls.saved_iteration
        )
        cls.saved_weights = _learner_weights(original, cls.source_pid)
        cls.saved_champion_acting = _acting_only(
            _runner_weights(original, cls.champion_id)
        )
        original.stop()

        cls.restored, cls.restored_callback = build_algo(
            dataclasses_replace(cls.cfg, is_restore=True)
        )

    @classmethod
    def teardown_class(cls):
        cls.restored.stop()
        ray.shutdown()
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_the_checkpoint_is_where_the_driver_expects_it(self):
        assert self.checkpoint_path == os.path.join(
            self.cfg.checkpoint_dir,
            f"{CHECKPOINT_PREFIX}{self.saved_iteration:05d}",
        )
        assert os.path.isfile(
            os.path.join(self.checkpoint_path, LEAGUE_STATE_FILE)
        )

    def test_trained_weights_survive(self):
        """The point of the whole mechanism: not a fresh initialisation."""
        restored = _learner_weights(self.restored, self.source_pid)
        mismatched = _mismatched(self.saved_weights, restored)

        assert mismatched == [], (
            f"{len(mismatched)}/{len(self.saved_weights)} parameters of "
            f"{self.source_pid} differ after restore: {mismatched}. The "
            f"restored run is not the one that was saved."
        )

    def test_the_champion_module_comes_back_and_acts_the_same(self):
        """Champions are added at runtime, so they are the modules most at risk.

        Checked on the EnvRunner because that is where a champion does its only
        job - playing as an opponent. A champion restored into the LearnerGroup
        but not onto the runners would leave the league matchmaking against a
        randomly initialised network, which is the bug this guards.
        """
        modules = self.restored.env_runner.module
        assert self.champion_id in modules, (
            f"{self.champion_id} is missing after restore; the league lost the "
            f"opponent it was matchmaking against."
        )

        restored = _acting_only(_runner_weights(self.restored, self.champion_id))
        assert _mismatched(self.saved_champion_acting, restored) == []

    def test_league_bookkeeping_comes_back(self):
        """The callback handed back is the algorithm's own, holding the league."""
        assert self.restored_callback is not None
        assert self.restored_callback is train_mod.algo_callback(self.restored)
        assert [
            c["id"] for c in self.restored_callback.champion_history
        ] == self.champion_ids
        for champion_id in self.champion_ids:
            assert champion_id in self.restored_callback.available_modules
        # Nothing may re-mint an ID a live champion already holds.
        assert self.restored_callback.champion_id_counter >= self.champion_id_counter

    def test_iteration_count_comes_back(self):
        """`num_iters` is a target, which only works if this survives."""
        assert int(self.restored.iteration) == self.saved_iteration

    def test_optimizer_betas_are_plain_floats(self):
        """`_fix_checkpoint_optimizer_betas` runs only on a real restore.

        Adam's betas deserialise as tensors, and torch's step() then does
        tensor arithmetic on them; the repair is applied in `build_algo` and is
        stubbed out everywhere else in the suite.
        """

        def tensor_betas(learner):
            return [
                repr(beta)
                for optimizer in learner._optimizer_parameters.keys()
                for group in optimizer.param_groups
                for beta in group.get("betas", ())
                if torch.is_tensor(beta)
            ]

        offenders = []
        for result in self.restored.learner_group.foreach_learner(tensor_betas):
            # Remote learners come back wrapped in a ResultOrError.
            offenders.extend(result.get() if hasattr(result, "get") else result)

        assert offenders == [], f"betas came back as tensors: {offenders}"

    def test_the_restored_algorithm_trains_further(self):
        """A restore that cannot take another gradient step is not a restore.

        Runs last: it advances the shared algorithm's iteration counter and
        moves the weights the other tests compare.
        """
        before = _learner_weights(self.restored, self.source_pid)

        result = self.restored.train()

        assert int(self.restored.iteration) == self.saved_iteration + 1
        assert result.get(ENV_RUNNER_RESULTS), (
            "the resumed iteration produced no env_runners block, i.e. it "
            "trained on no samples"
        )
        after = _learner_weights(self.restored, self.source_pid)
        assert any(
            not np.allclose(before[k], after[k]) for k in before
        ), "weights did not move: the resumed run is not learning"
