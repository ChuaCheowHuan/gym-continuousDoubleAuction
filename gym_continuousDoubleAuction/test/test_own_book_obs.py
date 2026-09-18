"""Phase 1 of doc/15 S3-24: the agent can see its own resting orders.

The private block gains an own-book block - this agent's resting size at each
of the k_rows public levels on each side, on the public book's scale and sign
convention - then its order counts per side, then the dead-action flag of
phase 3. Level k of the own book is level k of the public book in the same
snapshot, which is what lets the tokenising encoders carry it as two extra
channels of each level token (test_encoder_registry covers that half).
"""
import numpy as np

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.envs.exchg.state_helper import (
    BASE_PRIVATE_FIELDS,
    OBSERVATION_LAYOUT_VERSION,
    OWN_BOOK_OFFSET,
    PRIVATE_FIELDS,
    own_book_fields,
    private_fields,
)


def _env(agents=2, **cfg):
    env = continuousDoubleAuctionEnv({
        "num_of_agents": agents, "is_render": False, "max_step": 64,
        "initial_price_min": 100, "initial_price_max": 100, **cfg,
    })
    env.reset(seed=7)
    return env


def _act(category, price=0, offset=1, mean=0.5, slot=0):
    return {
        "category": category,
        "size_mean": np.array([mean], dtype=np.float32),
        "size_sigma": np.array([0.0], dtype=np.float32),
        "price": price,
        "price_offset": offset,
        "order_slot": slot,
    }


_PASS = _act(0)


def _private(env, obs, agent="agent_0"):
    tail = obs[agent][-env.private_dim:]
    return dict(zip(env.private_fields, tail))


class TestLayout:

    def test_field_list_shape(self):
        k = 10
        fields = private_fields(k)
        assert fields[:9] == BASE_PRIVATE_FIELDS
        assert fields[9:9 + k] == own_book_fields(k)[:k]
        assert fields[9 + k:9 + 2 * k] == own_book_fields(k)[k:]
        assert fields[-3:] == ("own_bid_count", "own_ask_count", "unmatched_last_step")
        assert len(fields) == 32 == len(PRIVATE_FIELDS)
        assert OWN_BOOK_OFFSET == 9
        assert fields[OWN_BOOK_OFFSET] == "own_bid_size_0"

    def test_env_declares_the_width(self):
        env = _env()
        assert env.private_dim == 32
        assert env.observation_spaces["agent_0"].shape == (4 * 46 + 32,)
        assert OBSERVATION_LAYOUT_VERSION == 2

    def test_reset_shows_an_empty_own_book(self):
        env = _env()
        obs, _ = env.reset(seed=1)
        p = _private(env, obs)
        for name in own_book_fields(env.k_rows) + ("own_bid_count", "own_ask_count",
                                                   "unmatched_last_step"):
            assert p[name] == 0.0, name


class TestOwnSizes:

    def test_own_bid_at_the_touch(self):
        env = _env()
        # agent_0 posts a bid at level 0 (ghost: anchor - 1 tick), agent_1 passes.
        obs, _, _, _, _ = env.step({"agent_0": _act(2), "agent_1": _PASS})
        p0 = _private(env, obs, "agent_0")
        p1 = _private(env, obs, "agent_1")
        qty = int(env.LOB.bids.volume)
        expected = np.sqrt(qty / env.limit_max_size)
        assert p0["own_bid_size_0"] == np.float32(expected)
        # The public book shows the same level to both; only agent_0 owns it.
        assert p1["own_bid_size_0"] == 0.0
        assert p0["own_bid_count"] == np.float32(1 / env.max_own_orders)
        assert p1["own_bid_count"] == 0.0

    def test_own_ask_is_negative_like_the_public_book(self):
        env = _env()
        obs, _, _, _, _ = env.step({"agent_0": _act(6), "agent_1": _PASS})
        p0 = _private(env, obs)
        assert p0["own_ask_size_0"] < 0
        book = obs["agent_0"][-env.private_dim - env.snapshot_dim:-env.private_dim]
        # Same magnitude as the public ask size at level 0 (only one order there).
        public_ask_size_0 = book[3 * env.k_rows]
        assert p0["own_ask_size_0"] == public_ask_size_0

    def test_levels_are_aligned_with_the_public_book(self):
        """Two agents at different levels: each sees only its own, at its level."""
        env = _env()
        # agent_0 bids level 0 join; agent_1 bids one tick below (level 0, passive).
        obs, _, _, _, _ = env.step({"agent_0": _act(2, 0, 1), "agent_1": _act(2, 0, 0)})
        assert len(env.LOB.bids.price_map) == 2
        p0, p1 = _private(env, obs, "agent_0"), _private(env, obs, "agent_1")
        assert p0["own_bid_size_0"] > 0 and p0["own_bid_size_1"] == 0
        assert p1["own_bid_size_0"] == 0 and p1["own_bid_size_1"] > 0

    def test_orders_beyond_the_shown_depth_are_in_the_count_only(self):
        env = _env()
        trader = env.traders[0]
        for i in range(env.k_rows + 2):
            trader.place_order('limit', 'bid', 1, 90 - i, env.LOB, env.traders)
        own_bid, own_ask, n_bid, n_ask = env.own_book(trader)
        assert n_bid == env.k_rows + 2
        assert np.count_nonzero(own_bid) == env.k_rows
        # Count saturates at the cap in the observation.
        obs, _, _, _, _ = env.step({a: _PASS for a in env.agents})
        assert _private(env, obs)["own_bid_count"] == 1.0

    def test_cancel_clears_it(self):
        env = _env()
        env.step({"agent_0": _act(2), "agent_1": _PASS})
        obs, _, _, _, _ = env.step({"agent_0": _act(4, slot=0), "agent_1": _PASS})
        p = _private(env, obs)
        assert p["own_bid_size_0"] == 0.0 and p["own_bid_count"] == 0.0


class TestDeadActionFlag:

    def test_flag_is_set_on_the_step_of_the_miss_and_cleared_after(self):
        env = _env()
        obs, _, _, _, infos = env.step({"agent_0": _act(4, slot=1), "agent_1": _PASS})
        assert infos["agent_0"]["num_unmatched_step"] == 1
        assert _private(env, obs)["unmatched_last_step"] == 1.0
        assert _private(env, obs, "agent_1")["unmatched_last_step"] == 0.0
        obs, _, _, _, _ = env.step({a: _PASS for a in env.agents})
        assert _private(env, obs)["unmatched_last_step"] == 0.0

    def test_a_hit_does_not_set_it(self):
        env = _env()
        env.step({"agent_0": _act(2), "agent_1": _PASS})
        obs, _, _, _, _ = env.step({"agent_0": _act(4, slot=1), "agent_1": _PASS})
        assert _private(env, obs)["unmatched_last_step"] == 0.0
