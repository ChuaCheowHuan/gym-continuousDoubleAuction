"""Where a run executes: platform detection and hardware profile selection.

`CDA_NSP.ipynb` has to work unchanged on two machines with different shapes:

* a **Colab** VM - 2 vCPUs, an optional T4, the repo on a Drive mount;
* the **docker/ml/dockerfile_ray_torch** image - repo at `/workspace/code`,
  the package already installed editable, a GPU only when the container was
  started with `--gpus`.

What differs between them is resource counts and paths, never training values,
so the two parameter sets live in `config/runtime_profiles.json` and are
resolved here. The notebook picks a platform and a GPU toggle; everything else
is read from the file.

    from gym_continuousDoubleAuction.train.runtime import resolve, apply

    rt = resolve(platform="auto", use_gpu="auto")
    cfg = apply(TrainConfig(), rt)
    ray.init(**rt.ray_init_kwargs)

`train_config.json` is untouched by any of this: `TrainConfig()` still supplies
every training value, and a profile overlays only the resource fields it names.

Nothing here imports `ray` at module scope, because `apply_env_vars()` has to
run *before* ray is first imported.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, Optional, Union

from gym_continuousDoubleAuction.config_loader import constants, group
from gym_continuousDoubleAuction.logging_setup import get_logger

logger = get_logger(__name__)

#: The file both parameter sets are read from.
PROFILES_FILE = "runtime_profiles.json"

#: Overrides the detected platform / GPU toggle without editing the notebook,
#: so a headless run can pin what an interactive one detects.
PLATFORM_ENV_VAR = "CDA_PLATFORM"
USE_GPU_ENV_VAR = "CDA_USE_GPU"

#: The "work it out yourself" value, accepted for both knobs.
AUTO = "auto"

#: Keys every entry in the `platforms` group must declare. They are declared
#: even where they do not apply (as null) so a missing one is a typo rather
#: than a silent fallback - the same rule config_loader enforces elsewhere.
_REQUIRED_PLATFORM_KEYS = frozenset(
    {"repo_path", "results_root", "episode_data_root", "drive_mount_point",
     "pip_packages"}
)

_TRUE = frozenset({"1", "true", "yes", "on", "gpu"})
_FALSE = frozenset({"0", "false", "no", "off", "cpu"})


@dataclass(frozen=True)
class Runtime:
    """A resolved place to run: which machine, how much hardware, where files go."""

    #: A key of the `platforms` group: "colab", "docker", "local".
    platform: str
    #: A key of the `hardware` group: "gpu" or "cpu".
    hardware: str
    #: Ready to splat into `ray.init(**...)`.
    ray_init_kwargs: Dict[str, Any]
    #: TrainConfig field name -> value, applied by `apply()`.
    overrides: Dict[str, Any]
    #: The whole `platforms.<platform>` entry, paths included.
    platform_config: Dict[str, Any]
    #: True when a GPU was asked for (explicitly or by detection) and CUDA
    #: turned out to be absent, so the cpu set was substituted.
    gpu_unavailable: bool = False


def _toggle(value: Union[str, bool, None]) -> Optional[bool]:
    """Normalise a three-state toggle to True / False / None (= auto)."""
    if value is None or value is AUTO:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text == AUTO:
        return None
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise ValueError(
        f"Cannot read {value!r} as a GPU toggle. Use True, False, or "
        f"{AUTO!r} (also accepted: {sorted(_TRUE | _FALSE)})."
    )


def in_colab() -> bool:
    """True inside a Colab VM, before the package is necessarily importable."""
    if "COLAB_RELEASE_TAG" in os.environ or "google.colab" in sys.modules:
        return True
    try:
        import google.colab  # noqa: F401

        return True
    except Exception:
        return False


def detect_platform() -> str:
    """Which of the `platforms` groups this process is running in.

    `/.dockerenv` alone is not enough to claim "docker": it exists in *every*
    container, including a dev container that is not this image at all, and
    claiming it there would point `repo_path` at a directory that does not
    exist. The image is identified by its recorded repo path as well. Anything
    unrecognised is "local", which relocates nothing - so a container started
    with the working tree bind-mounted somewhere else degrades to exactly the
    right behaviour rather than the wrong one.
    """
    if in_colab():
        return "colab"
    docker_repo = group(PROFILES_FILE, "platforms")["docker"]["repo_path"]
    if os.path.exists("/.dockerenv") and docker_repo and os.path.isdir(docker_repo):
        return "docker"
    return "local"


def cuda_available() -> bool:
    """`torch.cuda.is_available()`, imported late so this module stays light."""
    import torch

    return bool(torch.cuda.is_available())


def detect_hardware(use_gpu: Union[str, bool, None] = AUTO) -> tuple[str, bool]:
    """Choose the "gpu" or "cpu" parameter set.

    Returns `(name, gpu_unavailable)`. `use_gpu=True` does not force the gpu
    set onto a machine without CUDA - RLlib would place the learner on a device
    that is not there. It falls back and says so, which is the same thing
    `TrainConfig.resolved_gpus_per_learner()` does one layer down.
    """
    want = _toggle(use_gpu)
    if want is None:
        want = _toggle(os.environ.get(USE_GPU_ENV_VAR))

    if want is False:
        return "cpu", False

    have = cuda_available()
    if want is True and not have:
        logger.warning(
            "GPU requested but torch.cuda.is_available() is False - using the "
            "cpu profile. On docker, start the container with `--gpus all`; "
            "on Colab, Runtime > Change runtime type > GPU."
        )
        return "cpu", True
    return ("gpu", False) if have else ("cpu", False)


def _platform_config(platform: str) -> Dict[str, Any]:
    platforms = group(PROFILES_FILE, "platforms")
    if platform not in platforms:
        raise KeyError(
            f"{PROFILES_FILE}: no platform {platform!r}. "
            f"Platforms present: {sorted(platforms)}."
        )
    entry = platforms[platform]
    missing = sorted(_REQUIRED_PLATFORM_KEYS - set(entry))
    if missing:
        raise KeyError(
            f"{PROFILES_FILE}: platform {platform!r} is missing {missing}. "
            f"Every platform declares all of {sorted(_REQUIRED_PLATFORM_KEYS)}, "
            f"as null where it does not apply."
        )
    return entry


def _hardware_profile(hardware: str) -> Dict[str, Any]:
    profiles = group(PROFILES_FILE, "hardware")
    if hardware not in profiles:
        raise KeyError(
            f"{PROFILES_FILE}: no hardware profile {hardware!r}. "
            f"Profiles present: {sorted(profiles)}."
        )
    profile = profiles[hardware]
    for section in ("ray_init", "train_config"):
        if section not in profile:
            raise KeyError(
                f"{PROFILES_FILE}: hardware profile {hardware!r} has no "
                f"{section!r} section. Keys present: {sorted(profile)}."
            )

    # Same policy as TrainConfig.from_json: a key that names no field is a
    # rename or a typo, and silently dropping it is the failure this check
    # exists to remove. Imported here, not at module scope, so train.py can
    # import this module without a cycle.
    from gym_continuousDoubleAuction.train.train import TrainConfig
    import dataclasses

    known = {f.name for f in dataclasses.fields(TrainConfig)}
    unknown = sorted(set(profile["train_config"]) - known)
    if unknown:
        raise ValueError(
            f"{PROFILES_FILE}: hardware profile {hardware!r} sets {unknown}, "
            f"which are not TrainConfig fields. Valid fields: {sorted(known)}."
        )
    return profile


def resolve(
    platform: str = AUTO,
    use_gpu: Union[str, bool, None] = AUTO,
) -> Runtime:
    """Pick a platform and a hardware profile, and read both from the file.

    `platform=AUTO` consults `$CDA_PLATFORM` before falling back to detection,
    so a headless or CI run can pin what an interactive one guesses.
    """
    if platform in (None, AUTO):
        platform = os.environ.get(PLATFORM_ENV_VAR, AUTO)
    if platform in (None, AUTO):
        platform = detect_platform()

    platform_config = _platform_config(platform)
    hardware, gpu_unavailable = detect_hardware(use_gpu)
    profile = _hardware_profile(hardware)

    ray_init_kwargs = dict(group(PROFILES_FILE, "ray_init_common"))
    ray_init_kwargs.update(profile["ray_init"])

    requested_cpus = ray_init_kwargs.get("num_cpus")
    available = os.cpu_count() or 1
    if requested_cpus is not None and requested_cpus > available:
        logger.warning(
            "profile %r asks Ray for %s CPUs but this machine reports %s. Ray "
            "will accept the number as a logical resource and oversubscribe "
            "the cores.", hardware, requested_cpus, available,
        )

    return Runtime(
        platform=platform,
        hardware=hardware,
        ray_init_kwargs=ray_init_kwargs,
        overrides=dict(profile["train_config"]),
        platform_config=platform_config,
        gpu_unavailable=gpu_unavailable,
    )


def apply(cfg, rt: Runtime):
    """Overlay a Runtime onto a TrainConfig, returning a new one.

    Two kinds of change: the hardware profile's resource fields, and the
    platform's output roots. `results_root` and `episode_data_root` are applied
    as absolute replacements rather than as parents, because the point of them
    is to move output off a path that would otherwise be resolved against the
    working directory - which under Jupyter is the notebook's own directory,
    not the repo root that `python -m ...train` runs from.

    `episode_data_dir=None` (pickles disabled in train_config.json) is left
    alone: relocating a disabled output would silently re-enable it.
    """
    import dataclasses

    overrides = dict(rt.overrides)

    results_root = rt.platform_config["results_root"]
    if results_root is not None:
        overrides["log_base_dir"] = results_root

    episode_data_root = rt.platform_config["episode_data_root"]
    if episode_data_root is not None and cfg.episode_data_dir is not None:
        overrides["episode_data_dir"] = episode_data_root

    return dataclasses.replace(cfg, **overrides)


def changed_fields(before, after) -> Dict[str, tuple]:
    """`{field: (old, new)}` for every field `apply()` actually moved."""
    import dataclasses

    return {
        f.name: (getattr(before, f.name), getattr(after, f.name))
        for f in dataclasses.fields(before)
        if getattr(before, f.name) != getattr(after, f.name)
    }


def apply_env_vars() -> Dict[str, str]:
    """Export the `runtime_env_vars` constants, before ray is imported.

    `setdefault`, so a value already exported in the shell wins over the file.
    Returns what is now in the environment for those names, so a caller can
    show it. `train.main()` calls this too - one behaviour, one call site.
    """
    applied = {}
    for name, val in constants("runtime_env_vars").items():
        os.environ.setdefault(name, str(val))
        applied[name] = os.environ[name]
    return applied


def ray_init_kwargs(rt: Runtime) -> Dict[str, Any]:
    """`rt.ray_init_kwargs` with the logging settings added as a runtime_env.

    A function rather than a field on `Runtime`, and called at the `ray.init`
    site rather than stored, because the variables it merges are exported by
    `configure_run_logging` - which runs after `resolve()`. A copy taken when
    the Runtime was built would always be empty.

    The profile's own `runtime_env`, if it ever grows one, is preserved: only
    the `env_vars` mapping is added to, and a name the profile set explicitly
    wins.
    """
    from gym_continuousDoubleAuction.logging_setup import merge_runtime_env

    kwargs = dict(rt.ray_init_kwargs)
    kwargs["runtime_env"] = merge_runtime_env(kwargs.get("runtime_env"))
    return kwargs


def summary(rt: Runtime) -> str:
    """A printable block describing what `resolve()` decided, and why."""
    lines = [
        f"platform         : {rt.platform}",
        f"hardware profile : {rt.hardware}"
        + ("  (GPU asked for but unavailable)" if rt.gpu_unavailable else ""),
        f"ray.init         : {rt.ray_init_kwargs}",
    ]
    repo_path = rt.platform_config["repo_path"]
    if repo_path and os.path.realpath(repo_path) != os.path.realpath(os.getcwd()):
        lines.append(f"repo path        : {repo_path}  (declared; not in use)")
    lines.append(f"working dir      : {os.getcwd()}")
    return "\n".join(lines)


def chdir_to_repo(rt: Runtime) -> str:
    """Move to the platform's `repo_path`, if it declares one and it exists.

    Best-effort on purpose: the docker image records `/workspace/code`, but a
    container started with the working tree bind-mounted somewhere else is
    still perfectly runnable, and refusing to start would be the wrong call.
    """
    repo_path = rt.platform_config["repo_path"]
    if repo_path and os.path.isdir(repo_path):
        os.chdir(repo_path)
    elif repo_path:
        logger.warning(
            "platform %r declares repo_path %r, which does not exist here - "
            "staying in %s.", rt.platform, repo_path, os.getcwd(),
        )
    return os.getcwd()
