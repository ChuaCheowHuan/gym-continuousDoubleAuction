"""Tests for compare and evaluate fixes.

Moved from `test_s4_minor_fixes.py` by issue #361; the class docstrings keep the
original issue numbers.
"""

from decimal import Decimal

import pytest


from gym_continuousDoubleAuction.envs.orderbook.order import Order


def _order(order_list, order_id, qty=1, price=10):
    quote = {
        "timestamp": 1,
        "quantity": Decimal(qty),
        "price": Decimal(price),
        "order_id": order_id,
        "trade_id": "t",
    }
    order = Order(quote, order_list)
    order_list.append_order(order)
    return order


class TestCompareSetRefusesAnUnrecognisedBoolean:
    """#236: `--set strict_nav_check=ture` was silently False."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("true", True),
            ("True", True),
            ("1", True),
            ("yes", True),
            ("on", True),
            ("false", False),
            ("FALSE", False),
            ("0", False),
            ("no", False),
            ("off", False),
        ],
    )
    def test_the_recognised_spellings(self, raw, expected):
        from gym_continuousDoubleAuction.train.compare import parse_overrides

        assert parse_overrides([f"action_mask={raw}"]) == {"action_mask": expected}

    @pytest.mark.parametrize("raw", ["ture", "enabled", "True1", "", "2"])
    def test_anything_else_is_refused_naming_the_flag(self, raw):
        from gym_continuousDoubleAuction.train.compare import parse_overrides

        with pytest.raises(SystemExit, match="--set action_mask: expected a boolean"):
            parse_overrides([f"action_mask={raw}"])


class TestCompareTableShowsAFailedRun:
    """#262: the `seeds` column counted runs with a non-None return, so a failed
    run was recorded as a smaller experiment rather than as a failure."""

    @staticmethod
    def _rows(returns):
        return [
            {
                "encoder": "mlp",
                "seed": i,
                "return": r,
                "vf_explained_var": 0.5,
                "pass_action_fraction": 0.1,
                "parameters": 1000,
            }
            for i, r in enumerate(returns)
        ]

    def test_all_runs_reporting_shows_the_plain_count(self):
        from gym_continuousDoubleAuction.train.compare import render

        table = render(self._rows([1.0, 1.1, 0.9]))
        assert "| mlp | 3 |" in table and "No return was recorded" not in table

    def test_a_failed_run_shows_n_over_total_and_is_named(self):
        from gym_continuousDoubleAuction.train.compare import render

        table = render(self._rows([1.0, None, 0.9]))
        assert "| mlp | 2/3 |" in table
        assert "No return was recorded for: mlp seed 1" in table

    def test_every_failed_run_is_named(self):
        from gym_continuousDoubleAuction.train.compare import render

        table = render(self._rows([None, 1.0, None]))
        assert "mlp seed 0, mlp seed 2" in table

    def test_the_few_seeds_warning_still_counts_usable_runs(self):
        from gym_continuousDoubleAuction.train.compare import render

        assert "Fewer than three seeds" in render(self._rows([1.0, None, 0.9]))


class TestEvaluateMaxStepInRandomMode:
    """#263: `--max-step` set `max_step`, which `episode_length_mode: random` ignores."""

    def test_fixed_mode_sets_only_max_step(self):
        from gym_continuousDoubleAuction.train.evaluate import apply_max_step

        config = {
            "episode_length_mode": "fixed",
            "max_step": 100,
            "max_step_min": 10,
            "max_step_max": 200,
        }
        assert apply_max_step(config, 50) == {**config, "max_step": 50}

    def test_random_mode_pins_both_bounds_to_it(self):
        from gym_continuousDoubleAuction.train.evaluate import apply_max_step

        config = {
            "episode_length_mode": "random",
            "max_step": 100,
            "max_step_min": 10,
            "max_step_max": 200,
        }
        out = apply_max_step(config, 50)
        assert (out["max_step"], out["max_step_min"], out["max_step_max"]) == (50, 50, 50)

    def test_no_override_changes_nothing(self):
        from gym_continuousDoubleAuction.train.evaluate import apply_max_step

        config = {"episode_length_mode": "random", "max_step_min": 10, "max_step_max": 200}
        assert apply_max_step(config, None) == config

    def test_the_input_is_not_modified(self):
        from gym_continuousDoubleAuction.train.evaluate import apply_max_step

        config = {"episode_length_mode": "random", "max_step_min": 10, "max_step_max": 200}
        apply_max_step(config, 5)
        assert config["max_step_min"] == 10

    def test_a_real_random_mode_env_then_runs_the_requested_length(self):
        from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
            continuousDoubleAuctionEnv,
        )
        from gym_continuousDoubleAuction.train.evaluate import apply_max_step

        base = {
            "num_of_agents": 2,
            "is_render": False,
            "episode_length_mode": "random",
            "max_step_min": 20,
            "max_step_max": 60,
        }
        lengths = set()
        for seed in range(4):
            env = continuousDoubleAuctionEnv(apply_max_step(base, 9))
            env.reset(seed=seed)
            steps = 0
            while steps < 200:  # a bound, so a regression fails instead of hanging
                steps += 1
                _o, _r, term, trunc, _i = env.step(
                    {a: env.action_spaces[a].sample() for a in env.agents}
                )
                if term["__all__"] or trunc["__all__"]:
                    break
            lengths.add(steps)
        assert lengths == {9}
