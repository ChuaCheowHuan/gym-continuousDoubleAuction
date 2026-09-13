"""Wiring Continual Backprop into RLlib's Learner.

The algorithm is in `cbp.py`; this file is only the plumbing, and there are
four pieces of it:

  CBPLearnerMixin        - registers forward hooks to observe hidden
                           activations, runs generate-and-test after each
                           optimiser step, logs the plasticity correlates, and
                           carries its own state through a checkpoint.
  with_continual_backprop - composes the mixin over whatever Learner the
                           configured encoder selected.
  configure_optimizers_for_module
                         - the papers' tuned Adam, opt-in.
  learner_config         - reads the config group off the AlgorithmConfig.

Why a mixin, and not another registry entry
-------------------------------------------
Every previous extension to the learning stack - the MoE load-balancing loss,
the JEPA latent-prediction loss - went through `encoders/`, whose `@register`
takes a `learner_class_path`. Continual Backprop must not, for three reasons
developed in `doc/25_continual_backprop.md` section 2.5:

  * `encoder_type: "mlp"` is a pass-through that never reaches `CDACatalog`, so
    an encoder-registry mechanism would be unavailable for the shipped default
    - which is the 2x256 tanh network the papers' Continual PPO used, and the
    configuration most at risk from the saturation CBP targets.
  * `learner_class_for` fills RLlib's single algorithm-wide Learner slot from
    the *configured encoder*. A CBP learner registered against an
    `encoder_type` would be mutually exclusive with `jepa` rather than
    composable with it.
  * Resetting Adam's moments for replaced units needs the optimiser, which only
    the Learner can see.

So CBP composes *over* the encoder's learner instead of occupying its slot. The
MoE and JEPA terms are inherited untouched, and when CBP is off the composition
is skipped entirely, so the resolved class is identical to today's.

Where the step fires
--------------------
`apply_gradients` - once per minibatch, immediately after the optimiser step -
which is a one-to-one correspondence with arXiv Algorithm 3 (Continual PPO):

    for each mini-batch:
        Compute the objectives for policy and value networks
        Update the weights of both networks using Adam
        Update the weights of both networks using generate-and-test

`fire_on: "iteration"` moves it to `after_gradient_based_update` instead, which
runs once per `update()` and so cannot disturb PPO's ratio between minibatches.
The papers use the per-step placement and it held up over 100M steps, so that
is the default; the conservative one stays available.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import torch

from gym_continuousDoubleAuction.train.model.cbp import (
    CBPConfig,
    CBPLayerState,
    ReplaceableLayer,
    activation_stats,
    find_replaceable_layers,
    mature_fraction,
    plasticity_metrics,
    select_and_replace,
    update_utility,
)

#: Key under which CBP's state rides in the Learner's checkpoint.
CBP_STATE = "continual_backprop"

#: Key under which the config group rides on `learner_config_dict`.
CBP_CONFIG_KEY = "continual_backprop"

#: Key under which the optimiser group rides on `learner_config_dict`.
OPTIMIZER_CONFIG_KEY = "optimizer"

#: Metric names, logged per module. Prefixed so they do not collide with the
#: MoE and JEPA metrics a composed learner also emits.
CBP_METRIC_PREFIX = "cbp_"

#: How many activation rows to keep for the effective-rank SVD. The full
#: minibatch is 16,384 rows at this project's defaults and the rank of a
#: 256-column matrix is bounded by 256 either way, so more rows buy nothing and
#: cost a much larger decomposition.
_RANK_SAMPLE_ROWS = 1024


def _as_config(learner_config_dict: Optional[Dict[str, Any]]) -> CBPConfig:
    """The CBP settings carried on the AlgorithmConfig, or the off default."""
    values = (learner_config_dict or {}).get(CBP_CONFIG_KEY)
    return CBPConfig.from_dict(values)


class CBPLearnerMixin:
    """Continual Backprop, composed over any PPO Learner.

    Inert unless `cbp_enabled` or `cbp_metrics_only` is set: `build` returns
    early, no hook is registered, and `apply_gradients` adds one attribute
    lookup to the update path.
    """

    # --- Setup ---------------------------------------------------------------

    def build(self) -> None:
        super().build()

        self._cbp_config = _as_config(
            getattr(self.config, "learner_config_dict", None)
        )
        self._cbp_layers: Dict[Any, List[ReplaceableLayer]] = {}
        self._cbp_state: Dict[Any, Dict[str, CBPLayerState]] = {}
        self._cbp_stats: Dict[Tuple[Any, str], Dict[str, torch.Tensor]] = {}
        self._cbp_activations: Dict[Tuple[Any, str], torch.Tensor] = {}
        self._cbp_handles: List[Any] = []
        self._cbp_updates = 0
        self._cbp_generator: Optional[torch.Generator] = None

        if not self._cbp_config.active:
            return

        # A dedicated stream, so a replacement drawing random numbers does not
        # shift the global one and make an otherwise seeded run diverge. Same
        # discipline as the `torch.random.fork_rng` fix in changelog 38.2.
        #
        # On the learner's own device, not the default one. `_reinitialise`
        # fills `torch.empty_like(weight[index])`, which lives wherever the
        # parameter does, and `uniform_` refuses a generator from a different
        # device type. A CPU generator on a CUDA run therefore raises - but not
        # until the accumulator first crosses 1.0, which at the shipped
        # replacement rate is some tens of optimiser steps in. A crash that
        # waits until the mechanism first does something is exactly the kind
        # this suite cannot catch, since it runs CPU-only.
        seed = getattr(self.config, "seed", None)
        self._cbp_generator = torch.Generator(device=self._cbp_device())
        if seed is not None:
            self._cbp_generator.manual_seed(int(seed))

        for module_id in self.module.keys():
            self._cbp_attach(module_id)

    def _cbp_device(self) -> torch.device:
        """The device the learner put its modules on.

        `TorchLearner.build` sets `self._device` and moves every module to it
        *before* the mixin's own setup runs, so this is authoritative by the
        time anything here needs it. Guarded anyway: the attribute is a
        `TorchLearner` implementation detail, and defaulting to CPU matches what
        a learner without one would be doing.
        """
        return getattr(self, "_device", None) or torch.device("cpu")

    def _cbp_attach(self, module_id) -> None:
        """Discover a module's replaceable layers and hook their activations.

        Only for modules the algorithm is actually training. Two kinds are
        excluded and both matter:

        * The frozen `RandomRLModule` baselines, which have no network at all.
        * **League champions.** A champion is a snapshot of a past policy, kept
          fixed so the opponent it represents does not drift. It lives in the
          same `MultiRLModule` as the trainable policies, so it is in
          `self.module`, but replacing a unit in it would silently mutate an
          opponent that is supposed to be constant - and the replacement would
          never be undone, because no gradient reaches it.

        This is the same rule `cbp._is_trained` applies one level down to the
        `jepa` encoder's EMA target trunk: continual backprop replaces units
        that gradient descent maintains, and nothing else. It also keeps the
        state keyed consistently across a restore, where champions are present
        from `build()` but were added mid-run the first time round.
        """
        if not self.should_module_be_updated(module_id):
            return

        module = self.module[module_id]
        if not isinstance(module, torch.nn.Module):
            return

        layers = find_replaceable_layers(module, self._cbp_config.scope)
        if not layers:
            return

        self._cbp_layers[module_id] = layers
        # On the layer's own device rather than the default one. The module has
        # already been moved to the learner's device by `super().build()`, so a
        # state tensor left on the CPU would meet a CUDA `h` in
        # `activation_stats`'s `h - f_hat` on the very first forward pass and
        # raise. Read off the weight rather than from `_cbp_device` so the two
        # cannot drift apart.
        self._cbp_state[module_id] = {
            layer.name: CBPLayerState.zeros(
                layer.num_units, device=layer.incoming.weight.device
            )
            for layer in layers
        }
        for layer in layers:
            self._cbp_handles.append(
                layer.hook_target.register_forward_hook(
                    self._cbp_hook(module_id, layer)
                )
            )

    def _cbp_hook(self, module_id, layer: ReplaceableLayer):
        """A forward hook reducing `h` to the per-unit statistics CBP needs.

        The reduction happens *here*, inside the hook, for two reasons. The
        cheap one is memory. The load-bearing one is that `mean|h - f_hat|`
        cannot be recovered from any reduction of `h` alone - it needs the
        running mean as it stood at the time of the forward pass.

        Nothing holding the autograd graph may be stored: `activation_stats`
        detaches, and the rank sample is detached and cloned. Keeping a live
        `h` would pin the graph until the next forward, which is the leak
        `jepa_learner.setup()` documents for its own training-only submodules.
        """
        key = (module_id, layer.name)

        def hook(_module, _inputs, output):
            if not torch.is_tensor(output):
                return
            state = self._cbp_state[module_id][layer.name]
            self._cbp_stats[key] = activation_stats(
                output, state, self._cbp_config
            )
            if self._cbp_wants_rank_sample():
                sample = output.detach()
                if sample.dim() > 2:
                    sample = sample.reshape(-1, sample.shape[-1])
                self._cbp_activations[key] = sample[:_RANK_SAMPLE_ROWS].clone()

        return hook

    def _cbp_wants_rank_sample(self) -> bool:
        every = max(1, int(self._cbp_config.metrics_every_n_updates))
        return self._cbp_updates % every == 0

    # --- The update path -----------------------------------------------------

    def apply_gradients(self, gradients_dict) -> None:
        """The optimiser step, then generate-and-test (arXiv Algorithm 3)."""
        super().apply_gradients(gradients_dict)
        if self._cbp_config.active and self._cbp_config.fire_on == "adam_step":
            self._cbp_run()

    def after_gradient_based_update(self, *, timesteps) -> None:
        super().after_gradient_based_update(timesteps=timesteps)
        if self._cbp_config.active and self._cbp_config.fire_on == "iteration":
            self._cbp_run()

    def _cbp_run(self) -> None:
        """One generate-and-test pass over every module's layers."""
        log_metrics = self._cbp_wants_rank_sample()
        for module_id, layers in self._cbp_layers.items():
            optimizer = self._cbp_optimizer(module_id)
            per_layer: List[Dict[str, float]] = []
            for layer in layers:
                stats = self._cbp_stats.pop((module_id, layer.name), None)
                if stats is None:
                    # No forward pass observed this layer - an inference-only
                    # branch, or a module not in this minibatch.
                    continue
                state = self._cbp_state[module_id][layer.name]
                corrected = update_utility(state, layer, stats, self._cbp_config)
                select_and_replace(
                    state, layer, corrected, self._cbp_config,
                    generator=self._cbp_generator, optimizer=optimizer,
                )
                if log_metrics:
                    metrics = plasticity_metrics(
                        layer, stats, corrected, self._cbp_config,
                        activations=self._cbp_activations.pop(
                            (module_id, layer.name), None
                        ),
                    )
                    metrics["mature_unit_frac"] = mature_fraction(
                        state, self._cbp_config
                    )
                    metrics["replacements"] = float(state.replacements)
                    per_layer.append(metrics)
            if per_layer:
                self._cbp_log(module_id, per_layer)
        # A layer that produced no stats this step never had its sample popped,
        # and a sample is a real tensor. Cleared unconditionally so the dict
        # cannot accumulate one entry per such layer for the life of the run.
        self._cbp_activations.clear()
        self._cbp_updates += 1

    def _cbp_optimizer(self, module_id):
        try:
            return self.get_optimizer(module_id=module_id)
        except (KeyError, ValueError):
            return None

    def _cbp_log(self, module_id, per_layer: List[Dict[str, float]]) -> None:
        """One set of metrics per module, reduced over that module's layers.

        Reduced rather than logged per layer because the metric key space is
        flat: logging each layer under the same module key would leave whichever
        layer happened to be last, which reads as a per-module number and is
        not one. Emitting a series per layer instead would mean 80 of them for a
        16-layer `moe_transformer`.

        Three reductions, and which one a metric gets follows from what a bad
        value would look like:

          sum   `replacements`, because it counts events in the network rather
                than describing a layer.
          worst `dead_unit_frac` and `saturated_unit_frac` (max) and
                `utility_min` (min), because one collapsing layer is the thing
                worth seeing and an average over healthy neighbours hides it.
          mean  everything else - `mean_weight_magnitude`, `utility_median`,
                `batch_effective_rank`, `mature_unit_frac` - where an average
                is what a reader comparing runs would take anyway.

        doc/11 lists the same table from the reader's side; the two have to
        agree, because that table is what someone plots against.
        """
        summed = {"replacements"}
        minimum = {"utility_min"}
        maximum = {"dead_unit_frac", "saturated_unit_frac"}

        reduced: Dict[str, float] = {}
        for name in {key for metrics in per_layer for key in metrics}:
            values = [m[name] for m in per_layer if name in m]
            if name in summed:
                reduced[name] = float(sum(values))
            elif name in minimum:
                reduced[name] = float(min(values))
            elif name in maximum:
                reduced[name] = float(max(values))
            else:
                reduced[name] = float(sum(values) / len(values))

        self.metrics.log_dict(
            {f"{CBP_METRIC_PREFIX}{name}": value
             for name, value in reduced.items()},
            key=module_id,
            window=1,
        )

    # --- Checkpointing -------------------------------------------------------

    def get_state(self, *args, **kwargs) -> Dict[str, Any]:
        """The base learner's state, plus CBP's utility, ages and accumulators.

        These are *learned* quantities. A resume that dropped them would put
        every unit back at age 0 and utility 0, so the maturity threshold would
        protect all of them and the first eligible sweep afterwards would rank
        by an estimate built from almost no data. On a project whose
        `chkpt_freq` is 2 that is a real and completely silent degradation.
        """
        state = super().get_state(*args, **kwargs)
        if self._cbp_state:
            state[CBP_STATE] = {
                str(module_id): {
                    name: layer_state.get_state()
                    for name, layer_state in layers.items()
                }
                for module_id, layers in self._cbp_state.items()
            }
        return state

    def set_state(self, state: Dict[str, Any]) -> None:
        """Restore, tolerating a checkpoint written before CBP existed.

        Read defensively rather than with `state[CBP_STATE]`: every checkpoint
        this project has already written lacks the key, and a restore is not
        the place to discover that. A layer absent from the checkpoint keeps
        its freshly zeroed state, which is also what a newly enabled CBP wants.
        """
        super().set_state(state)
        stored = state.get(CBP_STATE)
        if not stored:
            return
        for module_id, layers in self._cbp_state.items():
            saved = stored.get(str(module_id), {})
            for name, layer_state in layers.items():
                if name in saved:
                    layer_state.set_state(saved[name])


class TunedAdamMixin:
    """Adam's betas and weight decay, from config instead of torch's defaults.

    A mixin of its own rather than part of `CBPLearnerMixin`, because the two
    interventions are independent and the papers treat them that way. Both
    papers run every algorithm *except* the standard-PPO baseline with
    `beta_1 = beta_2 = 0.99`, on the grounds that the usual (0.9, 0.999)
    mismatch is itself a cause of plasticity loss: the squared-gradient
    estimate in the denominator updates far more slowly than the gradient
    estimate in the numerator, so one large gradient produces one very large,
    destabilising update. The Nature paper separately applies continual
    backprop together with L2 in every reinforcement-learning experiment, and
    reports that the pair is insensitive to the replacement rate where CBP
    alone is not.

    Keeping them separable is the point: composing this only when CBP is on
    would make every CBP-vs-baseline comparison a comparison of CBP *and* a
    retuned optimiser, which is exactly the confound to avoid.
    """

    def configure_optimizers_for_module(self, module_id, config=None) -> None:
        values = (getattr(self.config, "learner_config_dict", None) or {}).get(
            OPTIMIZER_CONFIG_KEY
        ) or {}
        betas = values.get("adam_betas")
        weight_decay = values.get("adam_weight_decay")
        if not betas and not weight_decay:
            # Nothing configured - defer, so the optimiser is bit-for-bit the
            # one RLlib builds. This is the path every existing run takes.
            super().configure_optimizers_for_module(module_id, config=config)
            return

        params = self.get_parameters(self.module[module_id])
        optimizer = torch.optim.Adam(
            params,
            betas=tuple(betas) if betas else (0.9, 0.999),
            weight_decay=float(weight_decay or 0.0),
        )
        self.register_optimizer(
            module_id=module_id,
            optimizer=optimizer,
            params=params,
            lr_or_lr_schedule=config.lr,
        )


def with_continual_backprop(base, tuned_adam: bool = False):
    """Compose the mixins over a Learner class.

    The mixins come first in the MRO so their `apply_gradients`, `get_state`
    and `configure_optimizers_for_module` run, while `compute_loss_for_module`
    still resolves to `base` - which is what keeps the MoE load-balancing term
    and the JEPA latent-prediction term intact for a run that selected one of
    those encoders.
    """
    mixins = (CBPLearnerMixin,)
    if tuned_adam:
        mixins = mixins + (TunedAdamMixin,)
    return type(f"CBP{base.__name__}", mixins + (base,), {})


def with_tuned_adam(base):
    """Compose only the optimiser mixin, for a run using it without CBP."""
    return type(f"TunedAdam{base.__name__}", (TunedAdamMixin, base), {})
