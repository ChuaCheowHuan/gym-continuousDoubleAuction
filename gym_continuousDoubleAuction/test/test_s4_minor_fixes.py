"""The S4-minor bugs, one class per issue (#230 to #275).

Each was filed from a review as a small defect with a reproduction, and each
test below fails on the source it was filed against.
"""
from decimal import Decimal

import pytest

from gym_continuousDoubleAuction.envs.account.account import Account, validate_fee_rates
from gym_continuousDoubleAuction.envs.orderbook.order import Order
from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook
from gym_continuousDoubleAuction.envs.orderbook.orderlist import OrderList
from gym_continuousDoubleAuction.envs.orderbook.ordertree import OrderTree


class TestFeeRatesAcceptDecimal:
    """#230: `Account` stores its rates as `Decimal`, and the validator refused them."""

    def test_a_rate_read_back_from_an_account_builds_another(self):
        a = Account(0, 1000, maker_fee_bps=5, taker_fee_bps=10)
        b = Account(1, 1000, maker_fee_bps=a.maker_fee_bps, taker_fee_bps=a.taker_fee_bps)
        assert (b.maker_fee_bps, b.taker_fee_bps) == (Decimal(5), Decimal(10))

    def test_a_decimal_mixes_with_a_float(self):
        validate_fee_rates(Decimal("2.5"), 10.0)

    @pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity"), True, "5", None])
    def test_nonsense_is_still_refused(self, bad):
        with pytest.raises(ValueError, match="maker_fee_bps"):
            validate_fee_rates(bad, 10)

    def test_the_limits_apply_to_a_decimal_too(self):
        with pytest.raises(ValueError, match="within"):
            validate_fee_rates(Decimal("5000"), 10)
        with pytest.raises(ValueError, match="taker_fee_bps must be >= 0"):
            validate_fee_rates(0, Decimal("-1"))
        with pytest.raises(ValueError, match="pays out more"):
            validate_fee_rates(Decimal("-20"), Decimal("10"))


def _order(order_list, order_id, qty=1, price=10):
    quote = {"timestamp": 1, "quantity": Decimal(qty), "price": Decimal(price),
             "order_id": order_id, "trade_id": "t"}
    order = Order(quote, order_list)
    order_list.append_order(order)
    return order


class TestOrderBookBookkeeping:
    """#232: three small defects in `envs/orderbook/`."""

    def test_an_unknown_id_leaves_the_counter_alone(self):
        tree = OrderTree()
        with pytest.raises(KeyError):
            tree.remove_order_by_id(99)
        assert tree.num_orders == 0

    def test_a_supplied_time_of_zero_is_used(self):
        book = OrderBook()
        book.time = 7
        book.cancel_order("bid", 1, time=0)
        assert book.time == 0
        book.time = 7
        book.modify_order(1, {"side": "bid", "price": 1, "quantity": 1}, time=0)
        assert book.time == 0

    def test_a_missing_time_still_advances_the_clock(self):
        book = OrderBook()
        before = book.time
        book.cancel_order("bid", 1)
        assert book.time == before + 1

    def test_an_emptied_list_has_no_head_or_tail(self):
        order_list = OrderList()
        only = _order(order_list, 1)
        order_list.remove_order(only)
        assert len(order_list) == 0
        assert order_list.head_order is None and order_list.tail_order is None
        assert list(order_list) == []


class TestLayoutStampSaysWhenOnlyTheOrderDiffers:
    """#234: a reordering is a mismatch, but the message came from set differences."""

    @staticmethod
    def _message(**changes):
        from gym_continuousDoubleAuction.envs.layout_version import (
            check_layout_stamp, layout_stamp)
        stamp = layout_stamp()
        stamp.update(changes)
        with pytest.raises(ValueError) as caught:
            check_layout_stamp({"layout": stamp}, "ckpt")
        return str(caught.value)

    def test_a_reordering_names_the_position(self):
        from gym_continuousDoubleAuction.envs.layout_version import layout_stamp
        fields = layout_stamp()["private_fields"]
        swapped = [fields[1], fields[0]] + fields[2:]
        message = self._message(private_fields=swapped)
        assert "lacks nothing" not in message
        assert "order, not membership" in message and "position 0" in message
        assert repr(fields[1]) in message and repr(fields[0]) in message

    def test_a_reordered_action_keys_listing_says_so_too(self):
        from gym_continuousDoubleAuction.envs.layout_version import layout_stamp
        keys = layout_stamp()["action_keys"]
        message = self._message(action_keys=list(reversed(keys)))
        assert "action_keys differ in order" in message

    def test_a_missing_field_is_still_named(self):
        from gym_continuousDoubleAuction.envs.layout_version import layout_stamp
        fields = layout_stamp()["private_fields"]
        message = self._message(private_fields=fields[1:])
        assert f"checkpoint lacks ['{fields[0]}']" in message


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
            SelfPlayCallback)
        cb = SelfPlayCallback(num_trainable_policies=2, num_random_policies=6,
                              min_iterations_between_champions=0, min_champion_trades=0)
        made = []
        cb._create_champion_snapshot_from_policy = lambda algo, pid, value, it: made.append(pid)
        returns = {"policy_0": 50.0, "policy_1": None,
                   **{f"policy_{i}": -float(i) for i in range(2, 8)}}
        result = {"training_iteration": 1,
                  "env_runners": {"module_episode_returns_mean": returns}}
        cb.on_train_result(algorithm=object(), result=result)  # used to raise TypeError
        assert made == ["policy_0"]

    def test_the_iteration_log_survives_a_none_return(self, caplog):
        import logging
        from gym_continuousDoubleAuction.logging_setup import ROOT_NAME
        from gym_continuousDoubleAuction.train.train import TrainConfig, _log_iteration
        result = {"env_runners": {"module_episode_returns_mean": {
            "policy_0": None, "policy_1": 2.345}}}
        with caplog.at_level(logging.INFO, logger=ROOT_NAME):
            _log_iteration(1, 3, result, TrainConfig())
        assert "'policy_0': None" in caplog.text and "'policy_1': 2.3" in caplog.text

    def test_export_logs_a_champion_with_no_recorded_return(self, tmp_path, monkeypatch, caplog):
        import json
        import logging
        from gym_continuousDoubleAuction.logging_setup import ROOT_NAME
        from gym_continuousDoubleAuction.train import export
        from gym_continuousDoubleAuction.train.train import LEAGUE_STATE_FILE
        (tmp_path / LEAGUE_STATE_FILE).write_text(json.dumps({"champion_history": [
            {"id": "champion_1", "source_policy": None, "iteration": 3, "return": None}]}))
        monkeypatch.setattr(export.features_module, "load_module", lambda *a: object())
        monkeypatch.setattr(export, "build_record", lambda *a: {
            "state_dict": {}, "module_class": "X"})
        import torch
        monkeypatch.setattr(torch, "save", lambda *a, **k: None)
        with caplog.at_level(logging.INFO, logger=ROOT_NAME):
            export.export(str(tmp_path), "champion_1", out=str(tmp_path / "o.pt"))
        assert "return n/a" in caplog.text

    def test_a_nan_champion_is_not_ranked(self):
        from gym_continuousDoubleAuction.train import export
        state = {"champion_history": [
            {"id": "champion_1", "return": float("nan")},
            {"id": "champion_2", "return": 1.0}]}
        assert export.best_champion(state)["id"] == "champion_2"


class TestPlatformEnvIsCaseInsensitive:
    """#237: `CDA_USE_GPU` was parsed case-insensitively and `CDA_PLATFORM` was not."""

    @pytest.mark.parametrize("value", ["auto", "Auto", " AUTO "])
    def test_auto_in_any_case_means_detect(self, monkeypatch, value):
        from gym_continuousDoubleAuction.train import runtime
        monkeypatch.setenv("CDA_PLATFORM", value)
        monkeypatch.setattr(runtime, "detect_platform", lambda: "local")
        assert runtime.resolve().platform == "local"

    @pytest.mark.parametrize("value", ["colab", "COLAB", " Colab\n"])
    def test_a_platform_name_in_any_case_is_found(self, monkeypatch, value):
        from gym_continuousDoubleAuction.train import runtime
        monkeypatch.setenv("CDA_PLATFORM", value)
        assert runtime.resolve().platform == "colab"

    def test_an_empty_value_is_unset(self, monkeypatch):
        from gym_continuousDoubleAuction.train import runtime
        monkeypatch.setenv("CDA_PLATFORM", "")
        monkeypatch.setattr(runtime, "detect_platform", lambda: "local")
        assert runtime.resolve().platform == "local"

    def test_an_explicit_argument_is_normalised_too(self):
        from gym_continuousDoubleAuction.train import runtime
        assert runtime.resolve(platform="Docker").platform == "docker"

    def test_an_unknown_platform_is_still_an_error(self, monkeypatch):
        from gym_continuousDoubleAuction.train import runtime
        monkeypatch.setenv("CDA_PLATFORM", "mars")
        with pytest.raises(KeyError, match="mars"):
            runtime.resolve()


class TestCompareSetRefusesAnUnrecognisedBoolean:
    """#236: `--set strict_nav_check=ture` was silently False."""

    @pytest.mark.parametrize("raw,expected", [
        ("true", True), ("True", True), ("1", True), ("yes", True), ("on", True),
        ("false", False), ("FALSE", False), ("0", False), ("no", False), ("off", False),
    ])
    def test_the_recognised_spellings(self, raw, expected):
        from gym_continuousDoubleAuction.train.compare import parse_overrides
        assert parse_overrides([f"action_mask={raw}"]) == {"action_mask": expected}

    @pytest.mark.parametrize("raw", ["ture", "enabled", "True1", "", "2"])
    def test_anything_else_is_refused_naming_the_flag(self, raw):
        from gym_continuousDoubleAuction.train.compare import parse_overrides
        with pytest.raises(SystemExit, match="--set action_mask: expected a boolean"):
            parse_overrides([f"action_mask={raw}"])


class TestVisualizeSurvivesBadRecords:
    """#240: an empty recorded observation, or a truncated `progress.jsonl`
    line, aborted the plots."""

    def test_an_empty_observation_is_a_gap_not_an_error(self):
        import numpy as np
        from gym_continuousDoubleAuction.envs.exchg.state_helper import PRIVATE_DIM, SNAPSHOT_DIM
        from gym_continuousDoubleAuction.visualize.visualize_orderbook import _book_sizes
        good = np.ones(SNAPSHOT_DIM + PRIVATE_DIM)
        bids, asks, skipped = _book_sizes([good, [], good])
        assert skipped == 1 and len(bids) == len(asks) == 3
        assert np.isnan(bids[1]) and np.isnan(asks[1])
        assert not np.isnan(bids[0]) and not np.isnan(asks[2])

    def test_a_malformed_non_empty_observation_still_raises(self):
        """Only the recorder's own `[]` is forgiven: a wrong-sized vector means
        the recording and the layout disagree, which the plot must not hide."""
        from gym_continuousDoubleAuction.visualize.visualize_orderbook import _book_sizes
        with pytest.raises(ValueError, match="whole number"):
            _book_sizes([[1.0, 2.0, 3.0]])

    def _progress(self, tmp_path, text):
        path = tmp_path / "progress.jsonl"
        path.write_text(text)
        return str(path)

    def test_a_truncated_last_line_is_skipped_with_a_warning(self, tmp_path):
        from gym_continuousDoubleAuction.visualize.visualize_training import load_progress
        path = self._progress(
            tmp_path, '{"training_iteration": 2}\n{"training_iteration": 1}\n{"training_it')
        with pytest.warns(UserWarning, match="skipped 1 line"):
            rows = load_progress(path)
        assert [r["training_iteration"] for r in rows] == [1, 2]

    def test_a_row_without_an_iteration_is_skipped_not_a_keyerror(self, tmp_path):
        from gym_continuousDoubleAuction.visualize.visualize_training import load_progress
        path = self._progress(tmp_path, '{"training_iteration": 1}\n{"other": 1}\n[1, 2]\n')
        with pytest.warns(UserWarning, match="skipped 2 line"):
            assert len(load_progress(path)) == 1

    def test_a_clean_file_warns_about_nothing(self, tmp_path, recwarn):
        from gym_continuousDoubleAuction.visualize.visualize_training import load_progress
        load_progress(self._progress(tmp_path, '{"training_iteration": 1}\n'))
        assert not [w for w in recwarn if "skipped" in str(w.message)]

    def test_a_file_with_no_complete_row_is_still_an_error(self, tmp_path):
        from gym_continuousDoubleAuction.visualize.visualize_training import load_progress
        with pytest.warns(UserWarning), pytest.raises(ValueError, match="no rows"):
            load_progress(self._progress(tmp_path, '{"training_it'))
