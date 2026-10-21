# 30. Extensions: Adding to the Learning Stack From Another Package

An extension is a separately installed Python package that adds to how agents learn, without an
edit to this repository. It can bring a Learner mixin (a new loss term, or a replacement for PPO's
loss), an RLModule mixin (extra heads or state), an env wrapper, or any mix of the three.

Installing a package changes no run. A run uses an extension only when its name is listed in
`extensions_enabled`; uninstalling the package and removing the name is the whole undo. With
nothing enabled, the Learner class, the module classes and the env are the same objects as before
this feature existed, the Learner's `learner_config_dict` gains no `extensions` group, and a
checkpoint's sidecar gains no key.

The first extension is DiscoRL (the `cda-discorl` package in its own repository,
[cda_disco_rl](https://github.com/ChuaCheowHuan/cda_disco_rl)),
which brings learning mechanisms from *Discovering state-of-the-art reinforcement learning
algorithms* (Oh et al., 2025) to the PPO learner. §7 shows how to install, enable and compare it.

The code is [`train/extensions.py`](../gym_continuousDoubleAuction/train/extensions.py). Related:
[18_configuration.md](18_configuration.md) §5.7 (the config group),
[25_continual_backprop.md](25_continual_backprop.md) §2.5 (why Learner-level changes are not
encoders), [10_testing.md](10_testing.md) (the two test files).

---

## 1. What a package declares

A package registers one `Extension` object under the `gym_cda.extensions` entry-point group:

```toml
# the extension package's pyproject.toml
[project.entry-points."gym_cda.extensions"]
myext = "my_package:EXTENSION"
```

```python
from gym_continuousDoubleAuction.train.extensions import Extension

EXTENSION = Extension(
    name="myext",  # must equal the entry-point name
    version="0.1.0",  # recorded beside each checkpoint
    defaults={"coeff": 0.1},  # every setting it accepts, with its default
    validate=check,  # optional (settings, train_config) -> None, raises
    learner_mixin=MyLearnerMixin,  # optional
    learner_order=0,  # optional; a higher value wraps further out
    module_mixin=MyModuleMixin,  # optional
    module_ids=pick,  # optional (settings, trainable_ids) -> ids; default all
    env_wrapper=wrap,  # optional (env, settings) -> env
    structural_keys=("width",),  # settings that change a tensor shape
)
```

Discovery fails loudly: an entry point that does not resolve to an `Extension`, or whose `name`
differs from the entry-point name, raises on the first lookup.

## 2. Enabling one

```json
"extensions_enabled": ["myext"],
"extension_settings": {"myext": {"coeff": 0.2}}
```

The extension owns its settings the way `config/*.json` owns this repository's: `defaults` lists
every key, and a key it does not list is an error when the `TrainConfig` is built (CLAUDE.md
rule 1). Missing keys take the default. Enabling a name that is not installed, or listing one
twice, raises. Settings for an extension that is not enabled are ignored, so a config can keep
them while the package is uninstalled.

## 3. Where each piece is composed

| Piece | Composed in | Order |
|---|---|---|
| Learner mixin | `build._learner_class`, after the encoder's Learner and before Continual Backprop and tuned Adam | Mixins sorted by `learner_order` (highest outermost), then by name, ahead of the base |
| Module mixin | `build.build_config`, on each trainable module the extension's `module_ids` selects | By extension name; frozen baselines are never touched |
| Env wrapper | `build.register_env`, on every env RLlib creates | By extension name |

So an extension inherits the MoE and JEPA loss terms, and CBP still wraps the result. The composed
classes are built with `type()` and travel to remote Learners and runners pickled by value, so a
remote process needs the package importable but no registration of its own.

Two modules in one league can differ: an extension whose `module_ids` picks `policy_0` only leaves
`policy_1` as plain PPO, which is how one run compares the two. The module class carries its
extension's resolved settings as `extension_settings`. A Learner mixin reads its own with
`settings_for(self.config.learner_config_dict, "myext")`.

An env wrapper must not change the observation or action space: the spaces are built from the
unwrapped env before any wrapper runs. `train.evaluate` builds its own env from the checkpoint's
`env_config`, so it rolls episodes without any wrapper.

## 4. Adding a loss term, or replacing PPO's

`CDAPPOTorchLearner.compute_loss_for_module` is PPO's loss plus the MoE term, and
`CDAJEPALearner` adds the JEPA term on top through `super()`. PPO's own part sits behind one
method, `_policy_value_loss`:

- **To add a term**, override `compute_loss_for_module` and add to `super()`'s result.
- **To replace PPO's policy, value and entropy loss**, override `_policy_value_loss`. The MoE and
  JEPA terms are still added around it. Overriding `compute_loss_for_module` instead would drop
  them.

[`test_loss_seam.py`](../gym_continuousDoubleAuction/test/test_loss_seam.py) pins both halves for
the PPO and JEPA Learners.

## 5. Checkpoints and resumes

- `league_state.json` records `{"extensions": {name: version}}` beside a checkpoint whose run
  enabled any. A restore reads it before RLlib unpickles anything, and refuses by name when one is
  not installed: "trained with extension(s) myext 0.1.0, which are not installed here".
- `extensions_enabled` is unrestorable: changing it on a resume raises, whether it turns an
  extension on or off. A default run's config carries no extensions group, and it is compared as
  "none enabled". A checkpoint from before this feature reads the same way, so it restores with the
  default config.
- Every resolved setting is fingerprinted as `ext.<name>.<key>`. Changing one on a resume raises
  as unrestorable; changing one listed in `structural_keys` raises as structural.

## 6. Tests

[`test_extensions.py`](../gym_continuousDoubleAuction/test/test_extensions.py) installs a dummy
package as a `*.dist-info` directory on `sys.path`, exactly as pip leaves one, so discovery goes
through real entry points. It covers discovery errors, the nothing-enabled identity, validation,
composition order and the resume guards.
[`integration/test_extensions_wiring.py`](../gym_continuousDoubleAuction/test/integration/test_extensions_wiring.py)
builds a real `Algorithm` with a dummy extension enabled, trains one iteration through the
replaced loss, and round-trips a checkpoint.

An extension's own repository runs its tests against this one, so these two files are the
contract it relies on.

## 7. Using the DiscoRL extension

The `cda-discorl` package lives in its own repository,
[cda_disco_rl](https://github.com/ChuaCheowHuan/cda_disco_rl), and imports nothing from DeepMind's
`disco_rl`. Its own documentation covers each component, every setting and the comparison
against PPO. This section covers only the steps on this side.

### 7.1 Install

Install this repository first, then the package:

```bash
pip install -e .
pip install "git+https://github.com/ChuaCheowHuan/cda_disco_rl"
```

Installing it changes no run. Run `pip uninstall cda-discorl` and remove its name from
`extensions_enabled` to undo it.

### 7.2 Enable it for a run

For `train.train`, copy `config/train_config.json`, set the `extensions` group in the copy, and
pass the copy with `--config`:

```json
"extensions": {
  "extensions_enabled": ["discorl"],
  "extension_settings": {"discorl": {"modules": ["policy_0"], "target_policy": true}}
}
```

With two trained agents, this setting gives `policy_0` the component and leaves `policy_1` as plain
PPO, so one league compares the two. The package's
[configuration guide](https://github.com/ChuaCheowHuan/cda_disco_rl/blob/main/docs/configuration.md)
lists the five components (`target_policy`, `adv_ema`, `value_norm`, `env_variety` and
`policy_prediction`), their settings and ready-made blocks.

### 7.3 Compare it against plain PPO

`train.compare` takes the same two keys with `--set`. Running it once with them and once without
gives a multi-seed comparison:

```bash
python -m gym_continuousDoubleAuction.train.compare \
  --encoders mlp --seeds 0 1 2 --iters 30 --out out/target_policy \
  --agents 4 --trained-agents 2 --max-step 512 --episodes-per-iter 4 --no-probe \
  --set 'extensions_enabled=["discorl"]' \
  --set 'extension_settings={"discorl":{"modules":["policy_0","policy_1"],"target_policy":true}}'
```

The package's
[findings](https://github.com/ChuaCheowHuan/cda_disco_rl/blob/main/docs/findings.md) record the
results so far. At three seeds and 30 iterations, no component separated from PPO on return.
Target policy had the best mean, and the categorical critic and Disco103 did not learn here, so
the package leaves both out.

### 7.4 What to read in the logs

Each component logs under its trained module's learner metrics, with a `discorl_` prefix:

| Metric | Component |
|---|---|
| `discorl_target_kl` | `target_policy` |
| `discorl_value_norm_mean`, `discorl_value_norm_std` | `value_norm` |
| `discorl_policy_prediction_loss` | `policy_prediction` |

`vf_explained_var` stays comparable with a plain PPO run's. With `value_norm` on it is computed
from normalised targets and predictions, and normalising both the same way leaves explained
variance unchanged.
