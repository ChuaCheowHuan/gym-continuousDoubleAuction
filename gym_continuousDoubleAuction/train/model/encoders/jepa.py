"""Joint-Embedding Predictive Architecture over the order-book grid.

A transformer encoder that, *in addition* to producing the policy's latent,
trains itself on a self-supervised objective: mask part of the book, predict the
masked part's representation from the visible part, and score the prediction
against a slowly-updated copy of the encoder itself. Nothing reconstructs the
input.

Why this objective for this observation
---------------------------------------
The obvious alternative - a masked autoencoder reconstructing the hidden
*input* - fails here for a measured reason. The per-channel standard deviations
of a `both` token `[bid_price, bid_size, ask_price, ask_size]` over 40 real
steps are `[1.27, 8.17, 0.046, 9.52]`: the size channels are `sqrt(volume)` and
run some 200x the ask-price channel. A squared-error loss in input space is
dominated by queue-size jitter, which is the least predictable and least
economically meaningful quantity in the observation.

Predicting in *representation* space removes that by construction. The target is
produced by an encoder that is itself being trained, so anything genuinely
unpredictable is free to be dropped from the representation and the loss stops
paying attention to it. See doc/22 2.2.

What is masked
--------------
The observation is a grid, so the masks are structural rather than random
patches, and each asks a microstructure question:

    "level"  hide a contiguous block of book levels, predict them from the rest
             - what shape of depth is consistent with this touch?
    "time"   hide whole snapshots, predict them from the others
             - where is the book heading?
    "random" hide scattered tokens; the ablation baseline that uses no structure

One mask is drawn per forward pass and shared across the batch. Per-sample masks
would make the context sequence ragged, and the gain - decorrelating the mask
from the batch - is not worth a variable-length path here, where a batch is a
few hundred rows and the mask is redrawn every step anyway.

The cost, stated plainly
------------------------
The policy latent is computed from the **unmasked** observation. It has to be:
the agent must act on everything it was given, not on a random subset. So a
training step runs the trunk twice - once unmasked for the policy, once masked
for the objective - plus the target encoder. Inference runs it once, exactly
like `transformer`.

Isolation
---------
This module imports the shared primitives and subclasses none of them.
`tokenize`, `positional_index`, `TransformerBlock`, `AttentionPool` and
`PrivateToken` are all reused as they stand, so selecting `mlp`, `transformer`,
`lstm` or `moe_transformer` produces exactly what it produced before this file
existed. The ~15 lines of "project, norm, add positions, attend, pool" that this
duplicates from `transformer` are the deliberate price of that.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import torch
import torch.nn as nn
import torch.nn.functional as F
from ray.rllib.core.columns import Columns
from ray.rllib.core.models.base import ENCODER_OUT, Encoder, Model
from ray.rllib.core.models.configs import ModelConfig
from ray.rllib.core.models.torch.base import TorchModel
from ray.rllib.utils.annotations import override

from gym_continuousDoubleAuction.train.model.encoders import (
    encoder_settings,
    register,
)
from gym_continuousDoubleAuction.train.model.encoders.blocks import (
    AttentionPool,
    PrivateToken,
    TransformerBlock,
)
from gym_continuousDoubleAuction.train.model.encoders.obs_layout import (
    ObsLayout,
    split_private,
)
from gym_continuousDoubleAuction.train.model.encoders.tokenize import (
    token_shape,
    tokenize,
)
from gym_continuousDoubleAuction.train.model.encoders.transformer import (
    positional_index,
)

#: Defaults for the `jepa` block of `encoder_specs`. The transformer keys mean
#: exactly what they do there; the rest configure the objective.
JEPA_DEFAULTS = {
    "tokenization": "both",
    "d_model": 128,
    "num_heads": 4,
    "num_layers": 2,
    "ff_dim": 256,
    "dropout": 0.0,
    "pool": "attention",
    "mask_axis": "level",
    "mask_ratio": 0.4,
    "predictor_layers": 1,
    "predictor_dim": 64,
    "ema_decay": 0.996,
    "aux_loss_coeff": 0.1,
    "variance_coeff": 1.0,
}

#: How a token sequence is reduced to one latent vector. Same set as
#: `transformer`, named here so this module does not depend on that one's.
POOLINGS = ("mean", "attention")

#: What a mask hides. See the module docstring.
MASK_AXES = ("level", "time", "random")

#: Floor the variance hinge pushes each latent dimension's standard deviation
#: above. Not a knob: it is the unit scale that LayerNormed targets already sit
#: near, so the hinge is inactive on a healthy encoder and only bites during a
#: collapse.
VARIANCE_TARGET = 1.0


def _num_tokens(layout: ObsLayout, tokenization: str) -> int:
    return token_shape(layout, tokenization)[0]


def sample_mask(
    num_tokens: int,
    layout: ObsLayout,
    tokenization: str,
    mask_axis: str,
    mask_ratio: float,
    generator: Optional[torch.Generator] = None,
) -> torch.Tensor:
    """Indices of the tokens to hide. One mask per forward, shared by the batch.

    Args:
        num_tokens: Length of the token sequence.
        layout: The observation layout, for the grid's stride.
        tokenization: Which tokenisation produced the sequence.
        mask_axis: One of `MASK_AXES`.
        mask_ratio: Fraction of tokens to hide.
        generator: Optional RNG, so a test can pin the draw.

    Returns:
        A 1-D long tensor of masked positions, never empty and never the whole
        sequence - a mask covering everything leaves the context encoder no
        input, and an empty one leaves the objective nothing to predict.

    Raises:
        ValueError: on an unknown `mask_axis`.
    """
    if mask_axis not in MASK_AXES:
        raise ValueError(
            f"Unknown mask_axis {mask_axis!r}. Available: {', '.join(MASK_AXES)}."
        )

    count = int(round(num_tokens * mask_ratio))
    count = max(1, min(count, num_tokens - 1))

    def draw(n, k):
        return torch.randperm(n, generator=generator)[:k]

    # A tokenisation only has the axes it has, and only `both` has two of them.
    # `level` tokenisation is one snapshot, so it has no time axis; `time`
    # tokenisation makes a whole snapshot one token, so it has no level axis.
    # Asking for the missing axis degenerates to a random mask rather than
    # raising: the axis is a property of the tokenisation, not a user error,
    # and an ablation sweeping (tokenization x mask_axis) should not have to
    # special-case the combinations that collapse.
    axis_exists = (
        mask_axis == "time" and tokenization in ("time", "both")
        or mask_axis == "level" and tokenization in ("level", "both")
    )
    if mask_axis == "random" or not axis_exists or tokenization != "both":
        return draw(num_tokens, count)

    # `both` lays tokens out time-major, `k_rows + 1` per snapshot.
    stride = layout.k_rows + 1

    if mask_axis == "time":
        snapshots = max(1, min(
            int(round(layout.n_hist * mask_ratio)), layout.n_hist - 1
        ))
        chosen = draw(layout.n_hist, snapshots)
        offsets = torch.arange(stride)
        return (chosen.unsqueeze(1) * stride + offsets).reshape(-1)

    # "level" under `both`: hide the same contiguous depth band in every
    # snapshot, so the question is "what depth is consistent with this touch"
    # rather than "what happened at t=2".
    levels = max(1, min(int(round(layout.k_rows * mask_ratio)), layout.k_rows - 1))
    start = int(torch.randint(0, layout.k_rows - levels + 1, (1,),
                              generator=generator).item())
    band = torch.arange(start, start + levels)
    times = torch.arange(layout.n_hist)
    return (times.unsqueeze(1) * stride + band).reshape(-1)


class _Trunk(nn.Module):
    """Project tokens, add positions, attend. The part that is EMA-copied.

    Kept as its own module for exactly that reason: the target encoder is a
    frozen copy of this and nothing else, so `copy.deepcopy(self.trunk)` is the
    whole of it. Folding these layers into the encoder would make the copy
    recursive.
    """

    def __init__(self, config: "JEPAEncoderConfig", token_dim: int,
                 time_size: int, level_size: int) -> None:
        super().__init__()
        self.project = nn.Linear(token_dim, config.d_model)
        # Not a knob, for the reason in the module docstring: the size channels
        # run ~200x the price channels and share a token with them.
        self.norm_in = nn.LayerNorm(config.d_model)
        self.time_embedding = nn.Embedding(time_size, config.d_model)
        self.level_embedding = nn.Embedding(level_size, config.d_model)
        self.blocks = nn.ModuleList(
            TransformerBlock(
                d_model=config.d_model,
                num_heads=config.num_heads,
                ff_dim=config.ff_dim,
                dropout=config.dropout,
            )
            for _ in range(config.num_layers)
        )
        self.norm_out = nn.LayerNorm(config.d_model)

    def embed(self, tokens: torch.Tensor, time_idx: torch.Tensor,
              level_idx: torch.Tensor) -> torch.Tensor:
        """Tokens plus their positions, before any attention."""
        x = self.norm_in(self.project(tokens))
        return x + self.time_embedding(time_idx) + self.level_embedding(level_idx)

    def forward(self, tokens: torch.Tensor, time_idx: torch.Tensor,
                level_idx: torch.Tensor,
                extra: Optional[torch.Tensor] = None) -> torch.Tensor:
        """`(B, T, token_dim)` -> `(B, T [+ extra], d_model)`.

        `extra` is appended after the positional embeddings and before the
        blocks - it is the private token, which belongs to no time and no book
        level and so must not receive either embedding.
        """
        x = self.embed(tokens, time_idx, level_idx)
        if extra is not None:
            x = torch.cat([x, extra], dim=-2)
        for block in self.blocks:
            x = block(x)
        return self.norm_out(x)


class _Predictor(nn.Module):
    """Predict masked-position latents from the visible ones.

    Narrower than the trunk by default (`predictor_dim` < `d_model`). That
    asymmetry is deliberate and is part of what discourages collapse: a
    predictor powerful enough to invert any encoding would let the trunk emit
    anything at all, including a constant.
    """

    def __init__(self, config: "JEPAEncoderConfig", time_size: int,
                 level_size: int) -> None:
        super().__init__()
        self.enter = nn.Linear(config.d_model, config.predictor_dim)
        #: Stands in for a hidden token; its position says which one.
        self.mask_token = nn.Parameter(torch.zeros(1, 1, config.predictor_dim))
        nn.init.normal_(self.mask_token, std=0.02)
        self.time_embedding = nn.Embedding(time_size, config.predictor_dim)
        self.level_embedding = nn.Embedding(level_size, config.predictor_dim)
        self.blocks = nn.ModuleList(
            TransformerBlock(
                d_model=config.predictor_dim,
                num_heads=config.num_heads,
                ff_dim=config.predictor_dim * 2,
                dropout=config.dropout,
            )
            for _ in range(config.predictor_layers)
        )
        self.norm = nn.LayerNorm(config.predictor_dim)
        self.leave = nn.Linear(config.predictor_dim, config.d_model)

    def forward(self, context: torch.Tensor, masked_time: torch.Tensor,
                masked_level: torch.Tensor) -> torch.Tensor:
        """`(B, C, d_model)` context -> `(B, M, d_model)` at the masked slots."""
        batch, num_masked = context.shape[0], masked_time.shape[0]

        x = self.enter(context)
        slots = self.mask_token.expand(batch, num_masked, -1)
        slots = slots + self.time_embedding(masked_time) + self.level_embedding(
            masked_level
        )

        x = torch.cat([x, slots], dim=-2)
        for block in self.blocks:
            x = block(x)
        return self.leave(self.norm(x[:, -num_masked:]))


@dataclass
class JEPAEncoderConfig(ModelConfig):
    """Config for `TorchJEPAEncoder`."""

    layout: ObsLayout = None
    tokenization: str = JEPA_DEFAULTS["tokenization"]
    d_model: int = JEPA_DEFAULTS["d_model"]
    num_heads: int = JEPA_DEFAULTS["num_heads"]
    num_layers: int = JEPA_DEFAULTS["num_layers"]
    ff_dim: int = JEPA_DEFAULTS["ff_dim"]
    dropout: float = JEPA_DEFAULTS["dropout"]
    pool: str = JEPA_DEFAULTS["pool"]
    mask_axis: str = JEPA_DEFAULTS["mask_axis"]
    mask_ratio: float = JEPA_DEFAULTS["mask_ratio"]
    predictor_layers: int = JEPA_DEFAULTS["predictor_layers"]
    predictor_dim: int = JEPA_DEFAULTS["predictor_dim"]
    ema_decay: float = JEPA_DEFAULTS["ema_decay"]
    #: Weight on the latent-prediction loss. Read by the Learner, not here.
    aux_loss_coeff: float = JEPA_DEFAULTS["aux_loss_coeff"]
    #: Weight on the variance hinge that guards against collapse.
    variance_coeff: float = JEPA_DEFAULTS["variance_coeff"]

    @property
    def output_dims(self):
        """Becomes `Catalog.latent_dims`, which sizes the pi and vf heads."""
        return (self.d_model,)

    def build(self, framework: str = "torch") -> Encoder:
        if framework != "torch":
            raise ValueError(
                f"{type(self).__name__} is torch-only; got framework={framework!r}."
            )
        return TorchJEPAEncoder(self)


class TorchJEPAEncoder(TorchModel, Encoder):
    """Tokenise, attend, pool - and, while training, predict masked latents."""

    def __init__(self, config: JEPAEncoderConfig) -> None:
        TorchModel.__init__(self, config)
        Encoder.__init__(self, config)

        if config.pool not in POOLINGS:
            raise ValueError(
                f"Unknown pool {config.pool!r}. Available: {', '.join(POOLINGS)}."
            )
        if config.mask_axis not in MASK_AXES:
            raise ValueError(
                f"Unknown mask_axis {config.mask_axis!r}. "
                f"Available: {', '.join(MASK_AXES)}."
            )
        if config.num_layers < 1:
            raise ValueError(f"num_layers must be >= 1; got {config.num_layers}.")
        if config.predictor_layers < 1:
            raise ValueError(
                f"predictor_layers must be >= 1; got {config.predictor_layers}."
            )
        if not 0.0 < config.mask_ratio < 1.0:
            raise ValueError(
                f"mask_ratio must be in (0, 1); got {config.mask_ratio}. "
                "0 leaves the objective nothing to predict and 1 leaves the "
                "context encoder no input."
            )

        self.layout = config.layout
        self.tokenization = config.tokenization
        self.mask_axis = config.mask_axis
        self.mask_ratio = config.mask_ratio
        self.ema_decay = config.ema_decay
        self.variance_coeff = config.variance_coeff

        num_tokens, token_dim = token_shape(self.layout, self.tokenization)
        time_idx, level_idx = positional_index(self.layout, self.tokenization)
        self.register_buffer("time_idx", time_idx, persistent=False)
        self.register_buffer("level_idx", level_idx, persistent=False)
        time_size = int(time_idx.max()) + 1
        level_size = int(level_idx.max()) + 1

        self.trunk = _Trunk(config, token_dim, time_size, level_size)
        self.private_token = (
            PrivateToken(self.layout.private_dim, config.d_model)
            if self.layout.private_dim else None
        )
        self.pool = (
            AttentionPool(config.d_model, config.num_heads, config.dropout)
            if config.pool == "attention"
            else None
        )

        # --- Training-only from here down ---------------------------------
        # Both are declared non-inference by JEPARLModule, so an inference-only
        # copy and every champion snapshot drop them.
        #
        # The target is a frozen EMA copy of the trunk. Frozen and slow-moving
        # is the whole anti-collapse mechanism: the predictor is chasing a
        # target that keeps moving, which a constant encoder cannot satisfy.
        self.target_trunk = copy.deepcopy(self.trunk)
        for parameter in self.target_trunk.parameters():
            parameter.requires_grad_(False)

        self.predictor = _Predictor(config, time_size, level_size)

        #: Stats from the most recent training forward, or None. Written by
        #: `_forward`, taken by `take_jepa_stats`.
        self._jepa_stats = None
        self._num_tokens = num_tokens

    # --- The auxiliary objective -----------------------------------------

    def take_jepa_stats(self):
        """The stats from the last training forward, clearing them.

        Taking rather than reading, for the reason `moe_transformer` gives for
        its own: a stale auxiliary loss silently added to a later batch's
        gradient would be invisible, while getting `None` because the plumbing
        broke is not.
        """
        stats, self._jepa_stats = self._jepa_stats, None
        return stats

    @torch.no_grad()
    def _update_target(self) -> None:
        """One EMA step of the target trunk toward the online one."""
        decay = self.ema_decay
        for target, online in zip(self.target_trunk.parameters(),
                                  self.trunk.parameters()):
            target.mul_(decay).add_(online.detach(), alpha=1.0 - decay)
        for target, online in zip(self.target_trunk.buffers(),
                                  self.trunk.buffers()):
            target.copy_(online)

    def _jepa_loss(self, tokens: torch.Tensor) -> Dict[str, torch.Tensor]:
        """Mask, predict, score. Returns the loss and the collapse metrics."""
        masked = sample_mask(
            self._num_tokens, self.layout, self.tokenization,
            self.mask_axis, self.mask_ratio,
        ).to(tokens.device)

        keep = torch.ones(self._num_tokens, dtype=torch.bool, device=tokens.device)
        keep[masked] = False
        context_idx = torch.nonzero(keep, as_tuple=False).squeeze(-1)

        # Context: the visible tokens only, but carrying their ORIGINAL
        # positions. Re-indexing them 0..C would tell the encoder the masked
        # levels never existed, instead of that they are hidden.
        context = self.trunk(
            tokens[:, context_idx],
            self.time_idx[context_idx],
            self.level_idx[context_idx],
        )

        with torch.no_grad():
            target = self.target_trunk(tokens, self.time_idx, self.level_idx)
            target = target[:, masked]
            # Normalised per token, as I-JEPA does: without it the trunk can
            # drive the loss down by shrinking the target's scale, which is
            # collapse by a slower route.
            target = F.layer_norm(target, target.shape[-1:])

        predicted = self.predictor(
            context, self.time_idx[masked], self.level_idx[masked]
        )

        loss = F.smooth_l1_loss(predicted, target)

        # Collapse metrics. A collapsed JEPA drives `loss` to ZERO, which reads
        # as success - so the loss alone cannot tell a working encoder from a
        # dead one. These can: `std` is the mean per-dimension standard
        # deviation of the targets across the batch, and it goes to 0 exactly
        # when every observation maps to the same vector.
        flat = target.reshape(-1, target.shape[-1])
        std = flat.std(dim=0).mean()

        # Dimensional collapse: variance held up while dimensions become
        # redundant. Off-diagonal covariance catches what `std` alone misses.
        centred = flat - flat.mean(dim=0, keepdim=True)
        covariance = (centred.T @ centred) / max(1, flat.shape[0] - 1)
        off_diagonal = covariance - torch.diag(torch.diag(covariance))
        offdiag = off_diagonal.abs().mean()

        # VICReg-style hinge: inactive on a healthy encoder, and the only thing
        # actively pushing back once a collapse starts.
        variance_penalty = F.relu(VARIANCE_TARGET - std)

        return {
            "aux_loss": loss + self.variance_coeff * variance_penalty,
            "latent_std": std.detach(),
            "offdiag_cov": offdiag.detach(),
            "predict_loss": loss.detach(),
        }

    # --- The encoder itself ------------------------------------------------

    @override(Model)
    def _forward(self, inputs: dict, **kwargs) -> dict:
        obs = inputs[Columns.OBS]
        tokens = tokenize(obs, self.layout, self.tokenization)

        extra = None
        if self.private_token is not None:
            _book, private = split_private(obs, self.layout)
            extra = self.private_token(private)

        # The POLICY latent, always from the unmasked observation. The agent
        # acts on everything it was given; masking exists only for the
        # objective below.
        x = self.trunk(tokens, self.time_idx, self.level_idx, extra=extra)
        latent = self.pool(x) if self.pool is not None else x.mean(dim=-2)

        # `self.training` and not a flag of our own: mask sampling is
        # stochastic, and PPO's ratio compares a log-prob recorded during
        # rollout against one recomputed on the learner. Anything stochastic on
        # the inference path shows up as noise in that ratio rather than as an
        # error, which is what `test_eval_forward_is_deterministic` exists to
        # catch. The objective therefore runs in train mode only, and the
        # latent above is not affected by it either way.
        if self.training:
            self._update_target()
            self._jepa_stats = self._jepa_loss(tokens)

        return {ENCODER_OUT: latent}


@register(
    "jepa",
    defaults=JEPA_DEFAULTS,
    module_class_path=(
        "gym_continuousDoubleAuction.train.model.jepa_learner", "JEPARLModule",
    ),
    learner_class_path=(
        "gym_continuousDoubleAuction.train.model.jepa_learner", "CDAJEPALearner",
    ),
)
def build_jepa_config(
    layout: ObsLayout,
    spec: Dict[str, Any],
    input_dims: List[int],
) -> JEPAEncoderConfig:
    settings = encoder_settings("jepa", spec)
    return JEPAEncoderConfig(input_dims=input_dims, layout=layout, **settings)
