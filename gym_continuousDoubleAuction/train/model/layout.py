"""Where a trainable RLModule's trunks end and which heads read them.

A small, stable description of the module layout for code that works on the
network's units from outside the model code, such as Continual Backprop.
Without it, such code has to know this repository's attribute paths
(`encoder.actor_encoder.net.mlp`, `pi`, `vf`, an LSTM encoder's `lstm`), and a
rename here would break it silently. `test_model_layout.py` pins what this
returns for every encoder, so a rename fails in this repository's own CI.

Plain torch only: nothing here imports RLlib.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import torch.nn as nn

#: The trunks of an RLlib PPO encoder, and the heads each one feeds. `encoder`
#: is the shared trunk under `vf_share_layers`, feeding both heads; otherwise the
#: actor and critic are independent networks with one head each.
_TRUNKS = (
    ("encoder", ("pi", "vf")),
    ("actor_encoder", ("pi",)),
    ("critic_encoder", ("vf",)),
)


@dataclass
class TrunkOutput:
    """One trunk: the module that produces its output, and the heads that read it.

    Attributes:
        name: The trunk's attribute on the encoder - `encoder`, `actor_encoder`
            or `critic_encoder`.
        mlp: The trunk's `nn.Sequential` when it is an MLP (RLlib's
            `TorchMLPEncoder`), else None.
        mlp_path: `mlp`'s path from the module root, e.g.
            `encoder.actor_encoder.net.mlp`.
        lstm: The trunk's `nn.LSTM` when it is the recurrent encoder, else None.
        lstm_path: `lstm`'s path from the module root.
        heads: The head modules that read this trunk's output, in `pi`, `vf`
            order; a head the module does not have is left out.
        extra_heads: Other modules that read this trunk's output, added by a
            module mixin (an extension's auxiliary head) and declared in the
            class attribute `extra_trunk_heads` (see `trunk_outputs`).
    """

    name: str
    mlp: Optional[nn.Sequential] = None
    mlp_path: Optional[str] = None
    lstm: Optional[nn.LSTM] = None
    lstm_path: Optional[str] = None
    heads: List[nn.Module] = field(default_factory=list)
    extra_heads: List[nn.Module] = field(default_factory=list)


def trunk_outputs(module: nn.Module) -> List[TrunkOutput]:
    """Every trunk of `module` that has an MLP or LSTM output, with its heads.

    `module` is expected unwrapped (not a DDP wrapper). A trunk of any other
    kind (a transformer, which ends in pooling and a LayerNorm) is left out:
    it has no single layer whose units are the trunk's output.

    A class in the module's MRO that adds a head reading a trunk declares it as
    `extra_trunk_heads = {trunk name: (attribute, ...)}`; the declarations of
    every class merge, nearest class first, each attribute once. Without it,
    code that resets a trunk unit would leave that head reading the new unit
    with the old unit's weights (#338).
    """
    encoder = getattr(module, "encoder", None)
    if encoder is None:
        return []
    extra = _extra_trunk_heads(type(module))
    found: List[TrunkOutput] = []
    for name, head_names in _TRUNKS:
        trunk = getattr(encoder, name, None)
        if trunk is None:
            continue
        heads = [h for h in (getattr(module, n, None) for n in head_names) if h is not None]
        mlp = getattr(getattr(trunk, "net", None), "mlp", None)
        lstm = getattr(trunk, "lstm", None)
        extra_heads = [
            h for h in (getattr(module, n, None) for n in extra.get(name, ())) if h is not None
        ]
        out = TrunkOutput(name=name, heads=heads, extra_heads=extra_heads)
        if isinstance(mlp, nn.Sequential):
            out.mlp, out.mlp_path = mlp, f"encoder.{name}.net.mlp"
        if isinstance(lstm, nn.LSTM):
            out.lstm, out.lstm_path = lstm, f"encoder.{name}.lstm"
        if out.mlp is not None or out.lstm is not None:
            found.append(out)
    return found


def _extra_trunk_heads(cls: type) -> Dict[str, List[str]]:
    """`extra_trunk_heads` of every class in `cls`'s MRO, merged nearest first."""
    merged: Dict[str, List[str]] = {}
    for klass in cls.__mro__:
        for trunk, names in (vars(klass).get("extra_trunk_heads") or {}).items():
            have = merged.setdefault(trunk, [])
            have.extend(n for n in names if n not in have)
    return merged
