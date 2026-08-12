# `gym-continuousDoubleAuction` — Independent Codebase Analysis

This folder contains a from-scratch technical analysis of the repository, derived
**exclusively from source code** (Python modules, notebooks, CI config, packaging
metadata). No pre-existing `.md` documentation in the repository was used as
input, and none of it has been modified.

Every non-trivial claim below was verified by reading the implementation and,
where behaviour was in question, by executing the code. Executed evidence is
marked **[verified]** and the reproduction snippet or observed output is quoted.

## Reading order

| # | Document | Audience |
|---|----------|----------|
| 1 | [01_overview.md](01_overview.md) | Everyone — what this project is and what problem it models |
| 2 | [02_architecture.md](02_architecture.md) | Everyone — module map, class graph, data flow, step lifecycle, tech stack |
| 3 | [03_perspective_rl_researcher.md](03_perspective_rl_researcher.md) | RL researcher — algorithm, reward, exploration, sample efficiency, stability |
| 4 | [04_perspective_financial_trader.md](04_perspective_financial_trader.md) | Trader / quant — microstructure realism, risk, execution, P&L, metrics |
| 5 | [05_perspective_ai_engineer.md](05_perspective_ai_engineer.md) | Engineer — code quality, packaging, scalability, observability, production readiness |
| 6 | [06_findings_and_recommendations.md](06_findings_and_recommendations.md) | Everyone — consolidated, severity-ranked findings with fixes |
| 7 | [07_verification_log.md](07_verification_log.md) | Everyone — the executed probes and their raw output |

## One-paragraph summary

The repository implements a **multi-agent continuous double auction (CDA)** — a
price/time-priority limit order book exchange — packaged as a Gymnasium /
RLlib `MultiAgentEnv`, together with a **league-based self-play PPO training
stack** built on Ray RLlib 2.56.1's new API stack. Agents are traders that
submit market/limit/modify/cancel orders into a shared book, are marked to
market against the tape, and are rewarded on a multi-term NAV-based function.
The matching engine, the double-entry-style accounting, and the RLlib league
wiring are all substantially correct and well covered by tests (90 unit tests +
3 integration classes, all passing). The weak points are concentrated in the
**learning problem formulation** rather than in the simulator: agents observe no
private state, the reward is strictly negative-sum with a dominant do-nothing
strategy, and the reward scale silently disables PPO's critic entirely.

## Repository facts (measured)

| Metric | Value |
|---|---|
| Python source files | 63 |
| Total Python LOC | 7,478 |
| Env + order book LOC | ~2,000 |
| Training stack LOC | ~1,100 |
| Test LOC | ~2,300 |
| Unit tests | 90, all passing (8.75 s) |
| Integration test classes | 3 (local learner, remote EnvRunner, remote LearnerGroup) |
| Runtime stack | Python 3.12, Ray 2.56.1, Gymnasium 1.2.2, PyTorch 2.13.0, NumPy 2.5 |
| Current branch | `update_lib` (ahead of `master` by the Ray 2.56 migration) |
