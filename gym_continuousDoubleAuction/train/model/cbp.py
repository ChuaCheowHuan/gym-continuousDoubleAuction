"""Continual Backprop: the algorithm, with no RLlib in it.

What this implements
--------------------
Continual Backprop (CBP) is backprop plus a *generate-and-test* process that
continually reinitialises low-utility hidden units. It is not an architecture
and not a loss term - it is a modification to the update rule, applied after
the optimiser step. See `docs/25_continual_backprop.md` for why it belongs on
the Learner rather than in the encoder registry.

Two papers define it and they do not agree in every detail. Where they differ,
the choice is a config knob rather than a decision taken here:

  Nature 2024   Dohare, Hernandez-Garcia, Lan, Rahman, Mahmood & Sutton,
                "Loss of plasticity in deep continual learning". Algorithm 1
                uses the *contribution* utility alone.
  arXiv 2108.06325v3
                Dohare, Sutton & Mahmood, "Continual Backprop: SGD with
                Persistent Randomness". Algorithm 2 adds the Adam-specific
                state resets; Appendix C ablates the utility measures and finds
                the full *overall* utility best, including on the RL task.

`utility: "overall"` is the default because that ablation is the one run on a
reinforcement-learning problem, which is what this project is.

Why this module imports no RLlib
--------------------------------
Everything here is plain torch, so the formulas can be tested against
hand-computed values without building an `Algorithm`. The RLlib wiring - where
the hooks are registered, when the step fires, how the state is checkpointed -
lives in `cbp_learner.py`. That split mirrors `encoders/` (architecture) versus
`moe_learner.py` (wiring).

The unit of time is one optimiser step
--------------------------------------
`replacement_rate` and `maturity_threshold` are both counted in **optimiser
steps**, not environment steps or training iterations. This matters more here
than in the papers: at this repo's defaults a training iteration performs 4
Adam steps (4 epochs over one full batch, `minibatch_size: null`) against the
320 of the papers' Continual PPO, so a maturity threshold transplanted from
the paper would never be reached. See `docs/25` and the `_note_cadence` in
`config/train_config.json`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import torch
import torch.nn as nn

#: Utility measures, in the order Appendix C ablates them.
#:
#: `contribution`   - Nature eq. 1: |h| * sum|w_out|.
#: `mean_corrected` - arXiv eq. 4: |h - f_hat| * sum|w_out|. Subtracting the
#:                    running mean activation matters because when a unit is
#:                    removed, gradient descent transfers the *mean* part of its
#:                    contribution to the consumer's bias over time - so that
#:                    part was never really this unit's to be credited with.
#: `overall`        - arXiv eq. 5: the above divided by sum|w_in|. The divisor
#:                    is the "adaptation utility": a unit with small incoming
#:                    weights can change its function faster under Adam, whose
#:                    per-step weight change is bounded by the step size, so it
#:                    is worth more than its contribution alone suggests.
UTILITY_MEASURES = ("contribution", "mean_corrected", "overall")

#: Where replaceable units are looked for. A config knob rather than a constant
#: so that widening the scope is a config change with a name, not a silent
#: behavioural change.
#:
#: `feedforward` - hidden units of a two-Linear feed-forward block, plus the
#:                 trunk-to-head join described in `find_replaceable_layers`.
#:                 Attention projections and embeddings are deliberately
#:                 excluded: a unit there has no single well-defined outgoing
#:                 weight matrix, and zeroing the outgoing weights is the whole
#:                 reason a replacement does not disturb the function.
#: `recurrent`   - everything in `feedforward`, plus the hidden units of the top
#:                 layer of an `nn.LSTM` core (docs/15 S3-32, docs/25 section 3.4).
#:                 The `lstm` encoder has nothing replaceable under
#:                 `feedforward`, which is why this exists. See `RecurrentLayer`
#:                 for what a unit is and what is zeroed.
SCOPES = ("feedforward", "recurrent")

#: When the generate-and-test step fires.
#:
#: `adam_step` - after every optimiser step, which is what arXiv Algorithm 3
#:               (Continual PPO) specifies: "Update the weights of both networks
#:               using Adam; Update the weights of both networks using
#:               generate-and-test", inside the minibatch loop.
#: `iteration` - once per training iteration. PPO's ratio
#:               `exp(logp_new - logp_old)` compares a rollout log-prob against
#:               one recomputed on the learner, and a replacement between
#:               minibatches moves the network underneath a `logp_old` recorded
#:               before it. The papers do it per Adam step anyway and it worked
#:               over 100M steps, so `adam_step` is the default - but the
#:               conservative placement stays available.
FIRE_ON = ("adam_step", "iteration")

#: Modules allowed between a layer's two Linears. Anything else means the pair
#: is not a plain feed-forward block and is left alone.
_PASSTHROUGH = (
    nn.ReLU,
    nn.GELU,
    nn.Tanh,
    nn.ELU,
    nn.SiLU,
    nn.Sigmoid,
    nn.LeakyReLU,
    nn.Dropout,
    nn.Identity,
)

#: Modules that *are* the hidden nonlinearity, i.e. whose output is `h`.
_ACTIVATIONS = (nn.ReLU, nn.GELU, nn.Tanh, nn.ELU, nn.SiLU, nn.Sigmoid, nn.LeakyReLU)


@dataclass(frozen=True)
class CBPConfig:
    """One run's Continual Backprop settings.

    Built from the `continual_backprop` group of `config/train_config.json` and
    carried to the Learner through RLlib's `learner_config_dict`.
    """

    enabled: bool = False
    #: Compute and log the utility and the plasticity correlates, but never
    #: replace anything. This is docs/25 Proposal A: it cannot change a run's
    #: trajectory, and it answers whether this system loses plasticity at all -
    #: which is the question the mechanism is only worth enabling *after*.
    metrics_only: bool = False
    replacement_rate: float = 1e-4
    maturity_threshold: int = 100
    utility_decay: float = 0.99
    utility: str = "overall"
    scope: str = "feedforward"
    fire_on: str = "adam_step"
    reset_optimizer_state: bool = True
    #: Move a replaced unit's mean contribution into the next layer's bias before its
    #: outgoing weights are zeroed, so the output does not jump (docs/15 R-13, #183). Off by
    #: default: the papers' rule zeroes and leaves the bias alone, and `docs/16` section 16.13
    #: measured CBP that way.
    compensate_mean: bool = False
    #: Mean |activation| below which a unit counts as dead, for the metric only.
    dead_unit_threshold: float = 0.01
    #: The effective-rank metric runs an SVD, so it is not worth doing on every
    #: minibatch. Also gates keeping an activation matrix in the forward hook.
    metrics_every_n_updates: int = 10

    def __post_init__(self) -> None:
        if self.utility not in UTILITY_MEASURES:
            raise ValueError(
                f"Unknown utility {self.utility!r}. Available: {', '.join(UTILITY_MEASURES)}."
            )
        if self.scope not in SCOPES:
            raise ValueError(f"Unknown scope {self.scope!r}. Available: {', '.join(SCOPES)}.")
        if self.fire_on not in FIRE_ON:
            raise ValueError(f"Unknown fire_on {self.fire_on!r}. Available: {', '.join(FIRE_ON)}.")
        if not 0.0 <= self.utility_decay < 1.0:
            raise ValueError(
                f"utility_decay must be in [0, 1), got {self.utility_decay}. "
                "It is the decay of a running average; 1.0 would never update."
            )
        if self.replacement_rate < 0.0:
            raise ValueError(f"replacement_rate must be >= 0, got {self.replacement_rate}.")
        if self.maturity_threshold < 0:
            raise ValueError(f"maturity_threshold must be >= 0, got {self.maturity_threshold}.")

    @classmethod
    def from_dict(cls, values: Optional[Dict[str, Any]]) -> "CBPConfig":
        """Build from the config group, whose keys carry a `cbp_` prefix.

        The prefix exists because `config_loader.flatten` collapses every group
        of `train_config.json` into one namespace and raises on a duplicate
        key, so `enabled` or `utility` as bare names would be a collision
        waiting to happen with any group added later.
        """
        values = values or {}
        fields = {
            key: values[f"cbp_{key}"]
            for key in (
                "enabled",
                "metrics_only",
                "replacement_rate",
                "maturity_threshold",
                "utility_decay",
                "utility",
                "scope",
                "fire_on",
                "reset_optimizer_state",
                "compensate_mean",
                "dead_unit_threshold",
                "metrics_every_n_updates",
            )
            if f"cbp_{key}" in values
        }
        return cls(**fields)

    @property
    def active(self) -> bool:
        """Whether anything at all should happen. Off means a no-op learner."""
        return self.enabled or self.metrics_only

    @property
    def replaces(self) -> bool:
        """Whether units are actually replaced, as opposed to only measured."""
        return self.enabled and not self.metrics_only


@dataclass
class ReplaceableLayer:
    """One layer of hidden units with a clean incoming/outgoing split.

    `incoming.weight` is `(n_units, fan_in)`, so unit `i`'s incoming weights are
    row `i`. Each outgoing `weight` is `(fan_out, n_units)`, so unit `i`'s
    outgoing weights are column `i`.

    `outgoing` is a *list* because a shared trunk feeds both the policy and the
    value head. The utility sums over all of them and a replacement zeroes all
    of them, which is the same rule as for a single consumer.
    """

    name: str
    incoming: nn.Linear
    outgoing: List[nn.Linear]
    #: The module whose output is `h`. None for a linear-only block, in which
    #: case the incoming Linear's own output is the hidden representation.
    activation: Optional[nn.Module] = None

    @property
    def num_units(self) -> int:
        return self.incoming.out_features

    @property
    def hook_target(self) -> nn.Module:
        """The module to hang the forward hook on to observe `h`."""
        return self.activation if self.activation is not None else self.incoming

    # The four things the algorithm asks of a layer besides replacing it. They
    # are methods so that `RecurrentLayer`, whose units are not a row of a
    # Linear, answers the same questions without the algorithm knowing which
    # kind it holds.

    @property
    def device(self) -> torch.device:
        return self.incoming.weight.device

    @property
    def trained(self) -> bool:
        return self.incoming.weight.requires_grad

    def incoming_abs_sum(self) -> torch.Tensor:
        """`sum_j |w_in[j, i]|` per unit `i`."""
        return self.incoming.weight.detach().abs().sum(dim=1)

    def outgoing_abs_sum(self) -> torch.Tensor:
        """`sum_k |w_out[i, k]|` per unit `i`, over every consumer."""
        return sum(out.weight.detach().abs().sum(dim=0) for out in self.outgoing)

    def mean_weight_magnitude(self) -> float:
        return float(self.incoming.weight.detach().abs().mean().item())


#: Adam's per-element moment buffers, the slots a replacement has to clear.
_ADAM_SLOTS = ("exp_avg", "exp_avg_sq", "max_exp_avg_sq")


@dataclass
class RecurrentLayer:
    """The hidden units of the top layer of an `nn.LSTM`, as one replaceable layer.

    A unit `i` is hidden unit `i` of the layer whose output the LSTM returns.
    PyTorch stacks the four gates, so its parameters are scattered:

      incoming  rows `i, H+i, 2H+i, 3H+i` of `weight_ih` and of `weight_hh`, and
                the same four entries of `bias_ih` and `bias_hh`. The gates are
                all *inputs* to the unit, so they are all incoming.
      outgoing  column `i` of `weight_hh` (every gate of every unit reads
                `h_i` at the next step) and column `i` of each head Linear that
                consumes the LSTM's output. Another stacked LSTM layer above
                this one would be a consumer too; only the top layer is covered,
                because only its activation is the module's observable output.

    A replacement resamples the incoming entries, sets the biases to 0 and zeroes
    the outgoing columns, exactly the Linear rule. Zeroing is what makes the new
    unit inert at that instant: nothing reads `h_i`, so its fresh weights reach
    no output. The four entries `weight_hh[g*H+i, i]` are in both sets (the unit
    reading its own previous state); outgoing is applied last, so they end at 0.

    What this does not do, and the Linear case does not need to: the unit's cell
    state `c_i` is not touched, because it is not a parameter. A replacement
    mid-training leaves each stored sequence's carried state as computed with the
    old weights until the sequence is recomputed.
    """

    name: str
    lstm: nn.LSTM
    outgoing: List[nn.Linear]
    #: Which LSTM layer's parameters carry the units. The top one.
    layer_index: int = 0

    def __post_init__(self) -> None:
        if self.lstm.bidirectional or self.lstm.proj_size:
            raise ValueError(
                "RecurrentLayer covers a plain unidirectional LSTM: with "
                "bidirectional or proj_size the output is not the hidden units."
            )

    @property
    def num_units(self) -> int:
        return self.lstm.hidden_size

    @property
    def hook_target(self) -> nn.Module:
        return self.lstm

    def _p(self, kind: str) -> torch.Tensor:
        return getattr(self.lstm, f"{kind}_l{self.layer_index}")

    def _gate_rows(self) -> torch.Tensor:
        h = self.lstm.hidden_size
        return torch.arange(4, device=self.device).unsqueeze(1) * h + torch.arange(
            h, device=self.device
        ).unsqueeze(0)  # (4, H): [gate, unit] -> row

    @property
    def device(self) -> torch.device:
        return self._p("weight_ih").device

    @property
    def trained(self) -> bool:
        return self._p("weight_ih").requires_grad

    def incoming_abs_sum(self) -> torch.Tensor:
        rows = self._gate_rows()
        total = self._p("weight_ih").detach().abs()[rows].sum(dim=(0, 2))
        return total + self._p("weight_hh").detach().abs()[rows].sum(dim=(0, 2))

    def outgoing_abs_sum(self) -> torch.Tensor:
        total = self._p("weight_hh").detach().abs().sum(dim=0)
        for out in self.outgoing:
            total = total + out.weight.detach().abs().sum(dim=0)
        return total

    def mean_weight_magnitude(self) -> float:
        return float(
            torch.cat(
                [
                    self._p("weight_ih").detach().abs().flatten(),
                    self._p("weight_hh").detach().abs().flatten(),
                ]
            )
            .mean()
            .item()
        )

    def reinitialise(self, index: int, generator: Optional[torch.Generator]) -> None:
        """Resample the unit's incoming entries and zero its outgoing ones."""
        h = self.lstm.hidden_size
        # `nn.LSTM`'s own default: U(-1/sqrt(hidden), 1/sqrt(hidden)) for every
        # weight, input and recurrent alike.
        bound = 1.0 / math.sqrt(h)
        rows = [g * h + index for g in range(4)]
        with torch.no_grad():
            for kind in ("weight_ih", "weight_hh"):
                weight = self._p(kind)
                for row in rows:
                    weight[row] = torch.empty_like(weight[row]).uniform_(
                        -bound, bound, generator=generator
                    )
            for kind in ("bias_ih", "bias_hh"):
                if self.lstm.bias:
                    self._p(kind)[rows] = 0.0
            # Outgoing last, so the self-recurrent entries end at 0.
            self._p("weight_hh")[:, index] = 0.0
            for out in self.outgoing:
                out.weight[:, index] = 0.0

    def reset_optimizer_slots(self, optimizer: torch.optim.Optimizer, index: int) -> None:
        """Zero Adam's moments for every entry `reinitialise` just reset."""
        h = self.lstm.hidden_size
        rows = [g * h + index for g in range(4)]
        targets = [("weight_ih", rows, None), ("weight_hh", rows, None), ("weight_hh", None, index)]
        if self.lstm.bias:
            targets += [("bias_ih", rows, None), ("bias_hh", rows, None)]
        with torch.no_grad():
            for kind, row_idx, col_idx in targets:
                slots = optimizer.state.get(self._p(kind))
                if not slots:
                    continue
                for key in _ADAM_SLOTS:
                    if key not in slots:
                        continue
                    if row_idx is not None:
                        slots[key][row_idx] = 0.0
                    else:
                        slots[key][:, col_idx] = 0.0
            for out in self.outgoing:
                slots = optimizer.state.get(out.weight)
                if not slots:
                    continue
                for key in _ADAM_SLOTS:
                    if key in slots:
                        slots[key][:, index] = 0.0


# --- Layer discovery --------------------------------------------------------


def _sequential_layers(seq: nn.Sequential, prefix: str) -> List[ReplaceableLayer]:
    """Replaceable layers wholly contained in one `nn.Sequential`.

    A layer is a `Linear -> (activation) -> Linear` run with nothing but
    pass-through modules in between. `blocks.feedforward`, the MoE experts,
    `jepa.predict` and the stock MLP's hidden layers all have exactly this
    shape. `token_embed.token_mlp` does not: it is `Linear -> GELU` with no
    second Linear, so it is never registered - and with nothing else of this
    shape in it, the `lstm` encoder has no replaceable layer at all.
    """
    layers: List[ReplaceableLayer] = []
    children = list(seq)
    for i, first in enumerate(children):
        if not isinstance(first, nn.Linear):
            continue
        activation = None
        for j in range(i + 1, len(children)):
            nxt = children[j]
            if isinstance(nxt, nn.Linear):
                layers.append(
                    ReplaceableLayer(
                        name=f"{prefix}.{i}",
                        incoming=first,
                        outgoing=[nxt],
                        activation=activation,
                    )
                )
                break
            if isinstance(nxt, _ACTIVATIONS) and activation is None:
                activation = nxt
            elif not isinstance(nxt, _PASSTHROUGH):
                # A LayerNorm, an attention block, a reshape - not a plain
                # feed-forward pair, so this Linear has no single consumer.
                break
    return layers


def _mlp_trunk(module: nn.Module) -> Optional[nn.Sequential]:
    """The `net.mlp` Sequential of an RLlib `TorchMLPEncoder`, or None.

    Duck-typed rather than an isinstance check against RLlib's class, so this
    module keeps its promise of importing no RLlib.
    """
    net = getattr(module, "net", None)
    mlp = getattr(net, "mlp", None)
    return mlp if isinstance(mlp, nn.Sequential) else None


def _trunk_head_layers(module: nn.Module) -> List[ReplaceableLayer]:
    """The layer whose units live in the trunk but whose consumer is the head.

    This is the one a walker confined to the encoder silently misses, and
    missing it would halve the mechanism on the default network. In a stock PPO
    module the encoder ends with `... Linear -> activation` and the pi/vf heads
    begin with their own Linear, so the *last* hidden layer's outgoing weights
    are not in the encoder at all:

        encoder.actor_encoder.net.mlp.2: Linear 256->256   <- incoming
        encoder.actor_encoder.net.mlp.3: Tanh              <- h
        pi.net.mlp.0:                    Linear 256->26    <- outgoing

    Only applied to an MLP trunk. A transformer trunk ends in pooling and a
    LayerNorm rather than a bare Linear, so there is no well-defined unit to
    join across; those encoders contribute their feed-forward blocks through
    `_sequential_layers` and nothing else.
    """
    encoder = getattr(module, "encoder", None)
    if encoder is None:
        return []

    pi, vf = getattr(module, "pi", None), getattr(module, "vf", None)
    # `encoder` is the shared trunk under vf_share_layers, feeding both heads;
    # otherwise the actor and critic are independent networks with one head
    # each. Both are handled by the same code because `outgoing` is a list.
    pairings = [
        (getattr(encoder, "encoder", None), [pi, vf]),
        (getattr(encoder, "actor_encoder", None), [pi]),
        (getattr(encoder, "critic_encoder", None), [vf]),
    ]

    layers: List[ReplaceableLayer] = []
    for trunk_name, (trunk, heads) in zip(("encoder", "actor_encoder", "critic_encoder"), pairings):
        mlp = _mlp_trunk(trunk) if trunk is not None else None
        if mlp is None:
            continue
        children = list(mlp)
        last_linear = next(
            (i for i in reversed(range(len(children))) if isinstance(children[i], nn.Linear)),
            None,
        )
        if last_linear is None:
            continue
        # Anything after the final Linear other than an activation means the
        # trunk's output is not simply that layer's units.
        tail = children[last_linear + 1 :]
        if any(not isinstance(m, _PASSTHROUGH) for m in tail):
            continue
        activation = next((m for m in tail if isinstance(m, _ACTIVATIONS)), None)

        consumers = []
        for head in heads:
            if head is None:
                continue
            first = next((m for m in head.modules() if isinstance(m, nn.Linear)), None)
            if first is not None and first.in_features == children[last_linear].out_features:
                consumers.append(first)
        if consumers:
            layers.append(
                ReplaceableLayer(
                    name=f"encoder.{trunk_name}.net.mlp.{last_linear}",
                    incoming=children[last_linear],
                    outgoing=consumers,
                    activation=activation,
                )
            )
    return layers


def _recurrent_layers(module: nn.Module) -> List["RecurrentLayer"]:
    """The LSTM core of each trunk, paired with the heads that read its output.

    The same trunk-to-head pairing as `_trunk_head_layers`: under
    `vf_share_layers` one `encoder.encoder` feeds both heads, otherwise the
    actor and critic each have an LSTM and one head. A trunk whose output is
    not the LSTM's (something after it) or whose heads do not read a vector of
    its width is skipped rather than guessed at.
    """
    encoder = getattr(module, "encoder", None)
    if encoder is None:
        return []
    pi, vf = getattr(module, "pi", None), getattr(module, "vf", None)
    pairings = (
        ("encoder", getattr(encoder, "encoder", None), [pi, vf]),
        ("actor_encoder", getattr(encoder, "actor_encoder", None), [pi]),
        ("critic_encoder", getattr(encoder, "critic_encoder", None), [vf]),
    )
    layers: List[RecurrentLayer] = []
    for trunk_name, trunk, heads in pairings:
        lstm = getattr(trunk, "lstm", None) if trunk is not None else None
        if not isinstance(lstm, nn.LSTM) or lstm.bidirectional or lstm.proj_size:
            continue
        consumers = []
        for head in heads:
            if head is None:
                continue
            first = next((m for m in head.modules() if isinstance(m, nn.Linear)), None)
            if first is not None and first.in_features == lstm.hidden_size:
                consumers.append(first)
        if consumers:
            layers.append(
                RecurrentLayer(
                    name=f"encoder.{trunk_name}.lstm",
                    lstm=lstm,
                    outgoing=consumers,
                    layer_index=lstm.num_layers - 1,
                )
            )
    return layers


def find_replaceable_layers(
    module: nn.Module, scope: str = "feedforward"
) -> List[ReplaceableLayer]:
    """Every layer of this module whose units CBP may replace.

    Two sources, and both are needed for the default network:

      1. Feed-forward blocks wholly inside one `nn.Sequential`.
      2. The trunk's final hidden layer, whose consumer is the pi/vf head.

    On the shipped default (`mlp`, `vf_share_layers: false`) this returns
    exactly four layers - two per network, policy and value - which is the
    (256, tanh, 256, tanh, Linear) network the papers' Continual PPO used.

    Ordered by `named_modules` traversal so the result is deterministic, which
    is what lets the state be keyed by layer name across a checkpoint.

    **Unwrapped first**, which is load-bearing in two ways at `num_learners > 1`.
    RLlib wraps each module in a `TorchDDPRLModule` at the end of
    `TorchLearner.build`, i.e. before anything here runs. That class subclasses
    `DistributedDataParallel`, keeps the real module as a submodule named
    `module`, and defines no attribute forwarding - so `_trunk_head_layers`
    would find no `encoder`, no `pi` and no `vf`, silently return nothing, and
    leave the default network with 2 replaceable layers instead of 4. It would
    also prefix every name from `named_modules` with `module.`, so the state
    keys of a distributed run would not match those of a single-learner one and
    a checkpoint could not move between them. `unwrapped()` is defined on the
    base `RLModule` and returns `self`, so this costs an undistributed run
    nothing.
    """
    if scope not in SCOPES:
        raise ValueError(f"Unknown scope {scope!r}. Available: {', '.join(SCOPES)}.")

    unwrapped = getattr(module, "unwrapped", None)
    if callable(unwrapped):
        module = unwrapped()

    layers: List[ReplaceableLayer] = []
    for name, sub in module.named_modules():
        if isinstance(sub, nn.Sequential):
            layers.extend(_sequential_layers(sub, name))
    layers.extend(_trunk_head_layers(module))
    if scope == "recurrent":
        layers.extend(_recurrent_layers(module))

    # A Linear can be the incoming weight of at most one layer. Nested
    # Sequentials are visited more than once by `named_modules`, so without
    # this a block could be registered twice and have its utility updated
    # twice per step.
    seen, unique = set(), []
    for layer in layers:
        key = id(layer.lstm) if isinstance(layer, RecurrentLayer) else id(layer.incoming)
        if key in seen or not _is_trained(layer):
            continue
        seen.add(key)
        unique.append(layer)
    return unique


def _is_trained(layer: ReplaceableLayer) -> bool:
    """Whether gradient descent is what maintains this layer's weights.

    Continual Backprop replaces units that *learning* has left useless, and
    then lets gradient descent decide whether they earn their way back. A layer
    no optimiser is updating gets neither half of that, so replacing its units
    would be pure damage.

    The case that makes this necessary rather than defensive is the `jepa`
    encoder's `target_trunk`: an EMA copy of the context trunk held under
    stop-gradient, which `_sequential_layers` finds because it is structurally
    identical to the trunk it mirrors. Reinitialising a unit there would break
    the EMA relationship the whole objective rests on, and would not be undone
    by any subsequent update, because nothing updates it.
    """
    return layer.trained


# --- Per-layer state --------------------------------------------------------


@dataclass
class CBPLayerState:
    """Utility, mean activation, age and the replacement accumulator.

    Held on the Learner rather than registered as module buffers, deliberately:
    a champion snapshot is an inference-only copy of the module, and state
    attached to the module would ride into every one of them as dead weight -
    the problem `jepa_learner`'s `_TRAINING_ONLY` list exists to solve. Keeping
    it here avoids the problem instead of managing it.
    """

    utility: torch.Tensor
    mean_act: torch.Tensor
    age: torch.Tensor
    accumulator: float = 0.0
    replacements: int = 0

    @classmethod
    def zeros(cls, num_units: int, device=None) -> "CBPLayerState":
        return cls(
            utility=torch.zeros(num_units, device=device),
            mean_act=torch.zeros(num_units, device=device),
            age=torch.zeros(num_units, dtype=torch.long, device=device),
        )

    def get_state(self) -> Dict[str, Any]:
        """A snapshot, not a view.

        `.detach().cpu()` on a tensor already on the CPU returns *the same
        object*, so without the clone the returned dict would alias the live
        state: a checkpoint would serialise whatever the values had become by
        the time it was written rather than what they were when it was taken,
        and any holder of the dict would watch it change underneath them.
        """
        return {
            "utility": self.utility.detach().cpu().clone(),
            "mean_act": self.mean_act.detach().cpu().clone(),
            "age": self.age.detach().cpu().clone(),
            "accumulator": self.accumulator,
            "replacements": self.replacements,
        }

    def set_state(self, state: Dict[str, Any]) -> None:
        """Restore from a snapshot, without aliasing it.

        Cloned for the same reason `get_state` clones, in the other direction:
        `.to(device)` is a no-op returning the same object when the tensor is
        already there, which would leave the live state and the restored dict
        sharing storage - so the next update would write through into the
        checkpoint the caller still holds.
        """
        device = self.utility.device
        self.utility = state["utility"].to(device).clone()
        self.mean_act = state["mean_act"].to(device).clone()
        self.age = state["age"].to(device).clone()
        self.accumulator = float(state["accumulator"])
        self.replacements = int(state["replacements"])


def bias_corrected(value: torch.Tensor, age: torch.Tensor, decay: float) -> torch.Tensor:
    """`v / (1 - decay^age)`, arXiv eqs. 3 and 7.

    A running average started at zero is biased toward zero for as long as it
    has been running; dividing by `1 - decay^age` removes that. Without it a
    freshly reinitialised unit looks useless for the ~1/(1-decay) steps it takes
    its average to charge up, and would be selected again immediately - which is
    the failure the maturity threshold is the *second* line of defence against.

    Age 0 gives a zero denominator; those units have no estimate yet, so the
    uncorrected zero is returned for them.
    """
    correction = 1.0 - decay ** age.clamp(min=1).to(value.dtype)
    return torch.where(age > 0, value / correction, value)


# --- The algorithm ----------------------------------------------------------


def _outgoing_abs_sum(layer: ReplaceableLayer) -> torch.Tensor:
    """`sum_k |w_out[i, k]|` per unit `i`, over every consumer."""
    return layer.outgoing_abs_sum()


def _incoming_abs_sum(layer: ReplaceableLayer) -> torch.Tensor:
    """`sum_j |w_in[j, i]|` per unit `i`."""
    return layer.incoming_abs_sum()


def update_utility(
    state: CBPLayerState,
    layer: ReplaceableLayer,
    stats: Dict[str, torch.Tensor],
    config: CBPConfig,
) -> torch.Tensor:
    """Advance age and utility by one optimiser step; return bias-corrected `u`.

    `stats` comes from the forward hook and holds per-unit reductions of `h`
    over the minibatch - see `activation_stats`. The papers define the utility
    on a single example; with minibatches, Nature's Methods section says the
    instantaneous contribution may be averaged over the minibatch, which is
    what the hook does before this is called.

    Order matters: age is incremented first, so a unit replaced on the previous
    step is age 1 here rather than age 0, and `bias_corrected` has a non-zero
    denominator to work with.
    """
    decay = config.utility_decay
    state.age += 1

    if config.utility == "contribution":
        instantaneous = stats["abs_mean"] * _outgoing_abs_sum(layer)
    else:
        instantaneous = stats["dev_abs_mean"] * _outgoing_abs_sum(layer)
        if config.utility == "overall":
            # Adaptation utility. Clamped because a unit whose incoming weights
            # are all exactly zero - which is possible, though not reachable by
            # a replacement, since only the *outgoing* side is zeroed - would
            # otherwise give an infinite utility and never be replaced again.
            instantaneous = instantaneous / _incoming_abs_sum(layer).clamp(min=1e-12)

    state.utility.mul_(decay).add_(instantaneous, alpha=1.0 - decay)
    state.mean_act.mul_(decay).add_(stats["mean"], alpha=1.0 - decay)
    return bias_corrected(state.utility, state.age, decay)


def activation_stats(
    h: torch.Tensor, state: CBPLayerState, config: CBPConfig
) -> Dict[str, torch.Tensor]:
    """Reduce a minibatch of activations to the per-unit quantities CBP needs.

    Called from inside a forward hook, so it must not keep `h` or anything
    holding a reference to the autograd graph - the graph would then stay alive
    until the next forward, which is the leak `jepa_learner.setup()` documents.
    Everything returned here is detached and of shape `(num_units,)`.

    `dev_abs_mean` is `mean_batch |h - f_hat|` and has to be computed here
    rather than recovered later: it needs the bias-corrected running mean at
    the time of the forward pass, and no reduction of `h` alone determines it.
    """
    h = h.detach()
    if h.dim() > 2:
        # A recurrent or token-major module gives (B, T, n); every row is an
        # independent observation of the unit, so flatten rather than pick one.
        h = h.reshape(-1, h.shape[-1])
    f_hat = bias_corrected(state.mean_act, state.age, config.utility_decay)
    return {
        "mean": h.mean(dim=0),
        "abs_mean": h.abs().mean(dim=0),
        "dev_abs_mean": (h - f_hat).abs().mean(dim=0),
        # How many rows these means are over, so calls can be combined exactly (`merge_stats`).
        "rows": torch.tensor(float(h.shape[0]), device=h.device),
    }


def merge_stats(
    old: Dict[str, torch.Tensor], new: Dict[str, torch.Tensor]
) -> Dict[str, torch.Tensor]:
    """Combine two calls' statistics of the same layer within one optimiser step.

    A layer can run more than once per step - each MoE expert once per top-k slot, the JEPA
    trunk on the masked context and again on the full observation - and the hook used to keep
    only the last call, so a unit was judged on a partial, order-dependent view (docs/15 R-14,
    #184). Each statistic is a mean over `rows`, so weighting by rows gives exactly the mean
    over all rows of both calls, as if they had been one batch.
    """
    rows = old["rows"] + new["rows"]
    merged = {
        key: (old[key] * old["rows"] + new[key] * new["rows"]) / rows
        for key in old
        if key != "rows"
    }
    merged["rows"] = rows
    return merged


def select_and_replace(
    state: CBPLayerState,
    layer: ReplaceableLayer,
    corrected_utility: torch.Tensor,
    config: CBPConfig,
    generator: Optional[torch.Generator] = None,
    optimizer: Optional[torch.optim.Optimizer] = None,
) -> List[int]:
    """Replace the lowest-utility mature units; return the indices replaced.

    The accumulator is the part most often got wrong, in two ways.

    First, the papers do *not* say "replace `rate * n` units per step". They
    carry a fractional counter, because at a replacement rate of 1e-4 over 256
    units the per-step quantity is 0.026 and rounding it to an integer would
    replace nothing, ever:

        c += n_eligible * replacement_rate
        if c > 1:  replace argmin utility; c -= 1

    Second, that is an `if`, not a `while` - Nature Algorithm 1 is explicit, and
    it caps the damage at **one unit per layer per optimiser step** however high
    the rate is set. Worth keeping rather than "fixing": the cap is what bounds
    how far a single step can move the function, which is the whole reason a
    replacement is safe to run inside PPO's minibatch loop. A rate high enough
    to make the counter outrun the cap is a misconfiguration, and
    `cbp_replacements` against the accumulator is what shows it.
    """
    if not config.replaces:
        return []

    eligible = state.age > config.maturity_threshold
    n_eligible = int(eligible.sum().item())
    if n_eligible == 0:
        return []

    state.accumulator += n_eligible * config.replacement_rate
    if state.accumulator <= 1.0:
        return []

    # +inf for ineligible units, so argmin can only land on a mature one.
    masked = torch.where(
        eligible,
        corrected_utility,
        torch.full_like(corrected_utility, float("inf")),
    )
    index = int(masked.argmin().item())
    _reinitialise(state, layer, index, generator, optimizer, config)
    state.accumulator -= 1.0
    state.replacements += 1
    return [index]


def _reinitialise(
    state: CBPLayerState,
    layer: ReplaceableLayer,
    index: int,
    generator: Optional[torch.Generator],
    optimizer: Optional[torch.optim.Optimizer],
    config: CBPConfig,
) -> None:
    """One replacement: resample incoming, zero outgoing, reset the bookkeeping.

    Zeroing the outgoing weights is what makes the fresh unit inert at the
    instant of replacement - the new random incoming weights are multiplied by
    zero and reach the output not at all. What *does* move the function is
    dropping the old unit's contribution, and nothing makes that zero; it is
    bounded only by having selected the minimum-utility unit. See docs/16
    section 16.13 for the measured decomposition.
    """
    if isinstance(layer, RecurrentLayer):
        layer.reinitialise(index, generator)
        state.utility[index] = 0.0
        state.mean_act[index] = 0.0
        state.age[index] = 0
        if config.reset_optimizer_state and optimizer is not None:
            layer.reset_optimizer_slots(optimizer, index)
        return

    with torch.no_grad():
        weight = layer.incoming.weight
        # The incoming weights are redrawn from PyTorch's default `nn.Linear`
        # weight init, which is what RLlib's MLP leaves in place:
        # U(-1/sqrt(fan_in), +1/sqrt(fan_in)). The bias is NOT drawn from the
        # default's bias distribution: it is set to 0 below, as the continual-
        # backprop papers prescribe (and as the recurrent layer does). An encoder
        # built with a custom initialiser would need this extended; none in this
        # repo is.
        bound = 1.0 / math.sqrt(layer.incoming.in_features)
        fresh = torch.empty_like(weight[index]).uniform_(-bound, bound, generator=generator)
        weight[index] = fresh
        if layer.incoming.bias is not None:
            layer.incoming.bias[index] = 0.0

        if config.compensate_mean:
            # What the unit fed the next layer on average, kept as a constant. The running mean
            # is bias-corrected like the one the utility uses; a consumer without a bias has
            # nowhere to put it.
            mean = bias_corrected(
                state.mean_act[index : index + 1],
                state.age[index : index + 1],
                config.utility_decay,
            )[0]
            for out in layer.outgoing:
                if out.bias is not None:
                    out.bias += out.weight[:, index] * mean

        for out in layer.outgoing:
            out.weight[:, index] = 0.0

        state.utility[index] = 0.0
        state.mean_act[index] = 0.0
        state.age[index] = 0

    if config.reset_optimizer_state and optimizer is not None:
        _reset_optimizer_slots(optimizer, layer, index)


def _reset_optimizer_slots(
    optimizer: torch.optim.Optimizer, layer: ReplaceableLayer, index: int
) -> None:
    # (A `RecurrentLayer` clears its own slots; see `_reinitialise`.)
    """Zero Adam's moment estimates for the weights a replacement just reset.

    arXiv Algorithm 2: a reinitialised weight that inherits a large second
    moment takes tiny steps and stays dead, which would defeat the point of
    replacing it.

    **Documented deviation.** Algorithm 2 also resets a *per-weight timestep*
    so Adam's bias correction restarts for that weight. `torch.optim.Adam`
    keeps one scalar `step` per parameter tensor, not per element, so this is
    not expressible without replacing the optimiser. The cost of omitting it:
    the new unit's zeroed moments are bias-corrected by ~1 instead of by
    `1 - beta`, so its effective step ramps up over roughly `1/(1 - beta_1)`
    updates rather than being full size immediately. That is a slower start for
    the replacement, not a wrong one.
    """
    with torch.no_grad():
        for param, rows in (
            (layer.incoming.weight, index),
            (layer.incoming.bias, index),
        ):
            if param is None:
                continue
            slots = optimizer.state.get(param)
            if not slots:
                continue
            for key in ("exp_avg", "exp_avg_sq", "max_exp_avg_sq"):
                if key in slots:
                    slots[key][rows] = 0.0

        for out in layer.outgoing:
            slots = optimizer.state.get(out.weight)
            if not slots:
                continue
            for key in ("exp_avg", "exp_avg_sq", "max_exp_avg_sq"):
                if key in slots:
                    slots[key][:, index] = 0.0


# --- Plasticity metrics -----------------------------------------------------


def effective_rank(activations: torch.Tensor, threshold: float = 0.99) -> float:
    """Threshold rank: the fewest singular values carrying `threshold` of the total.

    The rank-collapse correlate of loss of plasticity: a representation whose
    units have become redundant has a low rank even when none of them is
    individually dead, which is why the dead-unit fraction alone is not enough.

    **Not numerically the paper's figure.** This is the threshold ("srank")
    form: count singular values until `threshold` of their sum is covered. The
    effective rank the plasticity literature plots is usually the
    entropy-based one, exp of the entropy of the normalised singular values.
    The two move together but sit on different scales, so read this against
    its own history - and against `width` - not against the papers' curves.

    **Read the caller's caveat before reading the number.** The rank of an
    activation matrix depends on the inputs as much as on the network. Here the
    inputs are whatever minibatch training produced, and the policy shapes its
    own input distribution - so this falls when the network loses capacity and
    *also* when the agent simply starts visiting a narrower set of book states.
    Measured on this repo, the second effect alone moved it by -24.6% while the
    network's capacity on a fixed corpus did not move at all (docs/16 §16.16).
    `train/probe/rank.py` is the version that holds the inputs still.

    `train.probe.rank.effective_rank` is the same definition in numpy;
    `test_probe.py::TestEffectiveRank.test_it_agrees_with_the_torch_definition`
    pins that the two agree.

    They differ in exactly one place, deliberately. A matrix with fewer than
    two rows has nothing to decompose: this returns NaN, because the value goes
    into a metric series where a plotted 0.0 reads as total collapse, and the
    probe's version returns 0, because that value goes into a report column
    read as a rank. The agreement test pins both answers.
    """
    matrix = activations.detach()
    if matrix.dim() > 2:
        matrix = matrix.reshape(-1, matrix.shape[-1])
    if matrix.numel() == 0 or matrix.shape[0] < 2:
        return float("nan")
    singular = torch.linalg.svdvals(matrix.float())
    total = singular.sum()
    if total <= 0:
        return 0.0
    cumulative = torch.cumsum(singular, dim=0) / total
    return float((cumulative < threshold).sum().item() + 1)


def plasticity_metrics(
    layer: ReplaceableLayer,
    stats: Dict[str, torch.Tensor],
    corrected_utility: torch.Tensor,
    config: CBPConfig,
    activations: Optional[torch.Tensor] = None,
) -> Dict[str, float]:
    """The three correlates of loss of plasticity, plus the utility spread.

    The three are the ones both papers track: the fraction of dead units, the
    average weight magnitude, and the effective rank of the representation -
    the last of which is reported as `batch_effective_rank`, because on this
    system it is confounded by the policy's own input distribution and the name
    is the only thing standing between a reader and a false positive.
    Continual Backprop is the only algorithm in the Nature paper that keeps all
    three healthy, so they are what says whether it is working - and, run with
    `metrics_only`, whether there is anything for it to work on.

    `saturated_frac` is arXiv Appendix G and is specific to a bounded
    activation: this project's default is tanh, where a unit past |h| > 0.9 has
    a vanishing local gradient and is on its way to being stuck.
    """
    abs_mean = stats["abs_mean"]
    metrics = {
        "dead_unit_frac": float((abs_mean < config.dead_unit_threshold).float().mean().item()),
        "saturated_unit_frac": float((abs_mean > 0.9).float().mean().item()),
        "mean_weight_magnitude": layer.mean_weight_magnitude(),
        "utility_min": float(corrected_utility.min().item()),
        "utility_median": float(corrected_utility.median().item()),
    }
    if activations is not None:
        # Named for the batch it is measured on, not for what it looks like it
        # measures. It is NOT a clean read of the network's capacity: the
        # training minibatch reflects wherever the policy currently goes, so
        # this moves with the input distribution too. See `effective_rank`,
        # and use the probe harness for the comparable version.
        metrics["batch_effective_rank"] = effective_rank(activations)
    return metrics


def mature_fraction(state: CBPLayerState, config: CBPConfig) -> float:
    """Fraction of units old enough to be replaceable.

    Worth logging on its own: at this repo's update cadence a maturity
    threshold carried over from the papers leaves this pinned at 0.0 forever,
    and a Continual Backprop that never fires looks exactly like one that is
    working unless something says so.
    """
    return float((state.age > config.maturity_threshold).float().mean().item())
