import sys
import os

# Add the project root to sys.path
sys.path.append(os.getcwd())

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

def test_on_episode_end():
    # Setup mock data
    init_cash = 1000000
    num_agents = 4
    total_expected_cash = init_cash * num_agents
    
    # 1. Test Success Case
    print("\n--- Test Case 1: Success (NAV matches initial cash) ---")
    mock_info = {
        f"agent_{i}": {"NAV": str(float(init_cash))} for i in range(num_agents)
    }
    mock_episode = MockEpisode("test_ep_success", mock_info)
    mock_env = MockEnv(init_cash, num_agents)
    
    callback = SelfPlayCallback()
    callback.on_episode_end(
        episode=mock_episode,
        env_runner=None,
        metrics_logger=None,
        env=mock_env,
        env_index=0,
        rl_module=None
    )
    
    # 2. Test Failure Case
    print("\n--- Test Case 2: Failure (NAV does not match initial cash) ---")
    mock_info_fail = {
        f"agent_{i}": {"NAV": str(float(init_cash - 1000))} for i in range(num_agents)
    }
    mock_episode_fail = MockEpisode("test_ep_failure", mock_info_fail)
    
    callback.on_episode_end(
        episode=mock_episode_fail,
        env_runner=None,
        metrics_logger=None,
        env=mock_env,
        env_index=0,
        rl_module=None
    )

if __name__ == "__main__":
    test_on_episode_end()
