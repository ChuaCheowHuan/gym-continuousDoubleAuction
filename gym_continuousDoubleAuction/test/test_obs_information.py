"""The observation carries the information a policy needs (issue #205).

The suite would have passed unchanged with the varying-denominator stack (S2-6), the
zero-collision ambiguity (S3-14) and the dead tape loop (S2-7) all present. Each fix brought
tests for its own defect; these are the general ones, written as questions a policy would put
to its input:

- do two different markets look different?
- do two different accounts look different?
- over a stretch of play, does each field that is meant to carry information actually move?

They run against the real env, in both book modes, and none of them names a defect: they
say what the observation must be able to tell apart.
"""

import numpy as np
import pytest

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.envs.exchg.state_helper import EXTRA_FIELDS

MODES = ["grid", "levels"]

#: The `category` action codes (action_helper._CATEGORY_MAP).
PASS, BUY_MKT, BUY_LMT, BUY_CANCEL, SELL_MKT, SELL_LMT = 0, 1, 2, 4, 5, 6


def _env(mode, agents=3, seed=7, **cfg):
    env = continuousDoubleAuctionEnv(
        {
            "num_of_agents": agents,
            "is_render": False,
            "max_step": 64,
            "initial_price_min": 100,
            "initial_price_max": 100,
            "book_mode": mode,
            **cfg,
        }
    )
    env.reset(seed=seed)
    return env


def _act(category, price=0, offset=1, mean=0.5, slot=0):
    return {
        "category": category,
        "size": np.array([mean], dtype=np.float32),
        "price": price,
        "price_offset": offset,
        "order_slot": slot,
    }


def _step(env, **by_agent):
    actions = {a: _act(PASS) for a in env.agents}
    actions.update({k: v for k, v in by_agent.items()})
    obs, *_ = env.step(actions)
    return obs


def _book(env, vec):
    """The newest frame's public book block."""
    start = (env.n_hist - 1) * env.snapshot_dim
    return np.asarray(vec[start : start + env.obs_book_dim])


def _private(env, vec):
    return dict(zip(env.private_fields, np.asarray(vec)[-env.private_dim :]))


@pytest.mark.parametrize("mode", MODES)
class TestDifferentMarketsLookDifferent:
    def test_an_empty_book_differs_from_one_with_a_resting_order(self, mode):
        quiet = _step(_env(mode))
        env = _env(mode)
        busy = _step(env, agent_0=_act(BUY_LMT))
        assert not np.array_equal(_book(env, quiet["agent_1"]), _book(env, busy["agent_1"]))

    @pytest.mark.parametrize("category", [BUY_LMT, SELL_LMT])
    def test_the_resting_price_changes_what_a_bystander_sees(self, mode, category):
        seen = set()
        for offset in (0, 1, 2):
            env = _env(mode)
            obs = _step(env, agent_0=_act(category, price=offset, offset=1))
            seen.add(_book(env, obs["agent_1"]).tobytes())
        assert len(seen) == 3, "three different quote prices gave fewer than three observations"

    def test_the_resting_size_changes_what_a_bystander_sees(self, mode):
        seen = set()
        for mean in (0.2, 0.5, 0.9):
            env = _env(mode)
            obs = _step(env, agent_0=_act(BUY_LMT, mean=mean))
            seen.add(_book(env, obs["agent_1"]).tobytes())
        assert len(seen) == 3

    def test_the_two_sides_of_the_book_are_distinguishable(self, mode):
        env_bid, env_ask = _env(mode), _env(mode)
        bid = _step(env_bid, agent_0=_act(BUY_LMT))["agent_1"]
        ask = _step(env_ask, agent_0=_act(SELL_LMT))["agent_1"]
        assert not np.array_equal(_book(env_bid, bid), _book(env_ask, ask))

    def test_a_trade_shows_up_in_the_flow_fields(self, mode):
        env = _env(mode)
        _step(env, agent_0=_act(SELL_LMT))  # a resting ask for others to hit
        obs = _step(env, agent_1=_act(BUY_MKT))
        frame = np.asarray(obs["agent_2"])[
            (env.n_hist - 1) * env.snapshot_dim : env.n_hist * env.snapshot_dim
        ]
        extras = dict(zip(EXTRA_FIELDS, frame[env.obs_book_dim :]))
        assert extras["log1p_trade_count"] > 0
        assert extras["trade_direction"] == 1.0  # initiated by the buyer
        assert extras["signed_volume"] > 0

    def test_a_cancelled_order_leaves_the_book_it_came_from(self, mode):
        env = _env(mode)
        empty = _step(env)["agent_1"]
        posted = _step(env, agent_0=_act(BUY_LMT))["agent_1"]
        gone = _step(env, agent_0=_act(BUY_CANCEL, slot=0))["agent_1"]
        assert not np.array_equal(_book(env, empty), _book(env, posted))
        assert np.array_equal(_book(env, empty), _book(env, gone))


@pytest.mark.parametrize("mode", MODES)
class TestDifferentAccountsLookDifferent:
    def test_a_trade_moves_both_counterparties_private_state_in_opposite_directions(self, mode):
        env = _env(mode)
        _step(env, agent_0=_act(SELL_LMT))
        before = {a: _private(env, _step(env)[a]) for a in ("agent_0", "agent_1")}
        obs = _step(env, agent_1=_act(BUY_MKT))
        after = {a: _private(env, obs[a]) for a in ("agent_0", "agent_1")}
        assert after["agent_1"]["position"] > before["agent_1"]["position"]
        assert after["agent_0"]["position"] < before["agent_0"]["position"]
        assert after["agent_1"]["cash"] < before["agent_1"]["cash"]
        # A short seller's proceeds are margin, not free cash: the change shows up in what
        # is held against the position, so the pair is what must differ.
        assert (after["agent_0"]["cash"], after["agent_0"]["cash_on_hold"]) != (
            before["agent_0"]["cash"],
            before["agent_0"]["cash_on_hold"],
        )

    def test_the_same_public_book_gives_different_private_blocks_to_different_agents(self, mode):
        env = _env(mode)
        obs = _step(env, agent_0=_act(BUY_LMT))
        assert np.array_equal(_book(env, obs["agent_1"]), _book(env, obs["agent_2"]))
        assert not np.array_equal(
            np.asarray(obs["agent_0"])[-env.private_dim :],
            np.asarray(obs["agent_1"])[-env.private_dim :],
        )
        assert _private(env, obs["agent_0"])["own_bid_count"] > 0
        assert _private(env, obs["agent_1"])["own_bid_count"] == 0

    def test_resting_collateral_is_visible_to_its_owner_only(self, mode):
        env = _env(mode)
        obs = _step(env, agent_0=_act(BUY_LMT, mean=0.9))
        assert _private(env, obs["agent_0"])["cash_on_hold"] > 0
        assert _private(env, obs["agent_1"])["cash_on_hold"] == 0


@pytest.mark.parametrize("mode", MODES)
class TestFieldsMoveOverPlay:
    """Under random play every field that is meant to carry information varies."""

    @pytest.fixture
    def observations(self, mode):
        import logging

        logging.disable(logging.CRITICAL)
        try:
            collected = []
            for seed in range(4):
                env = _env(mode, agents=4, seed=seed, max_step=80)
                obs = env.reset(seed=seed)[0]
                for _ in range(79):
                    obs, _, terminated, truncated, _ = env.step(
                        {a: env.action_spaces[a].sample() for a in obs}
                    )
                    if "agent_0" in obs:
                        collected.append(np.asarray(obs["agent_0"]))
                    if terminated.get("__all__") or truncated.get("__all__"):
                        break
        finally:
            logging.disable(logging.NOTSET)
        return env, np.array(collected)

    def test_every_market_level_scalar_moves(self, mode, observations):
        env, obs = observations
        newest = obs[:, (env.n_hist - 1) * env.snapshot_dim :][:, : env.snapshot_dim]
        for i, name in enumerate(EXTRA_FIELDS):
            column = newest[:, env.obs_book_dim + i]
            assert column.std() > 0, f"{name} never changed over {len(column)} observations"

    def test_every_account_field_moves(self, mode, observations):
        env, obs = observations
        private = dict(zip(env.private_fields, obs[:, -env.private_dim :].T))
        for name in (
            "position",
            "position_val",
            "cash",
            "cash_on_hold",
            "nav",
            "drawdown",
            "vwap_vs_mid",
            "realised_pnl",
            "time_left",
            "own_bid_count",
            "own_ask_count",
        ):
            assert private[name].std() > 0, f"{name} never changed"

    def test_the_book_block_is_not_mostly_dead(self, mode, observations):
        """At least half the newest frame's cells ever carry a value other than a constant.

        Measured 69% in `grid` (the cells far from the touch rarely fill) and 70% in
        `levels`; a layout that slid the book out of its slots would leave nearly all of it
        constant."""
        env, obs = observations
        book = obs[:, (env.n_hist - 1) * env.snapshot_dim :][:, : env.obs_book_dim]
        moving = np.count_nonzero(book.std(axis=0) > 0)
        assert moving >= 0.5 * env.obs_book_dim, f"{moving} of {env.obs_book_dim} cells ever move"

    def test_older_frames_are_not_copies_of_the_newest(self, mode, observations):
        env, obs = observations
        if env.n_hist < 2:
            pytest.skip("single-frame history")
        d = env.snapshot_dim
        oldest, newest = obs[:, :d], obs[:, (env.n_hist - 1) * d : env.n_hist * d]
        assert np.mean(np.all(oldest == newest, axis=1)) < 0.5

    def test_every_value_is_finite_and_inside_the_declared_bounds(self, mode, observations):
        env, obs = observations
        low, high = env.observation_bounds()
        assert np.isfinite(obs).all()
        assert (obs >= low).all() and (obs <= high).all()
