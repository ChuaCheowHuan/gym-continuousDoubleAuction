import numpy as np
import pytest

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import continuousDoubleAuctionEnv
from gym_continuousDoubleAuction.envs.exchg.state_helper import (
    BOOK_DIM, EXTRA_DIM, EXTRA_FIELDS, OBS_BOOK_DIM, PRIVATE_DIM, SNAPSHOT_DIM,
)

#: In `levels` mode the emitted book block is the raw block, so the scalars
#: start at BOOK_DIM.
LEVELS_SNAPSHOT_DIM = BOOK_DIM + EXTRA_DIM
LOG_MID_IDX = BOOK_DIM
LOG1P_SPREAD_IDX = BOOK_DIM + 1


class TestObsMarketFeatures:
    """
    Tests for the two market-level scalars appended to each observation snapshot:
      - log_mid             = log(M) - log_mid_centre, the Level 1 midpoint
                              anchor, centred on the geometric mean of the
                              price-anchor range so it is not a standing
                              +4.6 bias into a tanh layer (doc/15 S2-2)
      - log1p_spread_ticks  = log1p(spread / min_tick), 0.0 when not two-sided
    """

    BASE_CONFIG = {
        "num_of_agents": 2,
        "init_cash": 1_000_000,
        "is_render": False,
        "n_hist": 1,
        # The scalar offsets below index a `levels` snapshot (S3-15 made the
        # grid the default; the scalars sit after the book block in both).
        "book_mode": "levels",
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
        assert SNAPSHOT_DIM == OBS_BOOK_DIM + EXTRA_DIM
        env = self._make_env()
        assert env.snapshot_dim == env.obs_book_dim + env.extra_dim == LEVELS_SNAPSHOT_DIM
        assert EXTRA_DIM == len(EXTRA_FIELDS)

    def test_observation_shape_across_n_hist(self):
        for n_hist in [1, 2, 4, 6, 10]:
            env = continuousDoubleAuctionEnv({"num_of_agents": 2, "is_render": False,
                                              "n_hist": n_hist})
            obs, _ = env.reset()
            # The default mode's width (grid since S3-15), n_hist times.
            expected = (n_hist * SNAPSHOT_DIM + PRIVATE_DIM,)
            assert SNAPSHOT_DIM == env.snapshot_dim
            for agent_id in env.agents:
                assert env.observation_spaces[agent_id].shape == expected
                assert obs[agent_id].shape == expected

    def test_agg_LOB_raw_still_book_sized(self):
        """The raw book used for action pricing must NOT gain the extra scalars."""
        env = self._make_env()
        assert env.agg_LOB_raw.shape == (BOOK_DIM,)
        self._insert(env, 'bid', 99, 10)
        env.set_agg_LOB()
        assert env.agg_LOB_raw.shape == (BOOK_DIM,)

    # ------------------------------------------------------------------
    # 2. log_mid correctness
    # ------------------------------------------------------------------

    def test_log_mid_two_sided_book(self):
        env = self._make_env()
        self._insert(env, 'bid', 98, 10)
        self._insert(env, 'ask', 102, 10)

        snap = env.set_agg_LOB()
        expected_M = (98 + 102) / 2.0
        assert float(snap[LOG_MID_IDX]) == pytest.approx(float(np.log(expected_M)) - env.log_mid_centre, abs=1e-5)

    def test_log_mid_bid_only_book_uses_last_price(self):
        """S3-14: a one-sided book is referenced to the last trade, not to its
        lone quote - otherwise that quote read exactly 0.0, like an absent
        level. Before 2026-09-18 this test expected log(47)."""
        env = self._make_env()
        env.last_price = 41.0
        self._insert(env, 'bid', 47, 10)

        snap = env.set_agg_LOB()
        assert float(snap[LOG_MID_IDX]) == pytest.approx(float(np.log(41.0)) - env.log_mid_centre, abs=1e-5)

    def test_log_mid_ask_only_book_uses_last_price(self):
        env = self._make_env()
        env.last_price = 41.0
        self._insert(env, 'ask', 63, 10)

        snap = env.set_agg_LOB()
        assert float(snap[LOG_MID_IDX]) == pytest.approx(float(np.log(41.0)) - env.log_mid_centre, abs=1e-5)

    def test_log_mid_one_sided_book_without_a_last_price_uses_the_quote(self):
        """The lone quote is still the reference when nothing has ever printed."""
        env = self._make_env()
        env.last_price = 0.0
        self._insert(env, 'ask', 63, 10)

        snap = env.set_agg_LOB()
        assert float(snap[LOG_MID_IDX]) == pytest.approx(float(np.log(63.0)) - env.log_mid_centre, abs=1e-5)

    def test_log_mid_empty_book_uses_last_price(self):
        env = self._make_env()
        env.last_price = 37.0

        snap = env.set_agg_LOB()
        assert float(snap[LOG_MID_IDX]) == pytest.approx(float(np.log(37.0)) - env.log_mid_centre, abs=1e-5)

    def test_log_mid_survives_non_positive_last_price(self):
        """M defaults to 100.0 when last_price is bad; log must stay finite."""
        env = self._make_env()
        env.last_price = 0.0

        snap = env.set_agg_LOB()
        assert float(snap[LOG_MID_IDX]) == pytest.approx(float(np.log(100.0)) - env.log_mid_centre, abs=1e-5)
        assert np.isfinite(snap).all()

    # ------------------------------------------------------------------
    # 3. log1p_spread_ticks correctness
    # ------------------------------------------------------------------

    def test_log1p_spread_two_sided_book(self):
        env = self._make_env()
        self._insert(env, 'bid', 98, 10)
        self._insert(env, 'ask', 102, 10)

        snap = env.set_agg_LOB()
        expected = np.log1p((102 - 98) / env.min_tick)
        assert float(snap[LOG1P_SPREAD_IDX]) == pytest.approx(float(expected), abs=1e-5)

    def test_log1p_spread_one_tick(self):
        """The tightest possible resting book maps to log1p(1) = 0.693..."""
        env = self._make_env()
        self._insert(env, 'bid', 100, 10)
        self._insert(env, 'ask', 101, 10)

        snap = env.set_agg_LOB()
        assert float(snap[LOG1P_SPREAD_IDX]) == pytest.approx(float(np.log1p(1.0)), abs=1e-5)

    def test_log1p_spread_is_monotonic_in_spread(self):
        values = []
        for ask in [101, 105, 120, 200]:
            env = self._make_env()
            self._insert(env, 'bid', 100, 10)
            self._insert(env, 'ask', ask, 10)
            values.append(float(env.set_agg_LOB()[LOG1P_SPREAD_IDX]))

        assert values == sorted(values)
        assert all(np.isfinite(values))

    # ------------------------------------------------------------------
    # 4. Sentinel semantics
    # ------------------------------------------------------------------

    def test_spread_sentinel_is_zero_when_not_two_sided(self):
        for side, price in [('bid', 90), ('ask', 110)]:
            env = self._make_env()
            self._insert(env, side, price, 10)
            snap = env.set_agg_LOB()
            assert float(snap[LOG1P_SPREAD_IDX]) == 0.0, \
                f"one-sided ({side}) book must use the 0.0 sentinel"

    def test_spread_sentinel_is_zero_on_empty_book(self):
        env = self._make_env()
        snap = env.set_agg_LOB()
        assert float(snap[LOG1P_SPREAD_IDX]) == 0.0

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
            assert value >= floor
            assert value > 0.0

    # ------------------------------------------------------------------
    # 5. Placement within the stacked observation
    # ------------------------------------------------------------------

    def test_scalars_present_in_every_frame_after_reset(self):
        """reset() pads the history with n_hist copies, so every frame carries them."""
        n_hist = 4
        env = continuousDoubleAuctionEnv({"num_of_agents": 2, "is_render": False,
                                          "n_hist": n_hist, "book_mode": "levels"})
        obs, _ = env.reset()
        stacked = obs["agent_0"]
        expected_log_mid = float(np.log(env.last_price)) - env.log_mid_centre

        for k in range(n_hist):
            frame = stacked[k * LEVELS_SNAPSHOT_DIM:(k + 1) * LEVELS_SNAPSHOT_DIM]
            assert frame.shape == (LEVELS_SNAPSHOT_DIM,)
            assert float(frame[LOG_MID_IDX]) == pytest.approx(expected_log_mid, abs=1e-5)
            assert float(frame[LOG1P_SPREAD_IDX]) == 0.0

    def test_book_block_slicing_unaffected(self):
        """Appending at the end must leave the existing block offsets valid."""
        env = self._make_env()
        self._insert(env, 'bid', 98, 10)
        self._insert(env, 'ask', 102, 10)

        snap = env.set_agg_LOB()
        bid_prices, bid_sizes = snap[0:10], snap[10:20]
        ask_prices, ask_sizes = snap[20:30], snap[30:40]

        # Both sides non-negative since S4-17: side is the block, not a sign.
        assert np.all(bid_prices >= 0)
        assert np.all(bid_sizes >= 0)
        assert np.all(ask_prices >= 0)
        assert np.all(ask_sizes >= 0)

    # ------------------------------------------------------------------
    # 6. Rollout safety
    # ------------------------------------------------------------------

    def test_no_nan_or_inf_across_random_rollout(self):
        env = continuousDoubleAuctionEnv({"num_of_agents": 3, "init_cash": 1_000_000,
                                          "is_render": False, "max_step": 32,
                                          "book_mode": "levels"})
        obs, _ = env.reset()
        for _ in range(20):
            actions = {a: env.action_spaces[a].sample() for a in env.agents}
            obs, _, _, _, _ = env.step(actions)
            for agent_id, vector in obs.items():
                assert np.isfinite(vector).all(), f"non-finite observation for {agent_id}"
                assert vector.shape == (env.n_hist * LEVELS_SNAPSHOT_DIM + PRIVATE_DIM,)
