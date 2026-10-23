# 22. JEPA: What It Is and How It Could Serve This Project

This research note moved, with the `jepa` encoder it led to, into the cda-jepa package:
**[docs/jepa.md](https://github.com/ChuaCheowHuan/cda_jepa/blob/main/docs/jepa.md)**. Its section numbers are unchanged, so a reference
elsewhere in these docs to "22 §4.2" is that document's §4.2. Its history is in this repository's
git log up to the move ([17](17_changelog.md)).

In short: a Joint-Embedding Predictive Architecture predicts the latents of masked parts of the
observation from the visible parts, scored against an EMA copy of the encoder, and reconstructs
nothing. The note argues it suits this observation (the book grid is already what JEPA masks, and
input-space reconstruction would be dominated by volume jitter) and not this reward, and proposes
four uses. Two live here: the probe harness ([23](23_probe_harness.md) Part 1, Proposal A) and the
pretrained-weights format ([30](30_extensions.md) §3.1). The encoder with its auxiliary loss
(Proposal B), the action-conditioned world model (C) and offline pretraining (D) are cda-jepa.

To use it:

```bash
pip install "git+https://github.com/ChuaCheowHuan/cda_jepa"
```

```json
"extensions_enabled": ["jepa"],
"encoder_type": "jepa"
```

[30](30_extensions.md) §9 says what stayed in this repository for old configs and checkpoints.
