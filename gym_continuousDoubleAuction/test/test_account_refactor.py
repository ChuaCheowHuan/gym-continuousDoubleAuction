"""Tests for account refactor.

Moved from `test_refactors.py` by issue #361; the class docstrings keep the
original issue numbers.
"""

import ast

import inspect

import os


from decimal import Decimal


from gym_continuousDoubleAuction.envs.account import account as account_module

from gym_continuousDoubleAuction.envs.account.account import STEP_COUNTERS, Account


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


class TestAccountIsInitialisedInOnePlace:
    """#255: `__init__` and `reset_acc` assigned the same 29 attributes twice."""

    def test_init_assigns_only_the_fee_rates_and_leaves_the_rest_to_reset(self):
        assert _stored(Account.__init__) == {"maker_fee_bps", "taker_fee_bps"}

    def test_a_reset_account_equals_a_fresh_one(self):
        fresh = Account(3, 5000, 2, 5)
        used = Account(3, 5000, 2, 5)
        used.cash, used.net_position, used.realised_pnl = Decimal(1), 9, Decimal(7)
        used.num_trades_step, used.fill_qty_step, used.reward_terms = 4, 2, {"x": 1.0}
        used.liquidation_steps_left, used.max_nav = 3, Decimal(10**9)
        used.reset_acc(3, 5000)
        assert vars(used) == vars(fresh)

    def test_a_reset_keeps_the_fee_rates(self):
        acc = Account(0, 1000, 2, 5)
        acc.reset_acc(0, 1000)
        assert (acc.maker_fee_bps, acc.taker_fee_bps) == (Decimal(2), Decimal(5))

    def test_reset_reads_the_configured_cash_when_none_is_given(self):
        acc = Account(0, 10)
        acc.reset_acc(0)
        assert acc.cash == Account(1).cash

    def test_the_step_counters_are_exactly_the_per_step_attributes_reset_creates(self):
        listed = {name for name, _zero in STEP_COUNTERS}
        created = {
            n for n in _stored(Account.reset_acc) if n.endswith("_step") or n == "order_step_placed"
        }
        assert listed == created

    def test_clearing_zeroes_them_and_nothing_else(self):
        acc = Account(0, 1000)
        for name, _zero in STEP_COUNTERS:
            setattr(acc, name, 7)
        acc.liquidation_steps_left, acc.num_trades = 4, 9
        acc.clear_step_counters()
        assert all(getattr(acc, name) == zero for name, zero in STEP_COUNTERS)
        assert isinstance(acc.fill_value_step, Decimal)
        assert acc.liquidation_steps_left == 4 and acc.num_trades == 9

    def test_the_exchange_clears_them_through_the_account(self):
        source = inspect.getsource(
            __import__(
                "gym_continuousDoubleAuction.envs.exchg.exchg_helper", fromlist=["x"]
            ).Exchg_Helper.set_step_outputs
        )
        assert "clear_step_counters()" in source and "_step = 0" not in source
        assert account_module.STEP_COUNTERS is STEP_COUNTERS
