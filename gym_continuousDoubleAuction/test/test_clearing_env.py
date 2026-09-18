"""The matching regime through the env: `matching_rule` and `step_clearing`.

doc/06 section 8. The knobs are env-config keys (and TrainConfig fields), so
the regimes can be compared under identical seeds. `sequential` / `fifo` is the
default and the behaviour to date. Under `batch` a step's new orders clear
against the resting book at one uniform price: two agents whose orders cross
within the same step trade at the reference inside their interval rather than
at whichever price the shuffle reached first, and the render path, the tape,
the per-step counters and NAV conservation are all unchanged in shape.
"""
from decimal import Decimal

import numpy as np
import pytest

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)


def _env(**overrides):
    config = {"num_of_agents": 2, "is_render": False, "max_step": 40,
              "initial_price_min": 100, "initial_price_max": 100}
    config.update(overrides)
    env = continuousDoubleAuctionEnv(config)
    env.reset(seed=1)
    return env


def _limit(category, price_code=0, offset=1, mean=0.02):
    return {"category": category, "order_slot": 0, "price": price_code, "price_offset": offset,
            "size_mean": np.array([mean], dtype=np.float32),
            "size_sigma": np.zeros(1, dtype=np.float32)}


_PASS = {"category": 0, "order_slot": 0, "price": 0, "price_offset": 1,
         "size_mean": np.zeros(1, dtype=np.float32), "size_sigma": np.zeros(1, dtype=np.float32)}


class TestConfig:

    def test_defaults_are_the_continuous_double_auction(self):
        env = _env()
        assert env.step_clearing == "sequential" and env.matching_rule == "fifo"
        assert env.LOB.matching_rule == "fifo"

    def test_the_rule_reaches_every_episode_book(self):
        env = _env(matching_rule="pro_rata")
        assert env.LOB.matching_rule == "pro_rata"
        env.reset(seed=2)
        assert env.LOB.matching_rule == "pro_rata"

    def test_validation(self):
        with pytest.raises(ValueError, match="matching_rule"):
            _env(matching_rule="lottery")
        with pytest.raises(ValueError, match="step_clearing"):
            _env(step_clearing="auction")

    def test_train_config_carries_both(self):
        import dataclasses
        from gym_continuousDoubleAuction.train.train import TrainConfig
        from gym_continuousDoubleAuction.train.compare import parse_overrides
        cfg = dataclasses.replace(TrainConfig(), **parse_overrides(["matching_rule=pro_rata", "step_clearing=batch"]))
        assert cfg.env_config["matching_rule"] == "pro_rata"
        assert cfg.env_config["step_clearing"] == "batch"


class TestBatchThroughTheEnv:

    def test_crossing_orders_in_one_step_clear_at_the_reference(self):
        """agent_0 bids 2 ticks above R, agent_1 asks 2 ticks below: sequentially
        the second arrival trades at the first's price; in a batch both trade
        at R = 100."""
        seq = _env(step_clearing="sequential")
        bat = _env(step_clearing="batch")
        for env in (seq, bat):
            env.last_price = 100.0
            env.set_agg_LOB()
            # grid mode: code 0 is R; offset 2 shades one tick aggressive, so
            # make the cross explicit with two aggressive quotes at code 0.
            env.step({"agent_0": _limit(2, 0, 2), "agent_1": _limit(6, 0, 2)})
        seq_prices = {str(t["price"]) for t in seq.LOB.tape}
        bat_prices = {str(t["price"]) for t in bat.LOB.tape}
        assert len(seq.LOB.tape) == 1 and len(bat.LOB.tape) == 1
        assert seq_prices <= {"99", "101", "99.0", "101.0"}   # whoever arrived first set it
        assert bat_prices <= {"100", "100.0"}                  # the reference inside the interval

    def test_the_result_is_the_same_whatever_the_shuffle(self):
        """Two agents, both quoting through R on opposite sides, in a batch: the
        trade price and each side's fill are independent of arrival order,
        which the random shuffle would otherwise decide."""
        prices, fills = set(), set()
        for seed in range(6):
            env = _env(step_clearing="batch")
            env.reset(seed=seed)
            env.last_price = 100.0
            env.set_agg_LOB()
            _, _, _, _, infos = env.step({"agent_0": _limit(2, 0, 2), "agent_1": _limit(6, 0, 2)})
            prices |= {str(t["price"]) for t in env.LOB.tape}
            fills.add((infos["agent_0"]["num_trades_step"], infos["agent_1"]["num_trades_step"]))
        assert prices == {"100.0"} or prices == {"100"}
        assert fills == {(1, 1)}

    def test_a_batch_fill_against_a_resting_order_is_a_passive_fill_for_the_rester(self):
        env = _env(step_clearing="batch")
        a, b = env.traders
        b.place_order('limit', 'ask', 10, 101.0, env.LOB, env.traders)   # rests before the step
        env.set_agg_LOB()
        _, _, _, _, infos = env.step({"agent_0": _limit(2, 0, 2, mean=0.02), "agent_1": _PASS})
        assert infos["agent_1"]["num_passive_fills_step"] == infos["agent_1"]["num_trades_step"] >= 1
        assert infos["agent_0"]["num_passive_fills_step"] == 0
        assert infos["agent_0"]["num_trades_step"] >= 1

    def test_two_batch_orders_have_no_passive_side(self):
        env = _env(step_clearing="batch")
        env.last_price = 100.0
        env.set_agg_LOB()
        _, _, _, _, infos = env.step({"agent_0": _limit(2, 0, 2), "agent_1": _limit(6, 0, 2)})
        assert infos["agent_0"]["num_passive_fills_step"] == 0
        assert infos["agent_1"]["num_passive_fills_step"] == 0

    def test_render_aligned_trade_lists(self):
        env = _env(step_clearing="batch")
        env.last_price = 100.0
        env.set_agg_LOB()
        env.step({"agent_0": _limit(2, 0, 2), "agent_1": _limit(6, 0, 2)})
        assert len(env.seq_trades) == 2 == len(env.shuffled_actions)
        attached = [len(t) for t in env.seq_trades]
        assert sorted(attached) == [0, 1]   # attached to the init party, once

    @pytest.mark.parametrize("clearing,rule", [("batch", "fifo"), ("batch", "pro_rata"), ("sequential", "pro_rata")])
    def test_random_play_conserves_nav_and_stays_in_the_space(self, clearing, rule):
        env = _env(num_of_agents=4, max_step=60, step_clearing=clearing, matching_rule=rule,
                   initial_price_min=10, initial_price_max=100)
        env.reset(seed=7)
        space = env.observation_spaces["agent_0"]
        while True:
            obs, _, dones, truncs, infos = env.step(
                {agent: env.action_spaces[agent].sample() for agent in env.agents}
            )
            for agent, o in obs.items():
                assert space.contains(o), agent
            total = sum(t.acc.nav for t in env.traders)
            assert total == Decimal(4) * Decimal(env.init_cash)
            for t in env.traders:
                assert t.acc.cash + t.acc.cash_on_hold >= 0
            if dones["__all__"] or truncs["__all__"]:
                break
        assert len(env.LOB.tape) > 0

    def test_a_modify_across_the_spread_is_part_of_the_batch(self):
        env = _env(step_clearing="batch")
        a, b = env.traders
        a.place_order('limit', 'bid', 5, 98.0, env.LOB, env.traders)
        b.place_order('limit', 'ask', 5, 102.0, env.LOB, env.traders)
        env.set_agg_LOB()
        # agent_0 re-prices its bid aggressively (modify, slot 1, code 0, aggressive).
        act = {"agent_0": {"category": 3, "order_slot": 1, "price": 0, "price_offset": 2,
                           "size_mean": np.array([0.01], dtype=np.float32),
                           "size_sigma": np.zeros(1, dtype=np.float32)},
               "agent_1": _PASS}
        _, _, _, _, infos = env.step(act)
        assert infos["agent_0"]["num_unmatched_step"] == 0
        # Whether it crossed depends on the drawn size vs the ask; either way
        # the book is consistent and nothing was matched sequentially mid-step.
        assert env.LOB.bids.volume >= 0 and env.LOB.asks.volume >= 0
        assert sum(t.acc.nav for t in env.traders) == Decimal(2) * Decimal(env.init_cash)
