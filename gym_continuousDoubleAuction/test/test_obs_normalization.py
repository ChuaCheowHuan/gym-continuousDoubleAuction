import numpy as np
import pytest
from decimal import Decimal

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import continuousDoubleAuctionEnv
from gym_continuousDoubleAuction.envs.exchg.state_helper import BOOK_DIM, SNAPSHOT_DIM


class TestObsNormalization:
    """
    Tests for LOB observation normalization (set_agg_LOB):
      - Midpoint-based symmetric price normalization
      - sqrt-based volume normalization
      - Observation sign preservation (bids >= 0, asks <= 0)
      - agg_LOB_raw stores unnormalized raw values
      - Division-by-zero safety (empty book falls back to last_price)
      - Action price unnormalization: _set_price() uses agg_LOB_raw
    """

    BASE_CONFIG = {
        "num_of_agents": 2,
        "init_cash": 1_000_000,
        "is_render": False,
        "n_hist": 1,          # single snapshot simplifies assertion indexing
    }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_env(self, extra_config=None):
        cfg = dict(self.BASE_CONFIG)
        if extra_config:
            cfg.update(extra_config)
        env = continuousDoubleAuctionEnv(cfg)
        return env

    def _place_limit(self, env, agent_id, category, level, offset,
                     size_mean=0.5, size_sigma=0.0):
        """Submit a single limit order action and return the step outputs."""
        action = {
            agent_id: {
                "category": category,
                "price": level,
                "price_offset": offset,
                "size_mean": np.array([size_mean], dtype=np.float32),
                "size_sigma": np.array([size_sigma], dtype=np.float32),
            }
        }
        return env.step(action)

    def _get_snapshot(self, obs, agent_id="agent_0"):
        """Extract the most recent snapshot (book block + scalars) from a stacked observation."""
        return obs[agent_id][-SNAPSHOT_DIM:]

    # ------------------------------------------------------------------
    # 1. agg_LOB_raw is always populated after reset and step
    # ------------------------------------------------------------------

    def test_agg_LOB_raw_exists_after_reset(self):
        """self.agg_LOB_raw must be a numpy array of shape (40,) after reset."""
        env = self._make_env()
        env.reset()
        assert hasattr(env, "agg_LOB_raw"), "agg_LOB_raw attribute missing after reset"
        raw = env.agg_LOB_raw
        assert isinstance(raw, np.ndarray)
        assert raw.shape == (40,)

    def test_agg_LOB_raw_updated_after_step(self):
        """agg_LOB_raw must be updated (and remain shape (40,)) after each step."""
        env = self._make_env()
        env.reset()
        raw_before = env.agg_LOB_raw.copy()

        # Place a bid limit to modify the book
        self._place_limit(env, "agent_0", category=2, level=0, offset=1)

        raw_after = env.agg_LOB_raw
        assert raw_after.shape == (40,)
        # Raw should now be non-zero in bid price slot
        assert not np.array_equal(raw_before, raw_after), \
            "agg_LOB_raw did not change after placing an order"

    # ------------------------------------------------------------------
    # 2. Sign preservation in the normalized observation
    # ------------------------------------------------------------------

    def test_obs_signs_empty_book(self):
        """With an empty book after reset, the book block should be all 0.0."""
        env = self._make_env()
        obs, _ = env.reset()
        snap = self._get_snapshot(obs)
        np.testing.assert_array_equal(
            snap[:BOOK_DIM], np.zeros(BOOK_DIM, dtype=np.float32),
            err_msg="Empty book block should be all zeros"
        )
        # The market scalars are not part of the book block: log_mid falls back to
        # last_price and the spread sentinel is 0.0 (no two-sided market).
        assert float(snap[BOOK_DIM]) == pytest.approx(float(np.log(env.last_price)), abs=1e-5)
        assert float(snap[BOOK_DIM + 1]) == 0.0

    def test_bid_obs_non_negative_with_orders(self):
        """After placing bid orders, bid price & size features must be >= 0."""
        env = self._make_env()
        env.reset()

        # Place several bid limit orders at different levels
        for level in range(3):
            self._place_limit(env, "agent_0", category=2, level=level, offset=1)

        obs_step, _, _, _, _ = self._place_limit(env, "agent_0", category=2,
                                                  level=3, offset=1)
        snap = self._get_snapshot(obs_step)
        bid_prices = snap[0:10]
        bid_sizes  = snap[10:20]

        assert np.all(bid_prices >= 0), f"Bid prices in obs must be >= 0, got {bid_prices}"
        assert np.all(bid_sizes >= 0), f"Bid sizes in obs must be >= 0, got {bid_sizes}"

    def test_ask_obs_non_positive_with_orders(self):
        """After placing ask orders, ask price & size features must be <= 0."""
        env = self._make_env()
        env.reset()

        # Place several ask limit orders at different levels
        for level in range(3):
            self._place_limit(env, "agent_0", category=6, level=level, offset=1)

        obs_step, _, _, _, _ = self._place_limit(env, "agent_0", category=6,
                                                  level=3, offset=1)
        snap = self._get_snapshot(obs_step)
        ask_prices = snap[20:30]
        ask_sizes  = snap[30:40]

        assert np.all(ask_prices <= 0), f"Ask prices in obs must be <= 0, got {ask_prices}"
        assert np.all(ask_sizes <= 0), f"Ask sizes in obs must be <= 0, got {ask_sizes}"

    # ------------------------------------------------------------------
    # 3. Midpoint price normalization correctness
    # ------------------------------------------------------------------

    def test_midpoint_price_normalization_correctness(self):
        """
        Directly test that set_agg_LOB() produces correct midpoint-normalized prices.

        Strategy:
          1. Reset the environment.
          2. Place a bid at known price P_bid and an ask at known price P_ask.
          3. Read back agg_LOB_raw and compute expected normalized values manually.
          4. Compare against the normalized snapshot from the observation.
        """
        env = self._make_env({"init_cash": 10_000_000,
                              "initial_price_min": 100,
                              "initial_price_max": 100})
        env.reset()
        env.last_price = 100.0   # pin anchor

        # Place Sell Limit at Level 1 Join → price = 100 + 1 = 101
        self._place_limit(env, "agent_0", category=6, level=0, offset=1)
        # Place Buy Limit at Level 1 Join → price = 100 - 1 = 99
        obs_step, _, _, _, _ = self._place_limit(
            env, "agent_1", category=2, level=0, offset=1)

        raw = env.agg_LOB_raw  # [bid_prices(10), bid_sizes(10), ask_prices(10), ask_sizes(10)]
        P_bid_1 = raw[0]       # best bid price (raw, positive)
        P_ask_1 = abs(raw[20]) # best ask price (raw, positive magnitude)

        # Only proceed if both sides were actually placed
        if P_bid_1 == 0 or P_ask_1 == 0:
            pytest.skip("Orders did not populate both book sides; skip normalization check.")

        M = (P_bid_1 + P_ask_1) / 2.0

        # Expected normalized best bid price
        expected_norm_bid = (M - P_bid_1) / M
        # Expected normalized best ask price (negative)
        expected_norm_ask = -((P_ask_1 - M) / M)

        snap = self._get_snapshot(obs_step)
        actual_norm_bid = snap[0]    # first bid price slot
        actual_norm_ask = snap[20]   # first ask price slot

        assert float(actual_norm_bid) == pytest.approx(expected_norm_bid, abs=1e-5), \
            "Normalized bid price does not match expected"
        assert float(actual_norm_ask) == pytest.approx(expected_norm_ask, abs=1e-5), \
            "Normalized ask price does not match expected"

    def test_level1_bid_ask_symmetric_distance(self):
        """
        At Level 1, the normalized bid distance and ask distance magnitudes
        must be equal: |norm_P_bid_1| == |norm_P_ask_1| == spread / (2 * M).
        """
        env = self._make_env({"init_cash": 10_000_000,
                              "initial_price_min": 100,
                              "initial_price_max": 100})
        env.reset()
        env.last_price = 100.0

        # Ask at 101, Bid at 99 → spread = 2, M = 100
        self._place_limit(env, "agent_0", category=6, level=0, offset=1)
        obs_step, _, _, _, _ = self._place_limit(
            env, "agent_1", category=2, level=0, offset=1)

        raw = env.agg_LOB_raw
        P_bid_1 = raw[0]
        P_ask_1 = abs(raw[20])

        if P_bid_1 == 0 or P_ask_1 == 0:
            pytest.skip("Could not populate both book sides.")

        snap = self._get_snapshot(obs_step)
        norm_bid_mag = abs(float(snap[0]))
        norm_ask_mag = abs(float(snap[20]))

        assert norm_bid_mag == pytest.approx(norm_ask_mag, abs=1e-5), \
            "Level-1 bid and ask normalized distances should be symmetric"

    # ------------------------------------------------------------------
    # 4. Volume normalization correctness (sqrt)
    # ------------------------------------------------------------------

    def test_volume_normalization_sqrt(self):
        """
        The size slots in the normalized observation must equal sqrt(raw_volume).
        """
        env = self._make_env({"init_cash": 10_000_000,
                              "initial_price_min": 100,
                              "initial_price_max": 100})
        env.reset()
        env.last_price = 100.0

        self._place_limit(env, "agent_0", category=6, level=0, offset=1)
        obs_step, _, _, _, _ = self._place_limit(
            env, "agent_1", category=2, level=0, offset=1)

        raw = env.agg_LOB_raw
        # [bid_prices(10), bid_sizes(10), ask_prices(10), ask_sizes(10)]
        raw_bid_size_l1 = raw[10]          # first bid size level
        raw_ask_size_l1 = abs(raw[30])     # first ask size level (stored negative)

        snap = self._get_snapshot(obs_step)
        norm_bid_size_l1 = float(snap[10])
        norm_ask_size_l1 = float(snap[30])

        if raw_bid_size_l1 > 0:
            assert norm_bid_size_l1 == pytest.approx(np.sqrt(raw_bid_size_l1), abs=1e-4), \
                "Bid size not sqrt-normalized"
        if raw_ask_size_l1 > 0:
            assert norm_ask_size_l1 == pytest.approx(-np.sqrt(raw_ask_size_l1), abs=1e-4), \
                "Ask size not sqrt-normalized (should be negative)"

    # ------------------------------------------------------------------
    # 5. Division-by-zero safety: empty book fallback to last_price
    # ------------------------------------------------------------------

    def test_empty_book_uses_last_price_anchor(self):
        """
        When both bid and ask are 0, midpoint M must fall back to last_price
        and no NaN or Inf should appear in the observation.
        """
        env = self._make_env()
        env.reset()
        # Ensure the book is empty (it always starts empty after reset)
        env.last_price = 50.0

        # Manually call set_agg_LOB with no orders in book
        snap = env.set_agg_LOB()

        assert not np.any(np.isnan(snap)), "NaN found in observation with empty book"
        assert not np.any(np.isinf(snap)), "Inf found in observation with empty book"
        # Empty book → all zeros in the book block
        np.testing.assert_array_equal(snap[:BOOK_DIM], np.zeros(BOOK_DIM, dtype=np.float32),
                                      err_msg="Empty book should produce an all-zero book block")
        # M falls back to last_price (50.0), and there is no two-sided spread
        assert float(snap[BOOK_DIM]) == pytest.approx(float(np.log(50.0)), abs=1e-5)
        assert float(snap[BOOK_DIM + 1]) == 0.0

    def test_zero_last_price_fallback(self):
        """
        If last_price is somehow 0 or negative, M must still be > 0 (defaults to 100).
        No NaN or division-by-zero should occur.
        """
        env = self._make_env()
        env.reset()
        env.last_price = 0.0  # Simulate bad state

        snap = env.set_agg_LOB()

        assert not np.any(np.isnan(snap)), "NaN with last_price=0"
        assert not np.any(np.isinf(snap)), "Inf with last_price=0"

    # ------------------------------------------------------------------
    # 6. Action price unnormalization: _set_price() uses agg_LOB_raw
    # ------------------------------------------------------------------

    def test_action_price_from_populated_book_is_raw(self):
        """
        When the book has a Level 1 bid at a known raw price, selecting price
        level 0 should resolve to that actual (unnormalized) market price, not
        a normalized value.
        """
        env = self._make_env({"init_cash": 10_000_000,
                              "initial_price_min": 100,
                              "initial_price_max": 100})
        env.reset()
        env.last_price = 100.0

        # Place a bid limit: Level 1 Join → price = 100 - 1 = 99
        self._place_limit(env, "agent_0", category=2, level=0, offset=1)

        # Now select Level 0 bid Join again — should reference raw bid price 99
        self._place_limit(env, "agent_0", category=2, level=0, offset=1)

        resolved_price = env.LOB_actions[0]["price"]

        # The raw price at level 0 of the bid tree should be 99
        raw_bid_l1 = env.agg_LOB_raw[0]  # bid_prices[0] (raw, positive)

        # Resolved action price == raw level price + offset(Join=0)
        assert resolved_price == pytest.approx(float(raw_bid_l1), abs=1e-4), \
            "Action price should equal unnormalized raw level price"

    def test_action_price_is_positive(self):
        """
        Regardless of book state, every resolved order price must be > 0.
        """
        env = self._make_env({"init_cash": 10_000_000})
        env.reset()

        for step in range(10):
            actions = {
                agent_id: env.action_spaces[agent_id].sample()
                for agent_id in env.agents
            }
            env.step(actions)
            for act in env.LOB_actions:
                price = act.get("price", -1.0)
                if price != -1.0:   # -1.0 is the sentinel for market orders
                    assert price > 0, f"Action price {price} is not positive at step {step}"
