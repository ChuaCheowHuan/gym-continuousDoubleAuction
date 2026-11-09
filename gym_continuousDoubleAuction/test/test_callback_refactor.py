"""Tests for callback refactor.

Moved from `test_refactors.py` by issue #361; the class docstrings keep the
original issue numbers.
"""

import ast

import inspect

import os

import sys

from decimal import Decimal


import pytest


_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _stored(function):
    """The attribute names a function assigns on `self`."""
    tree = ast.parse(inspect.getsource(function).lstrip())
    return {
        n.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Attribute)
        and isinstance(n.ctx, ast.Store)
        and isinstance(n.value, ast.Name)
        and n.value.id == "self"
    }


def _depth(node, d=0):
    """Deepest control-flow nesting under `node`."""
    deepest = d
    for child in ast.iter_child_nodes(node):
        step = d + 1 if isinstance(child, (ast.If, ast.For, ast.While, ast.Try, ast.With)) else d
        deepest = max(deepest, _depth(child, step))
    return deepest


def _function(module, qualname):
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == qualname:
            return node
    raise AssertionError(qualname)


_MOVED = {
    "config": "generate_run_id _default TrainConfig ENV_NAME TRAIN_CONFIG_FILE PROGRESS_FILE "
    "_BROADCAST_TIMEOUT_S VF_EXPLAINED_VAR_KEY",
    "build": "register_env make_spaces _next_obs_connector OPTIMIZER_CONFIG_KEY "
    "_learner_class _learner_config_dict build_config build_algo log_module_sizes",
    "checkpoint": "CHECKPOINT_PREFIX CHECKPOINT_TMP_SUFFIX LEAGUE_STATE_FILE _is_checkpoint "
    "list_checkpoints save_checkpoint _prune_checkpoints warn_about_foreign_checkpoints "
    "algo_callback _write_league_state _read_league_state _reconcile_league_state "
    "STRUCTURAL_CONFIG_KEYS UNRESTORABLE_CONFIG_KEYS "
    "PRE_FEATURE_BEHAVIOUR _config_fingerprint _check_restored_config restore_candidates "
    "_fix_checkpoint_optimizer_betas",
    "progress": "NavConservationError nav_violations _check_nav_conservation _apply_iteration "
    "_broadcast_iteration _json_safe _append_progress vf_explained_var _log_iteration",
    "cli": "_parse_args configure_run_logging ray_logging_config main",
}


class TestCallbackCollaborators:
    """#253: the NAV audit, the league's return statistics and the tally helpers, apart from the callback."""

    @staticmethod
    def _env(navs, fees=0):
        from types import SimpleNamespace

        traders = [
            SimpleNamespace(ID=i, acc=SimpleNamespace(nav=Decimal(n), fees_paid=Decimal(fees)))
            for i, n in enumerate(navs)
        ]
        return SimpleNamespace(traders=traders)

    # ---- nav_audit
    def test_ledger_navs_reads_the_accounts_and_checks_them_against_what_was_reported(self):
        from gym_continuousDoubleAuction.train.callbk import nav_audit

        env = self._env(["100", "200"])
        assert nav_audit.ledger_navs(env, 0, {"agent_0": {"NAV": "100"}}, 2) == {
            "agent_0": Decimal(100),
            "agent_1": Decimal(200),
        }
        assert nav_audit.ledger_navs(env, 0, {"agent_0": {"NAV": "101"}}, 2) is None
        assert nav_audit.ledger_navs(env, 0, {}, 3) is None  # wrong number of traders
        assert nav_audit.ledger_navs(object(), 0, {}, 2) is None  # nothing to read

    def test_ledger_fees_sums_what_the_traders_paid(self):
        from gym_continuousDoubleAuction.train.callbk import nav_audit

        assert nav_audit.ledger_fees(self._env(["1", "2"], fees="1.5"), 0, 2) == Decimal(3)
        assert nav_audit.ledger_fees(object(), 0, 2) is None

    def test_a_vector_env_is_indexed_by_env_index(self):
        from types import SimpleNamespace
        from gym_continuousDoubleAuction.train.callbk import nav_audit

        vector = SimpleNamespace(envs=[self._env(["1", "1"]), self._env(["7", "8"])])
        assert nav_audit.ledger_navs(vector, 1, {}, 2) == {
            "agent_0": Decimal(7),
            "agent_1": Decimal(8),
        }
        assert nav_audit.ledger_navs(vector, 5, {}, 2) is None

    def test_fees_configured_looks_at_the_runner_config_and_the_env(self):
        from types import SimpleNamespace
        from gym_continuousDoubleAuction.train.callbk import nav_audit

        runner = SimpleNamespace(
            config=SimpleNamespace(env_config={"maker_fee_bps": 0, "taker_fee_bps": 3})
        )
        assert nav_audit.fees_configured(runner, SimpleNamespace())
        assert not nav_audit.fees_configured(SimpleNamespace(), SimpleNamespace(maker_fee_bps=0))
        assert nav_audit.fees_configured(SimpleNamespace(), SimpleNamespace(taker_fee_bps="2"))
        assert not nav_audit.fees_configured(SimpleNamespace(), SimpleNamespace(taker_fee_bps=True))

    def test_run_parameters_prefer_the_env_over_the_runner_config_over_the_fallbacks(self):
        from types import SimpleNamespace
        from gym_continuousDoubleAuction.train.callbk import nav_audit

        runner = SimpleNamespace(
            config=SimpleNamespace(env_config={"init_cash": 500, "num_of_agents": 4})
        )
        assert nav_audit.run_parameters(object(), object(), 9, 2) == (9, 2)
        assert nav_audit.run_parameters(runner, object(), 9, 2) == (500, 4)
        env = SimpleNamespace(unwrapped=SimpleNamespace(init_cash=700, num_of_agents=6))
        assert nav_audit.run_parameters(runner, env, 9, 2) == (700, 6)
        bare = SimpleNamespace(init_cash=11)
        assert nav_audit.run_parameters(object(), bare, 9, 2) == (11, 2)

    def test_sum_navs_uses_the_ledger_then_the_carried_value(self):
        from gym_continuousDoubleAuction.train.callbk import nav_audit

        last = {"agent_0": {"NAV": "100"}}
        carried = {"agent_1": "50"}
        with_ledger = nav_audit.sum_navs(
            last, carried, {"agent_0": Decimal(100), "agent_1": Decimal(60)}, 2
        )
        assert with_ledger.total == 160 and "marked to the end" in with_ledger.lines[1]
        without = nav_audit.sum_navs(last, carried, None, 2)
        assert without.total == 150 and "last reported" in without.lines[1]
        assert nav_audit.sum_navs(last, {}, None, 2).total == 100  # no value anywhere: left out

    def test_the_report_names_fees_only_when_there_are_some(self):
        from gym_continuousDoubleAuction.train.callbk import nav_audit

        nav = nav_audit.NavTotal(Decimal(1000), ["  agent_0 NAV: 1,000.00"])
        assert "Exchange fees" not in nav_audit.report("e1", nav, Decimal(0), Decimal(1000))
        text = nav_audit.report("e1", nav, Decimal("2.5"), Decimal(1000))
        assert "Episode e1 NAV verification" in text and "Exchange fees collected: 2.50" in text
        assert "Expected total initial cash: 1,000.00" in text

    # ---- league_stats
    def test_nan_and_none_returns_are_idle_not_valid(self):
        from gym_continuousDoubleAuction.train.callbk import league_stats

        out = league_stats.split_returns({"b": float("nan"), "a": None, "c": 1.5, "d": -2.0})
        assert out.valid == [1.5, -2.0] and out.idle == ["a", "b"]

    def test_the_best_trainable_is_the_highest_usable_return(self):
        from gym_continuousDoubleAuction.train.callbk import league_stats

        returns = {"policy_0": 1.0, "policy_1": 3.0, "champion_1": 99.0, "policy_2": float("nan")}
        assert league_stats.best_trainable(returns, ["policy_0", "policy_1", "policy_2"]) == (
            "policy_1",
            3.0,
        )
        none = league_stats.best_trainable({"policy_0": float("nan")}, ["policy_0", "policy_9"])
        assert none.module_id is None and none.value == -float("inf")

    def test_candidate_trades_reads_the_named_metric(self):
        from gym_continuousDoubleAuction.train.callbk import league_stats

        results = {"m": {"policy_0": "4.5", "policy_1": float("nan")}}
        assert league_stats.candidate_trades(results, "policy_0", "m") == 4.5
        assert league_stats.candidate_trades(results, "policy_1", "m") is None
        assert league_stats.candidate_trades(results, "policy_0", "other") is None

    # ---- activity
    def test_a_new_tally_shares_nothing_with_the_last(self):
        from gym_continuousDoubleAuction.train.callbk.activity import new_tally

        first, second = new_tally(), new_tally()
        first["last_nav"]["agent_0"] = "1"
        first["per_agent_fills"]["agent_0"] = 3
        first["term_sum"][
            "order_penalty"
            if "order_penalty" in first["term_sum"]
            else next(iter(first["term_sum"]))
        ] = 5.0
        assert second["last_nav"] == {} and second["per_agent_fills"] == {}
        assert all(v == 0.0 for v in second["term_sum"].values())

    def test_market_mid_and_as_float(self):
        from gym_continuousDoubleAuction.train.callbk.activity import as_float, market_mid

        assert market_mid({"best_bid": 99, "best_ask": 101}) == 100.0
        assert market_mid({"best_bid": 0, "best_ask": 101, "last_price": 50}) == 50.0
        assert market_mid({}) is None
        assert as_float("2.5") == 2.5 and as_float(None) is None and as_float("x") is None

    # ---- the callback delegates
    def test_the_callback_keeps_its_names_and_delegates(self):
        from gym_continuousDoubleAuction.train.callbk import league_stats, nav_audit
        from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import (
            SelfPlayCallback,
        )

        assert SelfPlayCallback._ledger_navs is nav_audit.ledger_navs
        assert SelfPlayCallback._ledger_fees is nav_audit.ledger_fees
        assert SelfPlayCallback._fees_configured is nav_audit.fees_configured
        assert (
            SelfPlayCallback._candidate_trades({"module_trades_per_episode": {"p": 2}}, "p") == 2.0
        )
        assert league_stats.candidate_trades({}, "p", "m") is None

    def test_the_hooks_no_longer_hold_the_audit_arithmetic(self):
        from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import (
            SelfPlayCallback,
        )

        end = inspect.getsource(SelfPlayCallback.on_episode_end)
        train = inspect.getsource(SelfPlayCallback.on_train_result)
        assert "per_agent = []" not in end and "hasattr(env_runner" not in end
        assert "np.isnan" not in train and "best_return = -float" not in train


class TestTheCallbackIsComposed:
    """#253: the league and the activity tally were state and methods of the callback itself."""

    @staticmethod
    def _cb(**kwargs):
        from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import (
            SelfPlayCallback,
        )

        return SelfPlayCallback(
            num_trainable_policies=2, num_random_policies=6, episode_data_dir=None, **kwargs
        )

    def test_the_callback_holds_a_league_and_an_activity_log(self):
        from gym_continuousDoubleAuction.train.callbk.activity import ActivityLog
        from gym_continuousDoubleAuction.train.callbk.league import League

        cb = self._cb()
        assert isinstance(cb.league, League) and isinstance(cb.activity, ActivityLog)

    def test_the_old_attribute_names_read_and_write_through(self):
        cb = self._cb()
        cb.champion_count = 3
        assert cb.league.champion_count == 3 and "champion_count" not in vars(cb)
        cb.league.available_modules.append("champion_9")
        assert cb.available_modules[-1] == "champion_9"
        assert cb.num_trainable == 2 and cb.num_random == 6
        cb.markout_horizons = [2, 4]
        assert cb.activity.markout_horizons == (2, 4)

    def test_the_callback_is_a_quarter_of_the_size_it_was(self):
        from gym_continuousDoubleAuction.train.callbk import league_based_self_play_callback as mod

        assert len(inspect.getsource(mod).splitlines()) < 900  # was 1,803

    def test_no_champion_logic_is_left_in_the_callback(self):
        from gym_continuousDoubleAuction.train.callbk import league_based_self_play_callback as mod

        tree = ast.parse(inspect.getsource(mod))
        called = {
            n.func.attr
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        assert not called & {"add_module", "remove_module", "choice", "set_state"}
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        assert "RLModuleSpec" not in names

    def test_the_wrappers_reach_the_league(self):
        cb = self._cb()
        calls = []
        cb.league.create_snapshot = lambda *a: calls.append(a)
        cb._create_champion_snapshot_from_policy("algo", "policy_0", 1.5, 7)
        assert calls == [("algo", "policy_0", 1.5, 7)]
        assert cb.league_state() == cb.league.state()

    def test_the_mapping_function_closes_over_the_league_only(self):
        import cloudpickle

        cb = self._cb()
        fn = cb.get_mapping_fn(cb)
        shipped = cloudpickle.dumps(fn)
        assert b"ActivityLog" not in shipped and b"EpisodeRecorder" not in shipped

        class Ep:
            id_ = "e1"

        assert [fn(f"agent_{i}", Ep()) for i in range(2)] == ["policy_0", "policy_1"]
        assert all(fn(f"agent_{i}", Ep()).startswith("policy_") for i in range(2, 8))

    def test_the_mapping_follows_the_pool_it_is_given(self):
        cb = self._cb(champion_weight=1e9, original_opponent_weight=1e-9)
        cb.available_modules.append("champion_1")

        class Ep:
            id_ = "x"

        picks = {cb.get_mapping_fn(cb)(f"agent_{i}", Ep()) for i in range(2, 8)}
        assert picks == {"champion_1"}


class TestACheckpointWrittenBeforeTheSplitStillLoads:
    """#253: a callback is cloudpickled into every checkpoint; the new class must read the old one.

    `fixtures/callback_before_league.pkl` was written by Python 3.12 and holds
    cloudpickled *bytecode*. Loading it under another Python minor is not a
    supported operation: on 3.13 `test_its_mapping_function_still_maps` segfaults,
    and a segfault ends the whole pytest process rather than failing one test
    (#368). Skip the three fixture tests on any other minor; the fourth test in
    this class builds its callback from the current source and runs everywhere.
    """

    FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "callback_before_league.pkl")
    #: The interpreter that wrote `FIXTURE` (docs/15 #353/#368).
    FIXTURE_PYTHON = (3, 12)
    needs_fixture_python = pytest.mark.skipif(
        sys.version_info[:2] != FIXTURE_PYTHON,
        reason=(
            f"fixtures/callback_before_league.pkl holds Python "
            f"{FIXTURE_PYTHON[0]}.{FIXTURE_PYTHON[1]} cloudpickled bytecode; loading it "
            f"under {sys.version_info[0]}.{sys.version_info[1]} can segfault the suite"
        ),
    )

    @needs_fixture_python
    def test_a_real_pickle_from_the_previous_source_loads_and_keeps_its_league(self):
        import pickle

        with open(self.FIXTURE, "rb") as fh:
            cb, mapping_fn = pickle.load(fh)
        assert type(cb.league).__name__ == "League"
        assert cb.champion_history == [
            {"id": "champion_1", "source_policy": "policy_0", "iteration": 3, "return": 1.5}
        ]
        assert (cb.champion_count, cb.champion_id_counter) == (1, 1)
        assert cb.available_modules[-1] == "champion_1"
        assert cb.markout_horizons == (1, 5) and cb.num_trainable == 2
        assert cb.min_champion_trades == 1.0 and cb.promotion_reference == "pooled"

    @needs_fixture_python
    def test_its_mapping_function_still_maps(self):
        import pickle

        with open(self.FIXTURE, "rb") as fh:
            _cb, mapping_fn = pickle.load(fh)

        class Ep:
            id_ = "e1"

        assert mapping_fn("agent_0", Ep()) == "policy_0"
        assert mapping_fn("agent_5", Ep()) in {
            "policy_2",
            "policy_3",
            "policy_4",
            "policy_5",
            "policy_6",
            "policy_7",
            "champion_1",
        }

    @needs_fixture_python
    def test_the_restored_callback_keeps_working_and_can_be_pickled_again(self):
        import pickle

        with open(self.FIXTURE, "rb") as fh:
            cb, _fn = pickle.load(fh)
        again = pickle.loads(pickle.dumps(cb))
        assert again.champion_history == cb.champion_history
        assert again.league.available_modules == cb.league.available_modules

    def test_a_flat_state_is_migrated_whatever_knobs_it_lacks(self):
        from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import (
            SelfPlayCallback,
        )

        cb = TestTheCallbackIsComposed._cb()
        state = cb.__getstate__()
        state.update(vars(state.pop("league")))
        for name in ("min_champion_trades", "promotion_reference", "_warned_reference_fallback"):
            del state[name]
        del state["activity"]
        old = SelfPlayCallback.__new__(SelfPlayCallback)
        old.__setstate__(state)
        assert old.min_champion_trades == 0.0 and old.promotion_reference == "pooled"
        assert old.markout_horizons == () and old._activity == {}


class TestTheLeagueAloneAndTheActivityLogAlone:
    @staticmethod
    def _league(**kwargs):
        from gym_continuousDoubleAuction.train.callbk.league import League

        defaults = dict(
            std_dev_multiplier=1.0,
            max_champions=2,
            min_iterations_between_champions=1,
            original_opponent_weight=1.0,
            champion_weight=2.0,
            min_champion_trades=0.0,
            promotion_reference="pooled",
        )
        defaults.update(kwargs)
        return League(2, 4, **defaults)

    def test_a_bad_promotion_reference_is_refused_by_name(self):
        with pytest.raises(ValueError, match="promotion_reference"):
            self._league(promotion_reference="sometimes")

    def test_a_multiplier_that_can_never_be_cleared_is_warned_about(self, caplog):
        with caplog.at_level("WARNING"):
            self._league(std_dev_multiplier=9.0)
        assert "can never be cleared" in caplog.text

    def test_assess_promotes_the_best_trainable_that_clears_the_bar(self):
        league = self._league()
        made = []
        league.create_snapshot = lambda algo, pid, value, it: made.append((pid, value))
        returns = {
            "policy_0": 9.0,
            "policy_1": 1.0,
            "policy_2": 0.0,
            "policy_3": 0.0,
            "policy_4": 0.0,
            "policy_5": 0.0,
        }
        out = league.assess(object(), returns, {}, 4)
        assert made == [("policy_0", 9.0)]
        assert out.state["threshold"] < 9.0 and out.state["idle_modules"] == 0
        assert out.idle == 0 and out.std > 0

    def test_assess_with_no_usable_returns_is_none(self):
        assert self._league().assess(object(), {"policy_0": float("nan")}, {}, 1) is None

    def test_assess_refuses_a_passive_candidate(self):
        league = self._league(min_champion_trades=1.0)
        league.create_snapshot = lambda *a: pytest.fail("promoted a policy that does not trade")
        returns = {
            "policy_0": 9.0,
            "policy_1": 1.0,
            "policy_2": 0.0,
            "policy_3": 0.0,
            "policy_4": 0.0,
            "policy_5": 0.0,
        }
        out = league.assess(object(), returns, {"module_trades_per_episode": {"policy_0": 0.0}}, 2)
        assert out.state["refused_passive"] == 1

    def test_state_and_restore_round_trip_and_repair_the_counter(self):
        league = self._league()
        league.champion_history = [
            {"id": "champion_4", "source_policy": "policy_0", "iteration": 2, "return": 1.0}
        ]
        league.champion_count, league.champion_id_counter = 1, 1
        league.available_modules.append("champion_4")
        saved = league.state()
        other = self._league()
        repairs = other.restore(saved, present_modules=["policy_0", "champion_4"])
        assert other.champion_history == league.champion_history
        assert other.champion_id_counter >= 4  # never re-mints champion_4
        assert other.available_modules == league.available_modules
        assert repairs

    def test_activity_log_caps_the_open_episodes(self):
        from gym_continuousDoubleAuction.train.callbk.activity import ActivityLog

        log = ActivityLog()
        for i in range(log.max_live + 10):
            log.start(f"e{i}")
        assert len(log.tallies) <= log.max_live and "e0" not in log.tallies

    def test_activity_log_counts_a_step_and_emits_metrics_for_the_episode(self):
        from unittest.mock import MagicMock

        from gym_continuousDoubleAuction.train.callbk.activity import ActivityLog

        log = ActivityLog()
        log.start("e")
        info = {
            "NAV": "1000",
            "net_position": 0,
            "is_pass_action": True,
            "num_rejected_step": 1,
            "reward_terms": {},
        }
        tally = log.record_step("e", {"agent_0": dict(info), "agent_1": dict(info)})
        assert tally["agent_steps"] == 2 and tally["passes"] == 2 and tally["rejections"] == 2

        class Ep:
            id_ = "e"

        metrics = MagicMock()
        log.log_episode(Ep(), metrics)
        names = {c.args[0] for c in metrics.log_value.call_args_list if isinstance(c.args[0], str)}
        assert {"pass_action_fraction", "order_rejection_fraction"} <= names
        assert "e" not in log.tallies  # popped when it is logged

    def test_a_step_for_an_episode_the_start_hook_missed_does_not_raise(self):
        from gym_continuousDoubleAuction.train.callbk.activity import ActivityLog

        assert ActivityLog().record_step("never-started", {})["steps"] == 1
