# 27. Agent skills worth building for this repository

A proposal, not a specification. Each skill below is a reusable procedure for a coding agent (a
Claude Code `SKILL.md`, or the equivalent in another agent harness) that this repository would pay
for, picked because the work it replaces was done **by hand, more than once**, in the 2026-10-07 and
2026-10-08 review, fix and documentation passes ([17](17_changelog.md) §59 to §63). Nothing here has
been built except where marked **built** in §0; that section is also the order to build them in.

How to read an entry: **Trigger** is when the agent should reach for it; **Evidence** is what the
manual version cost or got wrong; **Steps** are the procedure; **Ships with** are the scripts it
needs checked into the repo (the helper scripts used in those passes lived in a throwaway scratch
directory and were rewritten each time); **Guardrails** are the mistakes already made once.

**Where things live.** This proposal stays here, in `docs/`, because it is read and linked like the
other documents. A skill, once built, goes in `.claude/skills/<name>/SKILL.md`, the project-level
location Claude Code loads from, and carries its own scripts in `.claude/skills/<name>/scripts/`.
Only a script that several skills run lives outside them, in a top-level `tools/`: today that is
the link checker (`cda-doc-sync`, `cda-findings-sync` and `cda-branch-and-pr` all run it). The
rules in §1 go in a root `CLAUDE.md`, which is loaded every session. When a skill exists, its entry
below should shrink to a pointer to it.

---

## 0. Build order

| # | Skill | Payoff | Effort | Why this position |
|---|---|---|---|---|
| 0 | **Built:** `CLAUDE.md` | high | 1 hour | There is none. §1 lists what belongs in it. Every skill below assumes it exists |
| 1 | **Built:** `cda-doc-sync` | high | 1 day | Test counts and observation widths had drifted across more than a dozen files; the cheapest recurring chore to automate |
| 2 | **Built:** `cda-verify-finding` | high | half a day | Of about 64 raw findings in the last full review, 24 were confirmed; the rest were false positives, unreachable, or already tracked. A skill that forces the reproduction saves the false fixes |
| 3 | `cda-ledger-invariants` | high | 1 day | The only tool that found S2-14, S2-15 and the crossed-book bug; it exists as scripts, not as a procedure |
| 4 | `cda-findings-sync` | medium | 1 day | Filed 135 issues by script once; the register and the tracker will drift without it |
| 5 | `cda-add-config-key` | medium | half a day | Adding the fee keys touched 6 places; a checklist skill is enough |
| 6 | `cda-branch-and-pr` | medium | half a day | Encodes the repository's commit and branch rules, which were re-derived every session |
| 7 | `cda-refactor-scout` | low | half a day | Measure-then-file; the profile found a 24% hot spot nobody had named |
| 8 | `cda-encoder-compare`, `cda-pretrain-then-probe`, `cda-cbp-check` | research | 1 day each | Wrap the three research workflows in [18](18_configuration.md) §5.5, [23](23_probe_harness.md) Part 2 and [25](25_continual_backprop.md) with their known traps |

Skills 1 to 4 are one theme: **keep the claims, the code and the tracker saying the same thing**.
That is the repository's main maintenance cost, because [15](15_findings_and_recommendations.md),
[16](16_verification_log.md) and the 26 documents carry a lot of numbers.

---

## 1. First, a `CLAUDE.md`

`CLAUDE.md` now exists at the repository root and is loaded every session (alongside
`.claude/settings.json` and a session-start hook that builds a Python 3.12 venv). The list below is
the proposal it was built from; **the file is the current statement**, so change it there and not
here. Each point came from something that went wrong once:

1. **Config is the only source of values.** `config/*.json`, read through `config_loader`; no
   literal defaults in Python ([18](18_configuration.md)). A new key is added to *both*
   `env_defaults.json` and `train_config.json`, and `gym_continuousDoubleAuction/config/` is a
   gitignored build copy that must not be edited.
2. **History files are not edited to match the code.** [16](16_verification_log.md) and
   [17](17_changelog.md) record what was true when written. New facts get a new section.
3. **Run `pytest`, never `python test_x.py`** ([10](10_testing.md) §0). The full suite is about four
   minutes (`test/` unit, then `test/integration/`). CI's smoke run is
   `python gym_continuousDoubleAuction/CDA_rand.py` with no arguments (the defaults);
   `CDA_rand --steps 200 --agents 4` is the manual check in [26](26_runbook.md).
4. **Test first, and show it failing.** A fix lands with a regression test that fails on the
   previous source (`git stash push -- gym_continuousDoubleAuction/envs` is the quick way to check).
5. **Atomic commits**, one fix per commit ([CONTRIBUTING](CONTRIBUTING.md)): code, then tests,
   then docs. After a PR merges, restart the working branch from `master`.
6. **Do not rest an unverified claim on a review.** Reproduce it first (skill 2).
7. **Counts move together.** Any new test file changes the unit total, the suite total, the
   line count in [14](14_perspective_ai_engineer.md) and the inventory in [10](10_testing.md).
8. **GitHub quirks of this environment:** links with a `#fragment` came out of the proxy wrapped in
   backticks (so they render as code, not links) in 21 of 135 issue bodies. It was not length
   alone: short fragment links pinned to a commit SHA were wrapped in a test, and links to `master`
   were wrapped once they were long (the shortest wrapped one was 153 characters; some fragment
   links up to 221 were not). Link to files, not anchors, in issue text. The REST create call did
   not set the issue `type`; use the issue tool and read the type back in the UI. GraphQL is blocked.

It was built with the existing `init` skill and trimmed to these points.

---

## 2. The skills

### `cda-doc-sync`

**Built:** [`.claude/skills/cda-doc-sync/SKILL.md`](../.claude/skills/cda-doc-sync/SKILL.md), with
`scripts/facts.py` and `scripts/claims.py` beside it and the shared `tools/check_links.py`. Read the
skill for the procedure; it is the one description of it.

**Evidence.** At the start of the 2026-10-07 pass the docs gave 1,144 unit tests (actual 1,173), had
153, 156, 165 and 112 integration tests in different files (actual 163), and called the
observation 216 floats in 17 current-tense lines (actual 233). 18 config keys and 9 CLI flags were
documented nowhere ([#249](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/249),
[#250](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/250)).

---

### `cda-verify-finding`

**Built:** [`.claude/skills/cda-verify-finding/SKILL.md`](../.claude/skills/cda-verify-finding/SKILL.md).
Read the skill for the procedure; it is the one description of it.

**Evidence.** Of about 64 raw findings in the last full review, 22 issues were filed (some
consolidating several findings) and 3 more were added as comments on existing ones. Dropped after a
reproduction or a careful read: "all agents draw identical actions" (the agents share one space
object, so seeding it repeatedly is harmless), a `None` sort key that cannot occur because the mark
is shared, a split cover said to escape the loss reserve (it does not: the total realised is the same).
While checking one PR review's findings, the agent's own first reproduction was wrong (a second bid
at the same price *replaced* the first rather than adding to it), which is the kind of mistake the
skill exists to catch.

---

### `cda-ledger-invariants`

**Trigger.** A change to `envs/orderbook/`, `envs/account/`, `envs/agent/trader.py`, the matching
regimes, fees or liquidation; or any report of negative cash, broken NAV conservation or a crossed
book.

**Evidence.** Seeded random play found what no example test had: 11 and 29 overdrawn agent-steps of
51,200 under batch clearing (S2-14), 32 and 61 under sequential (S2-15), and a crossed book that
made the next batch raise `KeyError`. The Hypothesis suite covers the book alone; these properties
need the whole env.

**Steps.** For each of `{sequential, batch} x {fees 0, 100 bps} x {liquidation off, market_adl}`,
run 160 seeded episodes of 80 steps (4 agents, 3,000 cash, prices 20 to 60, action spaces seeded
per episode) and assert, every step:
1. `sum(NAV) + env.fees_collected == agents x init_cash`, exactly;
2. `cash + cash_on_hold >= 0` for every trader;
3. `best_bid < best_ask`;
4. no `KeyError`, `AssertionError` or `RuntimeError` out of `step`.

Report agent-steps hit, seeds hit and the worst value per row, **before and after** the change
(stash the source to get "before").

**Ships with.** `scripts/scan_ledger.py` (the `scan160_all.py` of the passes), parameterised on the
config grid, printing the table above.

**Guardrails.** Unseeded `action_space.sample()` makes a failure unrepeatable; seed every space.
Pick the seeds that failed on the old code and keep them in a unit test. 160 seeds is minutes, not
seconds: keep it out of the default suite and run it when the ledger changes.

---

### `cda-findings-sync`

**Trigger.** A finding is added, fixed or re-scoped in [15](15_findings_and_recommendations.md); or
"file the issues"; or "close the resolved ones".

**Evidence.** 135 issues (#91 to #225) were created from the register by one script, 91 closed with
the doc's own resolution text, 44 left open, and each doc entry back-linked. Without a procedure the
register and the tracker disagree within a week.

**Steps.**
1. Parse the register: headed S1 to S3 entries, the S4 table, the R table, the legacy table, the
   open test gaps in [10](10_testing.md) §8.
2. Map status to state: `fixed` closes (reason *completed*, comment quoting the resolution and the
   fixing commits); `open`, partial and `[verified]`-with-no-fix stay open.
3. Labels: `S1-blocking` to `S4-minor`, `bug` or `enhancement`, `needs-decision` for open design
   questions, `question` when the finding was **not reproduced**.
4. Type through the issue tool (Bug, Task, Feature), not the REST body.
5. Write the `#N` back into the doc as a line under the heading (not in it: that keeps anchors).
6. Idempotent: match existing titles before creating; record numbers in a state file.

**Ships with.** `scripts/findings_to_issues.py` (manifest builder) and a dry-run mode that prints the
table of key, state, labels and title before anything is created.

**Guardrails.** No `#fragment` links in issue bodies. At about a second per write the full set (over 300 writes, with comments and closes) took about
10 minutes; a rate-limit retry must not double-create. Closing needs a comment first.

---

### `cda-add-config-key`

**Trigger.** "Add a knob", "make X configurable", or any new literal in Python that is a tunable.

**Evidence.** The fee keys touched `config/env_defaults.json`, `config/train_config.json`,
`TrainConfig` (two fields and `env_config`), `Account`, `Trader`, the env constructor and validation,
`train.compare --set` parsing, the callback's NAV check, [04](04_accounting.md), [18](18_configuration.md),
[10](10_testing.md) and the changelog ([#257](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/257)
proposes a settings object that would shrink this list).

**Steps.** A checklist, in order: JSON key plus a `_note` in both files, with the same default; the
`TrainConfig` field and its `env_config` entry; validation that raises `ValueError` naming the key,
in the layer that owns the invariant (and again in any class that can be built directly); the wiring
test (a configured value reaches its consumer: `test_config_wiring.py`'s pattern); whether it
changes the observation or action layout (then bump the version in `envs/layout_version.py` and
refuse old checkpoints by name); the doc 18 row; whether a checkpoint restores across it.

**Guardrails.** Default to the value that preserves behaviour and say so in the note (the fees
ship at 0). `gym_continuousDoubleAuction/config/` is a gitignored copy: edit the root `config/`.

---

### `cda-branch-and-pr`

**Trigger.** "Commit", "push", "file the PR", "review PR N", or the end of any change.

**Steps.**
1. If the designated branch's PR is merged, `git checkout -B <branch> origin/master` (carrying
   uncommitted work with a stash) before committing; never stack on merged history.
2. Atomic commits in the order code, tests, docs; each message states what was wrong and what
   changed, ends with the required trailer lines, and names no model.
3. Run the full suite and the link check before pushing; re-run after any rebase.
4. Open the PR with `Fixes #N` for each issue it closes, the measured before and after, the
   behaviour change in plain words, and an unchecked box for anything not re-run.
5. After pushing to a branch with an open PR, update the PR description's counts (they go stale).
6. On "review PR N": run the review, then **verify each finding** (`cda-verify-finding`) before
   reporting, fix the confirmed ones as separate commits, say plainly which were dropped and why.

**Guardrails.** Do not open a PR unprompted. A PR title and body carry no model identifier. The
issue a user names may be the wrong number (S2-14 is #109, not #99): look it up.

---

### `cda-refactor-scout`

**Trigger.** "Is there code to refactor?", a performance complaint, or before a large change to a
module.

**Evidence.** Measuring first gave a different list from reading: `info_helper._plain` (127,200
recursive calls per 300 steps, 19% of a step) and the action mask (24%) were not on anyone's list;
the length and nesting table named `clear_batch`, the league callback and `train/train.py`
([#252](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/252) to
[#259](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/259)).

**Steps.** `ast` metrics (code lines excluding docstrings, branch points, nesting depth) for every
non-test function; the duplicate-block scan; `cProfile` over 300 steps of an 8-agent episode in each
clearing mode; read the top of each list; file one issue per cohesive change with the numbers, label
`refactor`, type Task; **change nothing**.

**Ships with.** `scripts/code_metrics.py` and `scripts/profile_episode.py`.

**Guardrails.** Textual duplication was low here; the problems were long functions and mirrored
bid/ask code, so do not stop at a duplicate scan. A refactor issue states that behaviour must not
change and that the suite is the guard.

---

### `cda-encoder-compare`

**Trigger.** "Does encoder X learn better?", "compare the encoders", a new encoder.

**Evidence.** The largest test gap ([10](10_testing.md) §8, [#206](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/206)):
no run at scale (16 iterations, three seeds, every encoder) has been done, so no claim that one
encoder trades better than another is supported.

**Steps.** Run `python -m gym_continuousDoubleAuction.train.compare` per
[18](18_configuration.md) §5.5 with separate runs per (encoder, seed), the same corpus for the probe,
and `--set` overrides parsed as the CLI parses them; report per-encoder means and standard
deviations across seeds with parameter counts; end with one sentence on what the result **does
not** show (returns are noise at this scale; the probe is reward-free).

**Guardrails.** Say how many seeds. Do not turn a smoke-scale run into a ranking.
`--set` booleans silently become `False` on a typo ([#236](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/236)): echo the parsed config.

---

### `cda-pretrain-then-probe`

**Trigger.** Pretraining a JEPA encoder, or scoring one on the probe harness.

**Steps.** Pretrain with `train.pretrain`; read `latent_std` before the loss, since a collapsed run
has an excellent loss ([23](23_probe_harness.md) Part 2); probe with `--pretrained <dir> --pretrained-encoder jepa`
against the held-out fifth; compare to the untrained encoder on the same targets and horizons; report
the effective rank per feature set.

**Guardrails.** The command no longer saves a collapsed or NaN run (issue #239, changelog
[17](17_changelog.md) §72), but the skill should still read `latent_std` itself rather than trust an exit code alone. The
probe's `--per-agent` mode shifts targets by rows, not steps ([#188](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/188)): do not use it for horizon targets.

---

### `cda-cbp-check`

**Trigger.** Turning on Continual Backprop for a run, or reading its metrics.

**Steps.** Build the module for the chosen encoder and count replaceable layers (mlp 4, transformer
4, moe_transformer 16, jepa 6, **lstm 0** under `cbp_scope: "feedforward"`, where CBP does nothing and only warns, and 2 under `"recurrent"`, S3-32); confirm
the cadence caveat in [25](25_continual_backprop.md) (the papers' hyperparameters cannot be copied at
this repo's update rate); log the three correlates (dead-unit fraction, weight magnitude, rank) and
read them against a CBP-off run on the same seed.

**Guardrails.** With `num_learners > 1` the replicas can diverge ([#182](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/182)); the rank metric is a threshold rank, not the papers' entropy rank.

---

## 3. Existing skills to reuse, not rebuild

| Skill | Use it for here |
|---|---|
| `code-review` | Whole-codebase passes **in slices** (orderbook/account/agent; exchg/env; train core; model; probe/pretrain/visualize), with `--max-findings all`; a single run over the package hit session limits |
| `simplify` | Carrying out a refactor issue after it is accepted. It *applies* changes, so only on a branch |
| `init` | The `CLAUDE.md` in §1 |
| `session-start-hook` | Already present as `.claude/hooks/session-start.sh` (Python 3.12 venv, CPU torch from PyPI because the pytorch.org host is unreachable from the sandbox) |
| `skill-creator` | Writing and evaluating the skills above |
| `update-config` / `fewer-permission-prompts` | An allowlist for the read-only commands these skills run (`pytest --collect-only`, `git log`, `gh api` GETs) |

## 4. A skeleton, for the first one

```markdown
---
name: cda-doc-sync
description: Bring README.md and docs/*.md in line with the code after a change to tests, layouts,
  reward terms, config keys, CLI flags or the package tree. Use when asked to update, sync or audit
  the docs, or after adding a test file or a config key. Does not edit docs/16 or docs/17 history.
---

1. Run `python scripts/facts.py > /tmp/facts.json` (collects tests, widths, terms, keys, flags, tree).
2. Run `python scripts/claims.py /tmp/facts.json` and triage every `file:line claimed -> actual` hit
   as current (fix) or historical (leave). Never edit docs 16 and 17 except to append a section.
3. Recompute the dependent figures in doc 10 (inventory, mindmap), doc 14 (code size), doc 26.
4. Run `python tools/check_links.py .`; fix every broken link, including anchors after heading edits.
5. Append a numbered section to docs/17_changelog.md listing each correction by file.
6. Report counts before and after, and anything left as historical, with the reason.
```

## 5. Not worth building

- **A training-launch skill.** [26](26_runbook.md) is already the operator's page and every command
  in it was run; a skill would restate it. Keep the runbook current (skill 1) instead.
- **A generic "run the tests" skill.** One line in `CLAUDE.md` covers it.
- **A plotting skill.** `visualize.run_all` regenerates every chart; the reusable part is the
  reward-term colour table, which a test already pins (`test_visualize_reward_terms.py`).
