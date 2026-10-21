# Contributing

You are free to download, clone, fork and use this repository. If you find it useful, please
**reference it** in your work (see [How to cite](../README.md)).

Pull requests are welcome. **Open an issue first** to agree on the scope, so nobody's time is
wasted on work that will not be merged.

---

## 1. Set up

Python 3.12 is the only version CI tests.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev]"      # pytest, pyflakes, hypothesis, pytest-cov, mypy, ruff
```

On a CPU-only machine, install the CPU torch wheel first ([00_getting_started.md](00_getting_started.md) §0.3).

## 2. The rules a change has to follow

| Rule | What it means in practice | Details |
|---|---|---|
| **Config is the only source of values** | Values live in `config/*.json` and are read through `config_loader`. No literal defaults in Python. A new key goes in both `env_defaults.json` and `train_config.json`. Never edit `gym_continuousDoubleAuction/config/`: it is a gitignored build copy | [18_configuration.md](18_configuration.md) |
| **Test first, and show it failing** | A fix lands with a regression test that fails on the previous source: `git stash push -- gym_continuousDoubleAuction/envs`, run the test, `git stash pop` | [10_testing.md](10_testing.md) |
| **Atomic commits** | One fix per commit, in the order code, then tests, then docs | |
| **Reproduce before you fix** | A claim from a review, a linter or a bot is reproduced on the current source before anything is built on it | [`cda-verify-finding`](../.claude/skills/cda-verify-finding/SKILL.md) |
| **History is append-only** | [16_verification_log.md](16_verification_log.md) and [17_changelog.md](17_changelog.md) record what was true when they were written. New facts get a new section; old ones are not edited to match the code | |
| **Counts move together** | A new test file changes the unit total, the suite total, the code size in [14](14_perspective_ai_engineer.md) and the inventory in [10](10_testing.md) | [`cda-doc-sync`](../.claude/skills/cda-doc-sync/SKILL.md) |

## 3. Check before you push

```bash
ruff format .                                                      # the suite fails on unformatted code
python -m pytest gym_continuousDoubleAuction/test -q               # unit tests, ~3 minutes
python gym_continuousDoubleAuction/CDA_rand.py                      # CI's random-agent smoke run
python -m pytest gym_continuousDoubleAuction/test/integration -q   # real RLlib builds, ~3.5 minutes
python tools/check_links.py                            # must report 0 broken links
```

The suite also runs:

- `pyflakes` over the package, `tools/` and the skill scripts, so an unused import fails;
- `mypy` over `envs/`, which must have zero errors;
- `ruff format --check .`;
- the link checker, over `README.md` and `docs/`, `CLAUDE.md` and the skills.

`pytest --cov` fails below the floor set in `pyproject.toml`.

To see the pyflakes messages directly, run `python -m pyflakes gym_continuousDoubleAuction`
(pyflakes is in the `dev` extra). The Hypothesis-driven `test_orderbook_properties.py` runs in the
unit step; if it fails, the shrunk failing example it prints is the bug report.

The `packaging` CI job also builds the wheel and imports it from a directory with no checkout.
Reproduce it with `python -m build --wheel` and a clean venv if you touched `setup.py`,
`MANIFEST.in` or the config tree.

The push credential used by the hosted review sessions has no `workflow` scope, so a change to
`.github/workflows/` from one of those is rejected on push ([17](17_changelog.md) §37). Make
workflow edits from a local checkout.

What CI runs, job by job, is in [10_testing.md](10_testing.md).

## 4. Documentation

Everything except `README.md` lives in `docs/`; its [index](map.md) says which document owns
which topic. `README.md` is an overview only: put detail in the document that owns the topic, and
link to it.

When you change behaviour, update the document that describes the current state of that area,
including its diagrams. For a change worth recording, add a new section to
[17_changelog.md](17_changelog.md).

A change to behaviour is recorded in three places by convention: the finding or its status in
[15](15_findings_and_recommendations.md) (open) or [29](29_fixed_issues.md) (fixed), the
measurement in [16](16_verification_log.md), and the narrative in [17](17_changelog.md). A change
to the test inventory updates [10](10_testing.md) and the totals quoted in
[00](00_getting_started.md), [01](01_overview.md), [02](02_architecture.md),
[14](14_perspective_ai_engineer.md) and [15](15_findings_and_recommendations.md).

## 5. Reviews and issues

A review files each confirmed finding as a GitHub issue rather than fixing it in place. Each
issue gets:

- a severity label, `S1-blocking` to `S4-minor`;
- one of `bug`, `enhancement`, `documentation`, `test-gap` or `refactor`;
- an issue type: Bug, Task or Feature.

The findings register is [15_findings_and_recommendations.md](15_findings_and_recommendations.md) for
what is open; a finding moves, under the same ID, to [29_fixed_issues.md](29_fixed_issues.md) when it
is fixed.
