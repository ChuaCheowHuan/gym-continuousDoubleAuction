"""The `env_config` keys promoted from hardcoded literals actually take effect.

The reward coefficients and the order-sizing knobs were literals inside
`Reward_Helper.set_reward` and `Action_Helper.__init__` until they became config
keys. They reach their consumers through a cooperative `__init__` chain across
the env mixins, where a single mixin that calls `super().__init__()` without
forwarding `**kwargs` silently drops every key downstream of it - and the env
still constructs and runs, just with the defaults. These tests pin that the
values arrive, not merely that the keys are accepted.

See doc/18_configuration.md sections 2.1-2.3.
"""
import os

import pytest

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.train.train import TrainConfig


DEFAULTS = {
    "min_size": 1,
    "mkt_max_size": 100,
    "limit_size_multiple": 10,
    "order_penalty": 0.1,
    "trade_penalty": 0.05,
    "drawdown_penalty": 0.2,
    "passive_bonus": 0.1,
    "loss_multiplier": 1.5,
}

CUSTOM = {
    "min_size": 5,
    "mkt_max_size": 40,
    "limit_size_multiple": 3,
    "order_penalty": 0.9,
    "trade_penalty": 0.8,
    "drawdown_penalty": 0.7,
    "passive_bonus": 0.6,
    "loss_multiplier": 2.5,
}


def _env(**overrides):
    config = {
        "num_of_agents": 2,
        "init_cash": 100000,
        "is_render": False,
    }
    config.update(overrides)
    return continuousDoubleAuctionEnv(config)


class TestSizingKnobs:

    def test_defaults_when_keys_absent(self):
        env = _env()
        for key, expected in DEFAULTS.items():
            assert getattr(env, key) == expected, key

    def test_config_values_reach_action_helper(self):
        env = _env(**CUSTOM)
        assert env.min_size == 5
        assert env.mkt_max_size == 40
        assert env.limit_size_multiple == 3

    def test_derived_sizes_follow_the_config(self):
        """limit_max_size and the mean multipliers are derived, not configured."""
        env = _env(**CUSTOM)
        assert env.limit_max_size == 40 * 3
        assert env.mkt_size_mean_mul == (40 - 5) / 2
        assert env.limit_size_mean_mul == (120 - 5) / 2

    def test_tick_size_reaches_the_action_layer(self):
        assert _env(tick_size=0.25).min_tick == 0.25

    def test_max_price_is_gone(self):
        """It was stored, threaded through _set_price, and never read."""
        assert not hasattr(_env(), "max_price")


class TestRewardCoefficients:

    def _scored(self, **overrides):
        """Score one trader against a fixed account state."""
        env = _env(**overrides)
        env.reset()
        trader = env.traders[0]
        acc = trader.acc
        acc.prev_nav = 1000
        acc.nav = 1050            # nav_change = +50
        acc.max_nav = 1100        # drawdown = 50
        acc.order_step_placed = 1
        acc.num_trades_step = 2
        acc.num_passive_fills_step = 1
        return float(env.set_reward({}, trader)['agent_0'])

    def test_coefficients_reach_the_helper(self):
        env = _env(**CUSTOM)
        assert env.order_penalty == 0.9
        assert env.trade_penalty == 0.8
        assert env.drawdown_penalty == 0.7
        assert env.passive_bonus == 0.6
        assert env.loss_multiplier == 2.5

    def test_default_reward_matches_the_documented_formula(self):
        # 50 - 0.1*1 - 0.05*2 - 0.2*50 + 0.1*1
        assert self._scored() == pytest.approx(39.9, abs=1e-9)

    def test_configured_coefficients_change_the_reward(self):
        # 50 - 0.9*1 - 0.8*2 - 0.7*50 + 0.6*1
        assert self._scored(**CUSTOM) == pytest.approx(13.1, abs=1e-9)

    def test_loss_multiplier_applies_only_to_losses(self):
        """The custom multiplier must reach the asymmetric branch."""
        env = _env(loss_multiplier=2.5, drawdown_penalty=0.0)
        env.reset()
        trader = env.traders[0]
        acc = trader.acc
        acc.prev_nav = 1000
        acc.nav = 900             # nav_change = -100
        acc.max_nav = 1000
        acc.order_step_placed = 0
        acc.num_trades_step = 0
        acc.num_passive_fills_step = 0

        reward = float(env.set_reward({}, trader)['agent_0'])
        assert reward == pytest.approx(-250.0, abs=1e-9)  # -100 * 2.5


class TestTrainConfigRoundTrip:
    """TrainConfig must emit the new keys, or training runs cannot set them."""

    def test_env_config_carries_the_new_keys(self):
        cfg = TrainConfig(num_agents=2, mkt_max_size=55, order_penalty=0.7)
        env_config = cfg.env_config
        for key in DEFAULTS:
            assert key in env_config, f"TrainConfig.env_config drops {key}"
        assert env_config["mkt_max_size"] == 55
        assert env_config["order_penalty"] == 0.7

    def test_values_survive_into_the_env(self):
        cfg = TrainConfig(num_agents=2, mkt_max_size=55, order_penalty=0.7)
        env = continuousDoubleAuctionEnv(cfg.env_config)
        assert env.mkt_max_size == 55
        assert env.order_penalty == 0.7


class TestEpisodeRecordPath:
    """Where the per-step episode record is resolved to.

    doc/21 §2.3: this was the one output path with no protection at all. It was
    a bare relative string, pickled into every env runner and resolved there
    against whatever working directory that worker inherited - which today is
    usually the driver's, by accident rather than by guarantee. The run log has
    had `abspath` and a per-run directory since doc/11 §1.11; this had not.
    """

    def test_it_is_absolute(self):
        cfg = TrainConfig(episode_data_dir="episode_data")
        assert os.path.isabs(cfg.episode_data_path)

    def test_it_is_scoped_to_the_run(self):
        """Two concurrent runs writing into one directory is the same problem
        `run_dir` exists to solve for `run.log` and `progress.jsonl`."""
        a = TrainConfig(episode_data_dir="episode_data")
        b = TrainConfig(episode_data_dir="episode_data")

        assert a.episode_data_path != b.episode_data_path
        assert a.episode_data_path.endswith(a.run_id)

    def test_a_pinned_run_id_resolves_to_the_same_place(self):
        """A restored run extends what it left behind, as it does for
        progress.jsonl."""
        a = TrainConfig(episode_data_dir="episode_data", run_id="fixed")
        b = TrainConfig(episode_data_dir="episode_data", run_id="fixed")

        assert a.episode_data_path == b.episode_data_path

    def test_an_absolute_root_is_respected(self):
        """`runtime_profiles.json` points `episode_data_root` at the VM's local
        disk on Colab, deliberately off the Drive FUSE mount."""
        cfg = TrainConfig(episode_data_dir="/content/cda_episode_data")
        assert cfg.episode_data_path.startswith("/content/cda_episode_data/")

    def test_disabled_stays_disabled(self):
        assert TrainConfig(episode_data_dir=None).episode_data_path is None

    def test_it_is_not_under_the_run_directory(self):
        """Deliberate: `runtime_profiles.json` splits `results_root` from
        `episode_data_root` precisely so the bulky record can be kept off the
        filesystem the checkpoints must survive on."""
        cfg = TrainConfig(episode_data_dir="episode_data")
        assert not cfg.episode_data_path.startswith(cfg.run_dir)
