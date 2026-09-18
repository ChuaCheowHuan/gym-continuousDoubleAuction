"""Training a JEPA encoder on observations alone, before any PPO run.

Why
---
`doc/12` §7 puts the shipped budget at ~262k env steps and a realistic one at
10^7-10^8. Reward-driven learning is the expensive way to teach an encoder what
an order book looks like, and in this env it is also the *slow* way: the
gradient reaching the encoder is a high-variance policy gradient over a market
that only recently stopped rewarding passivity.

The JEPA objective needs none of that. It is dense - every token, every step -
and it needs no reward, no policy and no opponents, so it can be run on
observations that already exist, at whatever scale the disk allows, before a
single PPO iteration.

Reuse rather than rebuild
-------------------------
Nothing here reads a Parquet file or steps an env. `train/probe/corpus.py`
already does both, already deduplicates the per-agent copies (S1-2 means an
8-agent record holds eight copies of every observation), already marks episode
boundaries and already validates widths against the layout. `train/probe/probe.py`
already knows how to split by episode. This package is the optimiser and the
checkpoint format around them.

The checkpoint's fingerprint
----------------------------
Weights are saved beside `encoder_fingerprint(encoder_type, encoder_spec)` and a
mismatch on load is a hard error. That is the same guard `train.py` applies to a
restore, through the same function, and it exists for the same reason: the
weights are *that architecture's* weights. `_encoder_fingerprint` was itself
written after a `getattr`-only read silently reported the `mlp` default from the
first champion onward, disabling the structural check for a whole run - so this
is a failure mode the repository has already been bitten by once.

Run it
------
    python -m gym_continuousDoubleAuction.train.pretrain --steps 300
    python -m gym_continuousDoubleAuction.train.pretrain --parquet <log_dir>/episodes

Then score what it learned, reward-free, against the same architecture
untrained - which is exactly the comparison the probe harness already renders
side by side:

    python -m gym_continuousDoubleAuction.train.probe --encoders jepa \\
        --checkpoint <out_dir> --module-id pretrained

What to watch
-------------
`latent_std`, not the loss. A collapsed JEPA maps every observation to the same
vector, which makes its prediction *perfect* - the loss goes to zero and reads
as a spectacular success. `PretrainReport.collapsed` checks for it, and the CLI
says so in as many words rather than leaving a good-looking number to be
believed.

Detection is not prevention, and until recently this package had only the first.
The `variance_coeff` hinge that is supposed to resist a collapse was computed
from the EMA *target*, built under `torch.no_grad()`, so it contributed exactly
zero gradient and the encoder had no active defence at all - doc/15 S2-9. It is
computed on the online side now, so the knob does what this file says it does.

Distribution shift
------------------
A book made by uniformly-random agents does not look like a book made by a
trained league: different spreads, different depth, different arrival intensity.
Pretraining only on `--episodes` rollouts fits a market the agent will never
trade in. Once a run exists, prefer `--parquet` over its episode record, or
treat random-agent data as a warm start only.
"""
from gym_continuousDoubleAuction.train.pretrain.pretrain import (
    FINGERPRINT_FILE,
    MODULE_SUBDIR,
    PRETRAINABLE,
    WEIGHTS_FILE,
    PretrainReport,
    load_into,
    module_state_path,
    pretrain,
    save,
    verify_fingerprint,
)

__all__ = [
    "FINGERPRINT_FILE", "MODULE_SUBDIR", "PRETRAINABLE", "WEIGHTS_FILE",
    "PretrainReport", "load_into", "module_state_path", "pretrain", "save",
    "verify_fingerprint",
]
