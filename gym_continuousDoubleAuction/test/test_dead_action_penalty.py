"""Phase 3 of doc/15 S3-24, the reward half: `dead_action_penalty`.

Zero by default, so the reward is bit for bit what it was before the term
existed; when set, it charges per modify/cancel that named no resting order.
"""
import numpy as np

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.train.episode_record import REWARD_TERMS


def _act(category, slot=0):
    return {
        "category": category, "size_mean": np.array([0.0], dtype=np.float32),
        "size_sigma": np.array([0.0], dtype=np.float32), "price": 0,
        "price_offset": 1, "order_slot": slot,
    }


def _env(**cfg):
    env = continuousDoubleAuctionEnv({"num_of_agents": 2, "is_render": False,
                                      "max_step": 16, **cfg})
    env.reset(seed=0)
    return env


def test_term_exists_and_is_zero_by_default():
    assert "dead_action_penalty" in REWARD_TERMS
    env = _env()
    assert env.dead_action_penalty == 0.0
    _, rewards, _, _, infos = env.step({"agent_0": _act(4, slot=3), "agent_1": _act(0)})
    assert infos["agent_0"]["num_unmatched_step"] == 1
    assert infos["agent_0"]["reward_terms"]["dead_action_penalty"] == 0.0
    # -0.0 added to the other terms leaves the sum unchanged.
    terms = infos["agent_0"]["reward_terms"]
    total = 0.0
    for name in REWARD_TERMS:
        total += terms[name]
    assert rewards["agent_0"] == total


def test_penalty_charges_per_miss_when_set():
    env = _env(dead_action_penalty=0.001)
    _, rewards, _, _, infos = env.step({"agent_0": _act(4, slot=3), "agent_1": _act(0)})
    assert infos["agent_0"]["reward_terms"]["dead_action_penalty"] == -0.001
    assert infos["agent_1"]["reward_terms"]["dead_action_penalty"] == 0.0
    assert rewards["agent_0"] < rewards["agent_1"]


def test_train_config_forwards_it():
    from gym_continuousDoubleAuction.train.train import TrainConfig
    cfg = TrainConfig()
    assert cfg.dead_action_penalty == 0.0
    assert cfg.env_config["dead_action_penalty"] == 0.0
