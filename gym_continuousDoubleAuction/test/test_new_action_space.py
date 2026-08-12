import numpy as np
import pytest
import gymnasium as gym
from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import continuousDoubleAuctionEnv

class TestActionSpaceRobust:
    @classmethod
    def setup_class(cls):
        cls.config = {
            "num_of_agents": 2,
            "init_cash": 100000,
            "initial_price_min": 100,
            "initial_price_max": 200,
            "is_render": False
        }
        cls.env = continuousDoubleAuctionEnv(cls.config)

    def setup_method(self):
        self.env.reset()
        self.tick = self.env.min_tick

    def test_initial_price_integrity(self):
        """Verify last_price is an integer within the specified range at reset."""
        for _ in range(10):
            self.env.reset()
            lp = self.env.last_price
            assert isinstance(lp, float)
            assert lp == float(int(lp)), "last_price should be a whole number (integer float)"
            assert lp >= 100
            assert lp <= 200

    def test_bid_ghost_pricing(self):
        """Verify deterministic Buy Limit (Level 1-10) pricing when book is empty."""
        anchor = self.env.last_price
        for level in range(10): # 0-9 maps to Level 1-10
            action = {
                'agent_0': {
                    'category': 2, # Buy Limit
                    'price': level,
                    'price_offset': 1, # Join
                    'size_mean': np.array([0.0], dtype=np.float32),
                    'size_sigma': np.array([0.0], dtype=np.float32)
                }
            }
            self.env.step(action)
            actual_price = self.env.LOB_actions[0]['price']
            expected_price = anchor - (level + 1) * self.tick
            assert actual_price == pytest.approx(expected_price, abs=1e-5), f"Bid Level {level+1} failed"

    def test_ask_ghost_pricing(self):
        """Verify deterministic Sell Limit (Level 1-10) pricing when book is empty."""
        anchor = self.env.last_price
        for level in range(10): # 0-9 maps to Level 1-10
            action = {
                'agent_0': {
                    'category': 6, # Sell Limit
                    'price': level,
                    'price_offset': 1, # Join
                    'size_mean': np.array([0.0], dtype=np.float32),
                    'size_sigma': np.array([0.0], dtype=np.float32)
                }
            }
            self.env.step(action)
            actual_price = self.env.LOB_actions[0]['price']
            expected_price = anchor + (level + 1) * self.tick
            assert actual_price == pytest.approx(expected_price, abs=1e-5), f"Ask Level {level+1} failed"

    def test_price_offsets_bid(self):
        """Verify Passive/Join/Aggressive offsets for Bids."""
        anchor = self.env.last_price
        level = 0 # Level 1
        base_ghost = anchor - (level + 1) * self.tick # 99 if anchor 100

        offsets = {
            0: base_ghost - self.tick, # Passive (98)
            1: base_ghost,             # Join (99)
            2: base_ghost + self.tick  # Aggressive (100)
        }

        for off_code, expected in offsets.items():
            self.env.reset()
            self.env.last_price = anchor # Keep anchor consistent for trial
            action = {'agent_0': {'category': 2, 'price': level, 'price_offset': off_code,
                                 'size_mean': np.array([0.0]), 'size_sigma': np.array([0.0])}}
            self.env.step(action)
            assert self.env.LOB_actions[0]['price'] == pytest.approx(expected), f"Bid Offset {off_code} failed"

    def test_price_offsets_ask(self):
        """Verify Passive/Join/Aggressive offsets for Asks."""
        anchor = self.env.last_price
        level = 0 # Level 1
        base_ghost = anchor + (level + 1) * self.tick # 101 if anchor 100

        offsets = {
            0: base_ghost + self.tick, # Passive (102)
            1: base_ghost,             # Join (101)
            2: base_ghost - self.tick  # Aggressive (100)
        }

        for off_code, expected in offsets.items():
            self.env.reset()
            self.env.last_price = anchor # Keep anchor consistent for trial
            action = {'agent_0': {'category': 6, 'price': level, 'price_offset': off_code,
                                 'size_mean': np.array([0.0]), 'size_sigma': np.array([0.0])}}
            self.env.step(action)
            assert self.env.LOB_actions[0]['price'] == pytest.approx(expected), f"Ask Offset {off_code} failed"

    def test_market_order_mapping(self):
        """Verify Buy/Sell Market orders (Cat 1, 5) ignore price fields."""
        for cat in [1, 5]:
            action = {'agent_0': {'category': cat, 'price': 9, 'price_offset': 0,
                                 'size_mean': np.array([0.0]), 'size_sigma': np.array([0.0])}}
            self.env.step(action)
            assert self.env.LOB_actions[0]['price'] == -1.0
            assert self.env.LOB_actions[0]['type'] == 'market'

    def test_trading_updates_anchor(self):
        """Verify that a trade updates the environments last_price anchor."""
        # Force a trade by crossing a bid and an ask
        # Reset to known values
        self.env.reset()
        self.env.last_price = 100.0

        # 1. Place a Sell Limit at 100 (Level 1, Aggressive)
        # Sell(6), Level 1(0), Aggressive(2) -> 101 - 1 = 100
        action = {'agent_0': {'category': 6, 'price': 0, 'price_offset': 2,
                             'size_mean': np.array([0.0]), 'size_sigma': np.array([0.0])}}
        self.env.step(action)

        # 2. Place a Buy Market
        action = {'agent_1': {'category': 1, 'price': 0, 'price_offset': 1,
                             'size_mean': np.array([0.1]), 'size_sigma': np.array([0.0])}}
        self.env.step(action)

        # Check if trade happened and anchor updated
        assert len(self.env.LOB.tape) > 0, "No trade recorded"
        last_trade_price = float(self.env.LOB.tape[-1]['price'])
        assert self.env.last_price == last_trade_price, "Anchor did not update to trade price"

    def test_neutral_action(self):
        """Verify category 0 (Neutral) results in no order submission."""
        self.env.reset()
        action = {'agent_0': {'category': 0, 'price': 0, 'price_offset': 1,
                             'size_mean': np.array([0.0]), 'size_sigma': np.array([0.0])}}
        obs, rewards, term, trunc, info = self.env.step(action)
        # Category 0 results in side=None, which is filtered out before LOB_actions is populated in CDA_env
        assert len(self.env.LOB_actions) == 0, "Neutral action should not produce LOB actions"
