# 24. Offline JEPA Pretraining

`train/pretrain/` trains a JEPA encoder's self-supervised objective on observations alone — no
reward, no policy, no opponents — and writes weights a training run can start from. It is the
implementation of Proposal D in [22_jepa_integration.md](22_jepa_integration.md) §4.4.

Related: [22 §4.2](22_jepa_integration.md) (the encoder this pretrains),
[23_probe_harness.md](23_probe_harness.md) (the corpus reader it reuses, and how to measure what
pretraining did), [18_configuration.md](18_configuration.md) §5.4 (`pretrained_encoder_path`).

---

## 1. Why

[12](12_perspective_rl_researcher.md) §7 puts the shipped budget at ~262k env steps against a
realistic 10⁷–10⁸. Reward-driven learning is the expensive way to teach an encoder what an order
book looks like, and here it is also the *slow* way: the gradient reaching the encoder is a
high-variance policy gradient over a market that only just stopped rewarding passivity.

The JEPA objective needs none of that. It is dense — every token, every step — and it is defined on
observations, so it can run on data that already exists, at whatever scale the disk allows, before a
single PPO iteration.

---

## 2. Running it

```bash
python -m gym_continuousDoubleAuction.train.pretrain --steps 300
python -m gym_continuousDoubleAuction.train.pretrain --parquet <log_dir>/episodes --steps 2000
```

Defaults live in [`config/cli_defaults.json`](../config/cli_defaults.json) under `cda_pretrain`.
The encoder's *hyperparameters* are deliberately **not** duplicated there — they come from
`encoder_specs.jepa` in `train_config.json`, so a pretrained encoder is built from the same numbers
the training run will build it from, and the fingerprint written beside the weights is comparable
with the one `train.py` computes.

Then use it:

```jsonc
// config/train_config.json → encoder
"encoder_type": "jepa",
"pretrained_encoder_path": "pretrained/jepa"
```

---

## 3. What it reuses

Nothing here reads a Parquet file or steps an env:

| Reused | From | What it already handles |
|---|---|---|
| `from_rollouts`, `from_parquet` | `train/probe/corpus.py` | Both sources, the per-agent deduplication (S1-2 means an 8-agent record holds eight copies of every observation), episode marking, width validation |
| `split_masks` | `train/probe/probe.py` | The train/validation split, by episode |
| `build_module` | `train/probe/features.py` | Building the module *training* would build — same catalog, same `vf_share_layers`, same wrapper |

That last one matters more than it looks. Pretraining builds the whole `RLModuleSpec` and trains
the encoder inside it, rather than instantiating a `TorchJEPAEncoder` directly, so the pretrained
architecture is provably the one training will use. The pi and vf heads are built and never
touched; they cost a little memory and remove a whole class of "the pretrained thing was subtly not
the trained thing" bug.

---

## 4. The checkpoint, and the guard on it

A checkpoint directory holds three things:

| Piece | For |
|---|---|
| `encoder.pt` | The encoder's `state_dict`. What the probe loads into a module it built itself |
| `encoder_fingerprint.json` | `encoder_type` and `encoder_spec` — the guard |
| `rl_module/` | A full RLlib module checkpoint |

**The fingerprint is the point of the format.** `train.py` already refuses a restore whose
`encoder_type` or `encoder_spec` differs from the checkpoint's, because the weights are *that*
architecture's weights. Pretrained weights need exactly the same guard and get it from the same
`encoders.encoder_fingerprint` — one definition, so the two cannot drift apart.

That function exists because a `getattr`-only read once reported the `mlp` default from the first
champion onward, silently disabling the structural check for a whole run. This is a failure mode
the repository has already been bitten by.

The check runs at **spec-build time**, before the path reaches any encoder, so a mismatch names the
architectures instead of surfacing as a shape error on some env runner.

### 4.1 Why the path is not `RLModuleSpec.load_state_path`

There is a field on `RLModuleSpec` that looks made for this. It is not: in RLlib 2.56 it is stored,
merged and copied, and **never read back**. Setting it would have silently done nothing — the same
dead-config-key shape as `OrderBook`'s `tick_size` ([18](18_configuration.md) §6).

Instead the path rides on the model config, and `TorchJEPAEncoder.__init__` loads its own weights.
Every process that builds an encoder — env runners and learners alike — therefore loads them
itself, with no state to synchronise.

The load happens **last** in `__init__`, so anything explicit afterwards wins. That ordering is what
makes it safe on the two paths that would otherwise be surprising: a champion snapshot constructs
the encoder and then `set_state`s the trained weights over it, and a restored run does the same with
its checkpoint. Neither ends up running pretrained weights it did not ask for.

`mlp` cannot use a pretrained encoder and says so: it has no self-supervised objective, so nothing
could have produced those weights.

---

## 5. What to watch — and it is not the loss

```
steps            : 150
train loss       : 0.29140 -> 0.10990
validation loss  : 0.29386 -> 0.14596
latent std       : 0.71992 -> 0.66829
```

**`latent_std`, not the loss.** A collapsed JEPA maps every observation to the same vector, which
makes its prediction *perfect* — the loss goes to zero and reads as a spectacular success, with
throughput unchanged. `latent_std` goes to zero at the same moment and is the only signal that
separates the two. `PretrainReport.collapsed` checks for it and the CLI **exits non-zero**, rather
than leaving a good-looking number in the log beside weights nobody should load.

The validation curve is the second thing to read. It is split **by episode**, because consecutive
observations share three of their four snapshots — a row-level split would put near-duplicates of a
validation row into training, and the curve would mean nothing. In the run above it tracks the
training curve, so the objective is generalising to unseen episodes rather than memorising.

---

## 6. Measuring what pretraining did

The probe scores the same architecture twice, on identical rows with an identical split:

```bash
python -m gym_continuousDoubleAuction.train.probe --encoders jepa --pretrained pretrained/jepa
```

```
| target           | h  | metric | raw     | jepa    | jepa@pretrained |
| spread_change    | 1  | r2     | -0.0002 | -0.0094 | +0.0165         |
| spread_change    | 20 | r2     | -0.0733 | -0.0381 | +0.0105         |
| imbalance_change | 5  | r2     | -0.0248 | -0.0015 | +0.0438         |
| imbalance_change | 20 | r2     | -0.0245 | -0.3529 | +0.1090         |
| realized_vol     | 5  | r2     | +0.1197 | +0.1292 | -0.4961         |
```

Everything between the `jepa` and `jepa@pretrained` columns is what the objective taught the
encoder, and the pattern is coherent rather than uniform.

**It won on the structural targets and lost on the temporal ones.** `spread_change` and
`imbalance_change` improve at every horizon — `imbalance_change` at h=20 goes from −0.35 to +0.11 —
while `realized_vol` at h=5 falls from +0.13 to −0.50.

That is exactly what `mask_axis: level` should do. Level masking hides a contiguous depth band and
asks what depth is consistent with the rest of the book; it never asks a temporal question, so
nothing in the objective preserves temporal structure in the latent. The obvious next experiment is
`mask_axis: time`, or alternating the two.

**Do not over-read this.** It is a 150-step run on 4 random-agent episodes — a smoke budget. What it
establishes is that the mechanism works and that its effect is legible and directional, not that
pretraining is worth it at scale.

---

## 7. Distribution shift

A book made by uniformly-random agents does not look like one made by a trained league: different
spreads, different depth, different arrival intensity. Pretraining only on `--episodes` rollouts
fits a market the agent will never trade in.

Once a run exists, prefer `--parquet` over its episode record (`episode_sample_every` already bounds
what that costs), or treat random-agent data as a warm start only.

---

## 8. Layout

| Module | Owns |
|---|---|
| `pretrain.py` | The loop, the report, `save` / `load_into` / `verify_fingerprint` |
| `__init__.py` | What it is, why, and the exports |
| `__main__.py` | The CLI |

Tests: [`test/test_pretrain.py`](../gym_continuousDoubleAuction/test/test_pretrain.py) (20) — the
loop trains only what it should, a collapse is reported rather than hidden, the fingerprint refuses
a mismatched architecture, and a real training spec starts from the weights.
