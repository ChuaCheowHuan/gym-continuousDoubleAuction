# Changes from original_v1 to Current Version 2 (update 20251224)

This repository has undergone significant modernization since the `original_v1` branch (the original release from 2020, [README_v1.md](README_v1.md)).

For a detailed breakdown of codebase modernizations, please refer to the [17_changelog.md](doc/17_changelog.md) document.

---

# Version 2 README:

### Start here

| # | Document | What it answers |
|---|---|---|
| 1 | [01_overview.md](01_overview.md) | What this project is, the market it models, the research question, what an episode looks like |
| 2 | [02_architecture.md](02_architecture.md) | Layer map, package tree, the mixin/MRO chain, the step lifecycle, config keys, data flow, tech stack |

### Core mechanisms (reference)

| # | Document | What it answers |
|---|---|---|
| 3 | [03_matching_engine.md](03_matching_engine.md) | Book data structures, limit/market processing, modify-order semantics and the six accounting scenarios, invariants |
| 4 | [04_accounting.md](04_accounting.md) | Cash escrow, order approval, position transitions including atomic flips, mark-to-market, NAV conservation |
| 5 | [05_observation_space.md](05_observation_space.md) | The 42-float snapshot: midpoint normalization, `√V` sizing, `log_mid` / `log1p_spread_ticks`, temporal stacking, the raw/normalized split, measured feature scales |
| 6 | [06_action_space.md](06_action_space.md) | The `Dict` action space, ghost-level price anchoring, the two degenerate size dimensions, the legacy `Tuple` design it replaced |
| 7 | [07_reward_function.md](07_reward_function.md) | The five-term formula, its account plumbing, the measured decomposition, a coefficient tuning guide |

### Training

| # | Document | What it answers |
|---|---|---|
| 8 | [08_self_play_league.md](08_self_play_league.md) | League play: champion snapshotting and its four load-bearing ordering constraints, weighted matchmaking, configuration, monitoring, troubleshooting |
| 9 | [09_distributed_training.md](09_distributed_training.md) | `num_env_runners` and `num_learners`: what each distributes, worked examples, and three now-fixed bugs that existed only at non-default values |
| 10 | [10_testing.md](10_testing.md) | Every test file, what each case pins down, CI, and the gaps |
| 11 | [11_logging_and_observability.md](11_logging_and_observability.md) | What training records, where it goes, and the gap between what is computed and what is surfaced |

### Analysis

| # | Document | Audience |
|---|---|---|
| 12 | [12_perspective_rl_researcher.md](12_perspective_rl_researcher.md) | Algorithm, reward design, exploration, sample efficiency, training stability |
| 13 | [13_perspective_financial_trader.md](13_perspective_financial_trader.md) | Microstructure realism, risk, execution, P&L, desk metrics |
| 14 | [14_perspective_ai_engineer.md](14_perspective_ai_engineer.md) | Code quality, packaging, scalability, observability, production readiness |
| 15 | [15_findings_and_recommendations.md](15_findings_and_recommendations.md) | Consolidated, severity-ranked findings with fixes and a suggested sequence |
| 16 | [16_verification_log.md](16_verification_log.md) | Every executed probe and its raw output |
| 17 | [17_changelog.md](17_changelog.md) | What changed since `original_v1` (2020) and why |
| 18 | [18_configuration.md](18_configuration.md) | Every knob: the `config/` inventory, the env / `TrainConfig` / CLI surfaces, and what stays hardcoded and why |

---

## Reading paths

**New to the codebase**
[01](01_overview.md) → [02](02_architecture.md) → [03](03_matching_engine.md) →
[04](04_accounting.md) → [05](05_observation_space.md) → [06](06_action_space.md)

**Deciding whether to build on this**
[01](01_overview.md) → [15](15_findings_and_recommendations.md) → [16](16_verification_log.md)

**Planning changes to the RL layer**
[15](15_findings_and_recommendations.md) (severity order) → [12](12_perspective_rl_researcher.md) →
[05](05_observation_space.md) → [07](07_reward_function.md)

**Setting up training**
[08](08_self_play_league.md) → [09](09_distributed_training.md) (if raising `num_env_runners`
or `num_learners` above their `0` defaults) → [11](11_logging_and_observability.md)

**Modifying the engine or accounts**
[03](03_matching_engine.md) §4 (invariants) → [04](04_accounting.md) → [10](10_testing.md) §1–2

**Trading / microstructure review**
[13](13_perspective_financial_trader.md) → [03](03_matching_engine.md) → [04](04_accounting.md)

---

## Summary

This repository implements a multi-agent continuous double auction system, structured as a price- and time-priority limit order book exchange. It is provided as a Gymnasium / RLlib `MultiAgentEnv` and includes a league-based self-play PPO training pipeline built on Ray RLlib 2.56.1’s new API stack. 

In this environment, agents act as traders who can submit market, limit, modify, and cancel orders to a shared order book. They are marked to market based on the trade tape, and receive rewards derived from a multi-term NAV-based function. The codebase also includes a matching engine, supports `Decimal`-based accounting, includes the necessary RLlib league wiring, and comes with CI unit tests.

**Main problems:** The weak points are concentrated in the learning problem formulation rather than in the simulator: agents observe no private state, the reward is strictly negative-sum with a dominant do-nothing strategy, and the reward scale silently disables PPO's critic entirely.

---

## Acknowledgements:
The orderbook matching engine is adapted from
https://github.com/dyn4mik3/OrderBook

---

## Disclaimer:
This repository is only meant for research purposes & is **never** meant to be used in any form of trading. Past performance is no guarantee of future results. If you suffer losses from using this repository, you are the sole person responsible for the losses. The author will **NOT** be held responsible in any way.

---

## 📌 How to Cite

If you use this software in your research, please cite the appropriate version:

> Chua Cheow Huan. (2025). *gym-continuousDoubleAuction* (Version 2.0.0) [Computer software].

You can also view and export citations in various formats using the **"Cite this repository"** button on the top-right of this page.

For version 1.0.0 (original version released in 2020), see: https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/tree/original_v1