"""Installable training extensions, found through Python entry points (docs/30).

An extension is a separately installed package that adds to the learning stack
without editing this repository: a Learner mixin, an RLModule mixin, an env
wrapper, or any mix of them. It declares itself under the
`gym_cda.extensions` entry-point group, pointing at an `Extension` object:

    [project.entry-points."gym_cda.extensions"]
    myext = "my_package:EXTENSION"

and is switched on per run by naming it in `extensions_enabled`, with its own
settings under `extension_settings[<name>]`. Installing a package changes no
run; enabling one that is not installed raises.

With nothing enabled every function here returns its input unchanged, so a run
resolves exactly the classes and the env it did before this module existed.

Where each piece is composed, and why there:

* **Learner** - `compose_learner`, called by `build._learner_class` between the
  encoder's Learner and Continual Backprop, so an extension inherits the MoE and
  JEPA terms and CBP still wraps the result. An extension that adds a loss term
  overrides `compute_loss_for_module` and calls `super()`; one that replaces
  PPO's loss overrides `_policy_value_loss` (`moe_learner`).
* **RLModule** - `compose_module_specs`, applied by `build.build_config` to the
  trainable modules the extension selects. The class carries the extension's
  settings as `extension_settings`, so every process that builds the module
  sees the same values without a second channel.
* **Env** - `wrap_env`, applied by `build.register_env` to every env RLlib
  creates. A wrapper must not change the observation or action space.

Checkpoints: the enabled extensions and their versions are recorded beside each
checkpoint (`league_state.json`), and every resolved setting is compared on a
resume like any other config key (`checkpoint._config_fingerprint`).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from functools import lru_cache
from importlib.metadata import entry_points
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

#: The entry-point group an extension package registers under.
ENTRY_POINT_GROUP = "gym_cda.extensions"

#: The `learner_config_dict` group carrying the enabled extensions' settings.
EXTENSIONS_CONFIG_KEY = "extensions"

#: Key in `league_state.json` recording `{name: version}` of enabled extensions.
EXTENSIONS_STATE_KEY = "extensions"


@dataclass(frozen=True)
class Extension:
    """What an extension package exposes through its entry point.

    Attributes:
        name: Must equal the entry-point name; it is how a config enables it.
        version: Recorded with each checkpoint so a resume can name it.
        defaults: Every setting the extension accepts, with its default. A
            setting not listed here is an error - the same rule as the config
            files (CLAUDE.md rule 1), owned by the extension.
        validate: Optional `(settings, train_config) -> None`, raising on a bad
            value or combination. Called with defaults already filled in.
        learner_mixin: Composed over the Learner, ahead of it in the MRO.
        learner_order: How far out `learner_mixin` wraps. Mixins compose by
            `(-learner_order, name)`, so a higher value sits earlier in the MRO
            and wraps every lower one; equal values keep name order.
        module_mixin: Composed over the trainable RLModule class.
        module_ids: Optional `(settings, trainable_ids) -> ids` choosing which
            trainable modules get `module_mixin`. Default: all of them.
        env_wrapper: Optional `(env, settings) -> env`.
        structural_keys: Settings that change a tensor shape. A resume that
            changes one fails as structural; any other setting change fails as
            unrestorable (it is read when classes are built).
    """

    name: str
    version: str
    defaults: Mapping[str, Any] = field(default_factory=dict)
    validate: Optional[Callable[[Dict[str, Any], Any], None]] = None
    learner_mixin: Optional[type] = None
    learner_order: int = 0
    module_mixin: Optional[type] = None
    module_ids: Optional[Callable[[Dict[str, Any], Sequence[str]], Sequence[str]]] = None
    env_wrapper: Optional[Callable[[Any, Dict[str, Any]], Any]] = None
    structural_keys: Tuple[str, ...] = ()


@lru_cache(maxsize=None)
def discover() -> Dict[str, Extension]:
    """Every installed extension, keyed by name. Loaded once per process.

    Raises:
        TypeError: an entry point does not resolve to an `Extension`.
        ValueError: its `name` differs from the entry-point name.
    """
    found: Dict[str, Extension] = {}
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        ext = ep.load()
        if not isinstance(ext, Extension):
            raise TypeError(
                f"entry point {ep.name!r} in {ENTRY_POINT_GROUP!r} resolves to "
                f"{type(ext).__name__}, not an Extension."
            )
        if ext.name != ep.name:
            raise ValueError(
                f"entry point {ep.name!r} resolves to an Extension named {ext.name!r}; "
                "they must match, since the name is how a config enables it."
            )
        found[ext.name] = ext
    return found


def resolve(enabled: Sequence[str], settings: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """The enabled extensions' settings with defaults filled in, keyed by name.

    Settings for an extension that is not enabled are ignored, so uninstalling
    a package and dropping it from `extensions_enabled` needs no other edit.

    Raises:
        ValueError: a name is enabled twice, is not installed, or its settings
            carry a key it does not declare.
    """
    names = list(enabled)
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ValueError(f"extensions_enabled lists {duplicates} more than once.")

    installed = discover()
    missing = sorted(set(names) - set(installed))
    if missing:
        raise ValueError(
            f"extensions_enabled names {missing}, which are not installed. Installed "
            f"extensions: {sorted(installed) or 'none'}. Install the package, or remove "
            "the name from extensions_enabled."
        )

    resolved: Dict[str, Dict[str, Any]] = {}
    for name in sorted(names):
        ext = installed[name]
        given = dict(settings.get(name) or {})
        unknown = sorted(set(given) - set(ext.defaults))
        if unknown:
            raise ValueError(
                f"extension_settings[{name!r}]: unknown keys {unknown}. "
                f"Valid keys: {sorted(ext.defaults)}"
            )
        resolved[name] = {**copy.deepcopy(dict(ext.defaults)), **given}
    return resolved


def validate(cfg) -> Dict[str, Dict[str, Any]]:
    """Resolve and validate a TrainConfig's extensions; returns the settings."""
    resolved = resolve(cfg.extensions_enabled, cfg.extension_settings)
    installed = discover()
    for name, settings in resolved.items():
        check = installed[name].validate
        if check is not None:
            check(settings, cfg)
    return resolved


def _enabled(cfg) -> List[Tuple[Extension, Dict[str, Any]]]:
    installed = discover()
    return [
        (installed[name], s)
        for name, s in resolve(cfg.extensions_enabled, cfg.extension_settings).items()
    ]


def compose_learner(base: type, cfg) -> type:
    """`base` with every enabled extension's Learner mixin ahead of it.

    Returns `base` itself when none has one. Mixins are ordered by
    `(-learner_order, name)`: a higher `learner_order` wraps further out, and
    the order, so the class and its MRO, is the same on every process and run.
    """
    ordered = sorted(
        (ext for ext, _ in _enabled(cfg) if ext.learner_mixin is not None),
        key=lambda ext: (-ext.learner_order, ext.name),
    )
    mixins = tuple(ext.learner_mixin for ext in ordered)
    if not mixins:
        return base
    return type(f"Ext{base.__name__}", mixins + (base,), {})


def compose_module_class(
    base: type, extensions: Sequence[Tuple[Extension, Dict[str, Any]]]
) -> type:
    """`base` with the given extensions' module mixins, carrying their settings."""
    mixins = tuple(ext.module_mixin for ext, _ in extensions if ext.module_mixin is not None)
    if not mixins:
        return base
    settings = {ext.name: s for ext, s in extensions if ext.module_mixin is not None}
    return type(f"Ext{base.__name__}", mixins + (base,), {"extension_settings": settings})


def compose_module_specs(multi_spec, trainable_ids: Sequence[str], cfg) -> None:
    """Swap in the composed module class on each trainable module, in place.

    Each module gets only the mixins of the extensions that select it, so two
    trainable modules can differ - that is what lets one league run compare an
    extension against plain PPO.
    """
    enabled = [(ext, s) for ext, s in _enabled(cfg) if ext.module_mixin is not None]
    if not enabled:
        return
    for module_id in trainable_ids:
        chosen = [
            (ext, s)
            for ext, s in enabled
            if ext.module_ids is None or module_id in ext.module_ids(s, list(trainable_ids))
        ]
        spec = multi_spec.rl_module_specs[module_id]
        spec.module_class = compose_module_class(spec.module_class, chosen)


def wrap_env(env, enabled: Sequence[str], settings: Mapping[str, Any]):
    """Apply every enabled extension's env wrapper, in name order."""
    if not enabled:
        return env
    installed = discover()
    for name, s in resolve(enabled, settings).items():
        wrapper = installed[name].env_wrapper
        if wrapper is not None:
            env = wrapper(env, s)
    return env


def learner_config(cfg) -> Dict[str, Any]:
    """The `learner_config_dict` group: what is enabled and its full settings."""
    return {
        "extensions_enabled": sorted(cfg.extensions_enabled),
        "extension_settings": resolve(cfg.extensions_enabled, cfg.extension_settings),
    }


def settings_for(learner_config_dict: Optional[Mapping[str, Any]], name: str) -> Dict[str, Any]:
    """An extension's resolved settings, read off a Learner's config.

    For a Learner mixin: `settings_for(self.config.learner_config_dict, "myext")`.
    """
    group = (learner_config_dict or {}).get(EXTENSIONS_CONFIG_KEY) or {}
    return dict((group.get("extension_settings") or {}).get(name) or {})


def versions(learner_config_dict: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    """`{name: version}` of the extensions a run's config enabled.

    A name that is no longer installed is recorded as `"unknown"` rather than
    failing a checkpoint save over a bookkeeping field.
    """
    group = (learner_config_dict or {}).get(EXTENSIONS_CONFIG_KEY) or {}
    installed = discover()
    return {
        name: (installed[name].version if name in installed else "unknown")
        for name in group.get("extensions_enabled") or []
    }


def structural_keys(learner_config_dict: Optional[Mapping[str, Any]]) -> Tuple[str, ...]:
    """Fingerprint keys (`ext.<name>.<key>`) the enabled extensions declare structural."""
    installed = discover()
    keys: List[str] = []
    for name in versions(learner_config_dict):
        if name in installed:
            keys.extend(f"ext.{name}.{key}" for key in installed[name].structural_keys)
    return tuple(keys)


def check_installed(sidecar: Optional[Mapping[str, Any]], path: str) -> None:
    """Raise if a checkpoint used an extension this environment does not have.

    Checked before `Algorithm.from_checkpoint`, which would otherwise fail deep
    inside unpickling - or, for an unpinned restore, fall back to an older
    checkpoint and fail the same way there.
    """
    recorded = (sidecar or {}).get(EXTENSIONS_STATE_KEY) or {}
    missing = sorted(set(recorded) - set(discover()))
    if missing:
        detail = ", ".join(f"{name} {recorded[name]}" for name in missing)
        raise ValueError(
            f"Cannot restore {path}: it was trained with extension(s) {detail}, which "
            f"are not installed here. Install them, or start a fresh run."
        )
