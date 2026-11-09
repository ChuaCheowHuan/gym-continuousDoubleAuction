"""Tests for orderbook and league fixes.

Moved from `test_s3_moderate_fixes.py` by issue #361; the class docstrings keep the
original issue numbers.
"""

import logging

import pytest

from gym_continuousDoubleAuction.logging_setup import ROOT_NAME as LOGGER

from gym_continuousDoubleAuction.train.train import (
    TrainConfig,
    build_config,
)


from decimal import Decimal  # noqa: E402

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (  # noqa: E402
    continuousDoubleAuctionEnv,
)

CASH = 100000


def _env(multiple, **config):
    env = continuousDoubleAuctionEnv(
        {
            "num_of_agents": 2,
            "is_render": False,
            "init_cash": CASH,
            "initial_price_min": 100,
            "initial_price_max": 100,
            "allow_multiple_orders_per_level": multiple,
            **config,
        }
    )
    env.reset(seed=1)
    return env


def _place(env, tid, type, side, size, price=-1.0, slot=0):
    env.traders[tid].place_order(type, side, size, price, env.LOB, env.traders, slot=slot)


def _level(env, side, price):
    tree = env.LOB.bids if side == "bid" else env.LOB.asks
    return tree.get_price_list(Decimal(price))


from unittest.mock import MagicMock  # noqa: E402

from gym_continuousDoubleAuction.train.callbk.league import PROMOTION_REFERENCES  # noqa: E402

from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import (  # noqa: E402
    SelfPlayCallback,
)


def _league(reference, **kwargs):
    return SelfPlayCallback(
        num_trainable_policies=2,
        num_random_policies=6,
        min_iterations_between_champions=0,
        min_champion_trades=0,
        promotion_reference=reference,
        **kwargs,
    )


def _returns(trainable, champions, baseline):
    out = {f"policy_{i}": v for i, v in enumerate(trainable)}
    out.update({f"champion_{i + 1}": v for i, v in enumerate(champions)})
    out.update({f"policy_{i}": baseline for i in range(2, 8)})
    return out


def _check(cb, returns, monkeypatch=None):
    made = []
    cb.league.create_snapshot = lambda algo, pid, value, it: made.append(pid)
    result = {"training_iteration": 1, "env_runners": {"module_episode_returns_mean": returns}}
    cb.on_train_result(algorithm=MagicMock(), result=result)
    return made, result["league"]


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
        _place(env, 0, "limit", "bid", 10, 90.0)  # replaces: still 900 held
        assert _level(env, "bid", 90).volume == 10
        assert env.traders[0].acc.num_rejected_step == 0

    def test_when_allowed_the_cash_check_counts_both_orders(self):
        env = _env(True, init_cash=1000)
        _place(env, 0, "limit", "bid", 10, 90.0)
        _place(env, 0, "limit", "bid", 10, 90.0)  # would need 900 more: refused
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
                {a: env.action_spaces[a].sample() for a in env.agents}
            )
            for trader in env.traders:
                held = sum(
                    (
                        o.price * o.quantity
                        for tree in (env.LOB.bids, env.LOB.asks)
                        for o in tree.order_map.values()
                        if o.trade_id == trader.ID
                    ),
                    Decimal(0),
                )
                assert trader.acc.cash_on_hold == held
            if term["__all__"] or trunc["__all__"]:
                break

    def test_a_non_boolean_is_refused(self):
        with pytest.raises(ValueError, match="allow_multiple_orders_per_level"):
            continuousDoubleAuctionEnv(
                {"num_of_agents": 2, "is_render": False, "allow_multiple_orders_per_level": "yes"}
            )

    def test_train_config_forwards_it_to_the_env(self):
        assert TrainConfig().env_config["allow_multiple_orders_per_level"] is False
        cfg = TrainConfig(allow_multiple_orders_per_level=True)
        assert (
            continuousDoubleAuctionEnv(
                {**cfg.env_config, "is_render": False}
            ).allow_multiple_orders_per_level
            is True
        )


class TestPromotionReference:
    """#124: the threshold was a pooled mean + k*std over every module, the frozen
    random baselines included, though a baseline's return is what a random agent
    earns in whatever role it is dealt."""

    def test_the_default_is_the_pooled_behaviour(self):
        assert TrainConfig().promotion_reference == "pooled"
        assert (
            SelfPlayCallback(num_trainable_policies=2, num_random_policies=6).promotion_reference
            == "pooled"
        )

    def test_the_choices_are_named(self):
        assert PROMOTION_REFERENCES == ("pooled", "excluding_baselines")

    @pytest.mark.parametrize("bad", ["", "all", "excluding baselines", None])
    def test_nonsense_is_refused_naming_the_key(self, bad):
        with pytest.raises(ValueError, match="promotion_reference"):
            TrainConfig(promotion_reference=bad)

    def test_the_callback_refuses_it_too(self):
        with pytest.raises(ValueError, match="promotion_reference"):
            _league("nope")

    def test_train_config_hands_it_to_the_callback(self):
        _ppo_cfg, callback = build_config(TrainConfig(promotion_reference="excluding_baselines"))
        assert callback.promotion_reference == "excluding_baselines"

    # Learners 1.3 / 0.4, champions 1.0 / 0.9 / 1.1, baselines at -0.5: the baselines sit
    # just under the learners, so the pooled bar (1.27) is lower than the one over the
    # learners and champions alone (1.39), and 1.3 clears the first only.
    def test_baselines_close_to_the_learners_lower_the_bar_they_clear(self):
        returns = _returns([1.3, 0.4], [1.0, 0.9, 1.1], -0.5)
        pooled, league_p = _check(_league("pooled"), returns)
        excluded, league_e = _check(_league("excluding_baselines"), returns)
        assert pooled == ["policy_0"] and excluded == []
        assert league_p["threshold"] < 1.3 < league_e["threshold"]

    # The other direction: baselines far below inflate the pooled spread and raise the
    # bar past a learner that is clearly ahead of its peers.
    def test_baselines_far_below_raise_the_bar_past_a_clearly_better_learner(self):
        returns = _returns([2.0, 0.4], [1.0, 0.9, 1.1], -10.0)
        pooled, league_p = _check(_league("pooled"), returns)
        excluded, league_e = _check(_league("excluding_baselines"), returns)
        assert pooled == [] and excluded == ["policy_0"]
        assert league_e["threshold"] < 2.0 < league_p["threshold"]

    def test_the_result_says_which_set_the_threshold_used(self):
        returns = _returns([2.0, 0.4], [1.0, 0.9, 1.1], -10.0)
        assert _check(_league("pooled"), returns)[1]["reference"] == "pooled"
        assert (
            _check(_league("excluding_baselines"), returns)[1]["reference"] == "excluding_baselines"
        )

    def test_a_set_too_small_to_clear_falls_back_to_pooled_and_warns_once(self, caplog):
        """Two learners and no champion: sqrt(2 - 1) = 1 is under 1.5, so nobody could ever
        be promoted and the league would never grow."""
        cb = _league("excluding_baselines")
        returns = _returns([5.0, 0.4], [], -1.0)
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            _made, league = _check(cb, returns)
            _check(cb, returns)
        assert league["reference"] == "pooled"
        assert caplog.text.count("using the pooled threshold") == 1

    def test_an_idle_champion_is_left_out_of_the_reference(self):
        returns = _returns([2.0, 0.4], [1.0, 0.9, float("nan")], -10.0)
        made, league = _check(_league("excluding_baselines"), returns)
        assert league["reference"] == "excluding_baselines"  # 4 modules: sqrt(3) > 1.5
        assert made == ["policy_0"]

    def test_a_callback_saved_before_the_key_runs_pooled(self):
        cb = _league("pooled")
        state = cb.__getstate__()
        state.update(vars(state.pop("league")))  # as an older checkpoint held it: flat
        del state["promotion_reference"]
        del state["_warned_reference_fallback"]
        old = SelfPlayCallback.__new__(SelfPlayCallback)
        old.__setstate__(state)
        assert old.promotion_reference == "pooled"
