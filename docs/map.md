# Documentation

The index of everything in this folder: what each document answers, and the order to read them in
for a given goal. The project itself is introduced in the top-level [README](../README.md); what it
is, in depth, starts at [01_overview.md](01_overview.md).

## Documentation map

```mermaid
mindmap
  root(("gym-continuousDoubleAuction"))
    Orientation
      00 Getting started
      01 Overview
      02 Architecture
      28 Glossary
      17 Changelog
    Simulator
      03 Matching engine
      04 Accounting
    Learning problem
      05 Observation space
      06 Action space
      07 Reward function
    Training
      08 Self-play league
      09 Distributed training
      11 Logging
    Operations
      26 Runbook
      27 Agent skills
      18 Configuration
      19 Docker
      20 Colab
      10 Testing
      Contributing
    Assessment
      12 RL researcher
      13 Financial trader
      14 AI engineer
      15 Findings
      29 Fixed issues
      16 Verification log
    Research
      23 Probe harness
      30 Extensions
        cbp, cda-cbp
        discorl, cda-discorl
        jepa, cda-jepa
```

### Start here

| # | Document | What it answers |
|---|---|---|
| 0 | [00_getting_started.md](00_getting_started.md) | Minimum and recommended hardware with measured run times, then a clone to a first trained policy in four steps |
| 1 | [01_overview.md](01_overview.md) | What this project is, the market it models, the research question, what an episode looks like |
| 26 | [26_runbook.md](26_runbook.md) | Install, check, train, resume, inspect, probe and pretrain, step by step, with what to watch and a troubleshooting table |
| 2 | [02_architecture.md](02_architecture.md) | The system at a glance, layer map, package tree, the mixin/MRO chain, the step lifecycle, config keys, data flow, tech stack |
| 28 | [28_glossary.md](28_glossary.md) | The market, account, learning and project terms the documents use, each linked to the document that owns it |

### Core mechanisms (reference)

| # | Document | What it answers |
|---|---|---|
| 3 | [03_matching_engine.md](03_matching_engine.md) | Book data structures, limit/market processing, modify-order semantics and the six accounting scenarios, invariants |
| 4 | [04_accounting.md](04_accounting.md) | Cash escrow, order approval, position transitions including atomic flips, mark-to-market, NAV conservation |
| 5 | [05_observation_space.md](05_observation_space.md) | The 48-float grid snapshot (and the 66-float level view): the fixed tick-offset grid shared with the action, `√(V/limit_max_size)` sizing, the six market scalars, temporal stacking, the raw/normalized split, measured bounds and feature scales |
| 6 | [06_action_space.md](06_action_space.md) | The `Dict` action space, ghost-level price anchoring, the two degenerate size dimensions, the legacy `Tuple` design it replaced |
| 7 | [07_reward_function.md](07_reward_function.md) | The six-term formula (five shaping terms, and a sixth shipped at zero for dead order-management actions), its account plumbing, the measured decomposition, a coefficient tuning guide |

### Training

| # | Document | What it answers |
|---|---|---|
| 8 | [08_self_play_league.md](08_self_play_league.md) | League play: champion snapshotting and its four load-bearing ordering constraints, weighted matchmaking, configuration, monitoring, troubleshooting |
| 9 | [09_distributed_training.md](09_distributed_training.md) | `num_env_runners` and `num_learners`: what each distributes, worked examples, and what goes stale across a process boundary with the guard and test for each |
| 10 | [10_testing.md](10_testing.md) | Every test file, what each case pins down, CI, and the gaps |
| 11 | [11_logging_and_observability.md](11_logging_and_observability.md) | What training records, where it goes, the gap between what is computed and what is surfaced, and (§5) what changes with `num_env_runners > 0` |

### Analysis

| # | Document | Audience |
|---|---|---|
| 12 | [12_perspective_rl_researcher.md](12_perspective_rl_researcher.md) | Algorithm, reward design, exploration, sample efficiency, training stability |
| 13 | [13_perspective_financial_trader.md](13_perspective_financial_trader.md) | Microstructure realism, risk, execution, P&L, desk metrics |
| 14 | [14_perspective_ai_engineer.md](14_perspective_ai_engineer.md) | Code quality, packaging, scalability, observability, production readiness |
| 15 | [15_findings_and_recommendations.md](15_findings_and_recommendations.md) | Where the project stands, and what is still open: review decisions and the remainders of fixed findings |
| 29 | [29_fixed_issues.md](29_fixed_issues.md) | Every problem found and fixed, under its original ID: what was wrong, how it was found, what fixed it |
| 16 | [16_verification_log.md](16_verification_log.md) | Every executed probe and its raw output |
| 17 | [17_changelog.md](17_changelog.md) | What changed since `original_v1` (2020) and why |
| 23 | [23_probe_harness.md](23_probe_harness.md) | Scoring an encoder on microstructure targets without the reward, how to read it, why the probe is linear, and the effective rank of a network on a fixed corpus |
| 30 | [30_extensions.md](30_extensions.md) | The three extension packages (Continual Backprop, DiscoRL, JEPA) and the forks they build on; what a package declares, how a run enables it, where its pieces are composed, how resumes are guarded, and what stayed here when CBP and JEPA moved out |
| 27 | [27_agent_skills.md](27_agent_skills.md) | Which agent skills this repository would pay for, from the work that was done by hand in the review passes: what each does, its evidence, the scripts it needs, the mistakes it must not repeat, and the order to build them in |

### Configuration and deployment

| # | Document | What it answers |
|---|---|---|
| 26 | [26_runbook.md](26_runbook.md) | The operator's page: every command in order, which command answers which goal, where each output lands, what to watch during a run, and what to do when it goes wrong |
| 18 | [18_configuration.md](18_configuration.md) | The five `config/` files and what each owns, the loader's rules, precedence between file and flags, the runtime profiles that pick a hardware set, how to add a knob |
| 19 | [19_docker.md](19_docker.md) | The GPU training image: build and run, what each flag is for, GPU prerequisites, where artefacts land in an ephemeral container, troubleshooting |
| 20 | [20_colab.md](20_colab.md) | Running the notebook on a free Colab VM: setup, the forced restart, what the free tier gives you, where output goes, resuming after a disconnect |

### Contributing

| Document | What it answers |
|---|---|
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to set up for development, the rules every change follows, the checks to run before pushing, how reviews file issues |

### Version 1

| Document | What it is |
|---|---|
| [README_v1.md](README_v1.md) | The original 2020 README of the `original_v1` branch, kept as it was |

---

## Reading paths

**First run**
[00](00_getting_started.md) → [26](26_runbook.md) → [18](18_configuration.md)

**New to the codebase**
[01](01_overview.md) → [28](28_glossary.md) (keep it open) → [02](02_architecture.md) → [03](03_matching_engine.md) →
[04](04_accounting.md) → [05](05_observation_space.md) → [06](06_action_space.md)

**Deciding whether to build on this**
[01](01_overview.md) → [15](15_findings_and_recommendations.md) → [29](29_fixed_issues.md) → [16](16_verification_log.md)

**Planning changes to the RL layer**
[15](15_findings_and_recommendations.md) (what is open) → [29](29_fixed_issues.md) (what was wrong, in severity order) → [12](12_perspective_rl_researcher.md) →
[05](05_observation_space.md) → [07](07_reward_function.md)

**Weighing a representation-learning change (JEPA)**
[30](30_extensions.md) §9 (install cda-jepa) → cda-jepa's docs/jepa.md (the research note) →
[05](05_observation_space.md) → [18](18_configuration.md) §5.4–5.5

**Comparing encoders**
[23](23_probe_harness.md) (a metric that does not go through the reward) →
[18](18_configuration.md) §5.5 (seeds, separate runs, parameter counts)

**Pretraining an encoder before training a policy**
[30](30_extensions.md) §9 (install cda-jepa) → cda-jepa's docs/pretraining.md →
[23](23_probe_harness.md) (measuring what it taught)

**Weighing a plasticity change for long runs (Continual Backprop)**
[30](30_extensions.md) §8 (install cda-cbp, and what stayed here) → cda-cbp's
docs/continual_backprop.md (its note and cadence caveat) →
[18](18_configuration.md) §5.6 (tuned Adam, kept here) →
[23](23_probe_harness.md) §10 (the reward-free rank it must be scored on) →
[29](29_fixed_issues.md) (S1-1, S1-3, which gated the returns comparison)

**Adding a learning method from another package (extensions)**
[30](30_extensions.md) → [18](18_configuration.md) §5.7 (the config group) →
[30](30_extensions.md) §8 (Continual Backprop as an extension: `learner_order`, the layout contract)

**Setting up training**
[26](26_runbook.md) (the commands, in order) → [18](18_configuration.md) (where every value lives) → [08](08_self_play_league.md) →
[09](09_distributed_training.md) (if raising `num_env_runners` or `num_learners` above their
`0` defaults) → [11](11_logging_and_observability.md)

**Running it on Colab**
[20](20_colab.md) → [18](18_configuration.md) §8 (the `gpu` / `cpu` parameter sets
`CDA_train.ipynb` selects between)

**Running it on a local GPU box**
[19](19_docker.md) (the training image) → [18](18_configuration.md) §8 →
[09](09_distributed_training.md) §5

**Modifying the engine or accounts**
[CONTRIBUTING](CONTRIBUTING.md) → [03](03_matching_engine.md) §4 (invariants) → [04](04_accounting.md) →
[10](10_testing.md) §1–2

**Trading / microstructure review**
[13](13_perspective_financial_trader.md) → [03](03_matching_engine.md) → [04](04_accounting.md)

## Retired and moved numbers

21 (the logging review) is now [11](11_logging_and_observability.md) §5, and 24 (offline
pretraining) is cda-jepa's docs/pretraining.md. [22](22_jepa_integration.md) (JEPA) and [25](25_continual_backprop.md) (Continual Backprop) moved to
their packages; each keeps a one-paragraph page here with the new location, because code comments
and the history files cite them. The numbers are not reused.
