"""The selectable-encoder seam.

Two things are pinned here.

The first is that `mlp` did not change. It is the default and every existing
checkpoint was written with it, so the spec built for it must be exactly what
was built before encoders were selectable: a stock `DefaultModelConfig`, no
`catalog_class`, nothing from `train/model/encoders/` in the way.

The second is that the *custom* path works end to end. `mlp` cannot show that -
it is a pass-through and never touches any of the new code, so it can pass while
the whole custom route is broken. `_passthrough`, the registered test fixture,
is what travels that route: `CDAModelConfig` -> `CDACatalog` ->
`build_encoder_config` -> `ActorCriticEncoderConfig` -> the stock pi/vf heads.
"""
import dataclasses

import gymnasium as gym
import numpy as np
import pytest
import torch
from ray.rllib.algorithms.ppo.torch.default_ppo_torch_rl_module import (
    DefaultPPOTorchRLModule,
)
from ray.rllib.core.columns import Columns
from ray.rllib.core.rl_module.default_model_config import DefaultModelConfig

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.train.model.encoders import (
    ENCODER_REGISTRY,
    MLP_ENCODER_TYPE,
    CDAModelConfig,
    known_encoder_type,
    selectable_encoder_types,
    validate_encoder_type,
)
from gym_continuousDoubleAuction.train.model.encoders.obs_layout import ObsLayout
from gym_continuousDoubleAuction.train.model.encoders.tokenize import (
    TOKENIZATIONS,
    token_shape,
    tokenize,
)
from gym_continuousDoubleAuction.train.model.model_handler import (
    CDACatalog,
    build_trainable_module_spec,
    default_model_config,
)

FIXTURE = "_passthrough"


@pytest.fixture(scope="module")
def spaces():
    env = continuousDoubleAuctionEnv({})
    agent_id = env.agents[0]
    return env.get_observation_space(agent_id), env.get_action_space(agent_id)


def build_module(spaces, encoder_type, **kwargs):
    """A built PPO module for one encoder type."""
    obs_space, act_space = spaces
    spec = build_trainable_module_spec(
        obs_space, act_space, encoder_type=encoder_type, encoder_specs={}, **kwargs
    )
    # The `mlp` path leaves module_class None for RLlib to fill in from the
    # algorithm's default spec; building a spec standalone needs it set. Custom
    # encoders set their own, which must not be overwritten.
    if spec.module_class is None:
        spec.module_class = DefaultPPOTorchRLModule
    return spec, spec.build()


# --- Registry ---------------------------------------------------------------

def test_mlp_is_selectable_and_not_in_the_registry():
    """`mlp` is the pass-through, handled before the registry is consulted."""
    assert MLP_ENCODER_TYPE in selectable_encoder_types()
    assert MLP_ENCODER_TYPE not in ENCODER_REGISTRY


def test_unknown_encoder_type_raises_naming_the_alternatives():
    with pytest.raises(ValueError, match="Unknown encoder_type"):
        validate_encoder_type("no_such_encoder")
    with pytest.raises(ValueError, match="Unknown encoder_type"):
        known_encoder_type("no_such_encoder")


def test_fixture_is_buildable_but_not_config_selectable():
    """The strict check guards config; the permissive one lets tests build it."""
    assert FIXTURE in ENCODER_REGISTRY
    assert FIXTURE not in selectable_encoder_types()

    assert known_encoder_type(FIXTURE) == FIXTURE
    with pytest.raises(ValueError, match="test fixture"):
        validate_encoder_type(FIXTURE)


# --- Observation layout ------------------------------------------------------

def test_layout_matches_the_declared_observation_space(spaces):
    obs_space, _ = spaces
    layout = ObsLayout.from_obs_space(obs_space)

    assert layout.flat_dim == obs_space.shape[0]
    assert layout.snapshot_dim == layout.book_rows * layout.k_rows + layout.extra_dim
    assert layout.n_hist >= 1


def test_layout_rejects_a_space_that_is_not_whole_snapshots():
    with pytest.raises(ValueError, match="whole number"):
        ObsLayout.from_obs_space(gym.spaces.Box(-1.0, 1.0, shape=(41,)))


def test_layout_rejects_a_non_flat_space():
    with pytest.raises(TypeError, match="flat 1-D Box"):
        ObsLayout.from_obs_space(gym.spaces.Box(-1.0, 1.0, shape=(4, 42)))


# --- Tokenisation ------------------------------------------------------------

@pytest.mark.parametrize("tokenization", TOKENIZATIONS)
def test_tokenize_matches_its_declared_shape(spaces, tokenization):
    obs_space, _ = spaces
    layout = ObsLayout.from_obs_space(obs_space)
    obs = torch.from_numpy(np.stack([obs_space.sample() for _ in range(3)]))

    tokens = tokenize(obs, layout, tokenization)

    assert tuple(tokens.shape) == (3,) + token_shape(layout, tokenization)


def test_tokenize_rejects_an_unknown_tokenization(spaces):
    obs_space, _ = spaces
    layout = ObsLayout.from_obs_space(obs_space)
    obs = torch.from_numpy(np.stack([obs_space.sample()]))

    with pytest.raises(ValueError, match="Unknown tokenization"):
        tokenize(obs, layout, "sideways")


def test_time_tokenization_preserves_the_observation(spaces):
    """`time` is a pure reshape, so nothing may be dropped or reordered."""
    obs_space, _ = spaces
    layout = ObsLayout.from_obs_space(obs_space)
    obs = torch.from_numpy(np.stack([obs_space.sample() for _ in range(2)]))

    tokens = tokenize(obs, layout, "time")

    assert torch.equal(tokens.reshape(2, -1), obs)


def test_level_tokens_carry_one_level_per_token(spaces):
    """A level token is that level's 4 fields, read from the newest snapshot.

    The book block is field-major - all k bid_prices, then all k bid_sizes, ...
    - so this is what pins the transpose in `tokenize` as the right way round.
    """
    obs_space, _ = spaces
    layout = ObsLayout.from_obs_space(obs_space)
    obs = torch.from_numpy(np.stack([obs_space.sample()]))

    tokens = tokenize(obs, layout, "level")
    newest = obs[0, -layout.snapshot_dim :]

    for level in range(layout.k_rows):
        expected = torch.tensor(
            [newest[field * layout.k_rows + level] for field in range(layout.book_rows)]
        )
        assert torch.equal(tokens[0, level], expected)


def test_level_tokenization_appends_a_global_token(spaces):
    """The market-level scalars ride on their own token, not on a level."""
    obs_space, _ = spaces
    layout = ObsLayout.from_obs_space(obs_space)
    obs = torch.from_numpy(np.stack([obs_space.sample()]))

    tokens = tokenize(obs, layout, "level")
    newest = obs[0, -layout.snapshot_dim :]
    extras = newest[layout.book_dim :]

    assert tokens.shape[1] == layout.k_rows + 1
    assert torch.equal(tokens[0, -1, : layout.extra_dim], extras)


# --- The mlp pass-through ----------------------------------------------------

def test_mlp_spec_is_the_stock_rllib_path(spaces):
    """No catalog override, and a plain DefaultModelConfig - not a CDA one."""
    obs_space, act_space = spaces
    spec = build_trainable_module_spec(
        obs_space, act_space, encoder_type=MLP_ENCODER_TYPE, encoder_specs={}
    )

    assert spec.catalog_class is None
    assert type(spec.model_config) is DefaultModelConfig
    assert not isinstance(spec.model_config, CDAModelConfig)


def test_mlp_spec_matches_default_model_config(spaces):
    """The shape still comes from the `ppo` group, exactly as it always did."""
    obs_space, act_space = spaces
    spec = build_trainable_module_spec(
        obs_space, act_space, encoder_type=MLP_ENCODER_TYPE, encoder_specs={}
    )

    assert dataclasses.asdict(spec.model_config) == dataclasses.asdict(
        default_model_config()
    )


def test_default_config_selects_mlp():
    """The shipped config must not change what a run does."""
    from gym_continuousDoubleAuction.config_loader import group

    assert group("train_config.json", "encoder")["encoder_type"] == MLP_ENCODER_TYPE


# --- The custom path ---------------------------------------------------------

def test_custom_encoder_routes_through_the_cda_catalog(spaces):
    obs_space, act_space = spaces
    spec = build_trainable_module_spec(
        obs_space, act_space, encoder_type=FIXTURE, encoder_specs={}
    )

    assert spec.catalog_class is CDACatalog
    assert isinstance(spec.model_config, CDAModelConfig)
    assert spec.model_config.encoder_type == FIXTURE


@pytest.mark.parametrize("encoder_type", [MLP_ENCODER_TYPE, FIXTURE])
def test_module_forward_and_value_shapes(spaces, encoder_type):
    """Both paths produce a usable policy and critic over the real spaces."""
    obs_space, _ = spaces
    _, module = build_module(spaces, encoder_type)
    obs = torch.from_numpy(np.stack([obs_space.sample() for _ in range(4)]))
    batch = {Columns.OBS: obs}

    train_out = module.forward_train(batch)
    values = module.compute_values(batch)

    assert train_out[Columns.ACTION_DIST_INPUTS].shape[0] == 4
    assert tuple(values.shape) == (4,)
    assert torch.isfinite(train_out[Columns.ACTION_DIST_INPUTS]).all()
    assert torch.isfinite(values).all()


@pytest.mark.parametrize("encoder_type", [MLP_ENCODER_TYPE, FIXTURE])
@pytest.mark.parametrize("vf_share_layers", [False, True])
def test_vf_share_layers_is_honoured(spaces, encoder_type, vf_share_layers):
    """Sharing is what decides whether a separate critic trunk exists.

    `compute_values` reaches for `encoder.critic_encoder` when the trunks are
    separate, so a custom encoder that lost this attribute would silently fall
    back to recomputing the shared path.
    """
    _, module = build_module(spaces, encoder_type, vf_share_layers=vf_share_layers)

    has_critic_encoder = getattr(module.encoder, "critic_encoder", None) is not None
    assert has_critic_encoder is (not vf_share_layers)


@pytest.mark.parametrize("encoder_type", [MLP_ENCODER_TYPE, FIXTURE])
def test_non_inference_attributes_contract(spaces, encoder_type):
    """The inference-only optimisation strips these by name.

    An encoder built any way other than through `ActorCriticEncoderConfig`
    would not have `encoder.critic_encoder`, and the stripping would silently
    stop working rather than fail.
    """
    _, module = build_module(spaces, encoder_type, vf_share_layers=False)

    assert module.get_non_inference_attributes() == ["vf", "encoder.critic_encoder"]


@pytest.mark.parametrize("encoder_type", [MLP_ENCODER_TYPE, FIXTURE])
def test_module_state_round_trips(spaces, encoder_type):
    """What checkpointing and champion snapshotting both rely on."""
    obs_space, _ = spaces
    _, source = build_module(spaces, encoder_type)
    _, target = build_module(spaces, encoder_type)
    obs = torch.from_numpy(np.stack([obs_space.sample() for _ in range(4)]))
    batch = {Columns.OBS: obs}

    target.set_state(source.get_state())

    assert torch.allclose(
        source.forward_train(batch)[Columns.ACTION_DIST_INPUTS],
        target.forward_train(batch)[Columns.ACTION_DIST_INPUTS],
    )
    assert torch.allclose(source.compute_values(batch), target.compute_values(batch))


def test_custom_encoder_latent_dim_sizes_the_heads(spaces):
    """`latent_dims` is the encoder/head agreement; a wrong one would not build."""
    from gym_continuousDoubleAuction.train.model.encoders.passthrough import (
        _PASSTHROUGH_LATENT,
    )

    obs_space, act_space = spaces
    catalog = CDACatalog(
        observation_space=obs_space,
        action_space=act_space,
        model_config_dict=CDAModelConfig(encoder_type=FIXTURE),
    )

    assert tuple(catalog.latent_dims) == (_PASSTHROUGH_LATENT,)
