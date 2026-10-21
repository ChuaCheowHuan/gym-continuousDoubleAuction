"""The refactoring review's issues (#252-#259): behaviour kept, the shape that was asked for.

A refactor changes no behaviour, so most of these tests pin the behaviour the old shape
had (and the suite as a whole is the guard); each also holds the new shape in place so it
cannot quietly drift back.
"""

import ast
import inspect
import os
from decimal import Decimal

import numpy as np
import pytest

from gym_continuousDoubleAuction.envs.account import account as account_module
from gym_continuousDoubleAuction.envs.account.account import STEP_COUNTERS, Account
from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import continuousDoubleAuctionEnv
from gym_continuousDoubleAuction.envs.exchg import info_helper


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


class TestPlainConvertsWithoutTheNeedlessCalls:
    """#258: `_plain` made 127,200 calls per 300 steps, nearly all on values that were plain."""

    @staticmethod
    def _reference(value):
        """The conversion as it was written before: recursion into every element."""
        if isinstance(value, np.ndarray):
            if value.ndim == 0:
                return value.item()
            return [TestPlainConvertsWithoutTheNeedlessCalls._reference(v) for v in value.tolist()]
        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, dict):
            return {
                k: TestPlainConvertsWithoutTheNeedlessCalls._reference(v) for k, v in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [TestPlainConvertsWithoutTheNeedlessCalls._reference(v) for v in value]
        return value

    CASES = [
        np.arange(6, dtype=np.float32).reshape(2, 3),
        np.array(3),
        np.array([1.5]),
        np.int64(4),
        np.float32(2.5),
        np.bool_(True),
        (np.int32(1), np.array([0.25], dtype=np.float32), 7),
        {"a": np.int64(2), "b": [np.float64(1.0), np.array([1, 2])], "c": {"d": np.array(5)}},
        {"s": "x", "n": None, "t": True, "i": 3, "f": 0.5, "l": [], "e": {}},
        [],
    ]

    @pytest.mark.parametrize("case", range(len(CASES)))
    def test_same_output_as_the_recursive_version(self, case):
        value = self.CASES[case]
        got, want = info_helper._plain(value), self._reference(value)
        assert got == want and type(got) is type(want)

    def test_a_dict_of_plain_fields_costs_one_call(self, monkeypatch):
        calls = []
        real = info_helper._plain
        monkeypatch.setattr(info_helper, "_plain", lambda v: (calls.append(1), real(v))[1])
        info_helper._plain({f"k{i}": i for i in range(40)})
        assert len(calls) == 1

    def test_an_array_is_one_tolist_with_no_recursion(self, monkeypatch):
        calls = []
        real = info_helper._plain
        monkeypatch.setattr(info_helper, "_plain", lambda v: (calls.append(1), real(v))[1])
        info_helper._plain(np.zeros((4, 5)))
        assert len(calls) == 1

    def test_a_numpy_value_inside_a_dict_is_still_converted(self):
        out = info_helper._plain({"a": np.int64(1), "b": np.array([2.0])})
        assert type(out["a"]) is int and out["b"] == [2.0]


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


class TestTheBookIsWrittenOncePerOperation:
    """#256: each order-book operation wrote the bid case and the ask case out in full."""

    @staticmethod
    def _book(mirror):
        from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook

        book = OrderBook()
        # A resting ladder on the opposite side, then a crossing limit and a market order.
        rest, cross = ("ask", "bid") if not mirror else ("bid", "ask")
        sign = 1 if not mirror else -1
        for i, (px, qty, tid) in enumerate([(100, 5, 1), (101, 3, 2), (102, 4, 3)]):
            book.process_order(
                {
                    "type": "limit",
                    "side": rest,
                    "quantity": qty,
                    "price": Decimal(100 + sign * (px - 100)),
                    "trade_id": tid,
                },
                False,
                False,
            )
        trades, rested = book.process_order(
            {
                "type": "limit",
                "side": cross,
                "quantity": 10,
                "price": Decimal(100 + sign * 2),
                "trade_id": 9,
            },
            False,
            False,
        )
        mkt, _ = book.process_order(
            {"type": "market", "side": cross, "quantity": 2, "trade_id": 8}, False, False
        )
        return book, trades, rested, mkt

    def test_a_mirrored_book_gives_the_mirrored_result(self):
        _b1, t1, r1, m1 = self._book(False)
        _b2, t2, r2, m2 = self._book(True)
        assert [(t["quantity"], t["init_party"]["ID"], t["counter_party"]["ID"]) for t in t1] == [
            (t["quantity"], t["init_party"]["ID"], t["counter_party"]["ID"]) for t in t2
        ]
        assert (r1 is None) == (r2 is None) and len(m1) == len(m2)
        assert [Decimal(100) + (Decimal(100) - t["price"]) for t in t1] == [t["price"] for t in t2]

    @pytest.mark.parametrize(
        "call,name",
        [
            (
                lambda b: b.process_market_order({"side": "x", "quantity": 1}, False),
                "process_market_order",
            ),
            (
                lambda b: b.process_limit_order(
                    {"side": "x", "quantity": 1, "price": 1}, False, False
                ),
                "process_limit_order",
            ),
            (lambda b: b.cancel_order("x", 1), "cancel_order"),
            (lambda b: b.modify_order(1, {"side": "x", "price": 1, "quantity": 1}), "modify_order"),
        ],
    )
    def test_a_bad_side_is_refused_naming_the_operation(self, call, name):
        from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook

        with pytest.raises(ValueError, match=name + r"\(\): side must be 'bid' or 'ask', got 'x'"):
            call(OrderBook())

    def test_the_side_helper_names_own_and_opposite(self):
        from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook

        book = OrderBook()
        bid, ask = book._side("bid", "t"), book._side("ask", "t")
        assert bid.own is book.bids and bid.opposite is book.asks and bid.opposite_name == "ask"
        assert ask.own is book.asks and ask.opposite is book.bids and ask.opposite_name == "bid"

    def test_no_operation_branches_on_the_side_any_more(self):
        from gym_continuousDoubleAuction.envs.orderbook import orderbook

        for name in ("process_market_order", "process_limit_order", "cancel_order", "modify_order"):
            source = ast.unparse(_function(orderbook, name))
            assert "== 'bid'" not in source and "== 'ask'" not in source, name


class TestNestingIsFlat:
    """#256: `place_order` wrapped its whole body in `if approved`, `parse_overrides` mixed three jobs."""

    def test_place_order_is_guard_clauses_and_a_lookup(self):
        from gym_continuousDoubleAuction.envs.agent import trader

        assert _depth(_function(trader, "place_order")) <= 2

    def test_every_order_type_has_a_placer_that_exists(self):
        from gym_continuousDoubleAuction.envs.agent.trader import Trader

        assert set(Trader._PLACERS) == {"market", "limit", "modify", "cancel"}
        assert all(callable(getattr(Trader, name)) for name in Trader._PLACERS.values())

    def test_parse_overrides_is_a_loop_over_a_coercion(self):
        from gym_continuousDoubleAuction.train import compare

        assert _depth(_function(compare, "parse_overrides")) <= 2
        assert _depth(_function(compare, "_coerce")) <= 2

    @pytest.mark.parametrize(
        "annotation,raw,expected",
        [
            ("int", "64", 64),
            ("float", "0.5", 0.5),
            ("str", "abc", "abc"),
            ("bool", "yes", True),
            ("bool", "Off", False),
            ("List[int]", "[1, 2]", [1, 2]),
            ("Dict[str, int]", '{"a": 1}', {"a": 1}),
            ("int", "none", None),
            ("float", "NULL", None),
        ],
    )
    def test_coerce_by_annotation(self, annotation, raw, expected):
        from gym_continuousDoubleAuction.train.compare import _coerce

        assert _coerce("f", raw, annotation) == expected

    @pytest.mark.parametrize(
        "annotation,raw",
        [
            ("bool", "ture"),
            ("List[int]", "{}"),
            ("Dict[str, int]", "[1]"),
            ("List[int]", "[1,"),
        ],
    )
    def test_a_bad_value_names_the_field(self, annotation, raw):
        from gym_continuousDoubleAuction.train.compare import _coerce

        with pytest.raises(SystemExit, match="--set f"):
            _coerce("f", raw, annotation)

    def test_a_list_annotation_is_not_mistaken_for_its_element_type(self):
        from gym_continuousDoubleAuction.train.compare import _coerce

        assert _coerce("f", "[1]", "List[int]") == [1]


class TestClearBatchIsFourSteps:
    """#252: `clear_batch` was 158 lines with a nested closure and a class inside it."""

    @staticmethod
    def _book():
        from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook

        book = OrderBook()
        book.process_order(
            {
                "type": "limit",
                "side": "ask",
                "quantity": 5,
                "price": Decimal(100),
                "trade_id": 1,
                "timestamp": 0,
            },
            False,
            False,
        )
        book.begin_batch()
        book.process_order(
            {
                "type": "limit",
                "side": "bid",
                "quantity": 8,
                "price": Decimal(101),
                "trade_id": 2,
                "timestamp": 1,
            },
            False,
            False,
        )
        book.process_order(
            {"type": "market", "side": "ask", "quantity": 2, "trade_id": 3, "timestamp": 1},
            False,
            False,
        )
        return book

    def test_the_function_is_short_and_defines_nothing_inside_itself(self):
        from gym_continuousDoubleAuction.envs.orderbook import orderbook

        node = _function(orderbook, "clear_batch")
        nested = [
            n
            for n in ast.walk(node)
            if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.Lambda)) and n is not node
        ]
        assert not nested
        body = [
            n
            for n in node.body
            if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))
        ]
        assert sum(n.end_lineno - n.lineno + 1 for n in body) <= 30

    def test_each_job_is_a_method(self):
        from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook

        for name in (
            "_clear_round",
            "_allocate_side",
            "_pair_fills",
            "_rest_leftovers",
            "_limit_of",
        ):
            assert callable(getattr(OrderBook, name)), name

    def test_a_round_reports_price_volume_and_participants(self):
        book = self._book()
        pending, book.pending = book.pending, []
        clearing = book._clear_round(pending, None, None)
        assert clearing.volume == 7 and clearing.p_star == Decimal(100)
        assert len(clearing.live) == 2 and not clearing.disturbed

    def test_nothing_crossing_is_a_zero_volume_round_not_an_exception(self):
        from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook

        book = OrderBook()
        book.begin_batch()
        book.process_order(
            {
                "type": "limit",
                "side": "bid",
                "quantity": 1,
                "price": Decimal(90),
                "trade_id": 1,
                "timestamp": 0,
            },
            False,
            False,
        )
        pending, book.pending = book.pending, []
        clearing = book._clear_round(pending, None, None)
        assert clearing.volume == 0 and clearing.p_star is None

    def test_someone_who_cannot_pay_sits_out_and_the_round_says_so(self):
        book = self._book()
        pending, book.pending = book.pending, []
        clearing = book._clear_round(pending, None, lambda tid, *rest: tid != 2)
        assert clearing.disturbed and len(clearing.dropped) == 1

    def test_the_sides_fill_the_same_volume_in_priority_order(self):
        book = self._book()
        pending, book.pending = book.pending, []
        clearing = book._clear_round(pending, None, None)
        buys, sells = book._allocate_side(True, clearing), book._allocate_side(False, clearing)
        assert sum(f for *_, f in buys) == sum(f for *_, f in sells) == clearing.volume
        # the market ask is the most aggressive, so it fills before the resting one
        assert [(resting, f) for _o, resting, f in sells] == [(False, 2), (True, 5)]

    def test_clearing_end_to_end_is_unchanged(self):
        book = self._book()
        results = book.clear_batch()
        trades = [t for _tid, trs, _o in results for t in trs]
        assert sum(t["quantity"] for t in trades) == 7
        assert {t["price"] for t in trades} == {Decimal(100)}
        assert len(book.tape) >= 2


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
        ],
    )
    def test_a_bad_value_is_refused_naming_the_key(self, override, message):
        from gym_continuousDoubleAuction.envs.settings import EnvSettings

        with pytest.raises(ValueError, match=message):
            EnvSettings.from_config(override)

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

    def test_the_constructor_no_longer_reads_keys_one_by_one(self):
        source = inspect.getsource(continuousDoubleAuctionEnv.__init__)
        assert "self._cfg(" not in source


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


class TestTrainModuleIsSplit:
    """#254: `train/train.py` was 2,224 lines holding config, build, checkpointing, progress and CLI."""

    @pytest.mark.parametrize("module", sorted(_MOVED))
    def test_every_name_is_still_importable_from_train_train(self, module):
        import importlib

        train_mod = importlib.import_module("gym_continuousDoubleAuction.train.train")
        owner = importlib.import_module(f"gym_continuousDoubleAuction.train.{module}")
        for name in _MOVED[module].split():
            assert getattr(train_mod, name) is getattr(owner, name), name

    @pytest.mark.parametrize("module", sorted(set(_MOVED) - {"cli"}))
    def test_a_moved_definition_lives_in_its_new_module(self, module):
        import importlib

        owner = importlib.import_module(f"gym_continuousDoubleAuction.train.{module}")
        for name in _MOVED[module].split():
            obj = getattr(owner, name)
            if inspect.isfunction(obj) or inspect.isclass(obj):
                assert obj.__module__ == owner.__name__, name

    def test_train_py_holds_the_loop_and_the_re_exports_only(self):
        from gym_continuousDoubleAuction.train import train as train_mod

        tree = ast.parse(inspect.getsource(train_mod))
        defined = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        assert defined == {"train", "__getattr__"}
        assert len(inspect.getsource(train_mod).splitlines()) < 260

    def test_no_module_is_the_old_monolith(self):
        from gym_continuousDoubleAuction import train as package

        folder = os.path.dirname(package.__file__)
        for name in ("config", "build", "checkpoint", "progress", "cli", "train"):
            with open(os.path.join(folder, name + ".py")) as fh:
                assert len(fh.read().splitlines()) < 800, name

    def test_the_command_line_names_resolve_lazily_to_cli(self):
        from gym_continuousDoubleAuction.train import cli
        from gym_continuousDoubleAuction.train import train as train_mod

        assert train_mod.main is cli.main and train_mod._parse_args is cli._parse_args
        with pytest.raises(AttributeError, match="no attribute 'nope'"):
            train_mod.nope

    @pytest.mark.parametrize("first", ["cli", "checkpoint", "progress"])
    def test_any_module_can_be_imported_first(self, first):
        """No import cycle: a fresh interpreter importing the module alone succeeds."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-I", "-c", f"import gym_continuousDoubleAuction.train.{first}"],
            capture_output=True,
            text=True,
            timeout=240,
            cwd=_REPO,
        )
        assert result.returncode == 0, result.stderr[-600:]

    def test_the_documented_command_still_runs(self):
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "gym_continuousDoubleAuction.train.train", "--help"],
            capture_output=True,
            text=True,
            timeout=240,
            cwd=_REPO,
        )
        assert result.returncode == 0 and "--iters" in result.stdout

    def test_log_lines_keep_the_logger_name_they_always_had(self):
        from gym_continuousDoubleAuction.train import build, checkpoint, cli, progress

        for module in (build, checkpoint, cli, progress):
            assert module.logger.name == "gym_continuousDoubleAuction.train.train"


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
    """#253: a callback is cloudpickled into every checkpoint; the new class must read the old one."""

    FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "callback_before_league.pkl")

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
