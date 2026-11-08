---
name: cda-add-config-key
description: Add a new configurable value (an env or training knob), or turn a literal in Python into one. Use for "make X configurable", "add a knob", or whenever a change introduces a tunable number. A checklist of every place a key must reach.
---

# Add a config key

Values live only in `config/*.json` (CLAUDE.md rule 1). Adding the fee keys once touched about
a dozen places by hand. `EnvSettings` (issue #257) has since cut that down, and this is what is
left.

## Checklist, in order

1. **JSON.** Add the key, with a `_note_<key>` saying what it does and why the default is that
   value, to `config/env_defaults.json` **and** `config/train_config.json` (an env key), or to
   `train_config.json` alone (a training-only key). Use the same default in both. Edit the root
   `config/`, never `gym_continuousDoubleAuction/config/` (a gitignored build copy).
2. **Env key:** add a field to `envs/settings.py` `EnvSettings` (in the order `env_config`
   lists them). `test_refactors.py::TestEnvSettings` holds the fields to `env_defaults.json`
   key for key. If the exchange should not receive it, add it to `ENV_ONLY`. If it is a reward
   coefficient, add it to `REWARD_KEYS`.
3. **TrainConfig:** add a field `name: type = _default("name")` in `train/config.py`. Use the
   type the values really have (`float` for a tick, see #355), because `compare --set` parses
   by the annotation. `env_config` picks the key up from `EnvSettings` automatically.
4. **Validation** that raises `ValueError` naming the key, in the layer that owns the
   invariant (`EnvSettings.__post_init__` for an env key, `TrainConfig.__post_init__` for a
   training key), and again in any class that can be built without the env.
5. **Consumer:** read it where it is used. Do not put a literal default in a signature; use the
   `UNSET` sentinel and `env_default(key)` in the body (see #358).
6. **Layout:** if it changes the observation or the action layout, bump
   `OBSERVATION_LAYOUT_VERSION` (`envs/exchg/state_helper.py`) or `ACTION_LAYOUT_VERSION`
   (`envs/exchg/action_helper.py`); `envs/layout_version.py` stamps them into every checkpoint,
   so old ones are refused by name. If a restore must not
   change it, add it to `STRUCTURAL_CONFIG_KEYS` in `train/checkpoint.py`.
7. **Tests:** a wiring test that a configured value reaches its consumer (the pattern in
   `test_config_wiring.py`), and one per validation error.
8. **Docs:** a row in `docs/18_configuration.md`. `test_s4_docs_and_tooling.py` fails if any
   key is mentioned in no document. A new CLI flag goes in `docs/26_runbook.md`.
9. **Changelog:** a new section in `docs/17_changelog.md` (never edit an old one).

## Guardrails

- Default to the value that preserves today's behaviour, and say so in the note.
- `train.compare --set` parses through `compare._coerce` by the field's annotation; check that
  the new type parses there.
- Run the unit suite, then `python tools/check_links.py` (it must print `TOTAL 0`).
