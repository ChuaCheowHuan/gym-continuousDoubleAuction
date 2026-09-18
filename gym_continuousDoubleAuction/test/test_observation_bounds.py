"""The observation Box has finite, measured bounds, and a clip is counted.

doc/15 S4-15. The space used to be `Box(-inf, inf)`: a true statement about
nothing, which disabled RLlib's space checks and observation filters. Every
feature is a ratio, a log or a tanh with a known or measured range, so the
bounds now come from `observation_bounds` in tunable_constants.json, the
emitted vector is clipped to them, and the number of clipped elements is
`num_obs_clipped_step` in `info` and the episode record. A bound is a claim
about the market; the counter is what makes a wrong claim visible.

Two things these tests pin that the first smoke test got wrong: an older
frame's price row can be negative, because the whole stack is normalised by
the newest frame's midpoint (doc/05 section 2.2), so a bid resting above
`M_t` reads `(M_t - P) / M_t < 0` and must not be clipped away; and the
counter must be 0 on ordinary play, since every measured value sits inside
the bounds with headroom (doc/16 section 16.22).
"""
import numpy as np
import pytest

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.envs.exchg import state_helper
from gym_continuousDoubleAuction.envs.exchg.state_helper import (
    BOOK_ROW_ORDER,
    EXTRA_FIELDS,
)
from gym_continuousDoubleAuction.train.episode_record import INFO_COLUMNS


def _env(**overrides):
    config = {
        "num_of_agents": 2,
        "max_step": 40,
        "is_render": False,
        "initial_price_min": 100,
        "initial_price_max": 100,
    }
    config.update(overrides)
    config.setdefault("book_mode", "levels")
    env = continuousDoubleAuctionEnv(config)
    env.reset(seed=1)
    return env


def _pass(env):
    return {agent: {"category": 0, "order_slot": 0, "price": 0, "price_offset": 1,
                    "size_mean": np.zeros(1, dtype=np.float32),
                    "size_sigma": np.zeros(1, dtype=np.float32)}
            for agent in env.agents}


class TestTheSpace:

    def test_bounds_are_finite_and_ordered(self):
        env = _env()
        space = env.observation_spaces["agent_0"]
        assert np.isfinite(space.low).all()
        assert np.isfinite(space.high).all()
        assert (space.low < space.high).all()
        assert space.shape == (env.n_hist * env.snapshot_dim + env.private_dim,)

    def test_every_agent_shares_the_bounds(self):
        env = _env(num_of_agents=3)
        first = env.observation_spaces["agent_0"]
        for agent in env.agents:
            assert np.array_equal(env.observation_spaces[agent].low, first.low)
            assert np.array_equal(env.observation_spaces[agent].high, first.high)

    def test_the_layout_of_the_bounds_matches_the_vector(self):
        """Each book row's bound repeats k_rows times per frame, the extras
        once, and the private block follows the last frame."""
        env = _env()
        cfg = state_helper.constants("observation_bounds")
        cells = env.obs_book_cells
        assert env.obs_book_rows == BOOK_ROW_ORDER  # this env is in `levels` mode
        for frame in range(env.n_hist):
            base = frame * env.snapshot_dim
            for r, row in enumerate(env.obs_book_rows):
                lo, hi = cfg["book"][row]
                sl = slice(base + r * cells, base + (r + 1) * cells)
                assert (env.obs_low[sl] == np.float32(lo)).all(), row
                assert (env.obs_high[sl] == np.float32(hi)).all(), row
            for e, name in enumerate(EXTRA_FIELDS):
                lo, hi = cfg["extra"][name]
                assert env.obs_low[base + env.obs_book_dim + e] == np.float32(lo), name
                assert env.obs_high[base + env.obs_book_dim + e] == np.float32(hi), name
        tail_low = env.obs_low[-env.private_dim:]
        tail_high = env.obs_high[-env.private_dim:]
        for i, name in enumerate(env.private_fields):
            key = ("own_size" if name.startswith("own_bid_size") or name.startswith("own_ask_size")
                   else "own_count" if name.endswith("_count")
                   else "action_mask" if name.startswith("can_") else name)
            lo, hi = cfg["private"][key]
            assert tail_low[i] == np.float32(lo), name
            assert tail_high[i] == np.float32(hi), name

    def test_identity_bounds_are_exact(self):
        """The sides that are mathematics, not measurement."""
        cfg = state_helper.constants("observation_bounds")
        assert cfg["book"]["bid_price"][1] == 1.0     # (M - P) / M < 1 for P > 0
        assert cfg["book"]["ask_price"][0] == -1.0    # (P - M) / M > -1 for P > 0
        for row in ("bid_size", "ask_size"):
            assert cfg["book"][row][0] == 0.0
        assert cfg["extra"]["trade_direction"] == [-1.0, 1.0]
        assert cfg["extra"]["mid_return"][0] == -1.0  # M_t / M_prev - 1 > -1
        assert cfg["private"]["position"] == [-1.0, 1.0]
        assert cfg["private"]["time_left"] == [0.0, 1.0]
        assert cfg["private"]["drawdown"][1] == 0.0
        assert cfg["private"]["vwap_vs_mid"][1] == 1.0
        assert cfg["private"]["own_count"] == [0.0, 1.0]
        assert cfg["private"]["unmatched_last_step"] == [0.0, 1.0]

    def test_a_field_without_a_bound_fails_at_construction(self, monkeypatch):
        env = _env()
        cfg = state_helper.constants("observation_bounds")
        broken = {"book": dict(cfg["book"]), "extra": dict(cfg["extra"]),
                  "private": dict(cfg["private"])}
        del broken["private"]["nav"]
        monkeypatch.setattr(state_helper, "constants", lambda group: broken)
        with pytest.raises(ValueError, match="'nav'"):
            env.observation_bounds()

    def test_a_non_interval_fails_at_construction(self, monkeypatch):
        env = _env()
        cfg = state_helper.constants("observation_bounds")
        broken = {"book": dict(cfg["book"]), "extra": dict(cfg["extra"]),
                  "private": dict(cfg["private"])}
        broken["book"]["bid_size"] = [8.0, 0.0]
        monkeypatch.setattr(state_helper, "constants", lambda group: broken)
        with pytest.raises(ValueError, match="bid_size"):
            env.observation_bounds()


class TestEmission:

    def test_every_observation_is_inside_the_space(self):
        env = _env(num_of_agents=4, max_step=60)
        space = env.observation_spaces["agent_0"]
        obs, _ = env.reset(seed=3)
        for o in obs.values():
            assert space.contains(o)
        while True:
            obs, _, dones, truncs, infos = env.step(
                {agent: env.action_spaces[agent].sample() for agent in env.agents}
            )
            for agent, o in obs.items():
                assert space.contains(o), agent
            if dones["__all__"] or truncs["__all__"]:
                break

    def test_ordinary_play_clips_nothing(self):
        """The bounds carry headroom over everything measured, so the counter
        is 0 on every step of a short random episode."""
        env = _env(num_of_agents=4, max_step=60)
        env.reset(seed=5)
        while True:
            _, _, dones, truncs, infos = env.step(
                {agent: env.action_spaces[agent].sample() for agent in env.agents}
            )
            for agent, info in infos.items():
                assert info["num_obs_clipped_step"] == 0, agent
            if dones["__all__"] or truncs["__all__"]:
                break

    def test_an_older_frame_may_read_negative_and_is_not_clipped(self):
        """A bid resting above the newest midpoint reads below zero in the
        frame it was seen in. The first [0, 1] bid_price bound clipped exactly
        this; the bound is now signed on that side."""
        env = _env()
        a, b = env.traders
        # Frame 1: bid 98 / ask 102, M = 100.
        a.place_order('limit', 'bid', 10, 98.0, env.LOB, env.traders)
        b.place_order('limit', 'ask', 10, 102.0, env.LOB, env.traders)
        env.step(_pass(env))
        # Frame 2: a bid at 80 and an ask at 82 that lifts the 98 bid, so the
        # book is bid 80 / ask 102 and M = 91 while frame 1 still shows 98.
        a.place_order('limit', 'bid', 10, 80.0, env.LOB, env.traders)
        b.place_order('limit', 'ask', 10, 82.0, env.LOB, env.traders)
        obs, _, _, _, infos = env.step(_pass(env))
        stacked = obs["agent_0"]
        older = stacked[(env.n_hist - 2) * env.snapshot_dim:(env.n_hist - 1) * env.snapshot_dim]
        newest = stacked[(env.n_hist - 1) * env.snapshot_dim:env.n_hist * env.snapshot_dim]
        assert older[0] < 0, "the 98 bid, measured against M_t = 91, is above the midpoint"
        assert older[0] == pytest.approx((91 - 98) / 91, abs=1e-5)
        assert newest[0] == pytest.approx((91 - 80) / 91, abs=1e-5)
        assert infos["agent_0"]["num_obs_clipped_step"] == 0

    def test_a_clip_is_counted_and_reported(self):
        """Tighten one bound below what the market produces and the excess is
        clipped, counted in `info`, and the vector still sits in the space."""
        env = _env()
        a, b = env.traders
        a.place_order('limit', 'bid', 10, 98.0, env.LOB, env.traders)
        b.place_order('limit', 'ask', 10, 102.0, env.LOB, env.traders)
        # `time_left` sits near 1.0 early in the episode; cap it at 0.5.
        idx = -env.private_dim + env.private_fields.index("time_left")
        env.obs_high = env.obs_high.copy()
        env.obs_high[idx] = 0.5
        obs, _, _, _, infos = env.step(_pass(env))
        for agent in env.agents:
            assert obs[agent][idx] == np.float32(0.5)
            assert infos[agent]["num_obs_clipped_step"] == 1
            assert (obs[agent] <= env.obs_high).all()
            assert (obs[agent] >= env.obs_low).all()

    def test_the_counter_is_per_step(self):
        """Assigned each step, not accumulated: one clipped step, then none."""
        env = _env()
        idx = -env.private_dim + env.private_fields.index("time_left")
        high = env.obs_high.copy()
        env.obs_high = high.copy()
        env.obs_high[idx] = 0.5
        _, _, _, _, infos = env.step(_pass(env))
        assert infos["agent_0"]["num_obs_clipped_step"] == 1
        env.obs_high = high
        _, _, _, _, infos = env.step(_pass(env))
        assert infos["agent_0"]["num_obs_clipped_step"] == 0

    def test_the_counter_has_a_record_column(self):
        assert ("num_obs_clipped_step", "int64") in INFO_COLUMNS
