"""Checkpoints: save, retention, the league sidecar, restore checks and the optimiser fix (issue #254)."""

from __future__ import annotations
import json
import os
import shutil
from typing import List, Optional, Tuple
import torch
from gym_continuousDoubleAuction.envs.layout_version import LAYOUT_KEY, layout_stamp
from gym_continuousDoubleAuction.logging_setup import get_logger
from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import (
    SelfPlayCallback,
)
from gym_continuousDoubleAuction.train.model.encoders import (
    MLP_ENCODER_TYPE,
    encoder_fingerprint,
    model_config_get,
)
from gym_continuousDoubleAuction.train.policy.policy_handler import CHAMPION_PREFIX
from gym_continuousDoubleAuction.train.config import TrainConfig

logger = get_logger("gym_continuousDoubleAuction.train.train")


# --- Checkpoint layout -------------------------------------------------------
#
# Each save goes into its own `iter_<n>` directory under `checkpoint_dir`, and
# the newest `chkpt_keep` of them are kept. Every save used to be written to
# `chkpt/` itself, which gave a run exactly one recoverable state: a league that
# collapsed at iteration 12 could not be rolled back to 8, and a save
# interrupted partway - the thing checkpointing exists to survive - destroyed
# the only copy.
#
# A save is staged in `<dir>.tmp` and renamed into place, so an interrupted one
# leaves a `.tmp` directory the scanner skips rather than a half-written
# checkpoint that looks complete.

CHECKPOINT_PREFIX = "iter_"


CHECKPOINT_TMP_SUFFIX = ".tmp"


#: Champion bookkeeping, written beside each checkpoint. See `_write_league_state`.
LEAGUE_STATE_FILE = "league_state.json"


#: Checkpoint roots already reported as holding an old-layout checkpoint, so the
#: note is printed once per run rather than once per save.
_NOTED_OLD_LAYOUT = set()


def _is_checkpoint(path: str) -> bool:
    return os.path.isfile(os.path.join(path, "rllib_checkpoint.json"))


def list_checkpoints(root: str) -> List[Tuple[int, str]]:
    """Every readable checkpoint under `root`, oldest first, as (iteration, path).

    A checkpoint written by the old single-directory layout sits in `root`
    itself. It is reported with iteration -1 so it sorts oldest: still usable on
    a box that has one, never preferred over a save whose iteration is known.
    """
    found: List[Tuple[int, str]] = []
    if not os.path.isdir(root):
        return found

    if _is_checkpoint(root):
        found.append((-1, root))

    for name in sorted(os.listdir(root)):
        if not name.startswith(CHECKPOINT_PREFIX) or name.endswith(CHECKPOINT_TMP_SUFFIX):
            continue
        path = os.path.join(root, name)
        try:
            iteration = int(name[len(CHECKPOINT_PREFIX) :])
        except ValueError:
            continue
        if _is_checkpoint(path):
            found.append((iteration, path))

    return sorted(found)


def save_checkpoint(algo, cfg: TrainConfig, iteration: int) -> str:
    """Save `algo` as `iter_<iteration>`, then prune to `cfg.chkpt_keep`."""
    root = cfg.checkpoint_dir
    os.makedirs(root, exist_ok=True)

    final = os.path.join(root, f"{CHECKPOINT_PREFIX}{iteration:05d}")
    staging = final + CHECKPOINT_TMP_SUFFIX

    for stale in (staging, final):
        # `final` exists when a restored run reaches an iteration it already
        # saved; `staging` when a previous save was interrupted.
        if os.path.exists(stale):
            shutil.rmtree(stale, ignore_errors=True)

    algo.save(staging)
    _write_league_state(staging, algo, iteration)
    os.rename(staging, final)

    _prune_checkpoints(root, cfg.chkpt_keep)
    return final


def _prune_checkpoints(root: str, keep: int) -> None:
    """Delete all but the `keep` most recently written saves. <= 0 keeps everything.

    Recency is the directory's mtime, not its iteration number. Ranking by
    iteration number deletes the save that was just written whenever the
    directory also holds higher-numbered ones from an earlier run: a fresh run
    reaching `iter_00002` in a directory that still has `iter_00012/14/16` sees
    its own checkpoint pruned microseconds after the rename that made it real,
    and keeps the stale ones instead. Both GPU runs of 2026-08-15 did exactly
    that for iterations 2 through 10 - the whole first half of each run left
    unrecoverable while the previous run's checkpoints survived. mtime says
    what the iteration number cannot: which of these did *this* run write.

    Only `iter_*` directories are pruned. A checkpoint left in `root` by the old
    layout is another tool's data as far as this function is concerned, so it is
    reported once and left alone.
    """
    if not keep or keep <= 0:
        return

    checkpoints = list_checkpoints(root)
    if any(iteration < 0 for iteration, _ in checkpoints) and root not in _NOTED_OLD_LAYOUT:
        _NOTED_OLD_LAYOUT.add(root)
        logger.info(
            "note: %s also holds a checkpoint in the old single-directory "
            "layout. It is kept as a last-resort restore candidate and is never "
            "pruned; delete it by hand once the iter_* saves are trusted.",
            root,
        )

    prunable = [path for iteration, path in checkpoints if iteration >= 0]
    # Oldest first, so the tail of the list is what `keep` retains. The
    # iteration number breaks mtime ties, which is what a filesystem with
    # coarse timestamps produces when two saves land in the same second.
    prunable.sort(key=lambda path: (_mtime(path), _iteration_of(path)))

    for path in prunable[: max(0, len(prunable) - keep)]:
        shutil.rmtree(path, ignore_errors=True)
        logger.info("pruned old checkpoint: %s", path)


def _mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _iteration_of(path: str) -> int:
    """The iteration in an `iter_<n>` basename, or -1 if it has none."""
    name = os.path.basename(path)
    try:
        return int(name[len(CHECKPOINT_PREFIX) :])
    except ValueError:
        return -1


def warn_about_foreign_checkpoints(cfg: TrainConfig) -> List[str]:
    """Report checkpoints a fresh run is about to write alongside.

    A run that is not restoring shares its directory with whatever the last run
    left there, and the two are told apart only by iteration number. Until this
    run passes that number, `list_checkpoints` reports the *stale* save as the
    newest, so an interrupted run restored with `--restore` silently resumes
    someone else's weights - which is how a run that trained on nothing could
    have been picked up as if it were this one. Nothing is deleted here; the
    directory belongs to the operator, not to this function.

    Returns the stale paths, newest first, for the caller to log or test.
    """
    if cfg.is_restore:
        return []

    stale = [path for _iteration, path in reversed(list_checkpoints(cfg.checkpoint_dir))]
    if stale:
        logger.warning(
            "%s already holds %s checkpoint(s) from an earlier run, newest "
            "first: %s. This run is not restoring, so they are left alone - but "
            "until it passes their iteration numbers, a --restore would pick "
            "one of them over anything written here. Move or delete them, or "
            "point log_base_dir somewhere new.",
            cfg.checkpoint_dir,
            len(stale),
            ", ".join(os.path.basename(p) for p in stale),
        )
    return stale


def algo_callback(algo) -> Optional[SelfPlayCallback]:
    """The SelfPlayCallback instance the Algorithm is actually running.

    `.callbacks(lambda: callback_instance)` means the algorithm holds the same
    object the mapping fn closes over - but after a restore that object is
    RLlib's unpickled copy, not the one `build_config` just made. Anything that
    wants the live champion pool has to ask the algorithm for it.
    """
    callbacks = getattr(algo, "callbacks", None)
    if not isinstance(callbacks, (list, tuple)):
        callbacks = [callbacks]
    for callback in callbacks:
        if isinstance(callback, SelfPlayCallback):
            return callback
    return None


def _write_league_state(path: str, algo, iteration: int) -> None:
    """Write champion bookkeeping beside a checkpoint, as plain JSON.

    The champion *modules* are in the checkpoint proper. Their metadata -
    history, the monotonic ID counter, the matchmaking pool - lives only inside
    the cloudpickled callback, so it survives exactly as long as
    `SelfPlayCallback` stays unpickle-compatible. Rename the class, change its
    `__init__`, or resume across a Ray upgrade, and the modules come back while
    the league that indexes them does not: the counter restarts and mints a
    second `champion_1`. This sidecar is the readable copy that
    `_reconcile_league_state` repairs from.
    """
    callback = algo_callback(algo)
    if callback is None:
        return

    state = callback.league_state()
    state["training_iteration"] = iteration
    # Which observation and action layout the weights in this checkpoint were
    # trained against (doc/15 S4-19). A restore into a different layout fails
    # by name at `build_algo`, before RLlib gets as far as a tensor shape.
    env_config = getattr(getattr(algo, "config", None), "env_config", None) or {}
    state[LAYOUT_KEY] = layout_stamp(env_config.get("book_mode"))
    with open(os.path.join(path, LEAGUE_STATE_FILE), "w") as fh:
        json.dump(state, fh, indent=2)


def _read_league_state(path: str) -> Optional[dict]:
    state_file = os.path.join(path, LEAGUE_STATE_FILE)
    if not os.path.isfile(state_file):
        return None
    try:
        with open(state_file) as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        logger.warning("could not read %s: %s", state_file, exc)
        return None


def _present_module_ids(algo) -> Optional[set]:
    """ModuleIDs actually present on an EnvRunner, or None if unobtainable."""
    try:
        if algo.env_runner is not None:
            return set(algo.env_runner.module.keys())
    except Exception:
        pass
    try:
        per_runner = algo.env_runner_group.foreach_env_runner(
            lambda env_runner: list(env_runner.module.keys())
        )
        if per_runner:
            return set(per_runner[0])
    except Exception:
        pass
    return None


def _reconcile_league_state(algo, path: str) -> None:
    """Repair the restored callback's league bookkeeping against the sidecar."""
    callback = algo_callback(algo)
    if callback is None:
        logger.error(
            "restored algorithm has no SelfPlayCallback - league state cannot "
            "be checked. Champion matchmaking will not work."
        )
        return

    state = _read_league_state(path)
    if state is None:
        # Pre-sidecar checkpoints, and the old layout, have nothing to check
        # against. The pickled callback is all there is.
        return

    repairs = callback.restore_league_state(state, _present_module_ids(algo))
    if not repairs:
        logger.info(
            "league state verified: %s champion(s)",
            callback.champion_count,
        )
        return

    logger.warning(
        "league state repaired against league_state.json:\n%s\n"
        "  Repairs apply to the driver's matchmaking pool. With "
        "num_env_runners > 0 the remote runners hold their own pickled mapping "
        "fn, so prefer restoring from a checkpoint that verifies clean.",
        "\n".join(f"  - {repair}" for repair in repairs),
    )


# --- Config vs. checkpoint ---------------------------------------------------
#
# `Algorithm.from_checkpoint` rebuilds everything from the config stored in the
# checkpoint and discards the PPOConfig just built from `config/train_config.json`.
# Since resuming is documented as "edit train_config.json, set is_restore true",
# that is the same file holding lr, the reward coefficients and num_agents - so
# edits made in the same pass as the restore flag were silently ignored. These
# make the divergence loud, and fatal where it would invalidate the weights.

#: Keys whose value the restored weights depend on. A change here is a hard error.
#:
#: `encoder_type` and `encoder_spec` are here for the same reason `n_hist` is:
#: they decide the shape of the trainable modules' network, so a checkpoint's
#: weights simply do not fit a config that changed one. Comparing architectures
#: means separate runs, not editing the encoder group with is_restore set.
STRUCTURAL_CONFIG_KEYS = (
    "policies",
    "policies_to_train",
    "env_config.num_of_agents",
    "env_config.n_hist",
    "env_config.book_mode",
    "encoder_type",
    "encoder_spec",
)


#: Keys a restore cannot honour at all, for a different reason than the
#: structural ones: not that the weights would not fit, but that the value is
#: consumed when the Learner *class* is chosen and the optimiser is *built*,
#: both of which happen before a restore and are then overwritten by the
#: checkpoint's own config.
#:
#: `Algorithm.from_checkpoint` rebuilds from the config stored in the
#: checkpoint, so the `learner_class` and `learner_config_dict` assembled for
#: this run are used only for the comparison below and never take effect.
#: Editing any of these alongside `is_restore` therefore did exactly nothing,
#: and - because `_config_fingerprint` did not carry them - said nothing either.
#: A hard error rather than a warning: "I turned continual backprop on and it
#: made no difference" is a conclusion someone could carry a long way before
#: discovering it never ran.
#:
#: They are NOT structural. No tensor shape depends on them, and the per-unit
#: utility and ages restore cleanly. Changing one means a fresh run, not a
#: resume - the same rule as the encoder group, arrived at by a different route.
UNRESTORABLE_CONFIG_KEYS = (
    "cbp_enabled",
    "cbp_metrics_only",
    "adam_betas",
    "adam_weight_decay",
)


#: The rest of the continual-backprop group. Unrestorable for the same reason,
#: but only *material* when continual backprop is running on one side or the
#: other - a replacement rate edited while the mechanism is off in both the
#: checkpoint and the config changes nothing that was going to happen anyway,
#: and failing a resume over it would be noise.
UNRESTORABLE_WHEN_ACTIVE_KEYS = (
    "cbp_replacement_rate",
    "cbp_maturity_threshold",
    "cbp_utility_decay",
    "cbp_utility",
    "cbp_scope",
    "cbp_fire_on",
    "cbp_reset_optimizer_state",
    "cbp_compensate_mean",
    "cbp_dead_unit_threshold",
    "cbp_metrics_every_n_updates",
)


#: What a run that carried none of the above actually did, which is what every
#: checkpoint written before these groups existed did.
#:
#: Deliberately literals rather than a read of `config/train_config.json`: this
#: is a statement about the behaviour of a *past* run, and reading the current
#: file would make it a statement about the present one - so editing a default
#: would silently change what an old checkpoint is judged to have done. The
#: values are "continual backprop off" and "torch's own Adam", which is what the
#: code did before `cbp_learner` existed.
PRE_FEATURE_BEHAVIOUR = {
    "cbp_enabled": False,
    "cbp_metrics_only": False,
    "cbp_replacement_rate": 1e-4,
    "cbp_maturity_threshold": 100,
    "cbp_utility_decay": 0.99,
    "cbp_utility": "overall",
    "cbp_scope": "feedforward",
    "cbp_fire_on": "adam_step",
    "cbp_reset_optimizer_state": True,
    "cbp_compensate_mean": False,
    "cbp_dead_unit_threshold": 0.01,
    "cbp_metrics_every_n_updates": 10,
    "adam_betas": (0.9, 0.999),
    "adam_weight_decay": 0.0,
}


def _config_fingerprint(config) -> dict:
    """The comparable subset of an AlgorithmConfig, flattened to scalars."""
    missing = object()
    fingerprint = {}

    for key in (
        "lr",
        # RLlib's 0.0 in a checkpoint from before the entropy bonus: the
        # restore keeps it, and without this the run said nothing (S3-11).
        "entropy_coeff",
        # A different discount or GAE parameter is a different objective: a
        # resume of a 0.99/1.0 checkpoint under the new defaults would continue
        # optimising something else without saying so (S3-13).
        "gamma",
        "lambda_",
        "num_epochs",
        "minibatch_size",
        "train_batch_size_per_learner",
        "num_env_runners",
        "num_envs_per_env_runner",
        "sample_timeout_s",
        "num_learners",
        "num_gpus_per_learner",
    ):
        value = getattr(config, key, missing)
        if value is not missing:
            fingerprint[key] = value

    for key in ("policies", "policies_to_train"):
        value = getattr(config, key, missing)
        # Only the ids matter, and only the ones the config asks for: champions
        # are added to `policies` during a run, so a restored config legitimately
        # holds more of them than a freshly built one. `policies_to_train` can be
        # a callable, which has nothing comparable about it.
        if value is not missing and isinstance(value, (list, tuple, set, dict)):
            fingerprint[key] = sorted(m for m in value if not str(m).startswith(CHAMPION_PREFIX))

    for key, value in (getattr(config, "env_config", None) or {}).items():
        fingerprint[f"env_config.{key}"] = value

    # The continual-backprop and optimiser groups ride on `learner_config_dict`
    # rather than being AlgorithmConfig attributes, so they have to be flattened
    # in by hand. Without this they were invisible to the comparison entirely:
    # `_check_restored_config` only reports keys present in BOTH fingerprints,
    # so a restore that turned continual backprop on was neither applied nor
    # mentioned. See UNRESTORABLE_CONFIG_KEYS.
    for group, values in (getattr(config, "learner_config_dict", None) or {}).items():
        if isinstance(values, dict):
            for key, value in values.items():
                # The group name is dropped, so these share one namespace with
                # the AlgorithmConfig attributes above. That is why the CBP keys
                # carry a `cbp_` prefix and the optimiser ones an `adam_` one -
                # the same rule `config_loader.flatten` enforces one level up.
                # Raised rather than overwritten: a silent collision would hide
                # a real divergence from `_check_restored_config`, which is the
                # one thing this function exists to prevent.
                if key in fingerprint:
                    raise ValueError(
                        f"learner_config_dict[{group!r}][{key!r}] collides with "
                        f"an existing fingerprint key. These groups are "
                        f"flattened into one namespace, so give the key a "
                        f"group-specific prefix - see UNRESTORABLE_CONFIG_KEYS."
                    )
                # Lists are not comparable across a JSON round trip in the way
                # the `!=` here needs; `adam_betas` is the only one and a tuple
                # compares cleanly against a list once both are normalised.
                fingerprint[key] = tuple(value) if isinstance(value, list) else value

    fingerprint.update(_encoder_fingerprint(config))

    return fingerprint


def _encoder_fingerprint(config) -> dict:
    """The trainable modules' encoder identity, as comparable scalars.

    The encoder is not an `AlgorithmConfig` attribute - it lives on the
    `model_config` of each trainable module's spec - so it has to be dug out
    before `_check_restored_config` can compare it. Read from the first
    trainable module: `build_multi_rl_module_spec` gives them all the same
    encoder, and a champion's is cloned from whichever module it snapshotted.

    Returns an empty dict when there is no spec to read - a config built before
    the encoder group existed, or one whose modules are all baselines - so a
    fingerprint never gains a key that would compare against nothing.
    """
    spec = getattr(config, "rl_module_spec", None)
    module_specs = getattr(spec, "rl_module_specs", None) or {}

    for module_id in sorted(module_specs):
        if str(module_id).startswith(CHAMPION_PREFIX):
            continue
        model_config = getattr(module_specs[module_id], "model_config", None)
        if model_config is None:
            # A baseline RandomRLModule, which has no network at all.
            continue
        # Built by `encoders.encoder_fingerprint` rather than assembled here,
        # so this and the offline pretrainer - which writes the same
        # fingerprint beside its weights - cannot drift apart.
        return encoder_fingerprint(
            _model_config_get(model_config, "encoder_type", MLP_ENCODER_TYPE),
            _model_config_get(model_config, "encoder_spec", None),
        )

    return {}


def _model_config_get(model_config, key, default):
    """Alias for `encoders.model_config_get`; see there for why both shapes occur.

    Kept as a module-level name because the tests and `_encoder_fingerprint`
    both reach for it here.
    """
    return model_config_get(model_config, key, default)


def _check_restored_config(restored, desired) -> None:
    """Report config keys the restore is about to ignore; raise on the ones that
    cannot be ignored safely.

    Three categories, in the order they are checked:

    * **Structural** - the restored weights would not fit. Raises.
    * **Unrestorable** - the weights fit perfectly, but the value is consumed
      before a restore happens and is then discarded, so the setting would
      silently not apply. Raises, with a different message.
    * Everything else - reported as a warning, since the checkpoint's value
      simply stays in effect and that is usually what was wanted.

    Raises:
        ValueError: a structural or an unrestorable key differs.
    """
    old = _config_fingerprint(restored)
    new = _config_fingerprint(desired)

    def fail(kind, keys, explanation):
        detail = "\n".join(
            f"  {key}: checkpoint has {before!r}, config asks for {after!r}"
            for key, (before, after) in sorted(keys.items())
        )
        raise ValueError(f"Cannot restore: {kind}\n{detail}\n{explanation}")

    diverged = {key: (old[key], new[key]) for key in set(old) & set(new) if old[key] != new[key]}

    structural = {k: v for k, v in diverged.items() if k in STRUCTURAL_CONFIG_KEYS}
    if structural:
        fail(
            "the configuration changes the shape of the problem the checkpoint was trained on.",
            structural,
            "The restored weights do not fit. Either revert these keys, or "
            "start a fresh run (is_restore false, or a new log_base_dir).",
        )

    # Compared against what the checkpoint's run actually DID, rather than
    # against the intersection of the two fingerprints, and *before* the
    # no-divergence early return below. Every checkpoint written before these
    # groups existed carries none of these keys, so an intersection-only
    # comparison would skip them entirely - on exactly the checkpoints most
    # likely to be resumed, since at the time of writing every checkpoint in
    # existence predates the feature. A missing key means that run behaved as
    # PRE_FEATURE_BEHAVIOUR describes.
    def checkpoint_value(key):
        return old.get(key, PRE_FEATURE_BEHAVIOUR[key])

    checked = list(UNRESTORABLE_CONFIG_KEYS)
    # The tuning knobs only count when the mechanism is actually running on one
    # side or the other; otherwise they describe something that was not going to
    # happen either way, and failing a resume over one would be pure noise.
    if any(checkpoint_value(k) or new.get(k) for k in ("cbp_enabled", "cbp_metrics_only")):
        checked += list(UNRESTORABLE_WHEN_ACTIVE_KEYS)

    unrestorable = {
        key: (checkpoint_value(key), new[key])
        for key in checked
        if key in new and new[key] != checkpoint_value(key)
    }
    if unrestorable:
        fail(
            "these keys are read when the Learner class is chosen and the "
            "optimiser is built, both of which happen before a restore - and "
            "`Algorithm.from_checkpoint` then rebuilds from the checkpoint's "
            "own config, discarding them.",
            unrestorable,
            "The weights would restore fine; the settings simply would not "
            "apply, and a run that silently ignored them would look exactly "
            "like one that honoured them. Either revert these keys, or start a "
            "fresh run (is_restore false, or a new log_base_dir).",
        )

    if not diverged:
        return

    detail = "\n".join(
        f"  {key}: {was!r} (checkpoint, in effect) != {wants!r} (config, ignored)"
        for key, (was, wants) in sorted(diverged.items())
    )
    logger.warning(
        "restoring keeps the checkpoint's own config. These config values will "
        "NOT take effect:\n%s\n"
        "  Restore rebuilds the algorithm from the checkpoint, so only the "
        "driver-side knobs (num_iters, chkpt_freq, chkpt_keep) still apply. To "
        "train with these values, start a fresh run.",
        detail,
    )


def restore_candidates(cfg: TrainConfig) -> List[Tuple[int, str]]:
    """The checkpoints a restore may use, oldest first.

    Without `restore_path` that is every checkpoint under `checkpoint_dir`, so
    an unreadable newest one can fall back to the one before it. With
    `restore_path` it is exactly the one checkpoint named, because falling back
    from a pinned checkpoint would train from something other than what was
    asked for.

    Raises:
        ValueError: `restore_path` is set without `is_restore`, or does not name
            a checkpoint directory.
    """
    if cfg.restore_path and not cfg.is_restore:
        raise ValueError(
            f"restore_path is set to {cfg.restore_path!r} but is_restore is false, "
            f"so the run would start from scratch and ignore it. Set is_restore "
            f"true to resume from that checkpoint, or restore_path to null to "
            f"start fresh."
        )

    if not cfg.is_restore:
        return []

    if not cfg.restore_path:
        return list_checkpoints(cfg.checkpoint_dir)

    path = os.path.abspath(cfg.restore_path)
    if not _is_checkpoint(path):
        available = [p for _i, p in reversed(list_checkpoints(cfg.checkpoint_dir))]
        listing = (
            "\n".join(f"  {p}" for p in available)
            if available
            else f"  (none under {cfg.checkpoint_dir})"
        )
        raise ValueError(
            f"restore_path {path} is not a checkpoint directory - it has no "
            f"rllib_checkpoint.json. Name one save, not the directory holding "
            f"them. Available, newest first:\n{listing}"
        )

    return [(_checkpoint_iteration(path), path)]


def _checkpoint_iteration(path: str) -> int:
    """The iteration a checkpoint directory's name encodes, or -1 if it does not."""
    name = os.path.basename(os.path.normpath(path))
    if name.startswith(CHECKPOINT_PREFIX):
        try:
            return int(name[len(CHECKPOINT_PREFIX) :])
        except ValueError:
            pass
    return -1


def _fix_checkpoint_optimizer_betas(algo) -> None:
    """Work around Adam `betas` deserialising as tensors from a checkpoint."""

    def fix_betas(learner):
        for optimizer in learner._optimizer_parameters.keys():
            for param_group in optimizer.param_groups:
                if "betas" in param_group:
                    param_group["betas"] = tuple(
                        b.item() if torch.is_tensor(b) else b for b in param_group["betas"]
                    )

    algo.learner_group.foreach_learner(fix_betas)
