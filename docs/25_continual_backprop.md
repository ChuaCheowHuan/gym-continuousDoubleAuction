# 25. Continual Backprop (moved to cda-cbp)

Continual Backprop (CBP) is backprop plus the continual, selective reinitialisation of low-utility
hidden units, to keep a network able to learn while the data it trains on changes
(Dohare, Hernandez-Garcia, Lan, Rahman, Mahmood & Sutton, Nature 2024). League self-play
is that kind of non-stationary problem by construction, which is why it was built here.

**It is no longer part of this repository.** It is the `cbp` extension in the
[cda-cbp](https://github.com/ChuaCheowHuan/cda_cbp) package, loaded through the extension point
of [30_extensions.md](30_extensions.md). The mechanism, its measurements and its settings moved
with it unchanged; the package has since added two settings (below, "Using it"):

| What | Where in cda_cbp |
|---|---|
| The full note that was this document: what CBP is, why it sits on the Learner and not in the encoder registry, the measurement that found no effect at ~20,000 optimiser steps, the cadence caveat, the proposals | [docs/continual_backprop.md](https://github.com/ChuaCheowHuan/cda_cbp/blob/main/docs/continual_backprop.md) |
| Every setting, its default, and the notes that were in `train_config.json` | [docs/settings.md](https://github.com/ChuaCheowHuan/cda_cbp/blob/main/docs/settings.md) |
| The `cbp_*` metrics and how to read them | [docs/metrics.md](https://github.com/ChuaCheowHuan/cda_cbp/blob/main/docs/metrics.md) |
| Moving a config or a checkpoint from the built-in version | [docs/migration.md](https://github.com/ChuaCheowHuan/cda_cbp/blob/main/docs/migration.md) |

**Section numbers.** That note keeps this document's numbering, so a reference elsewhere in these
docs to "[25](25_continual_backprop.md) §3.6" (or any other §) means that section of
`docs/continual_backprop.md` in cda_cbp.

## Using it

```bash
pip install git+https://github.com/ChuaCheowHuan/cda_cbp
```

Then enable it in `train_config.json` (or a config passed with `--config`):

```json
"extensions": {
  "extensions_enabled": ["cbp"],
  "extension_settings": {"cbp": {"replacement_rate": 1e-4, "utility": "contribution"}}
}
```

The settings are the old `cbp_*` keys without the prefix; any left out take the package's
defaults. The package has since added two settings whose defaults differ from what the built-in
version did: `optimizer` (`adam_gnt`, the authors' Adam with a per-weight timestep, against torch
Adam) and `count_rule` (`arxiv`, the arXiv paper's counter, against at most one replacement per
layer per step). Set `"optimizer": "torch_adam", "count_rule": "nature"` to repeat a built-in run;
a resumed checkpoint keeps its own behaviour without them. `"metrics_only": true` measures the utility and the plasticity metrics without replacing
anything. Installing the package changes no run until `cbp` is listed.

What stayed here:

- **Tuned Adam** (`adam_betas`, `adam_weight_decay`, [18](18_configuration.md)), which the CBP
  papers pair with it but which is a separate intervention. Its mixin is
  `train/model/optim_learner.py`.
- **The module layout contract** (`train/model/layout.py`), which tells code outside the model
  where each trunk ends and which heads read it. CBP uses it to find the units it may replace;
  `test_model_layout.py` fails here if a rename would break it.
- **The probe's effective rank** (`train/probe/rank.py`, [23](23_probe_harness.md)), the
  reward-free instrument for plasticity. cda_cbp's tests keep its torch copy the same measurement.

## Old configs and checkpoints

- A config, a `--set` override or a `$CDA_CONFIG_DIR` copy of `train_config.json` that still
  carries a `cbp_*` key fails at load, naming cda-cbp, rather than being ignored.
- A checkpoint written **without** CBP resumes as before.
- A checkpoint written **with** CBP on (`cbp_enabled` or `cbp_metrics_only`) needs cda-cbp
  installed. Without it the restore stops before RLlib loads anything, with a message naming the
  package; it does not fall back to an older checkpoint or a fresh run.
- With cda-cbp installed, resume it with `extensions_enabled: ["cbp"]` and the settings the run
  used (the old `continual_backprop` group, prefixes dropped). The restore check reads the old
  group as the extension's settings, so a changed setting, or a config that leaves CBP out, is
  refused as before. The per-unit utility, ages and replacement counts carry over.

The one-learner limit (CBP with `num_learners > 1` is refused, R-12) is now enforced by the
package's own validation; synchronising the choice across learners is work for that package.

The history of the in-tree version is in [17_changelog.md](17_changelog.md),
[16_verification_log.md](16_verification_log.md) and [29_fixed_issues.md](29_fixed_issues.md); the
move is in [17](17_changelog.md) §101 and §102.
