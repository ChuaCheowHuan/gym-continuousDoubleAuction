"""docs/15 S3-11 against a real run, not a hand-built result.

The unit tests feed the champion check a dict shaped like RLlib's. That leaves
two assumptions untested, and either breaking would leave the guard looking
fine while doing nothing: that the per-module trade counts logged at episode end
really arrive, under the module ids the check asks about, in the compiled
result; and that RLlib applies the entropy schedule the config asks for.
"""

import shutil
import tempfile

import ray

from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import (
    MODULE_TRADES_METRIC,
)
from gym_continuousDoubleAuction.train.policy.policy_handler import (
    trainable_policy_ids,
)
from gym_continuousDoubleAuction.train.train import TrainConfig, train

NUM_ITERS = 2

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


class TestTheGuardOnARealRun:
    @classmethod
    def setup_class(cls):
        ray.init(ignore_reinit_error=True, include_dashboard=False, log_to_driver=False, num_cpus=2)
        cls.tmpdir = tempfile.mkdtemp(prefix="cda_guard_")
        cls.cfg = TrainConfig(
            log_base_dir=cls.tmpdir, num_iters=NUM_ITERS, chkpt_freq=0, chkpt_keep=0, **TEST_CFG
        )
        cls.algo, cls.result = train(cls.cfg)

    @classmethod
    def teardown_class(cls):
        cls.algo.stop()
        ray.shutdown()
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_every_trainable_module_reports_its_trades(self):
        reported = self.result["env_runners"][MODULE_TRADES_METRIC]
        for pid in trainable_policy_ids(self.cfg.num_trained_agents):
            assert pid in reported, (
                f"{pid} is missing from {MODULE_TRADES_METRIC}: {sorted(reported)}. "
                f"The champion guard would run on nothing and promote on return alone."
            )
            assert reported[pid] >= 0.0

    def test_the_league_state_says_whether_a_candidate_was_refused(self):
        assert self.result["league"]["refused_passive"] in (0, 1)

    def test_the_entropy_bonus_is_live_and_decaying(self):
        """RLlib reports the coefficient it is applying, per trainable module."""
        start, end = self.cfg.entropy_coeff, self.cfg.entropy_coeff_final
        for pid in trainable_policy_ids(self.cfg.num_trained_agents):
            applied = self.result["learners"][pid]["curr_entropy_coeff"]
            assert end < applied < start, (
                f"{pid} is applying entropy_coeff {applied}; expected a value "
                f"between {end} and {start} after {NUM_ITERS} iterations of a "
                f"decay over {self.cfg.entropy_decay_iters}"
            )
