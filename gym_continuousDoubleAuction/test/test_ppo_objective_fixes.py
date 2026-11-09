"""Tests for ppo objective fixes.

Moved from `test_s3_moderate_fixes.py` by issue #361; the class docstrings keep the
original issue numbers.
"""

import logging

import pytest

from gym_continuousDoubleAuction.logging_setup import ROOT_NAME as LOGGER

from gym_continuousDoubleAuction.train.train import (
    TrainConfig,
    _check_restored_config,
    build_config,
)


def _ppo(**overrides):
    built = build_config(TrainConfig(**overrides))
    return built[0] if isinstance(built, tuple) else built


from decimal import Decimal  # noqa: E402

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (  # noqa: E402
    continuousDoubleAuctionEnv,
)

CASH = 100000


def _env(multiple, **config):
    env = continuousDoubleAuctionEnv(
        {
            "num_of_agents": 2,
            "is_render": False,
            "init_cash": CASH,
            "initial_price_min": 100,
            "initial_price_max": 100,
            "allow_multiple_orders_per_level": multiple,
            **config,
        }
    )
    env.reset(seed=1)
    return env


def _place(env, tid, type, side, size, price=-1.0, slot=0):
    env.traders[tid].place_order(type, side, size, price, env.LOB, env.traders, slot=slot)


def _level(env, side, price):
    tree = env.LOB.bids if side == "bid" else env.LOB.asks
    return tree.get_price_list(Decimal(price))


from unittest.mock import MagicMock  # noqa: E402


from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import (  # noqa: E402
    SelfPlayCallback,
)


def _league(reference, **kwargs):
    return SelfPlayCallback(
        num_trainable_policies=2,
        num_random_policies=6,
        min_iterations_between_champions=0,
        min_champion_trades=0,
        promotion_reference=reference,
        **kwargs,
    )


def _returns(trainable, champions, baseline):
    out = {f"policy_{i}": v for i, v in enumerate(trainable)}
    out.update({f"champion_{i + 1}": v for i, v in enumerate(champions)})
    out.update({f"policy_{i}": baseline for i in range(2, 8)})
    return out


def _check(cb, returns, monkeypatch=None):
    made = []
    cb.league.create_snapshot = lambda algo, pid, value, it: made.append(pid)
    result = {"training_iteration": 1, "env_runners": {"module_episode_returns_mean": returns}}
    cb.on_train_result(algorithm=MagicMock(), result=result)
    return made, result["league"]


class TestDiscountAndGae:
    """#125: gamma 0.99 against 4,096-step episodes, and lambda_ 1.0 (pure Monte-Carlo)."""

    def test_the_shipped_values_reach_ppo(self):
        ppo = _ppo()
        assert (ppo.gamma, ppo.lambda_) == (0.999, 0.95)

    def test_the_effective_horizon_covers_a_real_share_of_an_episode(self):
        cfg = TrainConfig()
        assert 1 / (1 - cfg.gamma) >= 0.1 * 4096

    def test_the_old_behaviour_is_one_setting_away(self):
        ppo = _ppo(gamma=0.99, lambda_=1.0)
        assert (ppo.gamma, ppo.lambda_) == (0.99, 1.0)

    @pytest.mark.parametrize(
        "field,value",
        [
            ("gamma", 0.0),
            ("gamma", -0.1),
            ("gamma", 1.5),
            ("lambda_", -0.1),
            ("lambda_", 1.1),
        ],
    )
    def test_nonsense_is_refused_naming_the_key(self, field, value):
        with pytest.raises(ValueError, match=field):
            TrainConfig(**{field: value})

    def test_one_is_allowed_for_both(self):
        TrainConfig(gamma=1.0, lambda_=1.0)

    @staticmethod
    def _config(**overrides):
        from types import SimpleNamespace

        values = {
            "lr": 0.0001,
            "gamma": 0.999,
            "lambda_": 0.95,
            "num_epochs": 1,
            "minibatch_size": 64,
            "train_batch_size_per_learner": 256,
            "num_env_runners": 0,
            "num_envs_per_env_runner": 1,
            "sample_timeout_s": 60.0,
            "num_learners": 0,
            "num_gpus_per_learner": 0.0,
            "policies": ["policy_0"],
            "policies_to_train": ["policy_0"],
            "env_config": {"num_of_agents": 2},
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_resuming_a_checkpoint_trained_at_the_old_values_says_so(self, caplog):
        """A resume keeps the checkpoint's config; the new defaults would otherwise be
        ignored without a word, and the run would optimise something else."""
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            _check_restored_config(self._config(gamma=0.99, lambda_=1.0), self._config())
        assert "gamma" in caplog.text and "lambda_" in caplog.text

    def test_a_matching_resume_says_nothing(self, caplog):
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            _check_restored_config(self._config(), self._config())
        assert caplog.text == ""
