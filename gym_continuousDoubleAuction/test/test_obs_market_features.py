import unittest
import numpy as np

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import continuousDoubleAuctionEnv
from gym_continuousDoubleAuction.envs.exchg.state_helper import (
    BOOK_DIM, EXTRA_DIM, SNAPSHOT_DIM,
)

LOG_MID_IDX = BOOK_DIM
LOG1P_SPREAD_IDX = BOOK_DIM + 1


class TestObsMarketFeatures(unittest.TestCase):
    """
    Tests for the two market-level scalars appended to each observation snapshot:
      - log_mid             = log(M), the Level 1 midpoint anchor
      - log1p_spread_ticks  = log1p(spread / min_tick), 0.0 when not two-sided
    """

    BASE_CONFIG = {
        "num_of_agents": 2,
        "init_cash": 1_000_000,
        "is_render": False,
        "n_hist": 1,
    }

    def _make_env(self, extra_config=None):
        cfg = dict(self.BASE_CONFIG)
        if extra_config:
            cfg.update(extra_config)
        env = continuousDoubleAuctionEnv(cfg)
        env.reset()
        return env

    def _insert(self, env, side, price, quantity, trade_id=0):
        """Insert a resting limit order directly into the book at a known price."""
        quote = {
            'type': 'limit',
            'side': side,
            'quantity': quantity,
            'price': price,
            'trade_id': trade_id,
        }
        env.LOB.process_order(quote, False, False)

    # ------------------------------------------------------------------
    # 1. Shape
    # ------------------------------------------------------------------

    def test_snapshot_dim_is_book_plus_extras(self):
        self.assertEqual(SNAPSHOT_DIM, BOOK_DIM + EXTRA_DIM)
        self.assertEqual(EXTRA_DIM, 2)

    def test_observation_shape_across_n_hist(self):
        for n_hist in [1, 2, 4, 6, 10]:
            env = continuousDoubleAuctionEnv({"num_of_agents": 2, "is_render": False,
                                              "n_hist": n_hist})
            obs, _ = env.reset()
            expected = (n_hist * SNAPSHOT_DIM,)
            for agent_id in env.agents:
                self.assertEqual(env.observation_spaces[agent_id].shape, expected)
                self.assertEqual(obs[agent_id].shape, expected)

    def test_agg_LOB_raw_still_book_sized(self):
        """The raw book used for action pricing must NOT gain the extra scalars."""
        env = self._make_env()
        self.assertEqual(env.agg_LOB_raw.shape, (BOOK_DIM,))
        self._insert(env, 'bid', 99, 10)
        env.set_agg_LOB()
        self.assertEqual(env.agg_LOB_raw.shape, (BOOK_DIM,))

    # ------------------------------------------------------------------
    # 2. log_mid correctness
    # ------------------------------------------------------------------

    def test_log_mid_two_sided_book(self):
        env = self._make_env()
        self._insert(env, 'bid', 98, 10)
        self._insert(env, 'ask', 102, 10)

        snap = env.set_agg_LOB()
        expected_M = (98 + 102) / 2.0
        self.assertAlmostEqual(float(snap[LOG_MID_IDX]), float(np.log(expected_M)), places=5)

    def test_log_mid_bid_only_book(self):
        env = self._make_env()
        self._insert(env, 'bid', 47, 10)

        snap = env.set_agg_LOB()
        self.assertAlmostEqual(float(snap[LOG_MID_IDX]), float(np.log(47.0)), places=5)

    def test_log_mid_ask_only_book(self):
        env = self._make_env()
        self._insert(env, 'ask', 63, 10)

        snap = env.set_agg_LOB()
        self.assertAlmostEqual(float(snap[LOG_MID_IDX]), float(np.log(63.0)), places=5)

    def test_log_mid_empty_book_uses_last_price(self):
        env = self._make_env()
        env.last_price = 37.0

        snap = env.set_agg_LOB()
        self.assertAlmostEqual(float(snap[LOG_MID_IDX]), float(np.log(37.0)), places=5)

    def test_log_mid_survives_non_positive_last_price(self):
        """M defaults to 100.0 when last_price is bad; log must stay finite."""
        env = self._make_env()
        env.last_price = 0.0

        snap = env.set_agg_LOB()
        self.assertAlmostEqual(float(snap[LOG_MID_IDX]), float(np.log(100.0)), places=5)
        self.assertTrue(np.isfinite(snap).all())

    # ------------------------------------------------------------------
    # 3. log1p_spread_ticks correctness
    # ------------------------------------------------------------------

    def test_log1p_spread_two_sided_book(self):
        env = self._make_env()
        self._insert(env, 'bid', 98, 10)
        self._insert(env, 'ask', 102, 10)

        snap = env.set_agg_LOB()
        expected = np.log1p((102 - 98) / env.min_tick)
        self.assertAlmostEqual(float(snap[LOG1P_SPREAD_IDX]), float(expected), places=5)

    def test_log1p_spread_one_tick(self):
        """The tightest possible resting book maps to log1p(1) = 0.693..."""
        env = self._make_env()
        self._insert(env, 'bid', 100, 10)
        self._insert(env, 'ask', 101, 10)

        snap = env.set_agg_LOB()
        self.assertAlmostEqual(float(snap[LOG1P_SPREAD_IDX]), float(np.log1p(1.0)), places=5)

    def test_log1p_spread_is_monotonic_in_spread(self):
        values = []
        for ask in [101, 105, 120, 200]:
            env = self._make_env()
            self._insert(env, 'bid', 100, 10)
            self._insert(env, 'ask', ask, 10)
            values.append(float(env.set_agg_LOB()[LOG1P_SPREAD_IDX]))

        self.assertEqual(values, sorted(values))
        self.assertTrue(all(np.isfinite(values)))

    # ------------------------------------------------------------------
    # 4. Sentinel semantics
    # ------------------------------------------------------------------

    def test_spread_sentinel_is_zero_when_not_two_sided(self):
        for side, price in [('bid', 90), ('ask', 110)]:
            env = self._make_env()
            self._insert(env, side, price, 10)
            snap = env.set_agg_LOB()
            self.assertEqual(float(snap[LOG1P_SPREAD_IDX]), 0.0,
                             msg=f"one-sided ({side}) book must use the 0.0 sentinel")

    def test_spread_sentinel_is_zero_on_empty_book(self):
        env = self._make_env()
        snap = env.set_agg_LOB()
        self.assertEqual(float(snap[LOG1P_SPREAD_IDX]), 0.0)

    def test_sentinel_is_separable_from_every_real_spread(self):
        """
        A resting book can never be locked or crossed, so any two-sided book has a
        spread of >= 1 tick and therefore log1p >= log1p(1). The 0.0 sentinel can
        never collide with a real measurement.
        """
        floor = float(np.log1p(1.0))
        for ask in [101, 102, 110, 175]:
            env = self._make_env()
            self._insert(env, 'bid', 100, 10)
            self._insert(env, 'ask', ask, 10)
            value = float(env.set_agg_LOB()[LOG1P_SPREAD_IDX])
            self.assertGreaterEqual(value, floor)
            self.assertGreater(value, 0.0)

    # ------------------------------------------------------------------
    # 5. Placement within the stacked observation
    # ------------------------------------------------------------------

    def test_scalars_present_in_every_frame_after_reset(self):
        """reset() pads the history with n_hist copies, so every frame carries them."""
        n_hist = 4
        env = continuousDoubleAuctionEnv({"num_of_agents": 2, "is_render": False,
                                          "n_hist": n_hist})
        obs, _ = env.reset()
        stacked = obs["agent_0"]
        expected_log_mid = float(np.log(env.last_price))

        for k in range(n_hist):
            frame = stacked[k * SNAPSHOT_DIM:(k + 1) * SNAPSHOT_DIM]
            self.assertEqual(frame.shape, (SNAPSHOT_DIM,))
            self.assertAlmostEqual(float(frame[LOG_MID_IDX]), expected_log_mid, places=5)
            self.assertEqual(float(frame[LOG1P_SPREAD_IDX]), 0.0)

    def test_book_block_slicing_unaffected(self):
        """Appending at the end must leave the existing block offsets valid."""
        env = self._make_env()
        self._insert(env, 'bid', 98, 10)
        self._insert(env, 'ask', 102, 10)

        snap = env.set_agg_LOB()
        bid_prices, bid_sizes = snap[0:10], snap[10:20]
        ask_prices, ask_sizes = snap[20:30], snap[30:40]

        self.assertTrue(np.all(bid_prices >= 0))
        self.assertTrue(np.all(bid_sizes >= 0))
        self.assertTrue(np.all(ask_prices <= 0))
        self.assertTrue(np.all(ask_sizes <= 0))

    # ------------------------------------------------------------------
    # 6. Rollout safety
    # ------------------------------------------------------------------

    def test_no_nan_or_inf_across_random_rollout(self):
        env = continuousDoubleAuctionEnv({"num_of_agents": 3, "init_cash": 1_000_000,
                                          "is_render": False, "max_step": 32})
        obs, _ = env.reset()
        for _ in range(20):
            actions = {a: env.action_spaces[a].sample() for a in env.agents}
            obs, _, _, _, _ = env.step(actions)
            for agent_id, vector in obs.items():
                self.assertTrue(np.isfinite(vector).all(),
                                msg=f"non-finite observation for {agent_id}")
                self.assertEqual(vector.shape, (env.n_hist * SNAPSHOT_DIM,))


if __name__ == "__main__":
    unittest.main()
