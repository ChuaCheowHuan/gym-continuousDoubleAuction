import unittest
import numpy as np
from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import continuousDoubleAuctionEnv

class TestObservationHistory(unittest.TestCase):

    def test_default_n_hist_observation_space(self):
        env = continuousDoubleAuctionEnv()
        self.assertTrue(hasattr(env, 'mkt_size_mean_mul'))
        obs, infos = env.reset()
        
        # Default n_hist is 4, each snapshot has 40 features -> shape (160,)
        for agent_id in env.agents:
            self.assertEqual(env.observation_space[agent_id].shape, (160,))
            self.assertEqual(obs[agent_id].shape, (160,))

    def test_configurable_n_hist(self):
        for n_hist in [1, 2, 6, 10]:
            env = continuousDoubleAuctionEnv(config={"n_hist": n_hist})
            obs, infos = env.reset()
            expected_shape = (n_hist * 40,)
            for agent_id in env.agents:
                self.assertEqual(env.observation_space[agent_id].shape, expected_shape)
                self.assertEqual(obs[agent_id].shape, expected_shape)

    def test_reset_padding_identical_copies(self):
        n_hist = 4
        env = continuousDoubleAuctionEnv(config={"n_hist": n_hist})
        obs, _ = env.reset()
        
        agent_obs = obs["agent_0"]
        # Verify that all N segments of size 40 are identical at step 0
        snapshot_0 = agent_obs[0:40]
        for k in range(1, n_hist):
            snapshot_k = agent_obs[k*40:(k+1)*40]
            np.testing.assert_array_equal(snapshot_0, snapshot_k)

    def test_sliding_window_updates(self):
        n_hist = 4
        env = continuousDoubleAuctionEnv(config={"n_hist": n_hist})
        obs_0, _ = env.reset()
        
        # Collect snapshots across steps
        snapshots = [obs_0["agent_0"][-40:]]
        
        # Take a few steps with sample actions
        for step_i in range(n_hist + 2):
            actions = {agent_id: env.action_space[agent_id].sample() for agent_id in env.agents}
            obs_t, rewards, terminateds, truncateds, infos = env.step(actions)
            
            agent_obs = obs_t["agent_0"]
            self.assertEqual(agent_obs.shape, (n_hist * 40,))
            
            latest_snapshot = agent_obs[-40:]
            snapshots.append(latest_snapshot)
            
            # Verify trailing 40 elements match latest snapshot
            np.testing.assert_array_equal(agent_obs[-40:], latest_snapshot)

    def test_shared_history_multi_agent_uniformity(self):
        env = continuousDoubleAuctionEnv(config={"n_hist": 4})
        obs, _ = env.reset()
        
        # Check reset uniformity across agents
        agent_0_obs = obs["agent_0"]
        for agent_id in env.agents:
            np.testing.assert_array_equal(obs[agent_id], agent_0_obs)
            
        # Check step uniformity across agents
        actions = {agent_id: env.action_space[agent_id].sample() for agent_id in env.agents}
        obs_next, _, _, _, _ = env.step(actions)
        
        agent_0_next_obs = obs_next["agent_0"]
        for agent_id in env.agents:
            np.testing.assert_array_equal(obs_next[agent_id], agent_0_next_obs)

if __name__ == "__main__":
    unittest.main()
