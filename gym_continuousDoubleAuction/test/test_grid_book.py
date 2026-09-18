"""The fixed tick-offset grid shared by observation and action (S3-15).

doc/15 S3-15. In the `levels` layout slot k meant "the k-th occupied price",
whose distance from the market wandered - measured under random play the best
level sat 3.8 +- 2.5 ticks from the reference and its price changed on 35-54%
of steps, and the action's price code j landed anywhere from 0 to 20 ticks out
(doc/16 section 16.24). In the `grid` layout, the default since 2026-09-18,
cell c of each size row is the price `R + (c - k_rows) * tick` where `R` is
the reference price snapped to the tick, and the action's price code j quotes
exactly j ticks from `R` on the passive side. Same cell, same distance, on
every step and in every frame of the stack.
"""
import numpy as np
import pytest

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.envs.exchg.state_helper import (
    BOOK_DIM,
    GRID_ROWS,
    OBSERVATION_LAYOUT_VERSION,
    obs_book_cells,
    obs_book_rows,
    obs_row_slice,
)
from gym_continuousDoubleAuction.train.model.encoders.obs_layout import ObsLayout


def _env(**overrides):
    config = {
        "num_of_agents": 2,
        "max_step": 40,
        "is_render": False,
        "initial_price_min": 100,
        "initial_price_max": 100,
        "book_mode": "grid",
    }
    config.update(overrides)
    env = continuousDoubleAuctionEnv(config)
    env.reset(seed=1)
    return env


def _pass(env):
    return {agent: {"category": 0, "order_slot": 0, "price": 0, "price_offset": 1,
                    "size_mean": np.zeros(1, dtype=np.float32),
                    "size_sigma": np.zeros(1, dtype=np.float32)}
            for agent in env.agents}


def _frame(env, obs, index=-1, agent="agent_0"):
    """Snapshot `index` of the stack (-1 = newest) as a (rows, cells) grid."""
    o = obs[agent]
    i = env.n_hist + index if index < 0 else index
    snap = o[i * env.snapshot_dim:(i + 1) * env.snapshot_dim]
    return snap[:env.obs_book_dim].reshape(len(env.obs_book_rows), env.obs_book_cells), snap[env.obs_book_dim:]


BID, ASK = GRID_ROWS.index("bid_size"), GRID_ROWS.index("ask_size")


class TestLayout:

    def test_shape_and_version(self):
        env = _env()
        k = env.k_rows
        assert env.book_mode == "grid"
        assert env.obs_book_rows == ("bid_size", "ask_size")
        assert env.obs_book_cells == 2 * k + 1
        assert env.snapshot_dim == 2 * (2 * k + 1) + env.extra_dim
        assert env.observation_spaces["agent_0"].shape == (env.n_hist * env.snapshot_dim + env.private_dim,)
        # The raw snapshot the price logic reads is still the six-row levels frame.
        assert env.agg_LOB_raw.shape == (BOOK_DIM,)
        assert OBSERVATION_LAYOUT_VERSION == 5

    def test_module_helpers_agree(self):
        assert obs_book_rows("grid") == GRID_ROWS
        assert obs_book_cells("grid", 10) == 21
        assert obs_book_cells("levels", 10) == 10
        assert obs_row_slice("ask_size", "grid", 10) == slice(21, 42)
        assert obs_row_slice("ask_size", "levels", 10) == slice(30, 40)
        with pytest.raises(ValueError, match="book_mode"):
            obs_book_rows("ladder")

    def test_the_other_mode_is_a_config_key(self):
        env = _env(book_mode="levels")
        assert env.book_mode == "levels" and env.obs_book_cells == env.k_rows
        assert env.snapshot_dim == 6 * env.k_rows + env.extra_dim


class TestCells:

    def test_a_quote_sits_in_the_cell_of_its_tick_offset(self):
        """Bid 97 and ask 102 around M = 99.5 -> R = 100: cells k-3 and k+2."""
        env = _env()
        a, b = env.traders
        a.place_order('limit', 'bid', 10, 97.0, env.LOB, env.traders)
        b.place_order('limit', 'ask', 10, 102.0, env.LOB, env.traders)
        obs, *_ = env.step(_pass(env))
        k = env.k_rows
        grid, _ = _frame(env, obs)
        assert env.reference_price() == 100.0
        expected = np.sqrt(10 / env.limit_max_size)
        assert grid[BID][k - 3] == pytest.approx(expected, rel=1e-6)
        assert grid[ASK][k + 2] == pytest.approx(expected, rel=1e-6)
        assert np.count_nonzero(grid) == 2

    def test_same_price_same_cell_in_every_frame(self):
        """The S2-6 property, in grid coordinates: a resting order that has not
        moved sits in the same cell of every frame, because every frame is
        gridded against the NEWEST reference."""
        env = _env()
        a, b = env.traders
        a.place_order('limit', 'bid', 10, 97.0, env.LOB, env.traders)
        b.place_order('limit', 'ask', 10, 103.0, env.LOB, env.traders)  # R = 100
        env.step(_pass(env))
        # Move the reference: a new best ask at 101 makes M = 99, R = 99.
        b.place_order('limit', 'ask', 10, 101.0, env.LOB, env.traders)
        obs, *_ = env.step(_pass(env))
        k = env.k_rows
        assert env.reference_price() == 99.0
        newest, _ = _frame(env, obs, -1)
        older, _ = _frame(env, obs, -2)
        # The 97 bid is 2 ticks below the new reference in BOTH frames.
        assert newest[BID][k - 2] > 0 and older[BID][k - 2] > 0
        assert newest[BID][k - 3] == 0 and older[BID][k - 3] == 0

    def test_a_level_outside_the_window_is_not_shown(self):
        env = _env()
        a, b = env.traders
        k = env.k_rows
        a.place_order('limit', 'bid', 10, 99.0, env.LOB, env.traders)
        b.place_order('limit', 'ask', 10, 101.0, env.LOB, env.traders)   # R = 100
        b.place_order('limit', 'ask', 10, 100.0 + k + 5, env.LOB, env.traders)  # k+5 ticks out
        obs, *_ = env.step(_pass(env))
        grid, _ = _frame(env, obs)
        assert np.count_nonzero(grid[ASK]) == 1  # the far ask is beyond the window
        # It is still in the raw frame the price logic reads.
        assert (env.agg_LOB_raw[2 * k:3 * k] == 100.0 + k + 5).any()

    def test_sizes_at_one_price_aggregate(self):
        env = _env()
        a, b = env.traders
        a.place_order('limit', 'bid', 10, 98.0, env.LOB, env.traders)
        b.place_order('limit', 'bid', 30, 98.0, env.LOB, env.traders)
        obs, *_ = env.step(_pass(env))
        grid, _ = _frame(env, obs)
        k = env.k_rows
        # One-sided with no print: the reference is the lone quote itself, cell k.
        assert env.reference_price() == 98.0 or env.mid_price() == float(env.last_price)
        cell = k + int(round((98.0 - env.reference_price()) / env.min_tick))
        assert grid[BID][cell] == pytest.approx(np.sqrt(40 / env.limit_max_size), rel=1e-6)

    def test_every_observation_is_inside_the_space(self):
        env = _env(num_of_agents=4, max_step=40)
        space = env.observation_spaces["agent_0"]
        while True:
            obs, _, dones, truncs, infos = env.step(
                {agent: env.action_spaces[agent].sample() for agent in env.agents}
            )
            for agent, o in obs.items():
                assert space.contains(o), agent
                assert infos[agent]["num_obs_clipped_step"] == 0
            if dones["__all__"] or truncs["__all__"]:
                break


class TestSharedCoordinate:

    def test_price_code_j_is_j_ticks_from_the_reference(self):
        """The action's coordinate is the observation's: no ghost logic, no
        dependence on what is resting."""
        env = _env()
        a, b = env.traders
        a.place_order('limit', 'bid', 10, 99.0, env.LOB, env.traders)
        b.place_order('limit', 'ask', 10, 101.0, env.LOB, env.traders)
        env.set_agg_LOB()
        tick = env.min_tick
        R = env.reference_price()
        for j in range(env.k_rows):
            assert env._set_price(tick, 'bid', j, 1) == pytest.approx(R - j * tick)
            assert env._set_price(tick, 'ask', j, 1) == pytest.approx(R + j * tick)
            # The offset head still shades by one tick either way.
            assert env._set_price(tick, 'bid', j, 2) == pytest.approx(R - j * tick + tick)
            assert env._set_price(tick, 'ask', j, 0) == pytest.approx(R + j * tick + tick)

    def test_the_same_code_lands_at_the_same_distance_whatever_rests(self):
        """The S3-15 property. In `levels` mode the same code lands on
        whichever price happens to be the j-th occupied one."""
        env = _env()
        a, b = env.traders
        env.last_price = 100.0
        env.set_agg_LOB()
        before = env._set_price(env.min_tick, 'bid', 3, 1)
        a.place_order('limit', 'bid', 10, 99.0, env.LOB, env.traders)
        a.place_order('limit', 'bid', 10, 95.0, env.LOB, env.traders)
        b.place_order('limit', 'ask', 10, 101.0, env.LOB, env.traders)
        env.set_agg_LOB()
        after = env._set_price(env.min_tick, 'bid', 3, 1)
        assert before == after == 97.0

    def test_a_placed_order_lands_in_the_cell_its_code_names(self):
        """Round trip: quote with code j, see it in cell k - j."""
        env = _env()
        a, b = env.traders
        a.place_order('limit', 'bid', 10, 99.0, env.LOB, env.traders)
        b.place_order('limit', 'ask', 10, 101.0, env.LOB, env.traders)  # R = 100
        act = _pass(env)
        act["agent_0"] = {"category": 2, "order_slot": 0, "price": 4, "price_offset": 1,
                          "size_mean": np.array([0.5], dtype=np.float32),
                          "size_sigma": np.zeros(1, dtype=np.float32)}
        obs, *_ = env.step(act)
        k = env.k_rows
        grid, _ = _frame(env, obs)
        assert grid[BID][k - 4] > 0
        assert env.LOB_actions[0]["price"] == 96.0 or env.LOB_actions[1]["price"] == 96.0

    def test_own_block_is_aligned_with_the_grid(self):
        env = _env()
        a, b = env.traders
        a.place_order('limit', 'bid', 10, 99.0, env.LOB, env.traders)
        b.place_order('limit', 'ask', 10, 101.0, env.LOB, env.traders)  # R = 100
        a.place_order('limit', 'bid', 20, 96.0, env.LOB, env.traders)   # 4 ticks below
        obs, *_ = env.step(_pass(env))
        private = dict(zip(env.private_fields, obs["agent_0"][-env.private_dim:]))
        assert private["own_bid_size_1"] == pytest.approx(np.sqrt(10 / env.limit_max_size), rel=1e-6)
        assert private["own_bid_size_4"] == pytest.approx(np.sqrt(20 / env.limit_max_size), rel=1e-6)
        assert private["own_ask_size_1"] == 0.0  # the 101 ask is agent_1's
        p1 = dict(zip(env.private_fields, obs["agent_1"][-env.private_dim:]))
        assert p1["own_ask_size_1"] == pytest.approx(np.sqrt(10 / env.limit_max_size), rel=1e-6)


class TestEncoderLayout:

    def test_from_obs_space_reads_the_grid(self):
        env = _env()
        layout = ObsLayout.from_obs_space(env.observation_spaces["agent_0"])
        assert layout.book_mode == "grid"
        assert layout.book_rows == 2 and layout.k_rows == 2 * env.k_rows + 1
        assert layout.own_levels == env.k_rows
        assert layout.flat_dim == env.observation_spaces["agent_0"].shape[0]
        assert layout.row_slice("ask_size") == slice(layout.k_rows, 2 * layout.k_rows)

    def test_from_obs_space_reads_the_other_mode_too(self):
        env = _env(book_mode="levels")
        layout = ObsLayout.from_obs_space(env.observation_spaces["agent_0"])
        assert layout.book_mode == "levels" and layout.book_rows == 6
        explicit = ObsLayout.from_obs_space(env.observation_spaces["agent_0"], book_mode="levels")
        assert explicit == layout
        with pytest.raises(ValueError, match="any book mode"):
            ObsLayout.from_obs_space(env.observation_spaces["agent_0"], book_mode="grid")
