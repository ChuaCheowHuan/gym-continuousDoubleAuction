"""The S3-moderate design issues, one class each: #125 (gamma and lambda), #122 (several
resting orders at one price) and #124 (what the league promotes against)."""
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

    @pytest.mark.parametrize("field,value", [
        ("gamma", 0.0), ("gamma", -0.1), ("gamma", 1.5),
        ("lambda_", -0.1), ("lambda_", 1.1),
    ])
    def test_nonsense_is_refused_naming_the_key(self, field, value):
        with pytest.raises(ValueError, match=field):
            TrainConfig(**{field: value})

    def test_one_is_allowed_for_both(self):
        TrainConfig(gamma=1.0, lambda_=1.0)

    @staticmethod
    def _config(**overrides):
        from types import SimpleNamespace
        values = {"lr": 0.0001, "gamma": 0.999, "lambda_": 0.95, "num_epochs": 1,
                  "minibatch_size": 64, "train_batch_size_per_learner": 256,
                  "num_env_runners": 0, "num_envs_per_env_runner": 1,
                  "sample_timeout_s": 60.0, "num_learners": 0, "num_gpus_per_learner": 0.0,
                  "policies": ["policy_0"], "policies_to_train": ["policy_0"],
                  "env_config": {"num_of_agents": 2}}
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
