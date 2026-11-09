"""Tests for config refactor.

Moved from `test_refactors.py` by issue #361; the class docstrings keep the
original issue numbers.
"""

import pytest


from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import continuousDoubleAuctionEnv


class TestEnvSettings:
    """#257: the env's config read, validated and forwarded from one object."""

    @staticmethod
    def _json_keys():
        import json
        import os
        from gym_continuousDoubleAuction.config_loader import config_dir

        with open(os.path.join(config_dir(), "env_defaults.json")) as fh:
            raw = json.load(fh)["environment"]
        return [k for k in raw if not k.startswith("_")]

    def test_the_fields_are_exactly_the_env_defaults_keys(self):
        from gym_continuousDoubleAuction.envs.settings import EnvSettings

        assert sorted(EnvSettings.keys()) == sorted(self._json_keys())

    def test_train_config_generates_its_env_config_from_them(self):
        from gym_continuousDoubleAuction.envs.settings import EnvSettings
        from gym_continuousDoubleAuction.train.train import TrainConfig

        cfg = TrainConfig(num_agents=5, max_step=70, mkt_max_size=55)
        assert list(cfg.env_config) == list(EnvSettings.keys())
        assert cfg.env_config["num_of_agents"] == 5 and cfg.env_config["mkt_max_size"] == 55

    def test_every_key_has_a_train_config_field(self):
        import dataclasses
        from gym_continuousDoubleAuction.envs.settings import EnvSettings
        from gym_continuousDoubleAuction.train.train import TrainConfig

        names = {f.name for f in dataclasses.fields(TrainConfig)}
        for key in EnvSettings.keys():
            assert TrainConfig._ENV_KEY_FIELDS.get(key, key) in names, key

    def test_an_omitted_key_comes_from_the_json_and_a_given_one_wins(self):
        from gym_continuousDoubleAuction.config_loader import env_default
        from gym_continuousDoubleAuction.envs.settings import EnvSettings

        settings = EnvSettings.from_config({"num_of_agents": 3})
        assert settings.num_of_agents == 3 and settings.max_step == env_default("max_step")

    def test_it_is_frozen_and_gives_its_config_back(self):
        from dataclasses import FrozenInstanceError
        from gym_continuousDoubleAuction.envs.settings import EnvSettings

        settings = EnvSettings.from_config({})
        with pytest.raises(FrozenInstanceError):
            settings.max_step = 1
        assert EnvSettings.from_config(settings.as_config()) == settings

    def test_helper_kwargs_leave_out_what_only_the_env_reads(self):
        from gym_continuousDoubleAuction.envs.settings import EnvSettings

        kwargs = EnvSettings.from_config({}).helper_kwargs()
        assert not set(kwargs) & EnvSettings.ENV_ONLY
        assert {"init_cash", "n_hist", "book_mode", "liquidation"} <= set(kwargs)
        assert not set(kwargs) & set(EnvSettings.REWARD_KEYS)
        assert set(EnvSettings.from_config({}).reward_kwargs()) == set(EnvSettings.REWARD_KEYS)

    @pytest.mark.parametrize(
        "override,message",
        [
            ({"num_of_agents": 0}, "num_of_agents must be at least 1"),
            ({"maker_fee_bps": -5, "taker_fee_bps": 1}, "maker_fee_bps"),
            (
                {"allow_multiple_orders_per_level": 1},
                "allow_multiple_orders_per_level must be true or false",
            ),
            ({"episode_length_mode": "weekly"}, "episode_length_mode must be 'fixed' or 'random'"),
            (
                {"episode_length_mode": "random", "max_step_min": 9, "max_step_max": 3},
                "needs 1 <= max_step_min <= max_step_max",
            ),
            ({"episode_length_mode": "fixed", "max_step": 0}, "needs max_step >= 1"),
            # The order-shape keys (#354). Each used to be accepted and then fail
            # mid-episode, far from the key that caused it.
            ({"tick_size": 0}, "tick_size must be a number > 0"),
            ({"tick_size": -1}, "tick_size must be a number > 0"),
            ({"min_size": 0}, "min_size must be at least 1"),
            ({"min_size": 50, "mkt_max_size": 10}, "mkt_max_size must be at least min_size"),
            ({"limit_size_multiple": 0}, "limit_size_multiple must be at least 1"),
            ({"n_hist": 0}, "n_hist must be at least 1"),
            ({"initial_price_min": 0, "tick_size": 1}, "initial_price_min must be at least"),
        ],
    )
    def test_a_bad_value_is_refused_naming_the_key(self, override, message):
        from gym_continuousDoubleAuction.envs.settings import EnvSettings

        with pytest.raises(ValueError, match=message):
            EnvSettings.from_config(override)

    def test_an_unknown_key_is_refused_rather_than_ignored(self):
        """`init_cahs` used to fall back to the default silently (#354)."""
        from gym_continuousDoubleAuction.envs.settings import EnvSettings

        with pytest.raises(ValueError, match="unknown env config keys.*init_cahs"):
            EnvSettings.from_config({"init_cahs": 1})
        with pytest.raises(ValueError, match="nonsense"):
            EnvSettings.from_config({"nonsense": 1})

    def test_the_horizon_is_the_latest_possible_end(self):
        from gym_continuousDoubleAuction.envs.settings import EnvSettings

        assert EnvSettings.from_config({"max_step": 40}).time_left_horizon == 40
        random = EnvSettings.from_config(
            {"episode_length_mode": "random", "max_step_min": "5", "max_step_max": "30"}
        )
        assert random.time_left_horizon == 30 and random.max_step_min == 5

    def test_the_env_builds_from_it_and_keeps_its_attributes(self):
        env = continuousDoubleAuctionEnv(
            {"num_of_agents": 3, "max_step": 12, "maker_fee_bps": 1, "taker_fee_bps": 2}
        )
        assert env.settings.num_of_agents == env.num_of_agents == 3
        assert (env.max_step, env.time_left_horizon, env.episode_horizon) == (12, 12, 12)
        assert (env.maker_fee_bps, env.taker_fee_bps) == (1, 2)
        assert len(env.traders) == 3
