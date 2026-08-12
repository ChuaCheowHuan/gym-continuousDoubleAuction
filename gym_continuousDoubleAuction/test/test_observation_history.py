import numpy as np
from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import continuousDoubleAuctionEnv
from gym_continuousDoubleAuction.envs.exchg.state_helper import SNAPSHOT_DIM

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
        snapshots = [obs_0["agent_0"][-SNAPSHOT_DIM:]]

        # Take a few steps with sample actions
        for step_i in range(n_hist + 2):
            actions = {agent_id: env.action_spaces[agent_id].sample() for agent_id in env.agents}
            obs_t, rewards, terminateds, truncateds, infos = env.step(actions)

            agent_obs = obs_t["agent_0"]
            assert agent_obs.shape == (n_hist * SNAPSHOT_DIM,)

            latest_snapshot = agent_obs[-SNAPSHOT_DIM:]
            snapshots.append(latest_snapshot)

            # Verify trailing SNAPSHOT_DIM elements match latest snapshot
            np.testing.assert_array_equal(agent_obs[-SNAPSHOT_DIM:], latest_snapshot)

    def test_shared_history_multi_agent_uniformity(self):
        env = continuousDoubleAuctionEnv(config={"n_hist": 4})
        obs, _ = env.reset()

        # Check reset uniformity across agents
        agent_0_obs = obs["agent_0"]
        for agent_id in env.agents:
            np.testing.assert_array_equal(obs[agent_id], agent_0_obs)

        # Check step uniformity across agents
        actions = {agent_id: env.action_spaces[agent_id].sample() for agent_id in env.agents}
        obs_next, _, _, _, _ = env.step(actions)

        agent_0_next_obs = obs_next["agent_0"]
        for agent_id in env.agents:
            np.testing.assert_array_equal(obs_next[agent_id], agent_0_next_obs)
