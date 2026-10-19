import numpy as np
import pytest
from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import continuousDoubleAuctionEnv


class TestActionSpaceRobust:
    @classmethod
    def setup_class(cls):
        cls.config = {
            "num_of_agents": 2,
            "init_cash": 100000,
            "initial_price_min": 100,
            "initial_price_max": 200,
            "is_render": False,
            # Ghost pricing and level-relative offsets are the `levels` book
            # mode's; the grid's price codes are pinned in test_grid_book.py.
            "book_mode": "levels",
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
        for level in range(10):  # 0-9 maps to Level 1-10
            action = {
                'agent_0': {
                    'category': 2,  # Buy Limit
                    'price': level,
                    'price_offset': 1,  # Join
                    'size': np.array([0.0], dtype=np.float32),
                }
            }
            self.env.step(action)
            actual_price = self.env.LOB_actions[0]['price']
            expected_price = anchor - (level + 1) * self.tick
            assert actual_price == pytest.approx(expected_price, abs=1e-5), (
                f"Bid Level {level + 1} failed"
            )

    def test_ask_ghost_pricing(self):
        """Verify deterministic Sell Limit (Level 1-10) pricing when book is empty."""
        anchor = self.env.last_price
        for level in range(10):  # 0-9 maps to Level 1-10
            action = {
                'agent_0': {
                    'category': 6,  # Sell Limit
                    'price': level,
                    'price_offset': 1,  # Join
                    'size': np.array([0.0], dtype=np.float32),
                }
            }
            self.env.step(action)
            actual_price = self.env.LOB_actions[0]['price']
            expected_price = anchor + (level + 1) * self.tick
            assert actual_price == pytest.approx(expected_price, abs=1e-5), (
                f"Ask Level {level + 1} failed"
            )

    def test_price_offsets_bid(self):
        """Verify Passive/Join/Aggressive offsets for Bids."""
        anchor = self.env.last_price
        level = 0  # Level 1
        base_ghost = anchor - (level + 1) * self.tick  # 99 if anchor 100

        offsets = {
            0: base_ghost - self.tick,  # Passive (98)
            1: base_ghost,  # Join (99)
            2: base_ghost + self.tick,  # Aggressive (100)
        }

        for off_code, expected in offsets.items():
            self.env.reset()
            self.env.last_price = anchor  # Keep anchor consistent for trial
            action = {
                'agent_0': {
                    'category': 2,
                    'price': level,
                    'price_offset': off_code,
                    'size': np.array([0.0]),
                }
            }
            self.env.step(action)
            assert self.env.LOB_actions[0]['price'] == pytest.approx(expected), (
                f"Bid Offset {off_code} failed"
            )

    def test_price_offsets_ask(self):
        """Verify Passive/Join/Aggressive offsets for Asks."""
        anchor = self.env.last_price
        level = 0  # Level 1
        base_ghost = anchor + (level + 1) * self.tick  # 101 if anchor 100

        offsets = {
            0: base_ghost + self.tick,  # Passive (102)
            1: base_ghost,  # Join (101)
            2: base_ghost - self.tick,  # Aggressive (100)
        }

        for off_code, expected in offsets.items():
            self.env.reset()
            self.env.last_price = anchor  # Keep anchor consistent for trial
            action = {
                'agent_0': {
                    'category': 6,
                    'price': level,
                    'price_offset': off_code,
                    'size': np.array([0.0]),
                }
            }
            self.env.step(action)
            assert self.env.LOB_actions[0]['price'] == pytest.approx(expected), (
                f"Ask Offset {off_code} failed"
            )

    def test_market_order_mapping(self):
        """Verify Buy/Sell Market orders (Cat 1, 5) ignore price fields."""
        for cat in [1, 5]:
            action = {
                'agent_0': {'category': cat, 'price': 9, 'price_offset': 0, 'size': np.array([0.0])}
            }
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
        action = {
            'agent_0': {'category': 6, 'price': 0, 'price_offset': 2, 'size': np.array([0.0])}
        }
        self.env.step(action)

        # 2. Place a Buy Market
        action = {
            'agent_1': {'category': 1, 'price': 0, 'price_offset': 1, 'size': np.array([0.1])}
        }
        self.env.step(action)

        # Check if trade happened and anchor updated
        assert len(self.env.LOB.tape) > 0, "No trade recorded"
        last_trade_price = float(self.env.LOB.tape[-1]['price'])
        assert self.env.last_price == last_trade_price, "Anchor did not update to trade price"

    def test_neutral_action(self):
        """Verify category 0 (Neutral) results in no order submission."""
        self.env.reset()
        action = {
            'agent_0': {'category': 0, 'price': 0, 'price_offset': 1, 'size': np.array([0.0])}
        }
        obs, rewards, term, trunc, info = self.env.step(action)
        # Category 0 results in side=None, which is filtered out before LOB_actions is populated in CDA_env
        assert len(self.env.LOB_actions) == 0, "Neutral action should not produce LOB actions"


class TestTickGrid:
    """`tick_size` drives the price grid through `Action_Helper.min_tick`.

    `min_tick` was a hardcoded 1 that made the configured `tick_size` a no-op;
    it now comes from the config key. `OrderBook` still accepts and stores a
    `tick_size` it never reads - that copy is retained deliberately, because the
    orderbook package is off-limits. See docs/29 S3-4; these tests cover the
    action-layer half only.
    """

    def _env(self, tick_size, anchor=37):
        env = continuousDoubleAuctionEnv(
            {
                "num_of_agents": 2,
                "init_cash": 100000,
                "tick_size": tick_size,
                "initial_price_min": anchor,
                "initial_price_max": anchor,
                "is_render": False,
                "book_mode": "levels",
            }
        )
        env.reset()
        return env

    def test_tick_size_config_reaches_action_layer(self):
        """min_tick comes from config, and the ghost ladder is spaced by it."""
        env = self._env(0.25)
        assert env.min_tick == 0.25

        anchor = env.last_price
        for level in range(5):
            price = env._set_price(env.min_tick, 'bid', level, 1)
            assert price == pytest.approx(anchor - (level + 1) * 0.25, abs=1e-9)

    # There is deliberately no "prices stay on grid" test here. `_set_price`
    # performs no quantization, so that property is not enforced and does not
    # hold in general - `anchor=10, tick=0.3` puts bid level 8 at
    # 7.300000000000001. See docs/18 section 3.1.

    def test_action_price_levels_match_book_depth(self):
        """price codes index book levels, so the two depths cannot drift apart."""
        from gym_continuousDoubleAuction.envs.exchg.state_helper import K_ROWS

        env = self._env(1)
        assert env.action_spaces['agent_0']['price'].n == K_ROWS


class TestSizeHead:
    """S3-1 to S3-3: one `size` head the policy samples itself.

    `size_mean`/`size_sigma` were turned into a size by a draw inside the env:
    a signed mean folded by `abs()` (S3-1), a sigma too small to matter (S3-2),
    and a realised size outside the log-probability PPO scores (S3-3).
    """

    @staticmethod
    def _env(**extra):
        return continuousDoubleAuctionEnv({"num_of_agents": 2, "is_render": False, **extra})

    def test_there_is_one_size_head_in_zero_to_one(self):
        space = self._env().action_spaces["agent_0"]
        assert "size_mean" not in space.spaces and "size_sigma" not in space.spaces
        assert (float(space["size"].low[0]), float(space["size"].high[0])) == (0.0, 1.0)

    @pytest.mark.parametrize("kind", ["market", "limit"])
    def test_every_point_of_the_range_is_a_different_size(self, kind):
        """No two declared sizes give the same contracts, so no part of the range is dead."""
        env = self._env()
        env.reset(seed=0)
        space = env.action_spaces["agent_0"]["size"]
        fractions = np.linspace(float(space.low[0]), float(space.high[0]), 11)
        sizes = [env._set_size(kind, np.array([f], dtype=np.float32)) for f in fractions]
        assert sizes == sorted(set(sizes))

    def test_the_same_action_gives_the_same_size_whatever_the_env_seed(self):
        """S3-3: the realised size is the action, not a draw the env makes."""
        action = {
            "category": 2,
            "order_slot": 0,
            "price": 3,
            "price_offset": 1,
            "size": np.array([0.5], dtype=np.float32),
        }
        sizes = set()
        for seed in range(8):
            env = self._env()
            env.reset(seed=seed)
            sizes.add(env._set_action_mkt_depth("agent_0", dict(action))["size"])
        assert len(sizes) == 1

    def test_the_size_is_the_fraction_times_the_multiplier_plus_the_minimum(self):
        env = self._env()
        env.reset(seed=0)
        for category, mul in ((1, env.mkt_size_mul), (2, env.limit_size_mul)):
            act = env._set_action_mkt_depth(
                "agent_0",
                {
                    "category": category,
                    "order_slot": 0,
                    "price": 0,
                    "price_offset": 1,
                    "size": np.array([0.4], dtype=np.float32),
                },
            )
            assert act["size"] == int(np.rint(0.4 * mul)) + env.min_size

    def test_a_value_outside_the_range_is_clipped_not_folded(self):
        env = self._env()
        env.reset(seed=0)
        low = env._set_size("limit", np.array([0.0], dtype=np.float32))
        high = env._set_size("limit", np.array([1.0], dtype=np.float32))
        assert env._set_size("limit", np.array([-0.7], dtype=np.float32)) == low
        assert env._set_size("limit", np.array([9.0], dtype=np.float32)) == high

    def test_a_sampled_size_is_in_the_range(self):
        space = self._env().action_spaces["agent_0"]["size"]
        space.seed(0)
        assert all(0.0 <= float(space.sample()[0]) <= 1.0 for _ in range(200))

    def test_a_negative_lower_bound_is_refused(self):
        """Config is the only source of the bounds (CLAUDE.md rule 1), so a bad one must fail."""
        import json
        from gym_continuousDoubleAuction.envs.exchg.action_helper import Action_Helper

        helper = Action_Helper.__new__(Action_Helper)
        helper._act = {
            **json.load(open("config/tunable_constants.json"))["action_space"],
            "size_low": -0.5,
        }
        with pytest.raises(ValueError, match="size_low"):
            helper._validate_action_space()
