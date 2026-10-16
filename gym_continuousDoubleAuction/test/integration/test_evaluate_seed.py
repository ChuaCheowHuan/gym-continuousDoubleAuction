"""Issue #243: `train.evaluate --seed` has to make *sampled* evaluation repeat.

It pinned the env reset and the league's opponent draw, but actions are drawn
from torch's global RNG and from each baseline's action-space generator, and
nothing seeded those. Two runs with the same seed on one checkpoint therefore
gave different returns without `--deterministic`, and a comparison of two
checkpoints could measure sampling noise.

A real module set from a freshly built algorithm: no checkpoint is needed, only
the modules and the league's mapping function that `roll_episode` reads.
"""

import shutil
import tempfile

import pytest
import ray

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.train import evaluate
from gym_continuousDoubleAuction.train.train import TrainConfig, build_config

TEST_CFG = dict(
    num_agents=4,
    num_trained_agents=2,
    max_step=48,
    num_episodes_per_iter=2,
    num_epochs=1,
    minibatch_size=48,
    num_env_runners=0,
    num_learners=0,
    num_gpus_per_learner=0,
    episode_data_dir=None,
    log_level="ERROR",
)


@pytest.fixture(scope="module")
def rig():
    ray.init(ignore_reinit_error=True, include_dashboard=False, log_to_driver=False, num_cpus=2)
    tmp = tempfile.mkdtemp(prefix="cda_evalseed_")
    cfg = TrainConfig(log_base_dir=tmp, **TEST_CFG)
    ppo, _ = build_config(cfg)
    algo = ppo.build_algo()
    env = continuousDoubleAuctionEnv({**cfg.env_config, "is_render": False})
    yield algo, env
    algo.stop()
    ray.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)


def _returns(rig, seed, episodes=2, deterministic=False):
    algo, env = rig
    mapping_fn = algo.config.policy_mapping_fn
    records = [
        evaluate.roll_episode(algo, env, mapping_fn, i, seed, deterministic)
        for i in range(episodes)
    ]
    return [[a["return"] for a in r["agents"]] for r in records]


def test_the_same_seed_repeats_sampled_actions(rig):
    assert _returns(rig, seed=0) == _returns(rig, seed=0)


def test_a_different_seed_gives_a_different_run(rig):
    """Otherwise the test above could pass by the env being insensitive to sampling."""
    assert _returns(rig, seed=0) != _returns(rig, seed=1)


def test_the_seed_is_what_makes_it_repeat(rig):
    """Not an unseeded run: with no seed nothing is pinned, and nothing is claimed."""
    assert _returns(rig, seed=None) != _returns(rig, seed=None)
