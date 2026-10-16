"""The action distribution, with a log-probability that survives a time rank of 1.

RLlib builds a `TorchMultiDistribution` for a `Dict` action space, and its
`logp` has a line meant for a `Discrete` child whose value carries a trailing
singleton:

    if isinstance(dist, TorchCategorical) and val.shape[-1] == 1 and val.ndim > 1:
        val = val.squeeze(-1)

A stateful module (the `lstm` encoder) is run with a time rank, and at
inference that rank is 1: logits are `(B, 1, n)` and a `Discrete` sample is
`(B, 1)`. The trailing 1 is then the *time* axis, not a stray dimension, and
squeezing it leaves `(B,)` against a distribution whose batch shape is `(B, 1)`.
The two broadcast to `(B, B)`. With one agent in the batch that is `(1, 1)` and
looks right; with two agents sharing a module in the same step, which is what
happens when a league champion is drawn for both opponent slots, every agent's
`action_logp` becomes a length-2 vector and the module-to-env connector, which
squeezes the time rank off each item, raises (issue #278). A stateless module has no time rank, so an `mlp` league never met it.

`time_rank_safe` returns the same distribution with that one condition fixed: a
trailing singleton is squeezed only when the value has more dimensions than the
distribution's batch shape, which is the case the line was written for.
"""

from __future__ import annotations

from typing import Dict, Type

import torch
import tree
from ray.rllib.core.distribution.torch.torch_distribution import (
    TorchCategorical,
    TorchMultiDistribution,
)

_SAFE: Dict[type, type] = {}


def _matched(value: torch.Tensor, dist) -> torch.Tensor:
    """`value`, squeezed only when it has a trailing dimension the dist lacks."""
    if (
        isinstance(dist, TorchCategorical)
        and value.dim() > 1
        and value.shape[-1] == 1
        and value.dim() > len(dist._dist.batch_shape)
    ):
        return torch.squeeze(value, dim=-1)
    return value


def time_rank_safe(dist_cls: Type) -> Type:
    """`dist_cls` with a `logp` that does not squeeze a time rank of 1.

    Anything that is not a `TorchMultiDistribution` is returned unchanged, so
    this is safe to apply to whatever class a catalog produced. The result is
    cached, so asking twice returns the same class.
    """
    if not (isinstance(dist_cls, type) and issubclass(dist_cls, TorchMultiDistribution)):
        return dist_cls
    if dist_cls in _SAFE:
        return _SAFE[dist_cls]
    if getattr(dist_cls, "_cda_time_rank_safe", False):
        return dist_cls

    class TimeRankSafe(dist_cls):
        _cda_time_rank_safe = True

        def logp(self, value):
            if isinstance(value, torch.Tensor):
                # The flattened, concatenated form: RLlib's own path, unchanged.
                return super().logp(value)
            flat = tree.flatten(value)
            return sum(
                dist.logp(_matched(val, dist))
                for val, dist in zip(flat, self._flat_child_distributions)
            )

    TimeRankSafe.__name__ = dist_cls.__name__
    TimeRankSafe.__qualname__ = dist_cls.__qualname__
    _SAFE[dist_cls] = TimeRankSafe
    _SAFE[TimeRankSafe] = TimeRankSafe
    return TimeRankSafe
