"""What the episode hooks produce has to survive the trip off the driver.

Every metric in `on_episode_end` and every row in the episode record is emitted
on an **env runner** whenever `num_env_runners > 0` - which is the shape the GPU
profile in `runtime_profiles.json` actually runs. The unit tests drive those
hooks in-process, where a returned value is simply a returned value; none of
them can tell whether the value reaches the driver, and two of the defects in
doc/21 were exactly that it did not:

* `strict_nav_check` raised inside the hook. On a remote runner RLlib's fault
  tolerance swallowed the raise and restarted the actor, so the run continued -
  and because `synchronous_parallel_sample` asks for `(sample(), get_metrics())`
  in one call, the throw also discarded that runner's metrics. The stop is now
  the driver's, decided from `nav_conservation_violations`; this asserts the
  metric is really there to decide from.
* The episode record resolved a relative path against the worker's working
  directory. It is absolute and run-scoped now; this asserts the files land
  where the driver said, written by a process that is not the driver.

One real one-runner PPO iteration, sized for speed rather than learning.
"""
import glob
import os
import shutil
import tempfile

import pytest
import ray
from ray.rllib.utils.metrics import ENV_RUNNER_RESULTS

from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import (
    NAV_VIOLATIONS_METRIC,
    REWARD_TERMS,
)
from gym_continuousDoubleAuction.train.train import (
    TrainConfig,
    _check_nav_conservation,
    build_config,
    nav_violations,
)

TEST_CFG = dict(
    num_agents=4,
    num_trained_agents=2,
    max_step=64,
    num_episodes_per_iter=4,
    num_epochs=1,
    minibatch_size=64,
    num_env_runners=1,
    num_cpus_per_env_runner=0.5,
    num_learners=0,
    num_gpus_per_learner=0,
    log_level="ERROR",
)


class TestMetricsCrossTheRunnerBoundary:

    @classmethod
    def setup_class(cls):
        ray.init(
            ignore_reinit_error=True,
            include_dashboard=False,
            log_to_driver=False,
            num_cpus=4,
        )
        cls.tmpdir = tempfile.mkdtemp(prefix="cda_distributed_")
        cls.cfg = TrainConfig(
            **TEST_CFG,
            episode_data_dir=os.path.join(cls.tmpdir, "episodes"),
            # Every episode: four of them is a small enough sample that
            # thinning it would leave the assertions below to chance.
            episode_sample_every=1,
            episode_rows_per_file=1,
            log_base_dir=os.path.join(cls.tmpdir, "results"),
        )
        ppo, cls.callback = build_config(cls.cfg)
        cls.algo = ppo.build_algo()
        cls.result = cls.algo.train()
        cls.env_runners = cls.result.get(ENV_RUNNER_RESULTS, {})

    @classmethod
    def teardown_class(cls):
        try:
            cls.algo.stop()
        finally:
            ray.shutdown()
            shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_sampling_really_happened_remotely(self):
        """Everything below is vacuous if the driver sampled in-process."""
        assert self.cfg.num_env_runners == 1
        assert self.algo.env_runner_group.num_remote_env_runners() == 1
        assert self.env_runners, "no env-runner metrics block at all"

    def test_the_violation_counter_reaches_the_driver(self):
        """The metric the stop is decided from. Present and zero on a healthy
        run - present because a key that only appears on failure cannot be told
        apart from a runner that died before reporting."""
        assert NAV_VIOLATIONS_METRIC in self.env_runners
        assert nav_violations(self.result) == 0.0

    def test_a_healthy_iteration_does_not_stop_the_run(self):
        _check_nav_conservation(1, self.result, self.cfg)

    def test_the_conservation_error_reaches_the_driver(self):
        assert "nav_conservation_error" in self.env_runners

    def test_the_activity_fractions_reach_the_driver(self):
        assert "pass_action_fraction" in self.env_runners
        assert "order_rejection_fraction" in self.env_runners

    def test_the_reward_decomposition_reaches_the_driver(self):
        """doc/11 §2.4: the five terms were captured per step and never
        aggregated, so the variance split doc/07 §6.4 prescribes could only be
        computed after the fact from a file."""
        for term in REWARD_TERMS:
            assert f"reward_term_mean_{term}" in self.env_runners

    def test_the_account_state_reaches_the_driver(self):
        """doc/11 §2.3 and §4 item 2."""
        for key in (
            "episode_nav_mean", "episode_nav_min", "episode_nav_max",
            "mean_agent_drawdown", "mean_abs_net_position", "mean_num_trades",
        ):
            assert key in self.env_runners

    def test_the_episode_record_lands_where_the_driver_said(self):
        """Written by the env-runner process, into the driver's absolute,
        run-scoped path. A relative path would have been resolved against
        whatever working directory that worker inherited."""
        expected = self.cfg.episode_data_path
        assert os.path.isabs(expected)
        assert expected.endswith(self.cfg.run_id)

        files = glob.glob(os.path.join(expected, "*.parquet"))
        assert files, f"no episode record under {expected}"

    def test_the_recorded_rows_are_readable_and_attributed(self):
        import pyarrow.parquet as pq

        files = sorted(glob.glob(os.path.join(self.cfg.episode_data_path, "*.parquet")))
        table = pq.read_table(files)
        df = table.to_pandas()

        assert len(df) > 0
        assert set(df["run_id"]) == {self.cfg.run_id}
        assert df["module_id"].notna().any(), "no row says which module played"
        assert df["nav_str"].notna().all()
        # One row per agent per step, so every episode covers every agent.
        assert df["agent_id"].nunique() == self.cfg.num_agents

    def test_the_record_was_written_by_the_worker_not_the_driver(self):
        """The file tag is pid plus Ray worker id, and the driver is neither of
        the runner's. If the driver had written these, the record would be of
        episodes it never sampled."""
        files = [
            os.path.basename(f)
            for f in glob.glob(os.path.join(self.cfg.episode_data_path, "*.parquet"))
        ]
        pids = {name.split(".")[1] for name in files}

        assert pids, "no files to attribute"
        assert str(os.getpid()) not in pids
