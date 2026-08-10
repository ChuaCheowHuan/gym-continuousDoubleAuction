"""
RLModules for the CDA environment (RLlib new API stack).

Two things live here:

  RandomRLModule   - a genuinely uniform-random, non-trainable policy, used for
                     the fixed baseline opponents in league-based self-play.
  default_model_config() - the network config for the *trainable* PPO modules.

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
from ray.rllib.core.columns import Columns
from ray.rllib.core.rl_module.default_model_config import DefaultModelConfig
from ray.rllib.core.rl_module.rl_module import RLModule
from ray.rllib.utils.annotations import override
from ray.rllib.utils.spaces.space_utils import batch as batch_func


class RandomRLModule(RLModule):
    """A uniformly-random, non-trainable policy.

    Emits `Columns.ACTIONS` directly rather than `ACTION_DIST_INPUTS`, so the
    action is drawn straight from `action_space.sample()` and never passes
    through a learned distribution. For this env's `spaces.Dict` action space
    that means each component is sampled from its own declared range:
    `category` uniform over 9, `price` over 10, `price_offset` over 3,
    `size_mean` ~ U(-1, 1), `size_sigma` ~ U(0, 1).

    This is the distinction that matters versus a *frozen randomly-initialised*
    PPO network, which is what the old `PolicySpec(RandomPolicy, ...)` wiring
    silently produced: that samples the Box components from a Gaussian
    (mean ~ 0, sigma ~ 1) and clips, so e.g. `size_sigma` piles up on 0 instead
    of being uniform on [0, 1], and the Discrete components carry a fixed
    initialisation bias for the whole run.

    MUST be excluded from `policies_to_train` - `_forward_train` raises.
    """

    @override(RLModule)
    def _forward(self, batch, **kwargs):
        # This env's observation space is a flat Box, so the batch dimension is
        # just len() of the obs tensor. (RLlib's own example uses dm-tree here
        # to cope with nested observation spaces; not needed for a Box.)
        obs_batch_size = len(batch[Columns.OBS])
        actions = batch_func(
            [self.action_space.sample() for _ in range(obs_batch_size)]
        )
        return {Columns.ACTIONS: actions}

    @override(RLModule)
    def _forward_train(self, *args, **kwargs):
        raise NotImplementedError(
            "RandomRLModule is not trainable. Exclude its ModuleID from "
            "`config.multi_agent(policies_to_train=[...])`."
        )

    def compile(self, *args, **kwargs):
        """No-op, for parity with TorchRLModule's compile hook."""


def default_model_config(fcnet_hiddens=None, fcnet_activation="tanh"):
    """Network config for the trainable PPO modules.

    Args:
        fcnet_hiddens: Hidden layer sizes. Defaults to [256, 256].
        fcnet_activation: Activation for the hidden layers.

    Returns:
        A `DefaultModelConfig` for `RLModuleSpec(model_config=...)`.
    """
    return DefaultModelConfig(
        fcnet_hiddens=list(fcnet_hiddens) if fcnet_hiddens else [256, 256],
        fcnet_activation=fcnet_activation,
        # Separate value network: the two learners are trained against
        # non-stationary opponents (the league), where sharing a trunk between
        # policy and value tends to destabilise the value estimate.
        vf_share_layers=False,
    )
