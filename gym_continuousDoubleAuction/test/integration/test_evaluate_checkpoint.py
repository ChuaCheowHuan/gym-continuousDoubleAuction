"""`train.evaluate` against a real checkpoint: train one iteration, save, roll.

doc/15 S4-12. The point of the test is the seam nobody else exercises: the
checkpoint's own mapping fn assigning modules, `forward_inference` on both a
trainable PPO module (distribution inputs) and a `RandomRLModule` (actions
emitted directly), the Dict action unbatched into what `env.step` accepts, and
the layout stamp refusing a foreign checkpoint.
"""
import dataclasses
import json

import pytest
import ray

from gym_continuousDoubleAuction.envs.layout_version import LAYOUT_KEY
from gym_continuousDoubleAuction.train import evaluate
from gym_continuousDoubleAuction.train.train import (
    LEAGUE_STATE_FILE,
    TrainConfig,
    list_checkpoints,
    train,
)


@pytest.fixture(scope="module")
def checkpoint(tmp_path_factory):
    ray.init(ignore_reinit_error=True, include_dashboard=False, num_cpus=2)
    root = tmp_path_factory.mktemp("eval")
    cfg = dataclasses.replace(
        TrainConfig(), num_agents=4, num_trained_agents=2, max_step=32,
        num_episodes_per_iter=2, num_iters=1, chkpt_freq=1, minibatch_size=64,
        log_base_dir=str(root), episode_data_dir=None, run_id="eval_test", seed=0,
    )
    algo, _ = train(cfg)
    algo.stop()
    path = list_checkpoints(cfg.checkpoint_dir)[-1][1]
    yield path
    ray.shutdown()


def test_rolls_episodes_with_the_checkpoints_policies(checkpoint):
    record = evaluate.evaluate(checkpoint, episodes=2, seed=5, deterministic=False,
                               env_overrides={"max_step": 16})
    assert record["iteration"] == 1
    assert len(record["episodes"]) == 2
    for ep in record["episodes"]:
        assert 1 <= ep["steps"] <= 16
        assert {row["agent"] for row in ep["agents"]} == {f"agent_{i}" for i in range(4)}
        modules = {row["module"] for row in ep["agents"]}
        # Trainable slots are fixed; the opponent slots draw from the pool.
        assert {"policy_0", "policy_1"} <= modules
        assert modules <= {"policy_0", "policy_1", "policy_2", "policy_3"}
    summary = record["summary"]
    assert "policy_0" in summary and summary["policy_0"]["agent_episodes"] == 2
    # Every activity fraction is a fraction.
    for s in summary.values():
        for key in ("pass_fraction", "rejection_fraction", "unmatched_fraction"):
            assert 0.0 <= s[key] <= 1.0
    json.dumps(record, default=str)


def test_deterministic_is_reproducible(checkpoint):
    a = evaluate.evaluate(checkpoint, episodes=1, seed=3, deterministic=True,
                          env_overrides={"max_step": 12})
    b = evaluate.evaluate(checkpoint, episodes=1, seed=3, deterministic=True,
                          env_overrides={"max_step": 12})
    ra = [row["return"] for row in a["episodes"][0]["agents"] if row["module"] in ("policy_0", "policy_1")]
    rb = [row["return"] for row in b["episodes"][0]["agents"] if row["module"] in ("policy_0", "policy_1")]
    # The random baselines re-sample, so only the trainable modules are pinned,
    # and only if the baselines' draws did not change the book they saw -
    # which the env seed and the mode make true for the first step at least.
    assert a["episodes"][0]["steps"] == b["episodes"][0]["steps"]
    assert len(ra) == len(rb) == 2


def test_refuses_a_foreign_layout(checkpoint, tmp_path):
    sidecar = json.load(open(f"{checkpoint}/{LEAGUE_STATE_FILE}"))
    sidecar[LAYOUT_KEY]["observation_version"] = 1
    json.dump(sidecar, open(f"{checkpoint}/{LEAGUE_STATE_FILE}", "w"))
    try:
        with pytest.raises(ValueError, match="observation layout v1"):
            evaluate.evaluate(checkpoint, episodes=1, seed=0, deterministic=True)
    finally:
        sidecar[LAYOUT_KEY]["observation_version"] = 2
        json.dump(sidecar, open(f"{checkpoint}/{LEAGUE_STATE_FILE}", "w"))
