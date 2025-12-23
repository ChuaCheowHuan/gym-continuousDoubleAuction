import unittest
import sys
import os
from unittest.mock import MagicMock

# Add the project root to sys.path to allow imports from gym_continuousDoubleAuction
# Assuming the tests are run from the project root or the test directory
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import SelfPlayCallback

class MockEpisode:
    def __init__(self, id, last_info):
        self.id_ = id
        self.last_info = last_info
    
    def get_infos(self, index):
        if index == -1:
            return self.last_info
        return {}

class MockEnv:
    def __init__(self, init_cash, num_of_agents):
        self.init_cash = init_cash
        self.num_of_agents = num_of_agents

class TestNAVCallback(unittest.TestCase):
    def setUp(self):
        self.callback = SelfPlayCallback(num_trainable_policies=2, num_random_policies=2)
        self.init_cash = 1000000
        self.num_agents = 4
        self.mock_env = MockEnv(self.init_cash, self.num_agents)
        self.mock_runner = MagicMock()
        # Mocking the config in env_runner to test the robust parameter retrieval
        self.mock_runner.config = MagicMock()
        self.mock_runner.config.env_config = {
            "init_cash": self.init_cash,
            "num_of_agents": self.num_agents
        }

    def test_on_episode_end_success(self):
        """Test that on_episode_end handles matching NAV correctly."""
        print("\n--- Running test_on_episode_end_success ---")
        mock_info = {
            f"agent_{i}": {"NAV": str(float(self.init_cash))} for i in range(self.num_agents)
        }
        mock_episode = MockEpisode("test_ep_success", mock_info)
        
        # This shouldn't raise any errors and should print SUCCESS
        self.callback.on_episode_end(
            episode=mock_episode,
            env_runner=self.mock_runner,
            metrics_logger=None,
            env=self.mock_env,
            env_index=0,
            rl_module=None
        )

    def test_on_episode_end_failure(self):
        """Test that on_episode_end handles mismatched NAV correctly."""
        print("\n--- Running test_on_episode_end_failure ---")
        # Deviate from the expected cash
        mock_info_fail = {
            f"agent_{i}": {"NAV": str(float(self.init_cash - 1000))} for i in range(self.num_agents)
        }
        mock_episode_fail = MockEpisode("test_ep_failure", mock_info_fail)
        
        # This shouldn't raise any errors and should print FAILED
        self.callback.on_episode_end(
            episode=mock_episode_fail,
            env_runner=self.mock_runner,
            metrics_logger=None,
            env=self.mock_env,
            env_index=0,
            rl_module=None
        )

if __name__ == "__main__":
    unittest.main()
