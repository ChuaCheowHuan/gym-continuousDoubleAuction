from decimal import Decimal

import pytest

from gym_continuousDoubleAuction.envs.account.account import Account
from gym_continuousDoubleAuction.envs.exchg.reward_helper import Reward_Helper

class MockTrader:
    def __init__(self, ID, cash):
        self.ID = ID
        self.acc = Account(ID, cash)

class TestRewardLogic:

    def test_max_nav_high_water_mark(self):
        """Verify that max_nav tracks the high-water mark of NAV."""
        trader = MockTrader(0, 1000)
        acc = trader.acc

        assert acc.nav == 1000
        assert acc.max_nav == 1000

        # Simulate a gain
        acc.cash = Decimal(1100)
        acc.cal_nav()
        assert acc.nav == 1100
        assert acc.max_nav == 1100

        # Simulate a loss
        acc.cash = Decimal(900)
        acc.cal_nav()
        assert acc.nav == 900
        assert acc.max_nav == 1100 # Should stay at peak

        # Recover and exceed peak
        acc.cash = Decimal(1200)
        acc.cal_nav()
        assert acc.nav == 1200
        assert acc.max_nav == 1200

    def test_trade_and_passive_counters(self):
        """Verify that num_trades_step and num_passive_fills_step increment correctly."""
        trader = MockTrader(0, 1000)
        acc = trader.acc

        trade = {'quantity': 10, 'price': Decimal(100), 'init_party': {'side': 'bid'}, 'counter_party': {'side': 'ask'}}

        # Aggressive trade
        acc.process_acc(trade, 'init_party')
        assert acc.num_trades_step == 1
        assert acc.num_passive_fills_step == 0

        # Passive trade
        acc.process_acc(trade, 'counter_party')
        assert acc.num_trades_step == 2
        assert acc.num_passive_fills_step == 1

    def test_reward_formula_components(self):
        """Verify the multi-factor reward formula in Reward_Helper.

        Every NAV quantity is a fraction of `acc.init_nav` (S1-1), and the
        drawdown term is the signed *change* in the level (S2-1).
        """
        helper = Reward_Helper(order_penalty=1e-5, trade_penalty=2e-5,
                               drawdown_penalty=0.2, passive_bonus=2e-5,
                               loss_multiplier=1.0)
        trader = MockTrader(0, 1000)
        acc = trader.acc
        rewards = {}

        # prev_nav 1000 -> nav 1050 against a peak of 1100, from a step that
        # placed one order, filled two trades, one of them passive.
        acc.prev_nav = Decimal(1000)
        acc.nav = Decimal(1050)
        acc.max_nav = Decimal(1100)
        acc.order_step_placed = 1
        acc.num_trades_step = 2
        acc.num_passive_fills_step = 1

        # nav_change      = +50/1000                   = +0.05
        # drawdown_change = (50 - 0)/1000              = +0.05
        # order_penalty   = -1e-5 * 1                  = -0.00001
        # trade_penalty   = -2e-5 * 2                  = -0.00004
        # drawdown        = -0.2 * 0.05                = -0.01
        # passive_bonus   = +2e-5 * 1                  = +0.00002
        helper.set_reward(rewards, trader)
        assert float(rewards['agent_0']) == pytest.approx(0.03997, abs=1e-9)

    def test_losses_and_gains_are_symmetric(self):
        """`loss_multiplier` 1.0 is the only value that keeps the game zero-sum.

        Total NAV is conserved exactly, so `sum(nav_change) == 0` across
        agents. Any multiplier above 1 makes `sum(reward) < 0`, which is what
        made passing dominant for everyone (S1-3).
        """
        helper = Reward_Helper(order_penalty=0.0, trade_penalty=0.0,
                               drawdown_penalty=0.0, passive_bonus=0.0,
                               loss_multiplier=1.0)

        winner, loser = MockTrader(0, 1000), MockTrader(1, 1000)
        winner.acc.prev_nav, winner.acc.nav = Decimal(1000), Decimal(1100)
        winner.acc.max_nav = Decimal(1100)
        loser.acc.prev_nav, loser.acc.nav = Decimal(1000), Decimal(900)
        loser.acc.max_nav = Decimal(1000)

        rewards = {}
        helper.set_reward(rewards, winner)
        helper.set_reward(rewards, loser)

        assert sum(rewards.values()) == pytest.approx(0.0, abs=1e-12)

    def test_the_reward_is_scale_invariant(self):
        """The same *relative* move pays the same, at any starting capital.

        This is the property normalising by `init_nav` buys, and it is what
        keeps value targets O(1) whatever `init_cash` is set to - so
        `vf_clip_param` cannot silently start binding again because someone
        raised the starting cash (S1-1).
        """
        helper = Reward_Helper()
        rewards = {}

        for ID, cash in enumerate((1_000, 1_000_000)):
            trader = MockTrader(ID, cash)
            trader.acc.prev_nav = Decimal(cash)
            trader.acc.nav = Decimal(cash) * Decimal("1.05")
            trader.acc.max_nav = Decimal(cash) * Decimal("1.10")
            helper.set_reward(rewards, trader)

        assert rewards['agent_0'] == pytest.approx(rewards['agent_1'], rel=1e-12)

    def test_an_idle_step_below_the_peak_costs_nothing(self):
        """S2-1: the drawdown term charged the *level* on all 4,096 steps.

        One early loss therefore taxed every later step of the episode even
        from an agent that never traded again. The signed change is zero when
        nothing moves, so standing still is free.
        """
        helper = Reward_Helper()
        trader = MockTrader(0, 1000)
        acc = trader.acc

        # Already 100 below a peak of 1100, and nothing happens this step.
        acc.prev_nav = acc.nav = Decimal(1000)
        acc.max_nav = Decimal(1100)
        acc.drawdown = 100.0

        rewards = {}
        helper.set_reward(rewards, trader)
        assert float(rewards['agent_0']) == pytest.approx(0.0, abs=1e-12)

    def test_a_drawdown_round_trip_is_free(self):
        """The signed change telescopes; a clipped one would not.

        Charging only *newly opened* drawdown would bill `nav_term` a second
        time on the way down and refund nothing on the way back up - an
        asymmetric loss multiplier by another name, reintroducing the
        negative-sum bias `loss_multiplier: 1.0` exists to remove.
        """
        helper = Reward_Helper(order_penalty=0.0, trade_penalty=0.0,
                               drawdown_penalty=0.2, passive_bonus=0.0,
                               loss_multiplier=1.0)
        trader = MockTrader(0, 1000)
        acc = trader.acc
        acc.max_nav = Decimal(1000)

        total = 0.0
        for nav in (Decimal(900), Decimal(950), Decimal(1000)):
            acc.prev_nav, acc.nav = acc.nav, nav
            rewards = {}
            helper.set_reward(rewards, trader)
            total += rewards['agent_0']

        # Down 100 and back: NAV nets to zero and so does the drawdown charge.
        assert total == pytest.approx(0.0, abs=1e-12)

    def test_a_non_positive_starting_nav_raises(self):
        """Rather than dividing by zero and poisoning training with inf/nan."""
        helper = Reward_Helper()
        trader = MockTrader(0, 0)
        with pytest.raises(ValueError, match="init_nav"):
            helper.set_reward({}, trader)
