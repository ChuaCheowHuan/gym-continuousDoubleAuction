"""The league statistics the champion trigger is computed from.

A module the mapping fn did not draw this iteration played no episodes, and
RLlib reports its mean return as NaN rather than omitting it. The trigger used
to filter only `None`, so a single NaN made `np.mean` NaN, made the threshold
NaN, and made `best_return > threshold` False for every candidate. Champion
creation then stopped - silently, permanently, and self-reinforcingly, since
each champion added to the pool makes it likelier that some baseline goes
undrawn.

Both GPU runs of 2026-08-15 died this way, at iterations 10 and 12 of 16,
reporting healthy league stats right up to the iteration it happened. See
doc/15_findings_and_recommendations.md S3-12.
"""
import logging

import pytest

from gym_continuousDoubleAuction.logging_setup import ROOT_NAME as LOGGER
from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import (
    SelfPlayCallback,
)


@pytest.fixture
def callback():
    cb = SelfPlayCallback(
        num_trainable_policies=2,
        num_random_policies=6,
        min_iterations_between_champions=0,
    )
    return cb


@pytest.fixture
def snapshots(callback, monkeypatch):
    """Records champion creation instead of touching an Algorithm."""
    created = []
    monkeypatch.setattr(
        callback, "_create_champion_snapshot_from_policy",
        lambda algorithm, pid, return_value, iteration: created.append(
            (pid, return_value, iteration)
        ),
    )
    return created


def _result(returns, iteration=1):
    return {
        "training_iteration": iteration,
        "env_runners": {"module_episode_returns_mean": returns},
    }


def _fire(callback, returns, iteration=1):
    callback.on_train_result(algorithm=object(), result=_result(returns, iteration))


class TestIdleModulesDoNotPoisonTheLeague:

    def test_a_champion_is_still_created(self, callback, snapshots, caplog):
        """The regression: one NaN used to veto every champion, forever."""
        with caplog.at_level(logging.INFO, logger=LOGGER):
            _fire(callback, {
                "policy_0": -1.0,       # far above the rest: a clear champion
                "policy_1": -100.0,
                "policy_2": -100.0,
                "policy_3": -100.0,
                "policy_6": float("nan"),   # never drawn this iteration
            })

        assert [pid for pid, _r, _i in snapshots] == ["policy_0"]
        assert "mean=nan" not in caplog.text

    def test_the_idle_modules_are_named(self, callback, snapshots, caplog):
        with caplog.at_level(logging.INFO, logger=LOGGER):
            _fire(callback, {
                "policy_0": -1.0,
                "policy_1": -100.0,
                "policy_5": float("nan"),
                "policy_6": float("nan"),
            })

        assert "policy_5, policy_6" in caplog.text
        assert "played no episodes" in caplog.text

    def test_a_full_league_says_nothing_about_idle_modules(self, callback, snapshots, caplog):
        with caplog.at_level(logging.INFO, logger=LOGGER):
            _fire(callback, {"policy_0": -1.0, "policy_1": -100.0})

        assert "played no episodes" not in caplog.text

    def test_the_statistics_ignore_the_idle_module(self, callback, snapshots, caplog):
        """Not just NaN-free - computed over the modules that actually played."""
        with caplog.at_level(logging.INFO, logger=LOGGER):
            _fire(callback, {
                "policy_0": 10.0,
                "policy_1": 10.0,
                "policy_2": 10.0,
                "policy_7": float("nan"),
            })

        assert "mean=10.00 std=0.00" in caplog.text

    def test_all_idle_is_reported_and_creates_nothing(self, callback, snapshots, caplog):
        """No episodes anywhere is a broken iteration, not a league update."""
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            _fire(callback, {"policy_0": float("nan"), "policy_1": float("nan")})

        assert snapshots == []
        assert "No valid policy returns" in caplog.text

    def test_an_idle_trainable_is_never_the_champion(self, callback, snapshots):
        """NaN loses every comparison, so it must not win by being first."""
        _fire(callback, {
            "policy_0": float("nan"),
            "policy_1": -1.0,
            "policy_2": -100.0,
            "policy_3": -100.0,
        })

        assert [pid for pid, _r, _i in snapshots] == ["policy_1"]


class TestLeagueMetrics:
    """League state as metrics, not only as log banners.

    doc/11 §2.5 listed four things the callback computes and discards, and §4
    item 4 asked for them as metrics: promotion events, the matchmaking pool
    size, and the time since the last snapshot - the last of which
    `_should_create_champion` has computed since it was written and thrown away
    every time. A banner in a worker's log file cannot be plotted against the
    return series; a metric can.
    """

    def _metrics(self):
        from unittest.mock import MagicMock
        return MagicMock()

    def _emitted(self, metrics, name):
        for call in metrics.log_value.call_args_list:
            if call.args and call.args[0] == name:
                return call
        return None

    def test_a_quiet_iteration_reports_no_promotion(self, callback, snapshots):
        metrics = self._metrics()
        callback.on_train_result(
            algorithm=object(), metrics_logger=metrics,
            result=_result({"policy_0": 1.0, "policy_1": 1.0}),
        )

        call = self._emitted(metrics, "champions_promoted")
        assert call.args[1] == 0.0
        assert call.kwargs["reduce"] == "sum"

    def test_the_pool_size_is_reported(self, callback, snapshots):
        metrics = self._metrics()
        callback.on_train_result(
            algorithm=object(), metrics_logger=metrics,
            result=_result({"policy_0": 1.0, "policy_1": 2.0}),
        )

        assert self._emitted(metrics, "available_modules").args[1] == float(
            len(callback.available_modules)
        )

    def test_idle_modules_are_counted(self, callback, snapshots):
        """The S3-12 signature as a number rather than a log line: a league that
        is quietly shrinking to the modules the mapping fn happens to draw."""
        metrics = self._metrics()
        callback.on_train_result(
            algorithm=object(), metrics_logger=metrics,
            result=_result({
                "policy_0": 1.0, "policy_1": 2.0,
                "policy_5": float("nan"), "policy_6": float("nan"),
            }),
        )

        assert self._emitted(metrics, "idle_modules").args[1] == 2.0

    def test_the_time_since_the_last_champion_is_reported(self, callback):
        """Computed by `_should_create_champion` since it was written, and
        discarded every time. It is what says whether the cooldown or the
        threshold is holding the league still."""
        callback.champion_history.append(
            {"id": "champion_1", "source_policy": "policy_0",
             "iteration": 4, "return": 1.0}
        )
        metrics = self._metrics()
        callback.on_train_result(
            algorithm=object(), metrics_logger=metrics,
            result=_result({"policy_0": 1.0, "policy_1": 1.0}, iteration=9),
        )

        assert self._emitted(metrics, "iterations_since_champion").args[1] == 5.0

    def test_no_champion_yet_reports_no_interval(self):
        """None-so-far and zero-iterations-ago are different states, and a 0
        here would read as "one was just made"."""
        cb = SelfPlayCallback(num_trainable_policies=2, num_random_policies=6)
        metrics = self._metrics()
        cb.on_train_result(
            algorithm=object(), metrics_logger=metrics,
            result=_result({"policy_0": 1.0, "policy_1": 1.0}),
        )

        assert self._emitted(metrics, "iterations_since_champion") is None

    def test_a_promotion_is_counted(self, callback, monkeypatch):
        """Counted from the champion count either side of the trigger, not from
        the branch that decided to try: a snapshot that raised and rolled itself
        back has not promoted anything, and `_create_champion_snapshot_from_policy`
        swallows its own exceptions."""
        def _promote(algorithm, pid, return_value, iteration):
            callback.champion_count += 1

        monkeypatch.setattr(
            callback, "_create_champion_snapshot_from_policy", _promote,
        )
        metrics = self._metrics()
        callback.on_train_result(
            algorithm=object(), metrics_logger=metrics,
            result=_result({"policy_0": 10.0, "policy_1": 0.0, "policy_5": 0.0}),
        )

        assert self._emitted(metrics, "champions_promoted").args[1] == 1.0

    def test_a_failed_snapshot_is_not_counted_as_a_promotion(self, callback, snapshots):
        """`snapshots` records the attempt without changing the count - which is
        exactly the shape of a snapshot that raised and rolled back."""
        metrics = self._metrics()
        callback.on_train_result(
            algorithm=object(), metrics_logger=metrics,
            result=_result({"policy_0": 10.0, "policy_1": 0.0, "policy_5": 0.0}),
        )

        assert snapshots, "the trigger should have fired"
        assert self._emitted(metrics, "champions_promoted").args[1] == 0.0
