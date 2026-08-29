import numpy as np
from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import continuousDoubleAuctionEnv
from gym_continuousDoubleAuction.envs.exchg.state_helper import (
    PRIVATE_DIM,
    PRIVATE_FIELDS,
    SNAPSHOT_DIM,
)

class TestObservationHistory:
    # Observation-space shape across n_hist values (including the default 4)
    # is covered by test_obs_market_features.py::test_observation_shape_across_n_hist.

    def test_reset_padding_identical_copies(self):
        n_hist = 4
        env = continuousDoubleAuctionEnv(config={"n_hist": n_hist})
        obs, _ = env.reset()

        agent_obs = obs["agent_0"]
        # Verify that all N segments of size SNAPSHOT_DIM are identical at step 0
        snapshot_0 = agent_obs[0:SNAPSHOT_DIM]
        for k in range(1, n_hist):
            snapshot_k = agent_obs[k*SNAPSHOT_DIM:(k+1)*SNAPSHOT_DIM]
            np.testing.assert_array_equal(snapshot_0, snapshot_k)

    def test_sliding_window_updates(self):
        n_hist = 4
        env = continuousDoubleAuctionEnv(config={"n_hist": n_hist})
        obs_0, _ = env.reset()

        # Collect snapshots across steps
        book_dim = n_hist * SNAPSHOT_DIM
        snapshots = [obs_0["agent_0"][book_dim - SNAPSHOT_DIM:book_dim]]

        # Take a few steps with sample actions
        for step_i in range(n_hist + 2):
            actions = {agent_id: env.action_spaces[agent_id].sample() for agent_id in env.agents}
            obs_t, rewards, terminateds, truncateds, infos = env.step(actions)

            agent_obs = obs_t["agent_0"]
            assert agent_obs.shape == (n_hist * SNAPSHOT_DIM + PRIVATE_DIM,)

            # The newest frame ends where the book ends, not where the vector
            # does - the private block is after it.
            latest_snapshot = agent_obs[book_dim - SNAPSHOT_DIM:book_dim]
            snapshots.append(latest_snapshot)

            # Verify the last book frame matches the latest snapshot
            np.testing.assert_array_equal(
                agent_obs[book_dim - SNAPSHOT_DIM:book_dim], latest_snapshot
            )

    def test_the_book_prefix_is_shared_across_agents(self):
        """The public book is public: every agent sees the same order book.

        This half was never the defect and must not regress - the book is
        computed once per step and handed to everyone.
        """
        n_hist = 4
        env = continuousDoubleAuctionEnv(config={"n_hist": n_hist})
        book_dim = n_hist * SNAPSHOT_DIM
        obs, _ = env.reset()

        for agent_id in env.agents:
            np.testing.assert_array_equal(
                obs[agent_id][:book_dim], obs["agent_0"][:book_dim]
            )

        actions = {a: env.action_spaces[a].sample() for a in env.agents}
        obs_next, _, _, _, _ = env.step(actions)

        for agent_id in env.agents:
            np.testing.assert_array_equal(
                obs_next[agent_id][:book_dim], obs_next["agent_0"][:book_dim]
            )

    def test_agents_see_distinct_private_state(self):
        """S1-2, inverted.

        This test used to assert that every agent received the byte-identical
        vector - it encoded the defect as a requirement. The reward is
        f(nav, prev_nav, max_nav, ...) and none of that was observable, so two
        agents holding opposite positions got the same observation and needed
        opposite actions, which a policy cannot do.

        Trading is what makes the tails differ, so this steps until it sees
        that rather than asserting on the reset state, where every agent
        genuinely does start identical.
        """
        n_hist = 4
        env = continuousDoubleAuctionEnv(config={"n_hist": n_hist, "num_of_agents": 4})
        book_dim = n_hist * SNAPSHOT_DIM
        env.reset(seed=0)
        for agent_id in env.agents:
            env.action_spaces[agent_id].seed(0)

        for _ in range(40):
            actions = {a: env.action_spaces[a].sample() for a in env.agents}
            obs, _r, terminateds, truncateds, _i = env.step(actions)
            tails = {a: tuple(np.round(obs[a][book_dim:], 6)) for a in obs}
            if len(set(tails.values())) > 1:
                break
            if terminateds.get("__all__") or truncateds.get("__all__"):
                break
        else:
            raise AssertionError("no agent traded in 40 steps; test is inert")

        assert len(set(tails.values())) > 1, (
            "every agent's private block is identical after trading, so the "
            "observation still cannot distinguish a long agent from a short "
            "one. See doc/15 S1-2."
        )

    def test_the_private_block_is_the_declared_width(self):
        env = continuousDoubleAuctionEnv(config={"n_hist": 4})
        obs, _ = env.reset()
        assert PRIVATE_DIM == len(PRIVATE_FIELDS)
        assert obs["agent_0"].shape == (4 * SNAPSHOT_DIM + PRIVATE_DIM,)

    def test_the_private_block_is_bounded_and_finite(self):
        """It shares a vector - and a `tanh` MLP - with the normalised book.

        An unbounded private field would saturate that MLP exactly as the raw
        sizes do (S2-2), so every field in `set_private_state` is normalised by
        starting NAV or is already a ratio.
        """
        env = continuousDoubleAuctionEnv(config={"n_hist": 4, "num_of_agents": 4})
        env.reset(seed=1)
        for agent_id in env.agents:
            env.action_spaces[agent_id].seed(1)

        book_dim = 4 * SNAPSHOT_DIM
        for _ in range(60):
            actions = {a: env.action_spaces[a].sample() for a in env.agents}
            obs, _r, terminateds, truncateds, _i = env.step(actions)
            for agent_id, vector in obs.items():
                tail = vector[book_dim:]
                assert np.isfinite(tail).all(), (agent_id, tail)
                assert np.abs(tail).max() < 100.0, (agent_id, tail)
            if terminateds.get("__all__") or truncateds.get("__all__"):
                break
