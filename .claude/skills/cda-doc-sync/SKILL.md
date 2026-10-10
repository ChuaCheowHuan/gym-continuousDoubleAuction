---
name: cda-doc-sync
description: Bring README.md and doc/*.md back in line with the code after a change to tests, the observation or action layout, reward terms, config keys, CLI flags or the file tree, or when asked to "update the docs". Computes the facts from the code, lists every doc line that disagrees, then fixes the current-tense ones.
---

# Keep the docs saying what the code does

The docs carry many numbers (test counts, observation widths, head counts, config keys, flags).
They drift. Work from the code, not from the docs.

## Steps

1. **Compute the facts** (about two minutes, it collects the whole suite):
   `python .claude/skills/cda-doc-sync/scripts/facts.py . "$TMPDIR/facts.json"`
   It writes test totals and per-file counts, the observation width in `grid` and `levels` mode,
   the private-block fields, the action heads, `REWARD_TERMS`, the encoders, every config file, each
   entry point's flags and the file tree.
2. **List disagreements:**
   `python .claude/skills/cda-doc-sync/scripts/claims.py . "$TMPDIR/facts.json"`
   Output is `category  file:line  claimed -> actual  | line`. `16_verification_log.md`,
   `17_changelog.md` and `27_agent_skills.md` are skipped on purpose.
3. **Triage every hit.** Current tense is corrected. Historical ("193 to 216 with the own-book
   block", "was 168 floats") is left alone. A measured figure that reads as current gets the
   current value added beside it. A hit may be a number that only sits near a noun; ignore those.
4. **Recompute the dependent figures** that the scanner cannot see: the per-file inventory and the
   coverage mindmap in `doc/10_testing.md`, the code size in `doc/14_perspective_ai_engineer.md`,
   the expected lines in `doc/26_runbook.md` (§26.2). Take them from `facts.json`.
5. **Check links:** `python tools/check_links.py`. It must print `TOTAL 0`. Re-run it after any
   heading edit: renaming a heading breaks anchors in other files.
6. **Render any changed Mermaid block** with `@mermaid-js/mermaid-cli` before committing.
7. **Record the pass** as a new section in `doc/17_changelog.md`. Never edit an old section, and
   never edit `doc/16` to match the code: both are history.

## Guardrails

- A "1,000-unit drawdown" is not a test count. The scanner has a minimum size per category; extend
  it rather than reading past noise.
- Counts move together. A new test file changes the unit total, the suite total, the line count in
  doc 14 and the inventory in doc 10.
- Commit docs separately from code (atomic commits), after the code and tests.
- A test that fails when a config key or CLI flag is documented nowhere would turn steps 1 and 2
  into CI. Issues #249 and #250 track the undocumented keys and flags.
