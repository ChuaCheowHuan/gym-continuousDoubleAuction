"""Tests for config and env hardening.

Moved from `test_s4_hardening.py` by issue #361; the class docstrings keep the
original issue numbers.
"""

import time

from decimal import Decimal

import pytest

from gym_continuousDoubleAuction import config_loader

from gym_continuousDoubleAuction.envs.account.account import Account

from gym_continuousDoubleAuction.envs.agent.trader import Trader

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)


from gym_continuousDoubleAuction.train import train as train_module


import numpy as np  # noqa: E402
from pathlib import Path


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
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        data["environment"].update(changes)
        Path(path).write_text(json.dumps(data), encoding="utf-8")
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
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        data["ppo"]["gamma"] = 0.9
        Path(path).write_text(json.dumps(data), encoding="utf-8")
        config_loader.reload()
        assert train_module.TrainConfig().gamma == 0.9
        config_loader.reload()


class TestEnvResetHandsOptionsOn:
    def test_reset_with_options_and_a_seed_still_works(self):
        env = continuousDoubleAuctionEnv({"num_of_agents": 2, "is_render": False})
        first, _ = env.reset(seed=3, options={"anything": 1})
        again, _ = env.reset(seed=3)
        assert {k: list(v) for k, v in first.items()} == {k: list(v) for k, v in again.items()}
