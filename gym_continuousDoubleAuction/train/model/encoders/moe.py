"""Top-k gated mixture of experts, as a transformer feed-forward sublayer.

Replaces the dense feed-forward in `TransformerBlock`. Each token is routed by a
learned gate to its `top_k` experts out of `num_experts`, and the experts'
outputs are combined weighted by the renormalised gate probabilities.

The auxiliary loss
------------------
Nothing in the policy gradient rewards a gate for using more than one expert -
collapsing onto a single expert is a perfectly good local optimum, and gives you
a dense feed-forward that cost `num_experts` times as much to build. The
standard remedy (Switch Transformer, Fedus et al. 2021) is a load-balancing
term:

    aux = num_experts * sum_i  f_i * P_i

where `f_i` is the fraction of tokens routed to expert `i` and `P_i` is the mean
gate probability assigned to it. It is minimised when both are uniform, and
because `f_i` is a counting statistic the gradient flows through `P_i` only.

That term has to reach the optimiser, and PPO's loss is computed in the Learner,
not here. So `forward` returns it alongside the output, `TransformerBlock` and
the encoder pass it up, `CDAPPOTorchRLModule._forward_train` puts it in
`fwd_out`, and `CDAPPOTorchLearner` adds it to the total loss. Every step of that
chain exists because the one before it cannot see the next.

Expect collapse anyway
----------------------
This env's observation is 168 floats and the league is small. MoE's premise is
capacity you cannot afford densely, which is not obviously the situation here,
so the honest prior is that the experts specialise weakly or not at all. That is
why `expert_fractions` is reported as a metric rather than left implicit: a
degenerate MoE and a healthy one produce identical losses and identical
throughput, and differ only in that number.
"""
from __future__ import annotations

from typing import Tuple

import torch
import torch.nn as nn

from gym_continuousDoubleAuction.train.model.encoders.blocks import feedforward


class MoEFeedForward(nn.Module):
    """`num_experts` feed-forwards, `top_k` of them applied per token.

    `forward` returns `(output, stats)` rather than a bare tensor, which is what
    `TransformerBlock` detects to decide whether it is holding an MoE.
    """

    def __init__(
        self,
        d_model: int,
        ff_dim: int,
        num_experts: int,
        top_k: int,
        dropout: float = 0.0,
    ) -> None:
        super().__init__()
        if num_experts < 2:
            raise ValueError(
                f"num_experts must be >= 2 for a mixture; got {num_experts}. "
                "Use the `transformer` encoder for a dense feed-forward."
            )
        if not 1 <= top_k <= num_experts:
            raise ValueError(
                f"top_k must be in [1, num_experts={num_experts}]; got {top_k}."
            )

        self.num_experts = num_experts
        self.top_k = top_k
        self.gate = nn.Linear(d_model, num_experts, bias=False)
        self.experts = nn.ModuleList(
            feedforward(d_model, ff_dim, dropout) for _ in range(num_experts)
        )

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, dict]:
        """`(B, T, d_model)` in; `(output, stats)` out.

        `stats` carries the load-balancing loss and the per-expert routing
        fractions, which is what makes expert collapse visible.
        """
        flat = x.reshape(-1, x.shape[-1])
        probs = self.gate(flat).softmax(dim=-1)

        top_probs, top_idx = probs.topk(self.top_k, dim=-1)
        # Renormalise so each token's expert weights sum to 1 regardless of how
        # much mass the gate put outside its top k.
        top_probs = top_probs / top_probs.sum(dim=-1, keepdim=True)

        out = torch.zeros_like(flat)
        for slot in range(self.top_k):
            idx = top_idx[:, slot]
            weight = top_probs[:, slot].unsqueeze(-1)
            for expert_id, expert in enumerate(self.experts):
                selected = idx == expert_id
                if selected.any():
                    out[selected] += weight[selected] * expert(flat[selected])

        # f_i: share of (token, slot) assignments each expert received. Counting
        # only, so it carries no gradient - the aux loss learns through P_i.
        one_hot = torch.zeros_like(probs)
        one_hot.scatter_(-1, top_idx, 1.0)
        fractions = one_hot.mean(dim=0)
        mean_prob = probs.mean(dim=0)
        aux_loss = self.num_experts * torch.sum(fractions.detach() * mean_prob)

        return out.reshape(x.shape), {
            "aux_loss": aux_loss,
            "expert_fractions": fractions.detach(),
        }


def moe_factory(
    d_model: int,
    ff_dim: int,
    num_experts: int,
    top_k: int,
    dropout: float = 0.0,
):
    """An `ff_factory` for `TransformerBlock` that builds `MoEFeedForward`."""

    def build() -> MoEFeedForward:
        return MoEFeedForward(
            d_model=d_model,
            ff_dim=ff_dim,
            num_experts=num_experts,
            top_k=top_k,
            dropout=dropout,
        )

    return build
