"""
Integration tests for the RLlib league-based self-play wiring.

These cover the class of bug that unit tests cannot see: RLlib accepting a
configuration, running without error, and silently doing something other than
what was asked. Three such bugs existed before this suite:

  1. Baseline opponents declared as `PolicySpec(RandomPolicy, ...)` were built
     as DefaultPPOTorchRLModule instead - the new API stack reads only the dict
     keys of `policies`, never `policy_class`.
  2. Champion snapshots got their trained weights written into the LearnerGroup
     but never synced to the EnvRunners, so the champion actually playing in the
     environment stayed at its random initialisation.
  3. The champion trigger read old-API-stack metric keys that no longer exist.

Each test below fails loudly if any of those regress.
"""
import unittest

import numpy as np
import ray
import torch
from ray.rllib.utils.metrics import ENV_RUNNER_RESULTS

from gym_continuousDoubleAuction.train.model.model_handler import RandomRLModule
from gym_continuousDoubleAuction.train.policy.policy_handler import (
    baseline_policy_ids,
    trainable_policy_ids,
)
from gym_continuousDoubleAuction.train.train import TrainConfig, build_config

# Small and short: these tests are about wiring, not learning.
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


def _state_as_numpy(state):
    out = {}
    for k, v in state.items():
        out[k] = (
            v.detach().cpu().numpy() if torch.is_tensor(v) else np.asarray(v)
        ).astype(np.float64)
    return out


class TestLeagueWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ray.init(
            ignore_reinit_error=True,
            include_dashboard=False,
            log_to_driver=False,
            num_cpus=2,
        )
        cfg = TrainConfig(**TEST_CFG)
        ppo, cls.callback = build_config(cfg)
        cls.cfg = cfg
        cls.algo = ppo.build_algo()

        # One training iteration, then one champion, created up-front so every
        # test sees the same state regardless of unittest's alphabetical
        # method ordering.
        cls.train_result = cls.algo.train()
        cls.source_pid = trainable_policy_ids(cfg.num_trained_agents)[0]
        cls.callback._create_champion_snapshot_from_policy(
            cls.algo, cls.source_pid, return_value=0.0, iteration=1
        )
        cls.champion_id = cls.callback.champion_history[-1]["id"]

    @classmethod
    def tearDownClass(cls):
        cls.algo.stop()
        ray.shutdown()

    def test_baseline_opponents_are_random_modules(self):
        """The frozen baselines must be RandomRLModule, not PPO modules.

        Regression guard: declaring them via PolicySpec(RandomPolicy, ...) was
        accepted silently and produced DefaultPPOTorchRLModule for every ID, so
        the "random" opponents were frozen randomly-initialised networks whose
        Box action components came from a clipped Gaussian rather than a uniform.
        """
        modules = self.algo.env_runner.module

        for pid in baseline_policy_ids(
            self.cfg.num_agents, self.cfg.num_trained_agents
        ):
            self.assertIsInstance(
                modules[pid],
                RandomRLModule,
                f"{pid} should be a RandomRLModule, got {type(modules[pid]).__name__}",
            )

        for pid in trainable_policy_ids(self.cfg.num_trained_agents):
            self.assertNotIsInstance(
                modules[pid],
                RandomRLModule,
                f"{pid} is trainable and must not be a RandomRLModule",
            )

    def test_baselines_excluded_from_training(self):
        """RandomRLModule._forward_train raises, so it must not be trained."""
        to_train = set(self.algo.config.policies_to_train)
        for pid in baseline_policy_ids(
            self.cfg.num_agents, self.cfg.num_trained_agents
        ):
            self.assertNotIn(pid, to_train)
        for pid in trainable_policy_ids(self.cfg.num_trained_agents):
            self.assertIn(pid, to_train)

    def test_module_returns_metric_key_exists(self):
        """The champion trigger depends on this exact key being present."""
        env_runners = self.train_result.get(ENV_RUNNER_RESULTS, {})

        self.assertIn("module_episode_returns_mean", env_runners)
        returns = env_runners["module_episode_returns_mean"]
        self.assertTrue(returns, "module_episode_returns_mean is empty")

        # Keyed by real ModuleID, which is what makes remapping unnecessary.
        for pid in trainable_policy_ids(self.cfg.num_trained_agents):
            self.assertIn(pid, returns)

    def test_champion_weights_reach_the_env_runner(self):
        """A champion snapshot must actually carry the trained weights.

        This is the load-bearing one. `add_module` syncs weights to the
        EnvRunners internally, but that happens *before* the snapshot's weights
        are copied in; and PPO's per-iteration sync only covers modules that
        produced losses, which never includes a frozen champion. Without an
        explicit unfiltered sync after set_state, the champion acting in the
        env stays randomly initialised forever while the trained copy sits
        unused in the LearnerGroup.
        """
        trained = _state_as_numpy(
            self.algo.learner_group._learner.module[self.source_pid].get_state()
        )
        on_runner = _state_as_numpy(
            self.algo.env_runner.module[self.champion_id].get_state()
        )

        shared = sorted(set(trained) & set(on_runner))
        self.assertTrue(shared, "champion and source share no parameters")

        mismatched = [
            k for k in shared if not np.allclose(trained[k], on_runner[k])
        ]
        self.assertEqual(
            mismatched,
            [],
            f"Champion on the EnvRunner does not match the trained policy for "
            f"{len(mismatched)}/{len(shared)} parameters: {mismatched}. "
            f"The champion playing in the environment is not the snapshot.",
        )

    def test_champion_enters_the_opponent_pool(self):
        """After snapshotting, the mapping fn must be able to select it."""
        champion_ids = [c["id"] for c in self.callback.champion_history]
        self.assertTrue(champion_ids, "no champion was created")

        for cid in champion_ids:
            self.assertIn(cid, self.callback.available_modules)

        # Opponent slots can draw a champion; trainable slots never do.
        mapping_fn = self.callback.get_mapping_fn(self.callback)

        class _Ep:
            id_ = "deterministic-episode-id"

        for i in range(self.cfg.num_trained_agents):
            self.assertEqual(mapping_fn(f"agent_{i}", _Ep()), f"policy_{i}")

        drawn = {
            mapping_fn(f"agent_{i}", _Ep())
            for i in range(self.cfg.num_trained_agents, self.cfg.num_agents)
        }
        pool = set(self.callback.available_modules[self.cfg.num_trained_agents:])
        self.assertTrue(drawn.issubset(pool), f"{drawn} not within pool {pool}")

    def test_mapping_fn_is_deterministic_across_processes(self):
        """Selection must not depend on PYTHONHASHSEED.

        The mapping fn used to seed from the builtin hash(), which is salted
        per process, so the "deterministic" selection it documented was only
        reproducible within a single interpreter.
        """
        mapping_fn = self.callback.get_mapping_fn(self.callback)

        class _Ep:
            id_ = "fixed-id-for-hash-check"

        first = [
            mapping_fn(f"agent_{i}", _Ep())
            for i in range(self.cfg.num_trained_agents, self.cfg.num_agents)
        ]
        again = [
            mapping_fn(f"agent_{i}", _Ep())
            for i in range(self.cfg.num_trained_agents, self.cfg.num_agents)
        ]
        self.assertEqual(first, again)

        # And every result is a plain str, not np.str_.
        for module_id in first:
            self.assertIs(type(module_id), str)


if __name__ == "__main__":
    unittest.main()
