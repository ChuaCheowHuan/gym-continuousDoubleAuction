"""
RLModules for the CDA environment (RLlib new API stack).

Four things live here:

  RandomRLModule   - a genuinely uniform-random, non-trainable policy, used for
                     the fixed baseline opponents in league-based self-play.
  default_model_config() - the stock MLP network config for the *trainable* PPO
                     modules.
  CDACatalog       - a PPO catalog whose encoder comes from
                     `train/model/encoders/` instead of RLlib's default decision
                     tree.
  build_trainable_module_spec() - builds one trainable module's RLModuleSpec,
                     routing to either of the two above depending on the
                     `encoder` group of `config/train_config.json`.

------------------------------------------------------------------------------
Swapping the network
------------------------------------------------------------------------------
`encoder_type: "mlp"` is the default and is a *pass-through*: it returns the
same stock `DefaultModelConfig` spec this module returned before encoders were
selectable, with no `catalog_class`, so a default run and every checkpoint
written by one are unaffected. Any other value routes the trainable modules
through `CDACatalog`. See `train/model/encoders/__init__.py` for why the catalog
is the right seam and what an encoder has to implement.

------------------------------------------------------------------------------
Why there is no custom trainable module any more
------------------------------------------------------------------------------
This file previously defined a `CustomRLModule` that was registered via
`ModelCatalog.register_custom_model("model_disc", CustomRLModule)` and referenced
from `PolicySpec(config={"model": {"custom_model": "model_disc"}})`.

On the new API stack neither of those hooks is read: `AlgorithmConfig` uses only
the *keys* of `policies` as module IDs and fills `module_class` from the
algorithm's default RLModule spec. So `CustomRLModule` was never instantiated -
and it could not have been, because it read `config.action_space.n`, while this
env's action space is a `spaces.Dict`.

The trainable modules therefore use RLlib's default PPO torch module, whose
network is configured through `DefaultModelConfig` (see `default_model_config`).
If you want a genuinely custom architecture later, subclass
`DefaultPPOTorchRLModule` and pass it as `RLModuleSpec(module_class=...)` in
policy_handler.build_multi_rl_module_spec - not via ModelCatalog.
"""
import numpy as np
from ray.rllib.algorithms.ppo.ppo_catalog import PPOCatalog
from ray.rllib.core.columns import Columns
from ray.rllib.core.models.configs import ModelConfig
from ray.rllib.core.rl_module.default_model_config import DefaultModelConfig
from ray.rllib.core.rl_module.rl_module import RLModule, RLModuleSpec
from ray.rllib.utils.annotations import override
from ray.rllib.utils.spaces.space_utils import batch as batch_func

from gym_continuousDoubleAuction.config_loader import group
from gym_continuousDoubleAuction.train.model.moe_learner import CDAPPOTorchRLModule
from gym_continuousDoubleAuction.train.model.encoders import (
    MLP_ENCODER_TYPE,
    CDAModelConfig,
    build_encoder_config,
    known_encoder_type,
    model_config_overrides,
    module_class_for,
    validate_encoder_type,
)
from gym_continuousDoubleAuction.train.model.action_mask import mask_slice


class RandomRLModule(RLModule):
    """A uniformly-random, non-trainable policy.

    Emits `Columns.ACTIONS` directly rather than `ACTION_DIST_INPUTS`, so the
    action is drawn straight from `action_space.sample()` and never passes
    through a learned distribution. For this env's `spaces.Dict` action space
    that means each component is sampled from its own declared range:
    `category` uniform over 9, `price` over 10, `price_offset` over 3,
    `order_slot` over max_own_orders + 1, `size_mean` ~ U(-1, 1),
    `size_sigma` ~ U(0, 1).

    This is the distinction that matters versus a *frozen randomly-initialised*
    PPO network, which is what the old `PolicySpec(RandomPolicy, ...)` wiring
    silently produced: that samples the Box components from a Gaussian
    (mean ~ 0, sigma ~ 1) and clips, so e.g. `size_sigma` piles up on 0 instead
    of being uniform on [0, 1], and the Discrete components carry a fixed
    initialisation bias for the whole run.

    MUST be excluded from `policies_to_train` - `_forward_train` raises.
    """

    _obs_mask = None

    @override(RLModule)
    def _forward(self, batch, **kwargs):
        # This env's observation space is a flat Box, so the batch dimension is
        # just len() of the obs tensor. (RLlib's own example uses dm-tree here
        # to cope with nested observation spaces; not needed for a Box.)
        obs = batch[Columns.OBS]
        obs_batch_size = len(obs)
        samples = [self.action_space.sample() for _ in range(obs_batch_size)]

        # Honour the observation's action mask (doc/06 section 6): a category
        # the env says is impossible is redrawn uniformly among the possible
        # ones, so the baseline is "random among what can be done" rather than
        # "random including the dead actions". With the mask off the env
        # emits all ones and nothing is redrawn.
        if self._obs_mask is None:
            self._obs_mask = mask_slice(self.observation_space) or False
        if self._obs_mask:
            rows = obs.detach().cpu().numpy() if hasattr(obs, "detach") else np.asarray(obs)
            rng = self.action_space.np_random
            for sample, row in zip(samples, rows):
                allowed = np.flatnonzero(row[self._obs_mask] > 0.5)
                if len(allowed) and row[self._obs_mask][int(sample["category"])] <= 0.5:
                    sample["category"] = int(rng.choice(allowed))
        return {Columns.ACTIONS: batch_func(samples)}

    @override(RLModule)
    def _forward_train(self, *args, **kwargs):
        raise NotImplementedError(
            "RandomRLModule is not trainable. Exclude its ModuleID from "
            "`config.multi_agent(policies_to_train=[...])`."
        )

    def compile(self, *args, **kwargs):
        """No-op, for parity with TorchRLModule's compile hook."""


def default_model_config(fcnet_hiddens=None, fcnet_activation=None,
                         vf_share_layers=None):
    """Network config for the trainable PPO modules.

    Args:
        fcnet_hiddens: Hidden layer sizes.
        fcnet_activation: Activation for the hidden layers.
        vf_share_layers: Whether policy and value share a trunk. Configured
            False because the learners train against non-stationary opponents
            (the league), where sharing a trunk between policy and value tends
            to destabilise the value estimate.

    Any argument left as None is read from the `ppo` group of
    `config/train_config.json` - the same group TrainConfig reads, so a call
    that goes through TrainConfig and a bare call agree by construction.

    Returns:
        A `DefaultModelConfig` for `RLModuleSpec(model_config=...)`.
    """
    ppo = group("train_config.json", "ppo")
    if fcnet_hiddens is None:
        fcnet_hiddens = ppo["fcnet_hiddens"]
    if fcnet_activation is None:
        fcnet_activation = ppo["fcnet_activation"]
    if vf_share_layers is None:
        vf_share_layers = ppo["vf_share_layers"]

    return DefaultModelConfig(
        fcnet_hiddens=list(fcnet_hiddens),
        fcnet_activation=fcnet_activation,
        vf_share_layers=vf_share_layers,
    )


class CDACatalog(PPOCatalog):
    """PPO catalog whose encoder comes from `train.model.encoders`.

    Only the encoder changes. `PPOCatalog.__init__` still wraps whatever
    `_get_encoder_config` returns in an `ActorCriticEncoderConfig` - which is
    what supplies the `ENCODER_OUT/{ACTOR, CRITIC}` contract, the
    `.critic_encoder` attribute `compute_values` looks for, `inference_only`
    handling, and the stateful wrapper for a recurrent config - and the pi and
    vf heads are still the stock ones, sized off `latent_dims`.

    Only reached when `encoder_type` is not `mlp`; see
    `build_trainable_module_spec`.
    """

    @classmethod
    @override(PPOCatalog)
    def _get_encoder_config(cls, observation_space, model_config_dict,
                            action_space=None, **kwargs) -> ModelConfig:
        # `action_space` is forwarded because the JEPA world model needs it to
        # size its action embedding. Every other encoder ignores it - the
        # catalog has always passed it and nothing read it until now.
        return build_encoder_config(
            observation_space, model_config_dict, action_space
        )


def build_trainable_module_spec(obs_space, act_space, encoder_type=None,
                                encoder_specs=None, fcnet_hiddens=None,
                                fcnet_activation=None, vf_share_layers=None,
                                pretrained_path=None):
    """The `RLModuleSpec` for one trainable PPO module.

    Args:
        obs_space: Single-agent observation space.
        act_space: Single-agent action space.
        encoder_type: Which encoder to use. None reads the `encoder` group of
            `config/train_config.json`.
        encoder_specs: Per-encoder hyperparameter blocks, keyed by encoder type.
            None reads the same group.
        fcnet_hiddens: Passed to `default_model_config`; `mlp` only.
        fcnet_activation: Ditto.
        vf_share_layers: Ditto. Also honoured by custom encoders, since
            `ActorCriticEncoderConfig` reads it to decide whether the actor and
            critic share a trunk.
        pretrained_path: A directory written by `train.pretrain`, whose weights
            the module starts from. The checkpoint's encoder fingerprint is
            verified against the encoder being built *here*, before the path
            reaches RLlib - a mismatch is a hard error rather than a shape
            failure several frames later. Ignored for `mlp`, which has no
            self-supervised objective to have been pretrained on.

    Returns:
        An `RLModuleSpec` with `module_class` left None, so RLlib fills in the
        algorithm's default PPO module. For `mlp` the spec is exactly what this
        function returned before encoders were selectable - stock
        `DefaultModelConfig`, no `catalog_class` - so a default run and the
        checkpoints it writes are unaffected.
    """
    encoder = group("train_config.json", "encoder")
    if encoder_type is None:
        # Read from config, so hold it to the config rules: no test fixtures.
        encoder_type = validate_encoder_type(encoder["encoder_type"])
    else:
        known_encoder_type(encoder_type)
    if encoder_specs is None:
        encoder_specs = encoder["encoder_specs"]

    encoder_spec = encoder_specs.get(encoder_type, {})
    # Validated for every encoder including `mlp`, which has no registered
    # defaults and so accepts only the common keys. Doing it before the branch
    # is what stops an `mlp` block being silently ignored: `mlp` returns early,
    # and a misspelled knob that reaches no builder would otherwise have no
    # symptom at all - the one failure the config loader exists to remove.
    overrides = model_config_overrides(encoder_type, encoder_spec)

    model_config = default_model_config(
        fcnet_hiddens=fcnet_hiddens,
        fcnet_activation=fcnet_activation,
        # An encoder may override the `ppo` group's value; see COMMON_SPEC_KEYS.
        vf_share_layers=overrides.get("vf_share_layers", vf_share_layers),
    )

    if encoder_type == MLP_ENCODER_TYPE:
        if pretrained_path:
            raise ValueError(
                "encoder_type 'mlp' cannot use a pretrained encoder: it has no "
                "self-supervised objective, so there is nothing that could have "
                "produced those weights. Set encoder_type to the architecture "
                "the checkpoint was trained for."
            )
        return RLModuleSpec(
            # The mask-aware module (identical to the stock one otherwise);
            # no catalog_class, so the encoder is still RLlib's own MLP.
            module_class=CDAPPOTorchRLModule,
            observation_space=obs_space,
            action_space=act_space,
            model_config=model_config,
        )

    fields = {
        "fcnet_hiddens": model_config.fcnet_hiddens,
        "fcnet_activation": model_config.fcnet_activation,
        "vf_share_layers": model_config.vf_share_layers,
        "encoder_type": encoder_type,
        "encoder_spec": encoder_spec,
    }

    if pretrained_path:
        # Verified HERE, before the path reaches the model config, so a
        # checkpoint for a different architecture fails while there is still a
        # name to put in the message - not as a shape error inside an encoder
        # constructor on some env runner.
        #
        # The path rides on the model config rather than on `RLModuleSpec`'s
        # `load_state_path`, which looks like the field for exactly this and is
        # not: nothing in RLlib 2.56 ever reads it back, so setting it would
        # have silently done nothing. Carrying it on the model config means
        # every process that constructs the encoder - env runners and learners
        # alike - loads the weights itself, with no state to synchronise.
        #
        # Imported here rather than at module scope: `train.pretrain` imports
        # the probe, which imports this module.
        from gym_continuousDoubleAuction.train.pretrain import verify_fingerprint

        verify_fingerprint(pretrained_path, encoder_type, encoder_spec)
        fields["pretrained_path"] = pretrained_path
    # Some spec keys configure RLlib rather than the encoder and cannot ride on
    # a custom encoder config: `max_seq_len`, which the connectors read to cut a
    # recurrent module's batch into sequences before any encoder is called, and
    # `vf_share_layers`, which an encoder may override because the `ppo` group's
    # value was chosen for the MLP. Applied last so an encoder that sets one
    # wins over the group.
    fields.update(overrides)

    return RLModuleSpec(
        # The stock module would do for every encoder except moe_transformer,
        # whose auxiliary loss needs a hop through `_forward_train` to reach the
        # Learner. CDAPPOTorchRLModule is identical to its base when there is no
        # such loss, so it is the default for all custom encoders rather than a
        # branch on one of them.
        #
        # An encoder may name a different one through `@register`. Nothing did
        # when that mechanism was added, so every encoder registered before it
        # still resolves to exactly this class - which is what lets a new
        # architecture bring its own module without editing any existing one.
        module_class=module_class_for(encoder_type, CDAPPOTorchRLModule),
        observation_space=obs_space,
        action_space=act_space,
        catalog_class=CDACatalog,
        model_config=CDAModelConfig(**fields),
    )
