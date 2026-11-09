"""Tests for market and accounting hardening.

Moved from `test_s4_hardening.py` by issue #361; the class docstrings keep the
original issue numbers.
"""

from decimal import Decimal


from gym_continuousDoubleAuction.envs.account.account import Account

from gym_continuousDoubleAuction.envs.agent.trader import Trader, _is_market_price

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)


from gym_continuousDoubleAuction.train.model.encoders import (
    token_embed,
    tokenize,
    transformer,
)


import numpy as np  # noqa: E402


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


class TestMarkToMarketUsesTheProfitRule:
    def test_it_agrees_with_cal_profit_for_a_long_and_a_short(self):
        for position, side in ((5, "long"), (-5, "short")):
            acc = Account(0, 1000)
            acc.net_position, acc.cost_basis = position, Decimal(500)
            acc.mark_to_mkt(0, Decimal(120))
            expected = acc.cal_profit(side, abs(position) * Decimal(120), Decimal(500))
            assert acc.profit == expected


class TestOneLookupForAnAgent:
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


class TestOnePoolingsDefinition:
    def test_the_encoders_share_the_tokenizers_tuple(self):
        assert transformer.POOLINGS is tokenize.POOLINGS
        assert token_embed.POOLINGS is tokenize.POOLINGS
        assert tokenize.POOLINGS == ("mean", "attention")
