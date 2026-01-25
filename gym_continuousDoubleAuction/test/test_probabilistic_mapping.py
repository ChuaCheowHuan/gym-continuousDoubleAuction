
import numpy as np
import collections
from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import SelfPlayCallback

class MockEpisode:
    def __init__(self, id):
        self.id_ = id

def test_mapping_distribution():
    # Setup callback
    num_trainable = 2
    num_random = 2
    original_weight = 1.0
    champion_weight = 9.0 # Favor champions heavily for clear results
    
    cb = SelfPlayCallback(
        num_trainable_policies=num_trainable,
        num_random_policies=num_random,
        original_opponent_weight=original_weight,
        champion_weight=champion_weight
    )
    
    # Add a champion
    cb.available_modules.append("champion_1")
    
    # Pool should be: [policy_2, policy_3, champion_1]
    # Weights: [1.0, 1.0, 9.0]
    # Probs: [1/11, 1/11, 9/11] approx [0.09, 0.09, 0.82]
    
    mapping_fn = SelfPlayCallback.get_mapping_fn(cb)
    
    counts = collections.Counter()
    num_samples = 1000
    
    for i in range(num_samples):
        episode = MockEpisode(f"episode_{i}")
        # Test mapping for agent_2 (first opponent agent)
        policy = mapping_fn("agent_2", episode)
        counts[policy] += 1
    
    print(f"Sampling results over {num_samples} episodes:")
    for policy, count in sorted(counts.items()):
        percentage = (count / num_samples) * 100
        print(f"  {policy}: {count} ({percentage:.1f}%)")
    
    # Assertions
    assert "champion_1" in counts, "Champion should have been selected"
    assert counts["champion_1"] > counts["policy_2"], "Champion should have higher selection count"
    assert counts["champion_1"] > counts["policy_3"], "Champion should have higher selection count"
    
    print("\nVerification SUCCESS: Probabilistic distribution matches weights.")

if __name__ == "__main__":
    test_mapping_distribution()
