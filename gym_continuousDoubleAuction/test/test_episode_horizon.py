"""Fixed or random episode horizons.

`episode_length_mode` is `"fixed"` (every episode truncates at `max_step`, as
always) or `"random"` (each reset draws the horizon from
`[max_step_min, max_step_max]` with the env's seeded generator). The drawn
horizon is reported once, in the reset infos, and never shown to the policy:
`time_left` counts against `time_left_horizon`, the latest possible end, so an
agent cannot learn the exact end of the game - the end-game is where a known
horizon lets inventory be dumped for free. doc/18 section 3.4.
"""
import dataclasses

import numpy as np
import pytest

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)


def _env(**overrides):
    config = {"num_of_agents": 2, "is_render": False, "max_step": 16,
              "initial_price_min": 100, "initial_price_max": 100}
    config.update(overrides)
    return continuousDoubleAuctionEnv(config)


def _pass(env):
    return {agent: {"category": 0, "order_slot": 0, "price": 0, "price_offset": 1,
                    "size_mean": np.zeros(1, dtype=np.float32),
                    "size_sigma": np.zeros(1, dtype=np.float32)}
            for agent in env.agents}


def _run(env):
    """Step with passes until the episode ends; return (steps, last obs)."""
    steps = 0
    while True:
        obs, _, dones, truncs, _ = env.step(_pass(env))
        steps += 1
        if dones["__all__"] or truncs["__all__"]:
            return steps, obs


def _time_left(env, obs):
    return float(obs["agent_0"][-env.private_dim + env.private_fields.index("time_left")])


class TestFixed:

    def test_default_is_fixed_at_max_step(self):
        env = _env()
        _, infos = env.reset(seed=1)
        assert env.episode_length_mode == "fixed"
        assert env.episode_horizon == env.max_step == 16
        assert infos["agent_0"]["episode_horizon"] == 16
        steps, obs = _run(env)
        assert steps == 16
        assert _time_left(env, obs) == 0.0

    def test_the_horizon_is_the_same_every_reset(self):
        env = _env()
        horizons = {env.reset(seed=s)[1]["agent_0"]["episode_horizon"] for s in range(5)}
        assert horizons == {16}


class TestRandom:

    def test_the_draw_is_inside_the_range_and_varies(self):
        env = _env(episode_length_mode="random", max_step_min=5, max_step_max=12)
        horizons = [env.reset(seed=s)[1]["agent_0"]["episode_horizon"] for s in range(40)]
        assert all(5 <= h <= 12 for h in horizons)
        assert len(set(horizons)) >= 5, "forty draws from eight values should spread"

    def test_both_ends_are_reachable(self):
        env = _env(episode_length_mode="random", max_step_min=3, max_step_max=4)
        horizons = {env.reset(seed=s)[1]["agent_0"]["episode_horizon"] for s in range(30)}
        assert horizons == {3, 4}

    def test_seeded_draws_reproduce(self):
        env = _env(episode_length_mode="random", max_step_min=5, max_step_max=60)
        first = [env.reset(seed=s)[1]["agent_0"]["episode_horizon"] for s in range(6)]
        second = [env.reset(seed=s)[1]["agent_0"]["episode_horizon"] for s in range(6)]
        assert first == second
        assert len(set(first)) > 1

    def test_truncation_lands_on_the_draw(self):
        env = _env(episode_length_mode="random", max_step_min=5, max_step_max=12)
        for seed in range(6):
            _, infos = env.reset(seed=seed)
            h = infos["agent_0"]["episode_horizon"]
            steps, _ = _run(env)
            assert steps == h == env.episode_horizon

    def test_time_left_counts_against_the_upper_bound(self):
        """The draw is not shown: at truncation `time_left` is `1 - h / max`,
        strictly positive unless the draw was the bound itself."""
        env = _env(episode_length_mode="random", max_step_min=4, max_step_max=20)
        obs, infos = env.reset(seed=2)
        assert _time_left(env, obs) == 1.0
        h = infos["agent_0"]["episode_horizon"]
        steps, obs = _run(env)
        assert steps == h
        assert _time_left(env, obs) == pytest.approx(1 - h / 20, abs=1e-6)
        assert env.time_left_horizon == 20

    def test_max_step_is_not_the_horizon_in_random_mode(self):
        env = _env(episode_length_mode="random", max_step=100, max_step_min=3, max_step_max=6)
        _, infos = env.reset(seed=0)
        assert infos["agent_0"]["episode_horizon"] <= 6
        assert env.time_left_horizon == 6


class TestValidation:

    def test_unknown_mode(self):
        with pytest.raises(ValueError, match="episode_length_mode"):
            _env(episode_length_mode="geometric")

    def test_inverted_range(self):
        with pytest.raises(ValueError, match="max_step_min"):
            _env(episode_length_mode="random", max_step_min=10, max_step_max=5)

    def test_zero_minimum(self):
        with pytest.raises(ValueError, match="max_step_min"):
            _env(episode_length_mode="random", max_step_min=0, max_step_max=5)

    def test_the_range_is_ignored_in_fixed_mode(self):
        env = _env(episode_length_mode="fixed", max_step_min=50, max_step_max=5)
        assert env.reset(seed=0)[1]["agent_0"]["episode_horizon"] == 16


class TestTrainConfig:

    def test_batch_is_sized_by_the_expected_length(self):
        from gym_continuousDoubleAuction.train.train import TrainConfig
        fixed = dataclasses.replace(TrainConfig(), max_step=64, num_episodes_per_iter=4)
        assert fixed.expected_episode_length == 64 and fixed.train_batch_size == 256
        rnd = dataclasses.replace(fixed, episode_length_mode="random", max_step_min=32, max_step_max=96)
        assert rnd.expected_episode_length == 64 and rnd.train_batch_size == 256
        cfg = rnd.env_config
        assert cfg["episode_length_mode"] == "random"
        assert (cfg["max_step_min"], cfg["max_step_max"]) == (32, 96)

    def test_compare_can_switch_it(self):
        from gym_continuousDoubleAuction.train.compare import parse_overrides
        out = parse_overrides(["episode_length_mode=random", "max_step_min=8", "max_step_max=32"])
        assert out == {"episode_length_mode": "random", "max_step_min": 8, "max_step_max": 32}
