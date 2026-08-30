"""The one piece of arithmetic in `visualize/` that can be silently wrong.

`visualize_orderbook` plots bid and ask depth by slicing the newest book
snapshot out of a recorded observation. Nothing downstream of that slice can
detect a bad one: every index still resolves, every sum is a float, and the
chart renders. It just plots the wrong numbers.

That is not hypothetical. The private-state block appended in
[17](../../doc/17_changelog.md) section 30 moved the end of the vector, and the
`obs[-SNAPSHOT_DIM:]` this module used went on working while returning the
private block plus a truncated final snapshot - shifted by exactly
PRIVATE_DIM, so the "ask sizes" it plotted were an agent's own position and
cash. The env, the tests and the probe were all updated for the new layout;
this file was missed, because nothing in `visualize/` was tested at all.

So these tests pin the slice, not the plot.
"""
import numpy as np
import pytest

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.envs.exchg.state_helper import (
    PRIVATE_DIM,
    SNAPSHOT_DIM,
)
from gym_continuousDoubleAuction.visualize.visualize_orderbook import (
    _newest_snapshot,
)

N_HISTS = [1, 2, 4]


def _stepped_obs(n_hist, steps=3, seed=7):
    """A real observation, several steps in so the stack is not all resets."""
    env = continuousDoubleAuctionEnv(
        {"num_of_agents": 4, "max_step": 16, "is_render": False, "n_hist": n_hist}
    )
    obs, _ = env.reset(seed=seed)
    space = env.action_spaces["agent_0"]
    for _ in range(steps):
        obs, *_ = env.step({agent: space.sample() for agent in obs})
    return np.asarray(obs["agent_0"], dtype=np.float64)


class TestNewestSnapshot:
    @pytest.mark.parametrize("n_hist", N_HISTS)
    def test_it_is_the_last_frame_of_the_stack(self, n_hist):
        """The newest snapshot ends at `n_hist * SNAPSHOT_DIM`, not at the end
        of the vector."""
        obs = _stepped_obs(n_hist)

        got = _newest_snapshot(obs)

        expected = obs[(n_hist - 1) * SNAPSHOT_DIM : n_hist * SNAPSHOT_DIM]
        assert got.size == SNAPSHOT_DIM
        assert np.array_equal(got, expected)

    @pytest.mark.parametrize("n_hist", N_HISTS)
    def test_it_never_reaches_the_private_block(self, n_hist):
        """The regression, stated as the property that was violated.

        Marking every private float with a value the book cannot produce makes
        the old slice fail loudly here: it took PRIVATE_DIM of them.
        """
        obs = _stepped_obs(n_hist)
        sentinel = -12345.0
        obs[-PRIVATE_DIM:] = sentinel

        got = _newest_snapshot(obs)

        assert sentinel not in got
        assert sentinel in obs[-SNAPSHOT_DIM:], (
            "the slice this replaced must still be shown to take private floats, "
            "or this test would pass for the wrong reason"
        )

    @pytest.mark.parametrize("n_hist", N_HISTS)
    def test_it_disagrees_with_the_slice_it_replaced(self, n_hist):
        """Pinned directly, because the two agree whenever PRIVATE_DIM is 0 -
        which is how the bug survived being read."""
        obs = _stepped_obs(n_hist)

        assert not np.array_equal(_newest_snapshot(obs), obs[-SNAPSHOT_DIM:])

    def test_the_frames_are_ordered_oldest_first(self):
        """Which frame is "newest" is the whole claim, so it is checked against
        the env rather than assumed: the newest frame of a stack must be the
        one that changed most recently."""
        n_hist = 4
        env = continuousDoubleAuctionEnv(
            {"num_of_agents": 4, "max_step": 16, "is_render": False, "n_hist": n_hist}
        )
        obs, _ = env.reset(seed=11)
        space = env.action_spaces["agent_0"]
        before = np.asarray(obs["agent_0"], dtype=np.float64)
        obs, *_ = env.step({agent: space.sample() for agent in obs})
        after = np.asarray(obs["agent_0"], dtype=np.float64)

        # The stack shifted by one frame, so the newest frame of `before` is
        # the second-newest of `after`.
        shifted = after[(n_hist - 2) * SNAPSHOT_DIM : (n_hist - 1) * SNAPSHOT_DIM]
        assert np.array_equal(_newest_snapshot(before), shifted)


class TestItRefusesAVectorItCannotRead:
    """The slice is arithmetic on a width, so a width it cannot decompose must
    raise rather than return a misaligned window - the same contract
    `ObsLayout.from_obs_space` holds on the model side."""

    def test_a_width_that_is_not_whole_snapshots_raises(self):
        obs = np.zeros(4 * SNAPSHOT_DIM + PRIVATE_DIM + 3, dtype=np.float64)

        with pytest.raises(ValueError, match="whole number"):
            _newest_snapshot(obs)

    def test_a_vector_too_short_for_one_snapshot_raises(self):
        obs = np.zeros(PRIVATE_DIM, dtype=np.float64)

        with pytest.raises(ValueError, match="whole number"):
            _newest_snapshot(obs)
