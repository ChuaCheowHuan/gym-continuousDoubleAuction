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
from ray.rllib.core import COMPONENT_LEARNER, COMPONENT_RL_MODULE
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


def _learner_module_state(algo, module_id):
    """Full module state from the LearnerGroup, local or remote.

    Deliberately not `learner_group._learner.module[...]`: that private
    attribute is None whenever num_learners > 0.
    """
    return algo.learner_group.get_state(
        components=f"{COMPONENT_LEARNER}/{COMPONENT_RL_MODULE}/{module_id}",
    )[COMPONENT_LEARNER][COMPONENT_RL_MODULE][module_id]


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
            _learner_module_state(self.algo, self.source_pid)
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


class TestLeagueWiringRemoteEnvRunners(unittest.TestCase):
    """The same wiring, but with sampling on a REMOTE EnvRunner.

    `num_env_runners > 0` is a different code path in every way that matters
    here: sampling moves off the driver, and each remote worker unpickles its
    own copy of the callback that the driver never updates again. Two bugs hid
    in exactly this gap, so it gets its own coverage rather than relying on the
    in-process case above.
    """

    NUM_ENV_RUNNERS = 1

    @classmethod
    def setUpClass(cls):
        ray.init(
            ignore_reinit_error=True,
            include_dashboard=False,
            log_to_driver=False,
            num_cpus=4,
        )
        cfg = TrainConfig(
            **{
                **TEST_CFG,
                "num_env_runners": cls.NUM_ENV_RUNNERS,
                "num_cpus_per_env_runner": 0.5,
            }
        )
        ppo, cls.callback = build_config(cfg)
        cls.cfg = cfg
        cls.algo = ppo.build_algo()
        cls.algo.train()

        cls.source_pid = trainable_policy_ids(cfg.num_trained_agents)[0]
        cls.callback._create_champion_snapshot_from_policy(
            cls.algo, cls.source_pid, return_value=0.0, iteration=1
        )
        cls.champion_id = cls.callback.champion_history[-1]["id"]

        # The probe is defined HERE, nested, and closes only over plain values.
        #
        # Two traps, both of which make the remote call die and get the
        # EnvRunner marked unhealthy - after which `foreach_env_runner` returns
        # [] and every assertion below passes vacuously over an empty list
        # (which is why `test_sampling_actually_happens_remotely` exists):
        #
        #   * Closing over `cls` drags the unittest class along with it.
        #   * A module-level helper is pickled by REFERENCE, and pytest imports
        #     this file as top-level `test_league_wiring`, a name the worker
        #     process cannot import. A nested function is pickled by value.
        champion_id = cls.champion_id
        num_agents = cfg.num_agents
        num_trained = cfg.num_trained_agents

        def probe(env_runner, n_draws=200):
            """Runs INSIDE the remote EnvRunner actor."""
            module = env_runner.module
            has_champion = champion_id in module
            state = dict(module[champion_id].get_state()) if has_champion else {}

            # Read the mapping the runner actually uses, not one derived from
            # the callback - the point of this probe is that they can disagree.
            map_fn = env_runner.config.policy_mapping_fn

            class _Ep:
                def __init__(self, i):
                    self.id_ = f"probe-episode-{i}"

            drawn = set()
            for i in range(n_draws):
                ep = _Ep(i)
                for a in range(num_trained, num_agents):
                    drawn.add(map_fn(f"agent_{a}", ep))

            return has_champion, state, drawn

        cls.remote_probes = cls.algo.env_runner_group.foreach_env_runner(
            probe, local_env_runner=False
        )

    @classmethod
    def tearDownClass(cls):
        cls.algo.stop()
        ray.shutdown()

    def test_sampling_actually_happens_remotely(self):
        """Guard the premise: if there are no remote runners, this whole class
        silently degrades into a duplicate of the in-process tests."""
        self.assertEqual(
            self.algo.env_runner_group.num_healthy_remote_workers(),
            self.NUM_ENV_RUNNERS,
        )
        self.assertEqual(len(self.remote_probes), self.NUM_ENV_RUNNERS)

    def test_champion_module_exists_on_remote_runners(self):
        for i, (has_champion, _state, _drawn) in enumerate(self.remote_probes):
            self.assertTrue(
                has_champion,
                f"remote runner {i} has no module {self.champion_id}",
            )

    def test_champion_weights_reach_remote_runners(self):
        """The weight force-push must cross the process boundary."""
        trained = _state_as_numpy(
            _learner_module_state(self.algo, self.source_pid)
        )

        for i, (_has, state, _drawn) in enumerate(self.remote_probes):
            on_runner = _state_as_numpy(state)
            shared = sorted(set(trained) & set(on_runner))
            self.assertTrue(shared, f"remote runner {i}: no shared parameters")

            mismatched = [
                k for k in shared if not np.allclose(trained[k], on_runner[k])
            ]
            self.assertEqual(
                mismatched,
                [],
                f"remote runner {i}: champion differs from the trained policy "
                f"for {len(mismatched)}/{len(shared)} parameters. The champion "
                f"sampling episodes is not the snapshot.",
            )

    def test_remote_mapping_fn_can_draw_the_champion(self):
        """The champion must be selectable by the mapping the runner uses.

        Regression guard for pool membership being published late: because
        `add_module` pickles the mapping fn (and with it a snapshot of
        `available_modules`) to ship it to the workers, appending the champion
        after that call left remote runners permanently one champion behind. A
        run with a single champion left them with none at all - which is what
        this asserts against.
        """
        for i, (_has, _state, drawn) in enumerate(self.remote_probes):
            self.assertIn(
                self.champion_id,
                drawn,
                f"remote runner {i} never draws {self.champion_id}; it sees "
                f"only {sorted(drawn)}. Champions are not entering play.",
            )


class TestLeagueWiringRemoteLearner(unittest.TestCase):
    """Champion snapshotting with num_learners > 0 (a remote LearnerGroup).

    Regression guard: the snapshot used to read `learner_group._learner`, which
    is only populated when the LearnerGroup is local. With num_learners > 0 it
    is None, so every snapshot attempt raised, the broad except swallowed it,
    and the league stayed permanently empty while printing one error per
    iteration - a silent degradation, not a crash.
    """

    @classmethod
    def setUpClass(cls):
        ray.init(
            ignore_reinit_error=True,
            include_dashboard=False,
            log_to_driver=False,
            num_cpus=4,
        )
        cfg = TrainConfig(**{**TEST_CFG, "num_learners": 1})
        ppo, cls.callback = build_config(cfg)
        cls.cfg = cfg
        cls.algo = ppo.build_algo()
        cls.algo.train()
        cls.source_pid = trainable_policy_ids(cfg.num_trained_agents)[0]
        cls.callback._create_champion_snapshot_from_policy(
            cls.algo, cls.source_pid, return_value=0.0, iteration=1
        )

    @classmethod
    def tearDownClass(cls):
        cls.algo.stop()
        ray.shutdown()

    def test_learner_group_is_actually_remote(self):
        """Guard the premise, or this class duplicates the local-learner tests."""
        self.assertFalse(self.algo.learner_group.is_local)

    def test_champion_is_created_with_a_remote_learner(self):
        self.assertTrue(
            self.callback.champion_history,
            "no champion was created with num_learners > 0",
        )

    def test_champion_weights_match_with_a_remote_learner(self):
        champion_id = self.callback.champion_history[-1]["id"]
        trained = _state_as_numpy(
            _learner_module_state(self.algo, self.source_pid)
        )
        on_runner = _state_as_numpy(
            self.algo.env_runner.module[champion_id].get_state()
        )
        shared = sorted(set(trained) & set(on_runner))
        self.assertTrue(shared, "champion and source share no parameters")

        mismatched = [
            k for k in shared if not np.allclose(trained[k], on_runner[k])
        ]
        self.assertEqual(
            mismatched,
            [],
            f"champion differs from the trained policy for "
            f"{len(mismatched)}/{len(shared)} parameters",
        )


if __name__ == "__main__":
    unittest.main()
