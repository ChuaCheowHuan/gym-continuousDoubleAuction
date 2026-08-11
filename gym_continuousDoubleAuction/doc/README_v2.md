# Documentation Index (v2)

Documentation for the `gym-continuousDoubleAuction` environment — a multi-agent RL environment
(Gymnasium + Ray RLlib) simulating a continuous double auction limit order book, where the price
series is generated entirely by the agents' own order flow.

This index replaces the previous `content.md`. The documentation was restructured from 27 overlapping
files — per-test walkthroughs, dated analysis snapshots, plans, and implementation reports — into
eleven topic-based documents.

---

## Table of Contents

### Start here

| Document | What it answers |
|---|---|
| **[architecture.md](architecture.md)** | How the system is put together: the four layers, the step loop, the mixin/MRO structure, and the config keys |
| **[changelog.md](changelog.md)** | What changed since `original_v1` (2020) and why |

### Core mechanisms

| Document | What it answers |
|---|---|
| **[matching_engine.md](matching_engine.md)** | Order book data structures, limit/market processing, and the modify-order semantics and six accounting scenarios |
| **[accounting.md](accounting.md)** | Cash escrow, order approval, position transitions including atomic flips, mark-to-market, and the NAV conservation invariant |
| **[observation_space.md](observation_space.md)** | The full 42-float snapshot: midpoint price normalization, `√V` volume scaling, `log_mid` and `log1p_spread_ticks`, temporal stacking, and the raw/normalized book split |
| **[action_space.md](action_space.md)** | The `Dict` action space, deterministic ghost-level price anchoring, and the legacy `Tuple` design it replaced |
| **[reward_function.md](reward_function.md)** | The multi-factor reward formula, its account plumbing, and a coefficient tuning guide |

### Training

| Document | What it answers |
|---|---|
| **[self_play_league.md](self_play_league.md)** | League-based self-play: champion snapshotting, weighted matchmaking, configuration, tuning, monitoring, and troubleshooting |
| **[distributed_training.md](distributed_training.md)** | `num_env_runners` and `num_learners`: what each one distributes, worked examples, and three bugs that only existed at non-default values |
| **[logging.md](logging.md)** | What training records, where it goes, and the substantial gap between what is computed and what is surfaced |

### Quality

| Document | What it answers |
|---|---|
| **[testing.md](testing.md)** | Every test file, what each case pins down, how to run the suite, and what it does not cover |
| **[known_issues.md](known_issues.md)** | A full critique — conceptual, design, implementation, hygiene, and observation-specific — with a prioritized fix list |

---

## Reading paths

**New to the codebase?**
[architecture.md](architecture.md) → [matching_engine.md](matching_engine.md) →
[accounting.md](accounting.md) → [observation_space.md](observation_space.md) →
[action_space.md](action_space.md)

**Planning changes to the RL layer?**
[known_issues.md](known_issues.md) §7 (priority order) → [observation_space.md](observation_space.md)
→ [reward_function.md](reward_function.md)

**Setting up training?**
[self_play_league.md](self_play_league.md) → [distributed_training.md](distributed_training.md)
(if running with `num_env_runners` or `num_learners` above their `0` defaults) →
[logging.md](logging.md)

**Modifying the engine or accounts?**
[matching_engine.md](matching_engine.md) §4 (invariants) → [accounting.md](accounting.md) →
[testing.md](testing.md) §1–2

---

## Conventions

- **Never hardcode observation widths.** Import `SNAPSHOT_DIM` / `BOOK_DIM` from
  [`state_helper.py`](../envs/exchg/state_helper.py). See
  [observation_space.md](observation_space.md) §1.
- **The reward is not zero-sum**, even though NAV is. See
  [reward_function.md](reward_function.md) §2.
- **Nothing enforces the test suite** — there is no CI. See [known_issues.md](known_issues.md) §4.
- **No episode is reproducible** — seeding is non-functional. See
  [known_issues.md](known_issues.md) §3.6.

---

## Compatibility shims

Four files exist only because the top-level `README.md` links to them and was left unchanged. Each
is a one-line redirect to its replacement and contains no content of its own:

| Shim | Redirects to |
|---|---|
| `change.md` | [changelog.md](changelog.md) |
| `CHANGES_obs_normalization.md` | [observation_space.md](observation_space.md) |
| `CHANGES_temporal_obs_history.md` | [observation_space.md](observation_space.md) |
| `CHANGES_obs_market_features.md` | [observation_space.md](observation_space.md) |

If `README.md` is ever updated to point at the consolidated documents, these four can be deleted.
