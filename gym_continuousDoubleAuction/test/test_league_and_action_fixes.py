"""Tests for league and action fixes.

Moved from `test_s4_minor_fixes.py` by issue #361; the class docstrings keep the
original issue numbers.
"""

import pytest


from pathlib import Path


class TestANoneModuleReturnIsHandledEverywhere:
    """#235: the league statistics treated `None` and NaN as "no return"; three
    other places compared, rounded or formatted the raw value."""

    def test_the_helper_treats_missing_nan_and_junk_alike(self):
        from gym_continuousDoubleAuction.train.returns import format_return, usable_return

        for bad in (None, float("nan"), "x", True):
            assert usable_return(bad) is None
            assert format_return(bad) == "n/a"
        assert usable_return(3) == 3.0
        assert format_return(1234567.891) == "1.23457e+06"
        assert format_return(2.5, ".1f") == "2.5"

    def test_the_best_candidate_loop_skips_a_trainable_that_played_nothing(self):
        from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import (
            SelfPlayCallback,
        )

        cb = SelfPlayCallback(
            num_trainable_policies=2,
            num_random_policies=6,
            min_iterations_between_champions=0,
            min_champion_trades=0,
        )
        made = []
        cb.league.create_snapshot = lambda algo, pid, value, it: made.append(pid)
        returns = {
            "policy_0": 50.0,
            "policy_1": None,
            **{f"policy_{i}": -float(i) for i in range(2, 8)},
        }
        result = {"training_iteration": 1, "env_runners": {"module_episode_returns_mean": returns}}
        cb.on_train_result(algorithm=object(), result=result)  # used to raise TypeError
        assert made == ["policy_0"]

    def test_the_iteration_log_survives_a_none_return(self, caplog):
        import logging
        from gym_continuousDoubleAuction.logging_setup import ROOT_NAME
        from gym_continuousDoubleAuction.train.train import TrainConfig, _log_iteration

        result = {
            "env_runners": {"module_episode_returns_mean": {"policy_0": None, "policy_1": 2.345}}
        }
        with caplog.at_level(logging.INFO, logger=ROOT_NAME):
            _log_iteration(1, 3, result, TrainConfig())
        assert "'policy_0': None" in caplog.text and "'policy_1': 2.3" in caplog.text

    def test_export_logs_a_champion_with_no_recorded_return(self, tmp_path, monkeypatch, caplog):
        import json
        import logging
        from gym_continuousDoubleAuction.logging_setup import ROOT_NAME
        from gym_continuousDoubleAuction.train import export
        from gym_continuousDoubleAuction.train.train import LEAGUE_STATE_FILE

        (tmp_path / LEAGUE_STATE_FILE).write_text(
            json.dumps(
                {
                    "champion_history": [
                        {"id": "champion_1", "source_policy": None, "iteration": 3, "return": None}
                    ]
                }
            )
        )
        monkeypatch.setattr(export.features_module, "load_module", lambda *a: object())
        monkeypatch.setattr(
            export, "build_record", lambda *a: {"state_dict": {}, "module_class": "X"}
        )
        import torch

        monkeypatch.setattr(torch, "save", lambda *a, **k: None)
        with caplog.at_level(logging.INFO, logger=ROOT_NAME):
            export.export(str(tmp_path), "champion_1", out=str(tmp_path / "o.pt"))
        assert "return n/a" in caplog.text

    def test_a_nan_champion_is_not_ranked(self):
        from gym_continuousDoubleAuction.train import export

        state = {
            "champion_history": [
                {"id": "champion_1", "return": float("nan")},
                {"id": "champion_2", "return": 1.0},
            ]
        }
        assert export.best_champion(state)["id"] == "champion_2"


class TestSizeHighCannotExceedTheMaximumOrder:
    """#275: `size_high` had no upper bound, so a config could ask for orders
    above `mkt_max_size` / `limit_max_size` (249 contracts against a maximum of
    100 at `size_high: 5.0`)."""

    @staticmethod
    def _validate(**changes):
        import json
        from gym_continuousDoubleAuction.envs.exchg.action_helper import Action_Helper

        helper = Action_Helper.__new__(Action_Helper)
        helper._act = {
            **json.loads(Path("config/tunable_constants.json").read_text(encoding="utf-8"))[
                "action_space"
            ],
            **changes,
        }
        helper._validate_action_space()

    def test_the_shipped_value_passes(self):
        self._validate()

    def test_the_boundary_is_allowed(self):
        self._validate(size_high=2.0)

    @pytest.mark.parametrize("too_high", [2.0001, 5.0, 100.0])
    def test_anything_above_it_is_refused_naming_the_key(self, too_high):
        with pytest.raises(ValueError, match="size_high"):
            self._validate(size_high=too_high)

    def test_the_bound_is_exactly_where_an_order_reaches_the_maximum(self):
        from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
            continuousDoubleAuctionEnv,
        )
        from gym_continuousDoubleAuction.envs.exchg.action_helper import SIZE_FRACTION_AT_MAX

        env = continuousDoubleAuctionEnv({"num_of_agents": 2, "is_render": False})
        assert SIZE_FRACTION_AT_MAX * env.mkt_size_mul + env.min_size == env.mkt_max_size
        assert SIZE_FRACTION_AT_MAX * env.limit_size_mul + env.min_size == env.limit_max_size
