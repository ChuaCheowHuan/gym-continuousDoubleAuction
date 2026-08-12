# `gym-continuousDoubleAuction` — Consolidated Documentation

This folder merges the two previous documentation sets — `gym_continuousDoubleAuction/doc/`
(17 files: 12 topic documents, an index, and 4 redirect shims) and `doc_new/` (8 analysis
files) — into one structured set. Both source folders are left untouched, as is the top-level
`README.md` and all code.

**Merge rules applied.** Where the two sets disagreed, `doc_new/` content took priority, but
every disputed claim was re-checked against the source tree and, where behavioural, re-executed.
A dozen claims from the older set were found stale (CI, `.gitignore`, champion eviction, the
model bottleneck, an `expectedFailure` test) and one arithmetic slip in the newer set was
corrected. The full list is in [§ Reconciliation](#reconciliation-of-the-two-source-sets) below,
and every re-run probe is in [16_verification_log.md](16_verification_log.md).

Claims marked **[verified]** were confirmed by executing code against the working tree on branch
`update_lib`. Everything else was confirmed by reading the implementation.

---

## Reading order

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
| 9 | [09_distributed_training.md](09_distributed_training.md) | `num_env_runners` and `num_learners`: what each distributes, worked examples, and three bugs that existed only at non-default values |
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

## One-paragraph summary

The repository implements a **multi-agent continuous double auction** — a price/time-priority
limit order book exchange — packaged as a Gymnasium / RLlib `MultiAgentEnv`, together with a
**league-based self-play PPO training stack** on Ray RLlib 2.56.1's new API stack. Agents are
traders that submit market/limit/modify/cancel orders into a shared book, are marked to market
against the tape, and are rewarded on a multi-term NAV-based function. The matching engine, the
`Decimal` accounting, and the RLlib league wiring are substantially correct and well covered by
tests (90 unit tests + 13 integration tests across 3 topologies, all passing). The weak points
are concentrated in the **learning problem formulation** rather than in the simulator: agents
observe no private state, the reward is strictly negative-sum with a dominant do-nothing
strategy, and the reward scale silently disables PPO's critic entirely.

## Repository facts (measured)

| Metric | Value |
|---|---|
| Python source files | 63 |
| Total Python LOC | 7,478 |
| Env + order book LOC | ~2,000 |
| Training stack LOC | ~1,100 |
| Test LOC | ~2,430 |
| Unit tests | 90, all passing **[verified]** |
| Integration tests | 13, in 3 classes (local learner, remote EnvRunner, remote LearnerGroup) |
| Runtime stack | Python 3.12, Ray 2.56.1, Gymnasium 1.2.2, PyTorch 2.13.0, NumPy 2.5 |
| CI | GitHub Actions, Python 3.11 + 3.12 matrix, three staged jobs |
| Current branch | `update_lib` (ahead of `master` by the Ray 2.56 migration) |

---

## Conventions

- **Never hardcode observation widths.** Import `SNAPSHOT_DIM` / `BOOK_DIM` from
  [`state_helper.py`](../gym_continuousDoubleAuction/envs/exchg/state_helper.py). See
  [05_observation_space.md](05_observation_space.md) §1.
- **NAV is zero-sum; the reward is not.** Total NAV across traders is conserved exactly, but the
  four shaping terms are not, so returns are not comparable across policies playing different
  roles. See [07_reward_function.md](07_reward_function.md) §2.
- **No episode is reproducible.** Seeding is non-functional: the env draws from global
  `np.random` and the action shuffle is always passed `random_state=None`. See
  [15_findings_and_recommendations.md](15_findings_and_recommendations.md) S3-5.
- **The default config is the single-process one.** `num_env_runners=0, num_learners=0` is the
  only configuration where the driver's objects and the "remote" objects are the same object.
  Three real bugs lived in that gap. See [09_distributed_training.md](09_distributed_training.md).

---

## Reconciliation of the two source sets

Every point where `doc/` and `doc_new/` disagreed, with the source-verified resolution.

| # | Claim | `doc/` said | `doc_new/` said | Resolution |
|---|---|---|---|---|
| 1 | Continuous integration | "doubly dead — `.travis.yml` targets a defunct service, there is no `.github/`" | GitHub Actions, 3.11/3.12 matrix, three staged jobs | **`doc_new` correct.** `.github/workflows/tests.yml` exists and runs unit tests → random-agent smoke run → RLlib integration. `.travis.yml` was deleted. |
| 2 | `episode_data/` in `.gitignore` | "absent from `.gitignore`, untracked noise after every run" | "`.gitignore` covers the artefact paths" | **`doc_new` correct.** Both `episode_data` and `gym_continuousDoubleAuction/episode_data` are ignored, with a comment explaining the working-directory subtlety. |
| 3 | Per-episode pickles | "written **unconditionally** — every episode, every worker, no cap, no flag" | "configurable to `None`; the default in both `TrainConfig` and the notebook is on" | **`doc_new` correct.** `SelfPlayCallback(episode_data_dir=...)`; `--no-episode-data` on the CLI. The volume concern remains valid. |
| 4 | Evicted champions | "`_remove_oldest_champion` never frees the removed module; league memory grows monotonically" | not claimed | **`doc/` stale.** The callback now calls `Algorithm.remove_module`, with the old behaviour described in a code comment. |
| 5 | `test_modify_order_price_change` | "marked `@unittest.expectedFailure` — documents a known limitation" | not mentioned | **`doc/` stale.** There is no `expectedFailure` anywhere in the repository; the test asserts `get_best_bid() == 101` and passes. The matching-engine invariant "no crossed resting book" is therefore fully, not partially, satisfied. |
| 6 | Trainable network | "whatever survives is squeezed through `Linear(160, 8)`" | `fcnet_hiddens=[256, 256]`, `tanh`, `vf_share_layers=False` | **`doc_new` correct.** See [`model_handler.py`](../gym_continuousDoubleAuction/train/model/model_handler.py). |
| 7 | Env spaces | "`observation_space` / `action_space` are plain dicts, not Spaces — modern RLlib expects the plural form" | not claimed | **`doc/` stale.** The env now exposes `observation_spaces` / `action_spaces` plus `get_observation_space(agent_id)` / `get_action_space(agent_id)`, and agent ordering is built from a sorted list for cross-process stability. |
| 8 | Matchmaking seed | "`hash(episode.id_)` — salted per process, so not reproducible" | `zlib.crc32`, reproducible across processes | **`doc_new` correct.** The `crc32` fix landed with the Ray 2.56 migration. |
| 9 | Max limit order size | `mkt_max_size = 100`, `limit_max_size = 1000` | "limit orders up to 5,000 contracts, `limit_max_size = 100 × 10`" | **`doc/` correct.** `limit_max_size = 100 × 10 = 1000`; `limit_size_mean_mul = 499.5`, so a full-scale draw is ≈ 500 contracts, not 5,000. **[verified]** |
| 10 | League example script | `example_league_based_training.py` presented as runnable | listed as deleted | **Deleted.** Do not reference it. |
| 11 | Feature-scale spread | "normalized prices ±0.7 vs `sqrt(volume)` ±430 — ~600×" | "±0.26 vs ±51 — ~250×" | **Both are book-dependent measurements of the same real defect.** An independent run measured ±0.58 vs ±47 (~80×). The invariant claim — sizes exceed prices by one to two orders of magnitude into a `tanh` layer — holds in every run. **[verified]** |
| 12 | Unit test count | "~89" | 90 | **90**, all passing. **[verified]** |
| 13 | `setup.py` | "broken for non-editable installs — RESOLVED" | "`install_requires` does not match the imports (`ray`, `sklearn`, `six`)" | **Both true, of different things.** Packaging works; the dependency manifest is still wrong. See [14](14_perspective_ai_engineer.md) §5.3. |
| 14 | Value function | "the README's own sample output shows `vf_explained_var: 0.0` — the value function never learned anything" | Diagnoses the mechanism: `vf_clip_param=10.0` vs value targets of 10⁴–10⁶ | **Complementary.** `doc/` spotted the symptom; `doc_new` found the cause. Both reproduced. **[verified]** |
| 15 | Callback defaults | `std_dev_multiplier=2.0`, `max_champions=5`, `min_iterations_between_champions=10` | not stated | **Neither.** The constructor signature defaults are `2.0 / 2 / 2`; `TrainConfig` overrides them to `0.1 / 8 / 2`. The `5 / 10` figures were from a superseded revision. |

### Findings unique to `doc/` that `doc_new` does not cover

These survived the merge because they are real and still present in the tree:

- **Every frame in the observation stack is normalized by its own midpoint**
  ([05](05_observation_space.md) §7.1) — frames cannot be differenced meaningfully, which
  defeats the purpose of stacking.
- **`0.0` means three different things** in the observation ([05](05_observation_space.md) §7.2)
  — empty level, price exactly at the midpoint, and the L1 price of a one-sided book.
- **The tape loop in `set_agg_LOB` is dead code** ([05](05_observation_space.md) §7.3) — it
  iterates the tape, uses nothing, and leaves the observation with zero trade-flow information.
- **Level index is a non-stationary coordinate** ([05](05_observation_space.md) §7.4) — slot *k*
  means "the *k*-th occupied price", and the action space selects by the same unstable index.
- **Silent no-ops give no learning signal** ([12](12_perspective_rl_researcher.md) §5.6) —
  rejected and unmatched orders return empty lists with nothing logged or surfaced in `infos`.
- **`test_shared_history_multi_agent_uniformity` cements the design flaw** as a requirement
  ([10](10_testing.md) §4.2) — it must be deleted the moment private state is added.

### Findings unique to `doc_new` that `doc/` does not cover

- The **`vf_clip_param` saturation mechanism** and its measured consequences (S1-1).
- The **four load-bearing ordering constraints** in champion snapshotting ([08](08_self_play_league.md) §5).
- **Checkpoint/restore actually preserves league state**; the narrower defect is that
  `build_algo` returns a detached callback on the restore path (S3-7).
- **Self-matching as a mark-manipulation channel** (S2-5).
- The **premise guards** on the remote integration test classes ([10](10_testing.md) §6).
