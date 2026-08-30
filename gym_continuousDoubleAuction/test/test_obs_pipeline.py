"""One normaliser per stack, and an observation that can see executions.

Two findings, fixed together because both live in how a frame becomes part of
the emitted observation.

**doc/15 S2-6.** `obs_history` used to hold frames that had each already been
normalised by their own midpoint, so frames t-3..t carried denominators
M_{t-3}..M_t and could not meaningfully be differenced - which is the entire
purpose of stacking them. A bid resting at 90 while the midpoint moved 100 ->
96 read 0.100 in one frame and 0.063 in the next; the order had not moved, its
denominator had. The deque now holds raw frames and the whole stack is
normalised once, at emission, by M_t.

**doc/15 S2-7.** `set_agg_LOB` iterated the tape, incremented a counter and
discarded it - the loop body a commented-out `write` copy-pasted from
`OrderBook.__str__` - so the observation carried *no* information about
executions: no last traded price, no direction, no signed volume, no trade
count. In a continuous double auction aggressive order flow is the most
predictive public signal there is.
"""
import numpy as np
import pytest

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.envs.exchg.state_helper import (
    EXTRA_FIELDS,
)


def _env(**overrides):
    config = {
        "num_of_agents": 2,
        "max_step": 50,
        "is_render": False,
        "initial_price_min": 100,
        "initial_price_max": 100,
    }
    config.update(overrides)
    env = continuousDoubleAuctionEnv(config)
    env.reset(seed=1)
    return env


def _frames(env, stacked):
    """The stacked observation split back into its snapshots, oldest first."""
    return [
        stacked[i * env.snapshot_dim:(i + 1) * env.snapshot_dim]
        for i in range(env.n_hist)
    ]


def _scalar(env, frame, name):
    return float(frame[env.book_dim + EXTRA_FIELDS.index(name)])


class TestOneNormaliserForTheWholeStack:
    def test_a_fixed_price_does_not_appear_to_move(self):
        """The exact case S2-6 is about."""
        env = _env()
        a, b = env.traders

        a.place_order('limit', 'bid', 10, 90.0, env.LOB, env.traders)
        b.place_order('limit', 'ask', 10, 110.0, env.LOB, env.traders)
        env.prep_next_state()                       # midpoint 100

        b.place_order('limit', 'ask', 10, 102.0, env.LOB, env.traders)
        stacked = env.prep_next_state()             # midpoint 96

        frames = _frames(env, stacked)
        # The two newest frames both hold the same resting bid at 90.
        assert frames[-1][0] == pytest.approx(frames[-2][0], abs=1e-6)
        assert frames[-1][0] == pytest.approx((96.0 - 90.0) / 96.0, abs=1e-5)

    def test_the_midpoint_move_is_still_visible(self):
        """Sharing a denominator must not hide that it moved."""
        env = _env()
        a, b = env.traders

        a.place_order('limit', 'bid', 10, 90.0, env.LOB, env.traders)
        b.place_order('limit', 'ask', 10, 110.0, env.LOB, env.traders)
        env.prep_next_state()
        b.place_order('limit', 'ask', 10, 102.0, env.LOB, env.traders)
        stacked = env.prep_next_state()

        frames = _frames(env, stacked)
        assert _scalar(env, frames[-1], "log_mid") != pytest.approx(
            _scalar(env, frames[-2], "log_mid"), abs=1e-6)
        assert _scalar(env, frames[-1], "mid_return") == pytest.approx(
            96.0 / 100.0 - 1.0, abs=1e-5)

    def test_each_frame_keeps_its_own_price_level(self):
        """`log_mid` is per-frame; only the price *denominator* is shared."""
        env = _env()
        a, b = env.traders
        a.place_order('limit', 'bid', 10, 90.0, env.LOB, env.traders)
        b.place_order('limit', 'ask', 10, 110.0, env.LOB, env.traders)
        env.prep_next_state()
        b.place_order('limit', 'ask', 10, 102.0, env.LOB, env.traders)
        stacked = env.prep_next_state()

        frames = _frames(env, stacked)
        assert _scalar(env, frames[-2], "log_mid") == pytest.approx(
            float(np.log(100.0)) - env.log_mid_centre, abs=1e-5)
        assert _scalar(env, frames[-1], "log_mid") == pytest.approx(
            float(np.log(96.0)) - env.log_mid_centre, abs=1e-5)

    def test_mid_return_is_zero_on_the_first_frame(self):
        """No previous midpoint reads the same as a midpoint that did not move."""
        env = _env()
        obs, _ = env.reset(seed=1)
        frames = _frames(env, obs["agent_0"][:env.n_hist * env.snapshot_dim])

        for frame in frames:
            assert _scalar(env, frame, "mid_return") == 0.0

    def test_the_history_holds_raw_frames(self):
        """The representation the fix depends on, asserted directly."""
        env = _env()
        a, b = env.traders
        a.place_order('limit', 'bid', 10, 90.0, env.LOB, env.traders)
        b.place_order('limit', 'ask', 10, 110.0, env.LOB, env.traders)
        env.prep_next_state()

        newest = env.obs_history[-1]
        assert float(newest[0]) == pytest.approx(90.0), (
            "the deque must hold the raw price, not a normalised one"
        )


class TestTheObservationCanSeeExecutions:
    def test_every_named_scalar_is_built(self):
        env = _env()
        assert env.extra_dim == len(EXTRA_FIELDS)

    def test_a_buy_initiated_trade_is_signed_positive(self):
        env = _env()
        a, b = env.traders
        b.place_order('limit', 'ask', 10, 100.0, env.LOB, env.traders)
        env.prep_next_state()

        a.place_order('limit', 'bid', 10, 100.0, env.LOB, env.traders)
        stacked = env.prep_next_state()

        newest = _frames(env, stacked)[-1]
        assert _scalar(env, newest, "signed_volume") > 0
        assert _scalar(env, newest, "trade_direction") == 1.0
        assert _scalar(env, newest, "log1p_trade_count") == pytest.approx(
            float(np.log1p(1.0)), abs=1e-5)

    def test_a_sell_initiated_trade_is_signed_negative(self):
        env = _env()
        a, b = env.traders
        a.place_order('limit', 'bid', 10, 100.0, env.LOB, env.traders)
        env.prep_next_state()

        b.place_order('limit', 'ask', 10, 100.0, env.LOB, env.traders)
        stacked = env.prep_next_state()

        newest = _frames(env, stacked)[-1]
        assert _scalar(env, newest, "signed_volume") < 0
        assert _scalar(env, newest, "trade_direction") == -1.0

    def test_signed_volume_scales_with_size(self):
        env = _env()
        a, b = env.traders
        b.place_order('limit', 'ask', 20, 100.0, env.LOB, env.traders)
        env.prep_next_state()
        a.place_order('limit', 'bid', 20, 100.0, env.LOB, env.traders)
        stacked = env.prep_next_state()

        newest = _frames(env, stacked)[-1]
        assert _scalar(env, newest, "signed_volume") == pytest.approx(
            20.0 / env.limit_max_size, abs=1e-5)

    def test_a_quiet_frame_reports_no_flow(self):
        env = _env()
        a, b = env.traders
        a.place_order('limit', 'bid', 10, 90.0, env.LOB, env.traders)
        stacked = env.prep_next_state()

        newest = _frames(env, stacked)[-1]
        assert _scalar(env, newest, "signed_volume") == 0.0
        assert _scalar(env, newest, "log1p_trade_count") == 0.0
        assert _scalar(env, newest, "trade_direction") == 0.0

    def test_flow_is_not_counted_twice(self):
        """The cursor advances only when a frame enters the history."""
        env = _env()
        a, b = env.traders
        b.place_order('limit', 'ask', 10, 100.0, env.LOB, env.traders)
        env.prep_next_state()
        a.place_order('limit', 'bid', 10, 100.0, env.LOB, env.traders)
        env.prep_next_state()

        stacked = env.prep_next_state()   # nothing happened since
        newest = _frames(env, stacked)[-1]

        assert _scalar(env, newest, "log1p_trade_count") == 0.0
        assert _scalar(env, newest, "signed_volume") == 0.0

    def test_the_render_path_does_not_consume_the_flow(self):
        """`set_agg_LOB` runs twice per step; only one commits a frame."""
        env = _env()
        a, b = env.traders
        b.place_order('limit', 'ask', 10, 100.0, env.LOB, env.traders)
        env.prep_next_state()

        a.place_order('limit', 'bid', 10, 100.0, env.LOB, env.traders)
        env.set_agg_LOB()                 # the pre-action/display call
        stacked = env.prep_next_state()

        newest = _frames(env, stacked)[-1]
        assert _scalar(env, newest, "log1p_trade_count") > 0, (
            "a display-only snapshot must not eat the step's trade flow"
        )

    def test_flow_survives_a_full_env_step(self):
        env = continuousDoubleAuctionEnv(
            {"num_of_agents": 4, "max_step": 300, "is_render": False}
        )
        env.reset(seed=5)
        # `reset(seed=)` seeds the env's generator, not the action spaces:
        # `Space.sample()` has a generator of its own. Seeding both is what
        # makes the thresholds below a fact rather than a coin toss.
        for index, agent in enumerate(env.agents):
            env.action_spaces[agent].seed(5 + index)

        seen = {"signed_volume": 0, "log1p_trade_count": 0, "trade_direction": 0}
        for _ in range(300):
            actions = {a: env.action_spaces[a].sample() for a in env.agents}
            obs, _rew, terminateds, truncateds, _infos = env.step(actions)
            newest = _frames(env, obs["agent_0"])[-1]
            for name in seen:
                if _scalar(env, newest, name) != 0.0:
                    seen[name] += 1
            if terminateds.get("__all__") or truncateds.get("__all__"):
                break

        for name, count in seen.items():
            assert count > 10, f"{name} was ~always zero over a real rollout"
