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


# --------------------------------------------------------------------------- #122
from decimal import Decimal  # noqa: E402

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (  # noqa: E402
    continuousDoubleAuctionEnv,
)

CASH = 100000


def _env(multiple, **config):
    env = continuousDoubleAuctionEnv({
        "num_of_agents": 2, "is_render": False, "init_cash": CASH,
        "initial_price_min": 100, "initial_price_max": 100,
        "allow_multiple_orders_per_level": multiple, **config})
    env.reset(seed=1)
    return env


def _place(env, tid, type, side, size, price=-1.0, slot=0):
    env.traders[tid].place_order(type, side, size, price, env.LOB, env.traders, slot=slot)


def _level(env, side, price):
    tree = env.LOB.bids if side == "bid" else env.LOB.asks
    return tree.get_price_list(Decimal(price))


class TestSeveralOrdersPerLevel:
    """#122: a second limit at a price the trader already rests at replaced the first."""

    def test_by_default_the_second_replaces_the_first(self):
        env = _env(False)
        _place(env, 0, "limit", "bid", 5, 90.0)
        _place(env, 0, "limit", "bid", 7, 90.0)
        level = _level(env, "bid", 90)
        assert level.volume == 7 and len(level) == 1

    def test_when_allowed_both_rest(self):
        env = _env(True)
        _place(env, 0, "limit", "bid", 5, 90.0)
        _place(env, 0, "limit", "bid", 7, 90.0)
        level = _level(env, "bid", 90)
        assert level.volume == 12 and len(level) == 2

    def test_each_order_carries_its_own_escrow(self):
        env = _env(True)
        _place(env, 0, "limit", "bid", 5, 90.0)
        _place(env, 0, "limit", "bid", 7, 90.0)
        assert env.traders[0].acc.cash_on_hold == Decimal(12 * 90)

    def test_they_queue_in_arrival_order(self):
        env = _env(True)
        _place(env, 0, "limit", "bid", 5, 90.0)
        _place(env, 0, "limit", "bid", 7, 90.0)
        assert [int(o.quantity) for o in _level(env, "bid", 90)] == [5, 7]

    def test_a_cancel_of_all_clears_every_one(self):
        env = _env(True)
        _place(env, 0, "limit", "bid", 5, 90.0)
        _place(env, 0, "limit", "bid", 7, 90.0)
        _place(env, 0, "cancel", "bid", 1, 90.0, slot=0)
        assert len(env.LOB.bids.order_map) == 0
        assert env.traders[0].acc.cash_on_hold == 0

    def test_a_cancel_by_slot_removes_exactly_one(self):
        env = _env(True)
        _place(env, 0, "limit", "bid", 5, 90.0)
        _place(env, 0, "limit", "bid", 7, 90.0)
        _place(env, 0, "cancel", "bid", 1, 90.0, slot=1)
        assert len(env.LOB.bids.order_map) == 1
        assert env.traders[0].acc.cash_on_hold == Decimal(7 * 90)

    def test_by_default_a_replacement_needs_no_extra_cash(self):
        env = _env(False, init_cash=1000)
        _place(env, 0, "limit", "bid", 10, 90.0)
        _place(env, 0, "limit", "bid", 10, 90.0)       # replaces: still 900 held
        assert _level(env, "bid", 90).volume == 10
        assert env.traders[0].acc.num_rejected_step == 0

    def test_when_allowed_the_cash_check_counts_both_orders(self):
        env = _env(True, init_cash=1000)
        _place(env, 0, "limit", "bid", 10, 90.0)
        _place(env, 0, "limit", "bid", 10, 90.0)       # would need 900 more: refused
        assert _level(env, "bid", 90).volume == 10 and len(_level(env, "bid", 90)) == 1
        assert env.traders[0].acc.num_rejected_step == 1

    def test_a_sweep_fills_every_resting_order_and_money_is_conserved(self):
        env = _env(True)
        _place(env, 0, "limit", "bid", 5, 90.0)
        _place(env, 0, "limit", "bid", 7, 90.0)
        _place(env, 1, "market", "ask", 12)
        assert len(env.LOB.bids.order_map) == 0
        assert env.traders[0].acc.net_position == 12 and env.traders[1].acc.net_position == -12
        assert sum(t.acc.nav for t in env.traders) + env.fees_collected == Decimal(2 * CASH)

    @pytest.mark.parametrize("clearing", ["sequential", "batch"])
    def test_random_play_keeps_escrow_equal_to_what_rests(self, clearing):
        env = _env(True, num_of_agents=4, step_clearing=clearing, max_step=60)
        for _ in range(60):
            _o, _r, term, trunc, _i = env.step(
                {a: env.action_spaces[a].sample() for a in env.agents})
            for trader in env.traders:
                held = sum(
                    (o.price * o.quantity for tree in (env.LOB.bids, env.LOB.asks)
                     for o in tree.order_map.values() if o.trade_id == trader.ID),
                    Decimal(0))
                assert trader.acc.cash_on_hold == held
            if term["__all__"] or trunc["__all__"]:
                break

    def test_a_non_boolean_is_refused(self):
        with pytest.raises(ValueError, match="allow_multiple_orders_per_level"):
            continuousDoubleAuctionEnv({"num_of_agents": 2, "is_render": False,
                                        "allow_multiple_orders_per_level": "yes"})

    def test_train_config_forwards_it_to_the_env(self):
        assert TrainConfig().env_config["allow_multiple_orders_per_level"] is False
        cfg = TrainConfig(allow_multiple_orders_per_level=True)
        assert continuousDoubleAuctionEnv(
            {**cfg.env_config, "is_render": False}).allow_multiple_orders_per_level is True
