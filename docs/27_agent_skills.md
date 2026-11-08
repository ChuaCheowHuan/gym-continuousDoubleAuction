# 27. Agent skills worth building for this repository

A proposal, not a specification. Each skill below is a reusable procedure for a coding agent (a
Claude Code `SKILL.md`, or the equivalent in another agent harness) that this repository would pay
for, picked because the work it replaces was done **by hand, more than once**, in the 2026-10-07 and
2026-10-08 review, fix and documentation passes ([17](17_changelog.md) §59 to §63). Five are built
(§0 marks them); the rest are proposals, and §0 is also the order to build them in.

How to read an entry: **Trigger** is when the agent should reach for it; **Evidence** is what the
manual version cost or got wrong; **Steps** are the procedure; **Ships with** are the scripts it
needs checked into the repo (the helper scripts used in those passes lived in a throwaway scratch
directory and were rewritten each time); **Guardrails** are the mistakes already made once.

**Where things live.** This proposal stays here, in `docs/`, because it is read and linked like the
other documents. A skill, once built, goes in `.claude/skills/<name>/SKILL.md`, the project-level
location Claude Code loads from, and carries its own scripts in `.claude/skills/<name>/scripts/`.
Only a script that several skills run lives outside them, in a top-level `tools/`: today that is
the link checker (`cda-doc-sync` and `cda-branch-and-pr` run it, and `test_links.py` does in CI). The
rules in §1 go in a root `CLAUDE.md`, which is loaded every session. When a skill exists, its entry
below should shrink to a pointer to it.

---

## 0. Build order

| # | Skill | Payoff | Effort | Why this position |
|---|---|---|---|---|
| 0 | **Built:** `CLAUDE.md` | high | 1 hour | Every skill below assumes it exists |
| 1 | **Built:** `cda-doc-sync` | high | 1 day | Test counts and observation widths had drifted across more than a dozen files; the cheapest recurring chore to automate |
| 2 | **Built:** `cda-verify-finding` | high | half a day | Of about 64 raw findings in the last full review, 24 were confirmed; the rest were false positives, unreachable, or already tracked |
| 3 | **Built:** `cda-ledger-invariants` | high | 1 day | The only tool that found S2-14, S2-15 and the crossed-book bug; now a script and a procedure |
| 4 | **Built:** `cda-issue-triage` | medium | half a day | Filing, closing, splitting and the `agent` / `human` label; replaces the `cda-findings-sync` proposal (§2) |
| 5 | **Built:** `cda-add-config-key` | medium | half a day | Adding the fee keys touched about a dozen places; a checklist skill is enough |
| 6 | `cda-branch-and-pr` | medium | half a day | Encodes the repository's commit and branch rules, which were re-derived every session |
| 7 | `cda-refactor-scout` | low | half a day | Measure-then-file; the profile found a 24% hot spot nobody had named |
| 8 | `cda-encoder-compare`, `cda-pretrain-then-probe` | research | 1 day each | Wrap the research workflows in [18](18_configuration.md) §5.5 and [23](23_probe_harness.md) Part 2 |

Skills 1, 2 and 4 are one theme: **keep the claims, the code and the tracker saying the same thing**.
That is the repository's main maintenance cost, because [15](15_findings_and_recommendations.md),
[16](16_verification_log.md) and the 26 documents carry a lot of numbers.

---

## 1. First, a `CLAUDE.md`

`CLAUDE.md` at the repository root is loaded every session, alongside `.claude/settings.json` and
a session-start hook that builds a Python 3.12 venv. It was built from a list in this section,
each point from something that went wrong once; **the file is the current statement**, so it is
not repeated here. Change it there.

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

**Built:** [`.claude/skills/cda-ledger-invariants/SKILL.md`](../.claude/skills/cda-ledger-invariants/SKILL.md),
with `scripts/scan_ledger.py`. Read the skill for the procedure; it is the one description of it.

**Evidence.** Seeded random play found what no example test had: 11 and 29 overdrawn agent-steps of
51,200 under batch clearing (S2-14), 32 and 61 under sequential (S2-15), and a crossed book that
made the next batch raise `KeyError`. The scripts lived in a throwaway scratch directory and were
rewritten each pass. Its first run as a skill (2026-11-08) was clean on every row.

---

### `cda-issue-triage`

**Built:** [`.claude/skills/cda-issue-triage/SKILL.md`](../.claude/skills/cda-issue-triage/SKILL.md).
Read the skill for the procedure; it is the one description of it.

It replaces the `cda-findings-sync` proposal. That one bulk-filed the register as issues (135 of
them, #91 to #225, by one script); every finding is an issue now, so what recurs is filing one
confirmed finding at a time, closing what merged, splitting an issue that needs both a person and
an agent, and the `agent` / `human` label.

---

### `cda-add-config-key`

**Built:** [`.claude/skills/cda-add-config-key/SKILL.md`](../.claude/skills/cda-add-config-key/SKILL.md).
Read the skill for the procedure; it is the one description of it.

**Evidence.** The fee keys touched `config/env_defaults.json`, `config/train_config.json`,
`TrainConfig`, `Account`, `Trader`, the env constructor and validation, `train.compare --set`
parsing, the callback's NAV check and four documents. `EnvSettings` (#257) has since removed the
constructor and `env_config` steps.

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

**Steps.** Pretrain with cda-jepa's `python -m cda_jepa.pretrain`; read `latent_std` before the loss, since a collapsed run
has an excellent loss ([23](23_probe_harness.md) Part 2); probe with `--pretrained <dir> --pretrained-encoder jepa`
against the held-out fifth; compare to the untrained encoder on the same targets and horizons; report
the effective rank per feature set.

**Guardrails.** The command no longer saves a collapsed or NaN run (issue #239, changelog
[17](17_changelog.md) §72), but the skill should still read `latent_std` itself rather than trust an exit code alone. The
probe's `--per-agent` mode shifts targets by rows, not steps ([#188](https://github.com/ChuaCheowHuan/gym-continuousDoubleAuction/issues/188)): do not use it for horizon targets.

---

### `cda-cbp-check`

Moved: Continual Backprop is the [cda-cbp](https://github.com/ChuaCheowHuan/cda_cbp) package, so a
skill for turning it on and reading its metrics belongs in that repository, not here.

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

## 4. Not worth building

- **A training-launch skill.** [26](26_runbook.md) is already the operator's page and every command
  in it was run; a skill would restate it. Keep the runbook current (skill 1) instead.
- **A generic "run the tests" skill.** One line in `CLAUDE.md` covers it.
- **A plotting skill.** `visualize.run_all` regenerates every chart; the reusable part is the
  reward-term colour table, which a test already pins (`test_visualize_reward_terms.py`).
