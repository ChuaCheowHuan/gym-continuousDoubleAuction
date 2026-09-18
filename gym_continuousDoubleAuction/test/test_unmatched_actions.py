"""doc/15 S4-14, the remaining half: a `modify` or `cancel` that names no
resting order is counted.

Three ways an action can silently do nothing, and the field that now records
each: a deliberate pass (`is_pass_action`), an order the cash check refused
(`num_rejected_step`), and an order-management action with nothing to manage
(`num_unmatched_step`). From the policy's side the three are identical - the
book does not change - and a return series cannot tell them apart. A policy
that has drifted to "cancel" at every step scored exactly like one that
passes, and nothing said so.
"""
from decimal import Decimal

import numpy as np

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook
from gym_continuousDoubleAuction.envs.agent.trader import Trader


def _act(category, price=0, offset=1):
    return {
        "category": category,
        "size_mean": np.array([0.5], dtype=np.float32),
        "size_sigma": np.array([0.0], dtype=np.float32),
        "price": price,
        "price_offset": offset,
    }


_PASS = _act(0)
_BID_LIMIT = _act(2)
_BID_MODIFY = _act(3)
_BID_CANCEL = _act(4)
_ASK_CANCEL = _act(8)


class TestTraderCounter:

    def setup_method(self):
        self.book = OrderBook()
        self.t = Trader(ID=1, cash=1000)

    def test_cancel_with_nothing_resting_counts_one(self):
        self.t.place_order('cancel', 'bid', 1, 100, self.book, [self.t])
        assert self.t.acc.num_unmatched_step == 1
        assert self.t.acc.num_rejected_step == 0

    def test_modify_with_nothing_resting_counts_one(self):
        self.t.place_order('modify', 'ask', 1, 100, self.book, [self.t])
        assert self.t.acc.num_unmatched_step == 1

    def test_cancel_at_the_wrong_price_counts(self):
        self.t.place_order('limit', 'bid', 1, 100, self.book, [self.t])
        self.t.place_order('cancel', 'bid', 1, 99, self.book, [self.t])
        assert self.t.acc.num_unmatched_step == 1
        assert len(self.book.bids) == 1, "the order at 100 is untouched"

    def test_matched_actions_do_not_count(self):
        self.t.place_order('limit', 'bid', 2, 100, self.book, [self.t])
        self.t.place_order('modify', 'bid', 1, 100, self.book, [self.t])
        self.t.place_order('cancel', 'bid', 1, 100, self.book, [self.t])
        assert self.t.acc.num_unmatched_step == 0
        assert len(self.book.bids) == 0

    def test_a_new_limit_is_not_unmatched(self):
        """A limit at a price with nothing resting is the ordinary path."""
        self.t.place_order('limit', 'bid', 1, 100, self.book, [self.t])
        assert self.t.acc.num_unmatched_step == 0

    def test_reset_clears_it(self):
        self.t.place_order('cancel', 'bid', 1, 100, self.book, [self.t])
        self.t.acc.reset_acc(1, Decimal(1000))
        assert self.t.acc.num_unmatched_step == 0


class TestEnvPlumbing:

    def _env(self):
        env = continuousDoubleAuctionEnv({
            "num_of_agents": 2, "is_render": False, "max_step": 16,
            "initial_price_min": 100, "initial_price_max": 100,
        })
        env.reset(seed=3)
        return env

    def test_info_carries_the_counter_as_int(self):
        env = self._env()
        _, _, _, _, infos = env.step({"agent_0": _BID_CANCEL, "agent_1": _PASS})
        assert isinstance(infos["agent_0"]["num_unmatched_step"], int)
        assert infos["agent_0"]["num_unmatched_step"] == 1
        assert infos["agent_1"]["num_unmatched_step"] == 0
        assert infos["agent_0"]["num_rejected_step"] == 0
        assert infos["agent_0"]["is_pass_action"] is False

    def test_counter_is_per_step(self):
        env = self._env()
        env.step({"agent_0": _ASK_CANCEL, "agent_1": _PASS})
        _, _, _, _, infos = env.step({"agent_0": _PASS, "agent_1": _PASS})
        assert infos["agent_0"]["num_unmatched_step"] == 0

    def test_modify_of_own_order_is_matched(self):
        env = self._env()
        env.step({"agent_0": _BID_LIMIT, "agent_1": _PASS})
        _, _, _, _, infos = env.step({"agent_0": _BID_MODIFY, "agent_1": _PASS})
        assert infos["agent_0"]["num_unmatched_step"] == 0

    def test_record_schema_has_the_column(self):
        from gym_continuousDoubleAuction.train.episode_record import INFO_COLUMNS
        assert ("num_unmatched_step", "int64") in INFO_COLUMNS
