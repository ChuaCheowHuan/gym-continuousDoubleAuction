# League-Based Self-Play Testing

This document outlines the testing procedures and verification scripts used to ensure the robustness and correctness of the league-based self-play implementation.

## Unit Testing: Probabilistic Mapping

The file `gym_continuousDoubleAuction/test/test_probabilistic_mapping.py` is used to verify the agent-to-policy mapping logic.

### Purpose
To ensure that:
1.  **Weighted Selection**: Policies are selected according to their configured weights (e.g., favoring champions over original policies).
2.  **Normalization**: Raw weights are correctly converted into a probability distribution.
3.  **Determinism**: Selection is stable and deterministic based on the episode and agent IDs.

### How to Run
```powershell
python gym_continuousDoubleAuction/test/test_probabilistic_mapping.py
```

### Test Methodology
The test uses **statistical sampling**:
- It mocks a `SelfPlayCallback` and an `Episode` object.
- It simulates 1,000 episode starts.
- It records the policy assigned to a specific agent in each episode.
- it calculates the distribution percentage and compares it against expected thresholds.

### Robustness Evaluation
| Feature | Status | Note |
|---------|--------|------|
| **Logic Verification** | ✅ High | catches errors in weight application or name parsing. |
| **Statistical Validity** | ✅ High | 1,000 samples provide a narrow confidence interval. |
| **Determinism** | ⚠️ Moderate | Current test verifies distribution but not per-episode stability (planned). |
| **Edge Cases** | ⚠️ Moderate | Doesn't yet test empty pools or zero weights. |

## Manual Verification

### Console Output
During training, the `SelfPlayCallback` prints the policy map at the start of each episode. You can manually verify the "feel" of the distribution here:

```text
========================================
Episode 12345 Started - Policy Map:
  agent_0 -> policy_0
  agent_1 -> policy_1
  agent_2 -> champion_1
  agent_3 -> policy_3
========================================
```

### Performance Monitoring
Monitor the `league_size` and `league_mean_return` in TensorBoard to ensure that adding/removing champions and shifting selection weights leads to the expected training dynamics (e.g., increased difficulty).
