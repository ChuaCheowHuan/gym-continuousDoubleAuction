"""Maker/taker fees: charged against NAV in settlement, collected by the exchange.

doc/15 S2-3 (second half). The reward proxies in `order_penalty`, `trade_penalty`
and `passive_bonus` charge the reward; these fees charge the ledger, so market
making has revenue and crossing the spread has a cost that shows up in NAV.

The fee on a fill is `price x quantity x bps / 10,000`. The record's
`init_party` is the taker and its `counter_party` the maker. Every fee a
trader pays is held on `Account.fees_paid`, and the exchange's ledger is the
sum of them, so money is still conserved:

    sum(NAV) + sum(fees_paid) == starting cash

The shipped rates are 0, which leaves every other test in the suite untouched.
"""
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from gym_continuousDoubleAuction.envs.account.account import Account
from gym_continuousDoubleAuction.envs.agent.trader import Trader
from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook
from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import (
    SelfPlayCallback,
)
from gym_continuousDoubleAuction.train.train import TrainConfig


def _trade(price=100, quantity=10):
    return {
        "price": Decimal(price), "quantity": quantity,
        "init_party": {"ID": 0, "side": "bid"},
        "counter_party": {"ID": 1, "side": "ask"},
    }


def _pair(maker_bps, taker_bps, cash=100_000):
    """Two traders on a bare book, a resting ask and a crossing market bid."""
    kw = dict(maker_fee_bps=maker_bps, taker_fee_bps=taker_bps)
    taker, maker = Trader(0, cash, **kw), Trader(1, cash, **kw)
    lob, agents = OrderBook(), [taker, maker]
    maker.place_order("limit", "ask", 10, 100, lob, agents)
    taker.place_order("market", "bid", 10, -1.0, lob, agents)
    return taker, maker


class TestTheLedger:
    def test_the_shipped_rates_are_zero(self):
        acc = Account(0, 1000)
        assert acc.maker_fee_bps == 0 and acc.taker_fee_bps == 0
        acc.process_acc(_trade(), "init_party")
        assert acc.fees_paid == 0

    def test_the_taker_pays_the_taker_rate_and_the_maker_the_maker_rate(self):
        taker, maker = _pair(maker_bps=5, taker_bps=10)
        # Notional 1,000: 10 bps is 1.0, 5 bps is 0.5.
        assert taker.acc.fees_paid == Decimal("1.0")
        assert maker.acc.fees_paid == Decimal("0.5")

    def test_a_fee_comes_out_of_nav_exactly(self):
        taker, maker = _pair(maker_bps=5, taker_bps=10)
        # A flat price: the only thing that moved NAV is the fee.
        taker.acc.mark_to_mkt(taker.ID, Decimal(100))
        maker.acc.mark_to_mkt(maker.ID, Decimal(100))
        assert taker.acc.nav == Decimal(100_000) - Decimal("1.0")
        assert maker.acc.nav == Decimal(100_000) - Decimal("0.5")

    def test_money_is_conserved_with_the_exchange_ledger(self):
        taker, maker = _pair(maker_bps=5, taker_bps=10)
        for t in (taker, maker):
            t.acc.mark_to_mkt(t.ID, Decimal(100))
        paid = taker.acc.fees_paid + maker.acc.fees_paid
        assert taker.acc.nav + maker.acc.nav + paid == Decimal(200_000)

    def test_a_negative_maker_fee_is_a_rebate(self):
        taker, maker = _pair(maker_bps=-2, taker_bps=5)
        assert maker.acc.fees_paid == Decimal("-0.2")
        for t in (taker, maker):
            t.acc.mark_to_mkt(t.ID, Decimal(100))
        assert maker.acc.nav == Decimal(100_000) + Decimal("0.2")
        assert taker.acc.nav + maker.acc.nav + taker.acc.fees_paid + maker.acc.fees_paid \
            == Decimal(200_000)

    def test_a_self_trade_pays_nothing(self):
        t = Trader(0, 100_000, maker_fee_bps=5, taker_fee_bps=10)
        lob = OrderBook()
        t.place_order("limit", "ask", 10, 100, lob, [t])
        t.place_order("limit", "bid", 10, 100, lob, [t])
        assert t.acc.fees_paid == 0

    def test_a_forced_transfer_at_the_mark_pays_nothing(self):
        """ADL is a transfer the exchange imposes, not a fill anyone chose."""
        acc = Account(0, 100_000, maker_fee_bps=5, taker_fee_bps=10)
        acc.process_acc(_trade(), "init_party", fee_role="none")
        assert acc.fees_paid == 0

    def test_reset_clears_the_fees_but_keeps_the_rates(self):
        acc = Account(0, 100_000, maker_fee_bps=5, taker_fee_bps=10)
        acc.process_acc(_trade(), "init_party")
        assert acc.fees_paid != 0
        acc.reset_acc(0, 100_000)
        assert acc.fees_paid == 0
        assert acc.taker_fee_bps == 10 and acc.maker_fee_bps == 5


class TestTheCashCheck:
    def test_a_fee_is_reserved_so_cash_cannot_be_overdrawn(self):
        """Cash exactly equal to the notional is not enough once a fee applies."""
        lob = OrderBook()
        free = Trader(0, 1000)
        fee = Trader(1, 1000, maker_fee_bps=0, taker_fee_bps=10)
        assert free._order_approved("bid", 10, 100, lob, "limit")
        assert not fee._order_approved("bid", 10, 100, lob, "limit")
        assert fee._order_approved("bid", 9, 100, lob, "limit")

    def test_cash_never_goes_negative_when_a_fee_is_charged(self):
        taker, maker = _pair(maker_bps=5, taker_bps=10, cash=1001)
        assert taker.acc.cash + taker.acc.cash_on_hold >= 0


def _env(**cfg):
    base = {"num_of_agents": 4, "init_cash": 100_000, "max_step": 60,
            "initial_price_min": 10, "initial_price_max": 100}
    base.update(cfg)
    return continuousDoubleAuctionEnv(base)


class TestTheEnv:
    def test_the_rates_reach_every_account(self):
        env = _env(maker_fee_bps=3, taker_fee_bps=7)
        assert all(t.acc.maker_fee_bps == 3 and t.acc.taker_fee_bps == 7 for t in env.traders)

    @pytest.mark.parametrize("clearing", ["sequential", "batch"])
    def test_random_play_conserves_money_with_the_fees(self, clearing):
        env = _env(maker_fee_bps=-1, taker_fee_bps=20, step_clearing=clearing)
        env.reset(seed=11)
        while True:
            _, _, dones, truncs, _ = env.step(
                {a: env.action_spaces[a].sample() for a in env.agents})
            assert env.fees_collected + sum(t.acc.nav for t in env.traders) \
                == Decimal(4) * Decimal(env.init_cash)
            if dones["__all__"] or truncs["__all__"]:
                break
        assert env.fees_collected != 0

    def test_liquidation_conserves_money_with_the_fees(self):
        env = _env(maker_fee_bps=0, taker_fee_bps=30, maintenance_margin=0.9,
                   initial_price_min=10, initial_price_max=12)
        env.reset(seed=3)
        for _ in range(60):
            _, _, dones, truncs, _ = env.step(
                {a: env.action_spaces[a].sample() for a in env.agents})
            assert env.fees_collected + sum(t.acc.nav for t in env.traders) \
                == Decimal(4) * Decimal(env.init_cash)
            if dones["__all__"] or truncs["__all__"]:
                break

    @pytest.mark.parametrize("bad", [
        {"taker_fee_bps": -1},
        {"maker_fee_bps": -6, "taker_fee_bps": 5},   # a rebate larger than the fee
        {"taker_fee_bps": None},
        {"taker_fee_bps": True},
        {"maker_fee_bps": float("nan")},
    ])
    def test_a_bad_rate_is_refused_naming_the_key(self, bad):
        with pytest.raises(ValueError, match="fee_bps"):
            _env(**bad)

    def test_train_config_carries_the_rates(self):
        cfg = TrainConfig()
        assert cfg.env_config["maker_fee_bps"] == 0
        assert cfg.env_config["taker_fee_bps"] == 0
        assert TrainConfig(maker_fee_bps=2, taker_fee_bps=6).env_config["taker_fee_bps"] == 6


class _Acc:
    def __init__(self, nav, fees):
        self.nav, self.fees_paid = Decimal(nav), Decimal(fees)


class _T:
    def __init__(self, ID, nav, fees):
        self.ID, self.acc = ID, _Acc(nav, fees)


class _LedgerEnv:
    def __init__(self, navs, fees):
        self.traders = [_T(i, n, f) for i, (n, f) in enumerate(zip(navs, fees))]
        self.unwrapped = self


class TestTheNavCheck:
    def test_the_fees_are_read_from_the_finished_envs_accounts(self):
        env = _LedgerEnv(["999", "1000", "1001", "998"], ["1", "0", "0", "2"])
        assert SelfPlayCallback._ledger_fees(env, 0, 4) == Decimal(3)

    def test_an_env_with_no_accounts_has_no_fees_to_read(self):
        assert SelfPlayCallback._ledger_fees(MagicMock(spec=[]), 0, 4) is None

    def test_an_account_without_fees_counts_as_zero(self):
        env = _LedgerEnv(["1000"] * 4, ["0"] * 4)
        for t in env.traders:
            del t.acc.fees_paid
        assert SelfPlayCallback._ledger_fees(env, 0, 4) == 0


class TestTheEpisodeEndCheck:
    """The check that stops a strict run counts the fees, or it would cry wolf."""

    def _end(self, navs, fees):
        from gym_continuousDoubleAuction.test.test_nav_callback import (
            NAV_VIOLATIONS_METRIC, MockEpisode, _emitted,
        )
        runner = MagicMock()
        runner.config.env_config = {"init_cash": 1_000_000, "num_of_agents": 4}
        cb = SelfPlayCallback(num_trainable_policies=2, num_random_policies=2,
                              episode_data_dir=None)
        metrics = MagicMock()
        info = {f"agent_{i}": {"NAV": str(n)} for i, n in enumerate(navs)}
        cb.on_episode_end(episode=MockEpisode("ep", info), env_runner=runner,
                          metrics_logger=metrics, env=_LedgerEnv(navs, fees),
                          env_index=0, rl_module=None)
        return _emitted(metrics, NAV_VIOLATIONS_METRIC).args[1]

    def test_navs_short_by_exactly_the_fees_are_conserved(self):
        assert self._end([999_999, 1_000_001, 999_998, 1_000_000], [1, 0, 2, -1]) == 0.0

    def test_a_shortfall_the_fees_do_not_explain_is_still_a_violation(self):
        assert self._end([999_999, 1_000_001, 999_998, 1_000_000], [1, 0, 2, 5]) == 1.0
