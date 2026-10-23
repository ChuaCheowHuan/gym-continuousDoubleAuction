"""The hardening and duplication pass of issue #247, one class per item."""

import ast
import inspect
import time
from decimal import Decimal

import pytest

from gym_continuousDoubleAuction import config_loader
from gym_continuousDoubleAuction.envs.account.account import Account
from gym_continuousDoubleAuction.envs.agent.trader import Trader, _is_market_price
from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook
from gym_continuousDoubleAuction.train import train as train_module
from gym_continuousDoubleAuction.train.model.encoders import (
    token_embed,
    tokenize,
    transformer,
)


def _q(side, qty, price, tid):
    return {"type": "limit", "side": side, "quantity": qty, "price": price, "trade_id": tid}


class TestAFreshBookHasBatchUnaffordable:
    def test_it_is_an_empty_list_before_any_clearing(self):
        assert OrderBook(10).batch_unaffordable == []


class TestBatchClearingChecksItsVolumeWithoutAssert:
    """A bare `assert` disappears under `python -O`, leaving a one-sided trade."""

    def test_clear_batch_contains_no_assert_statement(self):
        tree = ast.parse(
            inspect.getsource(OrderBook.clear_batch).replace("\n    ", "\n", 0).lstrip()
        )
        assert not [n for n in ast.walk(tree) if isinstance(n, ast.Assert)]

    def test_a_mismatch_raises_a_named_error(self, monkeypatch):
        book = OrderBook(10)
        book.begin_batch()
        book.process_order(_q("bid", 10, 102, 0), False, False)
        book.process_order(_q("ask", 10, 98, 1), False, False)
        real = book._auction
        # An auction that claims more volume than the orders can supply: both sides
        # fill 10, the "executable volume" says 15.
        monkeypatch.setattr(
            book, "_auction", lambda *a, **k: (lambda r: (r[0], r[1], r[2] + 5))(real(*a, **k))
        )
        with pytest.raises(RuntimeError, match="sides must match"):
            book.clear_batch(reference_price=100)

    def test_a_normal_batch_still_clears(self):
        book = OrderBook(10)
        book.begin_batch()
        book.process_order(_q("bid", 10, 102, 0), False, False)
        book.process_order(_q("ask", 10, 98, 1), False, False)
        assert len(book.clear_batch(reference_price=100)) == 2


class TestSettleBatchRefusesBeforeItBooksAnything:
    @staticmethod
    def _trade(init, counter, qty=2):
        return {
            "price": Decimal(100),
            "quantity": qty,
            "time": 1,
            "timestamp": 1,
            "init_party": {"ID": init, "side": "bid", "order_id": None, "new_book_quantity": None},
            "counter_party": {
                "ID": counter,
                "side": "ask",
                "order_id": None,
                "new_book_quantity": None,
                "resting": False,
            },
        }

    def test_a_self_pair_late_in_the_list_leaves_the_ledger_untouched(self):
        traders = [Trader(i, 100_000) for i in range(2)]
        before = (traders[0].acc.cash, traders[0].acc.net_position)
        with pytest.raises(ValueError, match="own order"):
            traders[0].settle_batch([self._trade(0, 1), self._trade(0, 0)], None, traders)
        assert (traders[0].acc.cash, traders[0].acc.net_position) == before
        assert traders[1].acc.net_position == 0

    def test_a_clean_list_is_still_booked(self):
        traders = [Trader(i, 100_000) for i in range(2)]
        traders[0].settle_batch([self._trade(0, 1)], None, traders)
        assert traders[0].acc.net_position == 2


class TestOneDefinitionOfAMarketPrice:
    def test_none_and_the_sentinel_are_market_prices(self):
        assert _is_market_price(None) and _is_market_price(-1.0) and _is_market_price(-1)

    def test_a_real_price_is_not(self):
        assert not _is_market_price(100.0) and not _is_market_price(Decimal("0.5"))

    def test_a_market_order_with_no_price_is_approved_and_fills(self):
        env = continuousDoubleAuctionEnv({"num_of_agents": 2, "is_render": False})
        env.reset(seed=1)
        t = env.traders
        t[1].place_order("limit", "ask", 5, 101.0, env.LOB, t)
        t[0].place_order("market", "bid", 3, None, env.LOB, t)  # was an InvalidOperation
        assert t[0].acc.net_position == 3


class TestOneLookupForAnAgent:
    def test_counter_party_lookup_uses_find_agent(self):
        assert "_find_agent" in inspect.getsource(Trader._process_counter_party)

    def test_it_finds_an_agent_whose_id_is_not_its_index(self):
        traders = [Trader(5, 1000), Trader(9, 1000)]
        trade = {
            "price": Decimal(10),
            "quantity": 1,
            "time": 1,
            "timestamp": 1,
            "init_party": {"ID": 5, "side": "bid"},
            "counter_party": {"ID": 9, "side": "ask", "order_id": None, "new_book_quantity": None},
        }
        traders[0]._process_counter_party(traders, trade)
        assert traders[1].acc.net_position == -1


class TestMarkToMarketUsesTheProfitRule:
    def test_it_agrees_with_cal_profit_for_a_long_and_a_short(self):
        for position, side in ((5, "long"), (-5, "short")):
            acc = Account(0, 1000)
            acc.net_position, acc.cost_basis = position, Decimal(500)
            acc.mark_to_mkt(0, Decimal(120))
            expected = acc.cal_profit(side, abs(position) * Decimal(120), Decimal(500))
            assert acc.profit == expected

    def test_calculate_no_longer_restates_the_rule(self):
        from gym_continuousDoubleAuction.envs.account.calculate import Calculate

        assert "cal_profit" in inspect.getsource(Calculate.mark_to_mkt)


class TestDefaultsAreReadWhenTheObjectIsBuilt:
    """Fee and cash defaults were `env_default(...)` in the signature, evaluated once at
    import, so a config change after import never reached a bare `Trader()`."""

    @staticmethod
    def _with_config(tmp_path, monkeypatch, **changes):
        import json
        import shutil

        tree = tmp_path / "config"
        shutil.copytree(config_loader.config_dir(), tree)
        path = tree / "env_defaults.json"
        data = json.load(open(path))
        data["environment"].update(changes)
        json.dump(data, open(path, "w"))
        monkeypatch.setenv(config_loader.CONFIG_DIR_ENV_VAR, str(tree))
        config_loader.reload()

    def teardown_method(self):
        config_loader.reload()

    def test_a_bare_trader_reads_the_current_cash(self, tmp_path, monkeypatch):
        self._with_config(tmp_path, monkeypatch, init_cash=12345)
        assert Trader(0).acc.cash == Decimal(12345)

    def test_a_bare_account_reads_the_current_fee(self, tmp_path, monkeypatch):
        self._with_config(tmp_path, monkeypatch, taker_fee_bps=7)
        assert Account(0).taker_fee_bps == Decimal(7)

    def test_an_explicit_none_is_still_refused_not_defaulted(self):
        with pytest.raises(ValueError, match="taker_fee_bps"):
            Account(0, 1000, 0, None)

    def test_an_explicit_value_still_wins(self):
        assert Trader(0, 777).acc.cash == Decimal(777)


class TestTrainConfigDoesNotReFlattenTheFilePerField:
    def test_instantiating_one_is_cheap(self):
        train_module.TrainConfig()  # warm the cache
        started = time.perf_counter()
        for _ in range(10):
            train_module.TrainConfig()
        assert (time.perf_counter() - started) / 10 < 0.012  # was ~0.023 s

    def test_the_file_is_flattened_once_across_instances(self, monkeypatch):
        calls = []
        real = config_loader.flatten
        monkeypatch.setattr(
            config_loader, "flatten", lambda *a, **k: calls.append(1) or real(*a, **k)
        )
        config_loader.reload()
        train_module.TrainConfig()
        train_module.TrainConfig()
        assert len(calls) == 1

    def test_a_list_default_is_still_its_own_object(self):
        a, b = train_module.TrainConfig(), train_module.TrainConfig()
        a.fcnet_hiddens.append(1)
        assert 1 not in b.fcnet_hiddens
        assert 1 not in train_module.TrainConfig().fcnet_hiddens

    def test_the_view_cannot_be_assigned_into(self):
        with pytest.raises(TypeError):
            config_loader.flat_view("train_config.json")["gamma"] = 0.5

    def test_flat_still_hands_out_a_copy(self):
        first = config_loader.flat("train_config.json")
        first["fcnet_hiddens"].append(99)
        assert 99 not in config_loader.flat("train_config.json")["fcnet_hiddens"]

    def test_a_reload_picks_up_a_changed_file(self, tmp_path, monkeypatch):
        import json
        import shutil

        tree = tmp_path / "config"
        shutil.copytree(config_loader.config_dir(), tree)
        monkeypatch.setenv(config_loader.CONFIG_DIR_ENV_VAR, str(tree))
        config_loader.reload()
        assert train_module.TrainConfig().gamma == 0.999
        path = tree / "train_config.json"
        data = json.load(open(path))
        data["ppo"]["gamma"] = 0.9
        json.dump(data, open(path, "w"))
        config_loader.reload()
        assert train_module.TrainConfig().gamma == 0.9
        config_loader.reload()


class TestEnvResetHandsOptionsOn:
    def test_reset_calls_the_parent_unconditionally(self):
        source = inspect.getsource(continuousDoubleAuctionEnv.reset)
        assert "if hasattr(super()" not in source
        assert "super().reset(seed=seed, options=options)" in source

    def test_reset_with_options_and_a_seed_still_works(self):
        env = continuousDoubleAuctionEnv({"num_of_agents": 2, "is_render": False})
        first, _ = env.reset(seed=3, options={"anything": 1})
        again, _ = env.reset(seed=3)
        assert {k: list(v) for k, v in first.items()} == {k: list(v) for k, v in again.items()}


class TestOnePoolingsDefinition:
    def test_the_encoders_share_the_tokenizers_tuple(self):
        assert transformer.POOLINGS is tokenize.POOLINGS
        assert token_embed.POOLINGS is tokenize.POOLINGS
        assert tokenize.POOLINGS == ("mean", "attention")


class TestTidiedDocsAndDeadCode:
    def test_the_record_docstring_does_not_claim_to_set_a_flag(self):
        doc = OrderBook._record.__doc__
        assert "sets no flag" in " ".join(doc.split())

    def test_process_order_list_carries_no_commented_out_block(self):
        source = inspect.getsource(OrderBook.process_order_list)
        assert "party1" not in source and "party2" not in source

    def test_size_decrease_does_not_assign_an_unused_value(self):
        tree = ast.parse(
            inspect.getsource(Account._size_decrease).replace("    ", "", 1).lstrip()
            if False
            else "def f():\n" + inspect.getsource(Account._size_decrease)
        )
        assigned = {
            t.id
            for n in ast.walk(tree)
            if isinstance(n, ast.Assign)
            for t in n.targets
            if isinstance(t, ast.Name)
        }
        # `mkt_val` is used in the branch that computes the position value, and was
        # assigned and dropped in the other; the else branch must not assign it.
        else_branch = [n for n in ast.walk(tree) if isinstance(n, ast.If)][0].orelse
        assert "mkt_val" not in {
            t.id
            for n in else_branch
            if isinstance(n, ast.Assign)
            for t in n.targets
            if isinstance(t, ast.Name)
        }
        assert "mkt_val" in assigned


# --------------------------------------------------------------------------- #248
import numpy as np  # noqa: E402

from gym_continuousDoubleAuction.envs.exchg.info_helper import _plain  # noqa: E402


def _plain_reference(value):
    """The function as it was before the fast path: the behaviour to preserve."""
    if isinstance(value, np.ndarray):
        if value.ndim == 0:
            return value.item()
        return [_plain_reference(v) for v in value.tolist()]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {k: _plain_reference(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_reference(v) for v in value]
    return value


class TestPlainKeepsItsBehaviourWithAFastPath:
    """#248: `_plain` was 14% of a profiled batch episode, nearly all of it plain scalars
    paying four isinstance checks to learn they needed nothing."""

    VALUES = [
        0,
        1,
        -3,
        2.5,
        True,
        False,
        None,
        "NAV",
        "",
        Decimal("1.5"),
        np.int32(4),
        np.int64(5),
        np.float32(0.25),
        np.float64(0.5),
        np.bool_(True),
        np.array(7),
        np.array([1, 2]),
        np.array([[1.0], [2.0]], dtype=np.float32),
        (np.int32(1), np.array([0.5], dtype=np.float32)),
        {"a": np.int64(1), "b": [np.float32(2.0), {"c": np.array([3])}], "d": "x"},
        [1, 2.5, None],
        {},
    ]

    @pytest.mark.parametrize("value", VALUES, ids=lambda v: type(v).__name__)
    def test_the_result_is_what_it_always_was(self, value):
        got, want = _plain(value), _plain_reference(value)
        assert got == want and type(got) is type(want)

    def test_a_numpy_scalar_is_still_converted_not_passed_through(self):
        assert type(_plain(np.float64(1.5))) is float
        assert type(_plain(np.int64(2))) is int

    def test_a_bool_stays_a_bool(self):
        assert _plain(True) is True

    def test_the_result_is_json_serialisable(self):
        import json

        json.dumps(_plain({"a": np.int64(1), "b": [np.float32(2.0)], "c": np.array([1, 2])}))


class TestReferencePriceIsCachedPerSnapshot:
    """#248: every trader's observation and mask asked for the same number."""

    @staticmethod
    def _uncached(env):
        return env._snap_to_tick(env.mid_price())

    @pytest.mark.parametrize("clearing", ["sequential", "batch"])
    def test_it_always_equals_the_uncached_value(self, clearing):
        env = continuousDoubleAuctionEnv(
            {"num_of_agents": 4, "max_step": 80, "is_render": False, "step_clearing": clearing}
        )
        env.reset(seed=3)
        for _ in range(80):
            for _call in range(3):  # repeated calls inside one step
                assert env.reference_price() == self._uncached(env)
            _o, _r, term, trunc, _i = env.step(
                {a: env.action_spaces[a].sample() for a in env.agents}
            )
            assert env.reference_price() == self._uncached(env)
            if term["__all__"] or trunc["__all__"]:
                break

    def test_a_new_print_on_the_same_snapshot_is_a_miss(self):
        """On a one-sided book the reference follows the last price, so the key has to
        include it, not only the snapshot."""
        env = continuousDoubleAuctionEnv({"num_of_agents": 2, "is_render": False})
        env.reset(seed=1)
        first = env.reference_price()
        env.last_price = Decimal(first) + 7
        assert env.reference_price() == self._uncached(env)

    def test_a_new_snapshot_is_a_miss(self):
        env = continuousDoubleAuctionEnv({"num_of_agents": 2, "is_render": False})
        env.reset(seed=1)
        env.reference_price()
        t = env.traders
        t[0].place_order("limit", "bid", 5, 95.0, env.LOB, t)
        t[1].place_order("limit", "ask", 5, 105.0, env.LOB, t)
        env.step(
            {
                a: {
                    "category": 0,
                    "order_slot": 0,
                    "price": 0,
                    "price_offset": 1,
                    "size": np.zeros(1, dtype=np.float32),
                }
                for a in env.agents
            }
        )
        assert env.reference_price() == self._uncached(env)

    def test_two_envs_do_not_share_a_cache(self):
        a = continuousDoubleAuctionEnv(
            {
                "num_of_agents": 2,
                "is_render": False,
                "initial_price_min": 50,
                "initial_price_max": 50,
            }
        )
        b = continuousDoubleAuctionEnv(
            {
                "num_of_agents": 2,
                "is_render": False,
                "initial_price_min": 150,
                "initial_price_max": 150,
            }
        )
        a.reset(seed=1)
        b.reset(seed=1)
        assert a.reference_price() != b.reference_price()
