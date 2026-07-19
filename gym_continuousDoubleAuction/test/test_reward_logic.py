import unittest
from decimal import Decimal
from gym_continuousDoubleAuction.envs.account.account import Account
from gym_continuousDoubleAuction.envs.exchg.reward_helper import Reward_Helper

class MockTrader:
    def __init__(self, ID, cash):
        self.ID = ID
        self.acc = Account(ID, cash)

class TestRewardLogic(unittest.TestCase):
    
    def test_max_nav_high_water_mark(self):
        """Verify that max_nav tracks the high-water mark of NAV."""
        trader = MockTrader(0, 1000)
        acc = trader.acc
        
        self.assertEqual(acc.nav, 1000)
        self.assertEqual(acc.max_nav, 1000)
        
        # Simulate a gain
        acc.cash = Decimal(1100)
        acc.cal_nav()
        self.assertEqual(acc.nav, 1100)
        self.assertEqual(acc.max_nav, 1100)
        
        # Simulate a loss
        acc.cash = Decimal(900)
        acc.cal_nav()
        self.assertEqual(acc.nav, 900)
        self.assertEqual(acc.max_nav, 1100) # Should stay at peak
        
        # Recover and exceed peak
        acc.cash = Decimal(1200)
        acc.cal_nav()
        self.assertEqual(acc.nav, 1200)
        self.assertEqual(acc.max_nav, 1200)

    def test_trade_and_passive_counters(self):
        """Verify that num_trades_step and num_passive_fills_step increment correctly."""
        trader = MockTrader(0, 1000)
        acc = trader.acc
        
        trade = {'quantity': 10, 'price': Decimal(100), 'init_party': {'side': 'bid'}, 'counter_party': {'side': 'ask'}}
        
        # Aggressive trade
        acc.process_acc(trade, 'init_party')
        self.assertEqual(acc.num_trades_step, 1)
        self.assertEqual(acc.num_passive_fills_step, 0)
        
        # Passive trade
        acc.process_acc(trade, 'counter_party')
        self.assertEqual(acc.num_trades_step, 2)
        self.assertEqual(acc.num_passive_fills_step, 1)

    def test_reward_formula_components(self):
        """Verify the multi-factor reward formula in Reward_Helper."""
        helper = Reward_Helper()
        trader = MockTrader(0, 1000)
        acc = trader.acc
        rewards = {}
        
        # Setup scenario:
        # prev_nav = 1000
        # nav = 1050 (nav_change = +50)
        # order_step_placed = 1
        # num_trades_step = 2
        # peak_nav = 1100 (drawdown = 50)
        # passive_fills = 1
        
        acc.prev_nav = Decimal(1000)
        acc.nav = Decimal(1050)
        acc.max_nav = Decimal(1100)
        acc.order_step_placed = 1
        acc.num_trades_step = 2
        acc.num_passive_fills_step = 1
        
        # Coeffs from reward_helper.py:
        # nav_change = 50
        # multiplier = 1.0 (positive) -> nav_term = 50
        # order_penalty = 0.1 * 1 = -0.1
        # trade_penalty = 0.05 * 2 = -0.1
        # drawdown_penalty = 0.2 * 50 = -10.0
        # passive_bonus = 0.1 * 1 = +0.1
        # Expected Reward = 50 - 0.1 - 0.1 - 10 + 0.1 = 39.9
        
        helper.set_reward(rewards, trader)
        self.assertAlmostEqual(float(rewards['agent_0']), 39.9, places=5)

    def test_asymmetric_loss_reward(self):
        """Verify that losses are penalized more heavily."""
        helper = Reward_Helper()
        trader = MockTrader(0, 1000)
        acc = trader.acc
        rewards = {}
        
        # NAV change = -100
        acc.prev_nav = Decimal(1000)
        acc.nav = Decimal(900)
        acc.max_nav = Decimal(1000)
        acc.order_step_placed = 0
        acc.num_trades_step = 0
        acc.num_passive_fills_step = 0
        
        # Loss multiplier = 1.5
        # nav_term = -100 * 1.5 = -150
        # drawdown = 100
        # drawdown_penalty = 0.2 * 100 = -20
        # Expected Reward = -150 - 20 = -170
        
        helper.set_reward(rewards, trader)
        self.assertAlmostEqual(float(rewards['agent_0']), -170.0, places=5)

if __name__ == '__main__':
    unittest.main()
