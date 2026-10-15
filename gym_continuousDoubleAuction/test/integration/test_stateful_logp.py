"""Issue #278 against the real module, not a hand-built distribution.

Two agents served by one stateful module in the same step is what a league
produces when a champion is drawn for both opponent slots. Each agent's log-
probability must stay `(batch, time) == (B, 1)`.
"""
import shutil
import tempfile

import pytest
import ray
import torch
from ray.rllib.core.columns import Columns

from gym_continuousDoubleAuction.train.train import TrainConfig, build_config

TEST_CFG = dict(
    num_agents=4, num_trained_agents=2, max_step=64, num_episodes_per_iter=2,
    num_epochs=1, minibatch_size=64, num_env_runners=0, num_learners=0,
    num_gpus_per_learner=0, episode_data_dir=None, log_level="ERROR",
)


@pytest.fixture(scope="module")
def algos():
    ray.init(ignore_reinit_error=True, include_dashboard=False,
             log_to_driver=False, num_cpus=2)
    tmp = tempfile.mkdtemp(prefix="cda_logp_")
    built = {}
    for enc in ("mlp", "lstm"):
        ppo, _ = build_config(TrainConfig(encoder_type=enc, log_base_dir=tmp, **TEST_CFG))
        built[enc] = ppo.build_algo()
    yield built
    for a in built.values():
        a.stop()
    ray.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)


def _logp(module, batch, stateful):
    obs = torch.zeros(batch, 1 if stateful else 0, *module.observation_space.shape) \
        if stateful else torch.zeros(batch, *module.observation_space.shape)
    inputs = {Columns.OBS: obs}
    if stateful:
        state = module.get_initial_state()
        inputs[Columns.STATE_IN] = torch.utils._pytree.tree_map(
            lambda x: x.unsqueeze(0).repeat(batch, *[1] * x.dim()), state)
    out = module.forward_exploration(inputs)
    dist = module.get_exploration_action_dist_cls().from_logits(
        out[Columns.ACTION_DIST_INPUTS])
    return dist.logp(dist.sample())


@pytest.mark.parametrize("batch", [1, 2, 3])
def test_a_stateful_module_keeps_batch_by_time(algos, batch):
    module = algos["lstm"].get_module("policy_0")
    assert tuple(_logp(module, batch, True).shape) == (batch, 1)


@pytest.mark.parametrize("batch", [1, 2, 3])
def test_a_stateless_module_gives_one_value_per_agent(algos, batch):
    module = algos["mlp"].get_module("policy_0")
    assert tuple(_logp(module, batch, False).shape) == (batch,)


def test_every_getter_returns_the_safe_class(algos):
    module = algos["lstm"].get_module("policy_0")
    for getter in (module.get_inference_action_dist_cls,
                   module.get_exploration_action_dist_cls,
                   module.get_train_action_dist_cls):
        assert getattr(getter(), "_cda_time_rank_safe", False)
