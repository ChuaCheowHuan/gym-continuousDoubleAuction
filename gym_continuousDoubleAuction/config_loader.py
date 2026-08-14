"""Single point of entry for every configured value in the project.

Nothing in this codebase defines a literal for a value that belongs to
configuration. The files in `config/` are the only place those numbers exist,
and this module is how the rest of the package reads them:

    from gym_continuousDoubleAuction.config_loader import group, value

    layout = group("tunable_constants.json", "observation_layout")
    k_rows = layout["k_rows"]

Design rules this module enforces:

* **A missing key raises.** There is no `.get(key, some_default)` anywhere,
  because a default written in Python is exactly the hardcoded value this
  module exists to remove. A key absent from the JSON is a configuration bug
  and fails loudly, naming the file, the group, and the keys that *are*
  present.
* **`_`-prefixed keys are documentation.** `_source`, `_note`, `_description`
  are stripped recursively before anything sees the data, so the files can stay
  self-explaining without polluting the value namespace.
* **Files are read once.** Results are cached per (directory, filename). Call
  `reload()` after pointing `CDA_CONFIG_DIR` somewhere else, which is what the
  tests do.

Derived quantities are deliberately *not* stored in the JSON. `snapshot_dim` is
`book_rows * k_rows + extra_dim` and `train_batch_size` is
`max_step * num_episodes_per_iter`; writing those out would create a second
copy that can disagree with the first. The files hold inputs, the code derives
the rest.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

#: Overrides where `config/` is looked for. Set this to run against an
#: alternative config tree without touching the checked-in one.
CONFIG_DIR_ENV_VAR = "CDA_CONFIG_DIR"

_PACKAGE_DIR = Path(__file__).resolve().parent


def config_dir() -> Path:
    """Locate the `config/` directory.

    Order: `$CDA_CONFIG_DIR`, then the repo layout (`<repo>/config`, i.e.
    alongside the package), then a packaged copy inside the package itself.
    The repo layout is the normal case; the in-package location is checked so
    an installed copy that ships the files as package data still works.
    """
    override = os.environ.get(CONFIG_DIR_ENV_VAR)
    if override:
        path = Path(override).expanduser().resolve()
        if not path.is_dir():
            raise FileNotFoundError(
                f"{CONFIG_DIR_ENV_VAR}={override!r} is not a directory."
            )
        return path

    for candidate in (_PACKAGE_DIR.parent / "config", _PACKAGE_DIR / "config"):
        if candidate.is_dir():
            return candidate

    raise FileNotFoundError(
        "Could not locate the config/ directory. Looked in "
        f"{_PACKAGE_DIR.parent / 'config'} and {_PACKAGE_DIR / 'config'}. "
        f"Set {CONFIG_DIR_ENV_VAR} to point at it."
    )


def _strip_doc_keys(node: Any) -> Any:
    """Drop `_`-prefixed documentation keys at every level."""
    if isinstance(node, dict):
        return {
            key: _strip_doc_keys(sub)
            for key, sub in node.items()
            if not key.startswith("_")
        }
    return node


@lru_cache(maxsize=None)
def _load_from(directory: str, filename: str) -> Dict[str, Any]:
    path = Path(directory) / filename
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing config file {path}. Every configured value is read from "
            f"{directory}; the file cannot be omitted."
        )
    with open(path) as fh:
        try:
            raw = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path} is not valid JSON: {exc}") from exc
    return _strip_doc_keys(raw)


def load(filename: str) -> Dict[str, Any]:
    """Whole config file as a dict, documentation keys removed."""
    return _load_from(str(config_dir()), filename)


def group(filename: str, group_name: str) -> Dict[str, Any]:
    """One top-level group of a config file.

    Raises if the group is absent rather than returning an empty dict - an
    empty group would silently produce missing-key errors further away from
    the actual cause.
    """
    data = load(filename)
    if group_name not in data:
        raise KeyError(
            f"{filename}: no group {group_name!r}. "
            f"Groups present: {sorted(data)}."
        )
    section = data[group_name]
    if not isinstance(section, dict):
        raise TypeError(
            f"{filename}: {group_name!r} is {type(section).__name__}, "
            f"expected a group of key/value pairs."
        )
    return section


def value(filename: str, group_name: str, key: str) -> Any:
    """One value from one group. Raises, with context, if it is missing."""
    section = group(filename, group_name)
    if key not in section:
        raise KeyError(
            f"{filename}: {group_name!r} has no key {key!r}. "
            f"Keys present: {sorted(section)}."
        )
    return section[key]


def flatten(raw: Dict[str, Any], label: str = "config") -> Dict[str, Any]:
    """Flatten a grouped config mapping one level into a single dict.

    The config files are grouped for readability while several consumers
    (`TrainConfig`, the env config dict) are flat. Top-level scalars are kept
    as-is, so a file may mix grouped and ungrouped keys. Documentation keys are
    stripped at both levels.

    Raises if two groups define the same key - with the groups collapsed, a
    duplicate silently resolves to whichever group is later in the file.
    """
    result: Dict[str, Any] = {}
    origin: Dict[str, str] = {}
    for key, node in _strip_doc_keys(raw).items():
        items = node.items() if isinstance(node, dict) else [(key, node)]
        for sub_key, sub_value in items:
            if sub_key in result:
                raise ValueError(
                    f"{label}: key {sub_key!r} appears in both "
                    f"{origin[sub_key]!r} and {key!r}; flattened groups must "
                    f"not overlap."
                )
            result[sub_key] = sub_value
            origin[sub_key] = key
    return result


def flat(filename: str) -> Dict[str, Any]:
    """A config file's groups flattened one level into a single dict."""
    return flatten(load(filename), filename)


def reload() -> None:
    """Forget every cached file. Call after changing `$CDA_CONFIG_DIR`."""
    _load_from.cache_clear()


# --- Convenience accessors for the most-read groups -------------------------
#
# These exist so the rest of the package names a group once, here, instead of
# repeating a filename string at every call site.

def env_default(key: str) -> Any:
    """A fallback used when the env is constructed without that config key.

    These are the *standalone* env defaults and deliberately differ from the
    training defaults in `train_config.json` (a bare env is small and renders;
    a training env is not). See `config/env_defaults.json`.
    """
    return value("env_defaults.json", "environment", key)


def env_defaults() -> Dict[str, Any]:
    """All standalone env fallbacks in one dict."""
    return group("env_defaults.json", "environment")


def constant(group_name: str, key: str) -> Any:
    """A structural constant from `config/tunable_constants.json`."""
    return value("tunable_constants.json", group_name, key)


def constants(group_name: str) -> Dict[str, Any]:
    """A whole group of structural constants."""
    return group("tunable_constants.json", group_name)


def cli_default(command: str, key: str) -> Any:
    """A command-line flag default from `config/cli_defaults.json`."""
    return value("cli_defaults.json", command, key)
