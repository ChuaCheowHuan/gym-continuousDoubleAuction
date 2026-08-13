"""
Multi-agent module wiring for the CDA environment (RLlib new API stack).

Layout, for n agents with k trainable:

    policy_0 .. policy_(k-1)    trainable PPO modules   (agents 0..k-1)
    policy_k .. policy_(n-1)    frozen RandomRLModule   (baseline opponents)
    champion_1, champion_2, ..  frozen PPO snapshots    (added at runtime by
                                                         SelfPlayCallback)

Agents k..n-1 do not map 1:1 to modules. Each episode they are drawn from the
opponent pool (baselines + champions) by
`SelfPlayCallback.get_mapping_fn`. Only agents 0..k-1 have a fixed mapping.

------------------------------------------------------------------------------
Migration note
------------------------------------------------------------------------------
This module previously built a dict of `PolicySpec`s, with the baseline
opponents declared as `PolicySpec(RandomPolicy, ...)` and the trainable ones
carrying `config={"model": {"custom_model": "model_disc"}}`.

On the new API stack `AlgorithmConfig.multi_agent(policies=...)` uses only the
*keys* of that dict as ModuleIDs; `policy_class` and the per-policy model config
are discarded (see `AlgorithmConfig.get_multi_rl_module_spec`, which fills
`module_class` from the algorithm's default RLModule spec). The result was that
every module - including the six "random" ones - was built as
`DefaultPPOTorchRLModule` with no warning, so the baseline opponents were
frozen randomly-initialised networks rather than random samplers.

Module classes are now declared explicitly through `MultiRLModuleSpec`, which is
the only thing the new stack actually reads.
"""
from ray.rllib.core.rl_module.multi_rl_module import MultiRLModuleSpec
from ray.rllib.core.rl_module.rl_module import RLModuleSpec

from gym_continuousDoubleAuction.train.model.model_handler import (
    RandomRLModule,
    default_model_config,
)

# Module ID conventions. The callback relies on these prefixes to tell baseline
# opponents (weight `original_opponent_weight`) from champion snapshots
# (weight `champion_weight`) when sampling the opponent pool.
POLICY_PREFIX = "policy_"
CHAMPION_PREFIX = "champion_"


def policy_id(i):
    """ModuleID for the i-th policy slot."""
    return f"{POLICY_PREFIX}{i}"


def trainable_policy_ids(num_trained_agents):
    """ModuleIDs of the trainable PPO modules."""
    return [policy_id(i) for i in range(num_trained_agents)]


def baseline_policy_ids(num_agents, num_trained_agents):
    """ModuleIDs of the frozen random baseline opponents."""
    return [policy_id(i) for i in range(num_trained_agents, num_agents)]


def build_multi_rl_module_spec(
    obs_space,
    act_space,
    num_agents,
    num_trained_agents,
    fcnet_hiddens=None,
    fcnet_activation="tanh",
    vf_share_layers=False,
):
    """Build the MultiRLModuleSpec for a league-based self-play run.

    Args:
        obs_space: Single-agent observation space.
        act_space: Single-agent action space.
        num_agents: Total number of agents, n.
        num_trained_agents: Number of trainable PPO modules, k.
        fcnet_hiddens: Hidden sizes for the trainable modules.
        fcnet_activation: Activation for the hidden layers.
        vf_share_layers: Whether policy and value share a trunk.

    Returns:
        MultiRLModuleSpec covering policy_0..policy_(n-1).

    Note:
        `module_class=None` on the trainable specs is intentional - it makes
        RLlib fill in the algorithm's default (PPO) module. The random modules
        set `module_class` explicitly, which is the whole point of this rewrite.
    """
    if not 0 < num_trained_agents <= num_agents:
        raise ValueError(
            f"num_trained_agents must be in (0, num_agents]; got "
            f"num_trained_agents={num_trained_agents}, num_agents={num_agents}"
        )

    model_config = default_model_config(
        fcnet_hiddens=fcnet_hiddens,
        fcnet_activation=fcnet_activation,
        vf_share_layers=vf_share_layers,
    )

    specs = {}
    for pid in trainable_policy_ids(num_trained_agents):
        specs[pid] = RLModuleSpec(
            observation_space=obs_space,
            action_space=act_space,
            model_config=model_config,
        )
    for pid in baseline_policy_ids(num_agents, num_trained_agents):
        specs[pid] = RLModuleSpec(
            module_class=RandomRLModule,
            observation_space=obs_space,
            action_space=act_space,
        )

    return MultiRLModuleSpec(rl_module_specs=specs)


def create_multi_agent_config(
    obs_space,
    act_space,
    num_agents,
    num_trained_agents,
    fcnet_hiddens=None,
    fcnet_activation="tanh",
    vf_share_layers=False,
):
    """Everything `AlgorithmConfig.multi_agent(...)` / `.rl_module(...)` needs.

    Returns:
        (policies, policies_to_train, rl_module_spec) where

        policies:         set of ModuleIDs, for `.multi_agent(policies=...)`
        policies_to_train: list of trainable ModuleIDs. The baseline modules
                          MUST be excluded - RandomRLModule._forward_train
                          raises if RLlib ever tries to update it.
        rl_module_spec:   MultiRLModuleSpec, for `.rl_module(rl_module_spec=...)`
    """
    spec = build_multi_rl_module_spec(
        obs_space,
        act_space,
        num_agents,
        num_trained_agents,
        fcnet_hiddens,
        fcnet_activation=fcnet_activation,
        vf_share_layers=vf_share_layers,
    )
    policies = set(spec.rl_module_specs.keys())
    policies_to_train = trainable_policy_ids(num_trained_agents)

    print(f"[PolicyHandler] modules: {sorted(policies)}")
    print(f"[PolicyHandler] trainable: {policies_to_train}")
    print(
        f"[PolicyHandler] frozen random baselines: "
        f"{baseline_policy_ids(num_agents, num_trained_agents)}"
    )
    return policies, policies_to_train, spec


def policy_mapping_fn(agent_id, episode=None, **kwargs):
    """Static 1:1 agent -> module mapping.

    Only useful for runs *without* league self-play (e.g. the integration
    tests). Live training uses `SelfPlayCallback.get_mapping_fn`, which maps the
    non-trainable agent slots to the opponent pool instead.
    """
    if isinstance(agent_id, str) and agent_id.startswith("agent_"):
        return policy_id(int(agent_id.split("_")[1]))
    return policy_id(int(agent_id))
