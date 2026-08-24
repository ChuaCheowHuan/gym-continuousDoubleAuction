"""The contract every encoder must satisfy, plus each one's own specifics.

`test_encoder_registry.py` covers the *seam* - the registry, the catalog, the
`mlp` pass-through. This file covers the encoders themselves.

The parametrised block runs over every registered encoder automatically, so a
new one is covered the moment it is registered rather than when someone
remembers to write its tests. What it pins is the contract the rest of RLlib
relies on: usable pi/vf outputs over the real spaces, a state dict that round
trips (checkpointing and champion snapshots both need it), `vf_share_layers`
honoured in both directions, and a forward pass that is deterministic in eval
mode - which PPO's ratio depends on, and which a stray dropout would break.
"""
import numpy as np
import pytest
import torch
import torch.nn as nn
from ray.rllib.algorithms.ppo.torch.default_ppo_torch_rl_module import (
    DefaultPPOTorchRLModule,
)
from ray.rllib.core.columns import Columns

from gym_continuousDoubleAuction.config_loader import group
from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.train.model.encoders import (
    ENCODER_REGISTRY,
    MLP_ENCODER_TYPE,
)
from gym_continuousDoubleAuction.train.model.encoders.obs_layout import ObsLayout
from gym_continuousDoubleAuction.train.model.encoders.tokenize import (
    TOKENIZATIONS,
    token_shape,
)
from gym_continuousDoubleAuction.train.model.encoders.transformer import (
    POOLINGS,
    TRANSFORMER_DEFAULTS,
    positional_index,
)
from gym_continuousDoubleAuction.train.model.model_handler import (
    build_trainable_module_spec,
)

#: Every encoder, fixtures included: all of them must meet the contract.
ALL_ENCODERS = [MLP_ENCODER_TYPE] + sorted(ENCODER_REGISTRY)

#: The ones a config file may actually select.
SHIPPED_ENCODERS = [
    e for e in ALL_ENCODERS if not e.startswith("_") and e != MLP_ENCODER_TYPE
]


@pytest.fixture(scope="module")
def spaces():
    env = continuousDoubleAuctionEnv({})
    agent_id = env.agents[0]
    return env.get_observation_space(agent_id), env.get_action_space(agent_id)


def build_module(spaces, encoder_type, spec=None, **kwargs):
    obs_space, act_space = spaces
    module_spec = build_trainable_module_spec(
        obs_space,
        act_space,
        encoder_type=encoder_type,
        encoder_specs={encoder_type: spec} if spec else {},
        **kwargs,
    )
    module_spec.module_class = DefaultPPOTorchRLModule
    return module_spec.build()


def sample_batch(obs_space, n=4, seed=0):
    rng = np.random.default_rng(seed)
    obs_space.seed(int(rng.integers(1 << 30)))
    return {Columns.OBS: torch.from_numpy(np.stack([obs_space.sample() for _ in range(n)]))}


# --- The contract, for every encoder ----------------------------------------

@pytest.mark.parametrize("encoder_type", ALL_ENCODERS)
class TestEveryEncoder:
    def test_produces_usable_policy_and_value_outputs(self, spaces, encoder_type):
        obs_space, _ = spaces
        module = build_module(spaces, encoder_type)
        batch = sample_batch(obs_space)

        out = module.forward_train(batch)
        values = module.compute_values(batch)

        assert out[Columns.ACTION_DIST_INPUTS].shape[0] == 4
        assert tuple(values.shape) == (4,)
        assert torch.isfinite(out[Columns.ACTION_DIST_INPUTS]).all()
        assert torch.isfinite(values).all()

    def test_inference_forward_works(self, spaces, encoder_type):
        """The rollout path, which is a different method from the train one."""
        obs_space, _ = spaces
        module = build_module(spaces, encoder_type)

        out = module.forward_inference(sample_batch(obs_space))

        assert torch.isfinite(out[Columns.ACTION_DIST_INPUTS]).all()

    def test_state_round_trips(self, spaces, encoder_type):
        """Checkpointing and champion snapshots both depend on this."""
        obs_space, _ = spaces
        source = build_module(spaces, encoder_type)
        target = build_module(spaces, encoder_type)
        batch = sample_batch(obs_space)

        target.set_state(source.get_state())

        assert torch.allclose(
            source.forward_train(batch)[Columns.ACTION_DIST_INPUTS],
            target.forward_train(batch)[Columns.ACTION_DIST_INPUTS],
        )
        assert torch.allclose(
            source.compute_values(batch), target.compute_values(batch)
        )

    @pytest.mark.parametrize("vf_share_layers", [False, True])
    def test_vf_share_layers_is_honoured(self, spaces, encoder_type, vf_share_layers):
        module = build_module(
            spaces, encoder_type, vf_share_layers=vf_share_layers
        )

        has_critic = getattr(module.encoder, "critic_encoder", None) is not None
        assert has_critic is (not vf_share_layers)

    def test_non_inference_attributes_contract(self, spaces, encoder_type):
        module = build_module(spaces, encoder_type, vf_share_layers=False)

        assert module.get_non_inference_attributes() == [
            "vf",
            "encoder.critic_encoder",
        ]

    def test_eval_forward_is_deterministic(self, spaces, encoder_type):
        """PPO's ratio compares a rollout log-prob against a recomputed one.

        Any nondeterminism in the forward pass - a live dropout being the usual
        culprit - shows up as noise in that ratio rather than as an error.
        """
        obs_space, _ = spaces
        module = build_module(spaces, encoder_type)
        module.eval()
        batch = sample_batch(obs_space)

        first = module.forward_train(batch)[Columns.ACTION_DIST_INPUTS]
        second = module.forward_train(batch)[Columns.ACTION_DIST_INPUTS]

        assert torch.equal(first, second)

    def test_gradients_reach_the_encoder(self, spaces, encoder_type):
        """An encoder detached from the loss would train silently as a constant."""
        obs_space, _ = spaces
        module = build_module(spaces, encoder_type)
        batch = sample_batch(obs_space)

        module.forward_train(batch)[Columns.ACTION_DIST_INPUTS].sum().backward()

        encoder_grads = [
            p.grad for name, p in module.named_parameters()
            if name.startswith("encoder.") and "critic" not in name
        ]
        assert encoder_grads, f"{encoder_type} exposed no actor-side encoder params"
        assert any(g is not None and g.abs().sum() > 0 for g in encoder_grads)


@pytest.mark.parametrize("encoder_type", SHIPPED_ENCODERS)
def test_every_shipped_encoder_has_a_config_block(encoder_type):
    """A spec block is the signal that an encoder is implemented, so it must
    exist for anything a config file can name."""
    specs = group("train_config.json", "encoder")["encoder_specs"]

    assert encoder_type in specs, (
        f"{encoder_type!r} is selectable but has no encoder_specs block in "
        "train_config.json."
    )


@pytest.mark.parametrize("encoder_type", SHIPPED_ENCODERS)
def test_config_block_keys_are_all_recognised(spaces, encoder_type):
    """The shipped defaults must be exactly what the builder accepts."""
    specs = group("train_config.json", "encoder")["encoder_specs"]

    build_module(spaces, encoder_type, spec=specs[encoder_type])


# --- Transformer specifics ---------------------------------------------------

class TestTransformer:
    ENCODER = "transformer"

    @pytest.mark.parametrize("tokenization", TOKENIZATIONS)
    def test_every_tokenization_builds_and_runs(self, spaces, tokenization):
        obs_space, _ = spaces
        module = build_module(
            spaces, self.ENCODER, spec={"tokenization": tokenization}
        )

        out = module.forward_train(sample_batch(obs_space))

        assert torch.isfinite(out[Columns.ACTION_DIST_INPUTS]).all()

    @pytest.mark.parametrize("pool", POOLINGS)
    def test_every_pooling_builds_and_runs(self, spaces, pool):
        obs_space, _ = spaces
        module = build_module(spaces, self.ENCODER, spec={"pool": pool})

        out = module.forward_train(sample_batch(obs_space))

        assert torch.isfinite(out[Columns.ACTION_DIST_INPUTS]).all()

    def test_unknown_pool_raises(self, spaces):
        with pytest.raises(ValueError, match="Unknown pool"):
            build_module(spaces, self.ENCODER, spec={"pool": "median"})

    def test_unknown_spec_key_raises(self, spaces):
        """A misspelled knob must not be silently ignored."""
        with pytest.raises(ValueError, match="Unknown key"):
            build_module(spaces, self.ENCODER, spec={"d_modle": 64})

    def test_num_heads_must_divide_d_model(self, spaces):
        with pytest.raises(ValueError, match="divisible"):
            build_module(spaces, self.ENCODER, spec={"d_model": 100, "num_heads": 8})

    def test_latent_width_is_d_model(self, spaces):
        """The encoder/head agreement: a wrong latent would not build at all."""
        module = build_module(spaces, self.ENCODER, spec={"d_model": 64})
        encoder = module.encoder.actor_encoder

        assert encoder.config.output_dims == (64,)

    def test_input_layernorm_is_present(self, spaces):
        """Not a knob. Without it attention collapses - see the module docstring."""
        module = build_module(spaces, self.ENCODER)
        encoder = module.encoder.actor_encoder

        assert isinstance(encoder.norm_in, nn.LayerNorm)

    def test_num_layers_is_respected(self, spaces):
        module = build_module(spaces, self.ENCODER, spec={"num_layers": 3})

        assert len(module.encoder.actor_encoder.blocks) == 3

    def test_zero_layers_raises(self, spaces):
        with pytest.raises(ValueError, match="num_layers"):
            build_module(spaces, self.ENCODER, spec={"num_layers": 0})

    def test_shipped_default_has_no_dropout(self):
        """Dropout corrupts PPO's ratio; the shipped value must stay 0."""
        specs = group("train_config.json", "encoder")["encoder_specs"]

        assert TRANSFORMER_DEFAULTS["dropout"] == 0.0
        assert specs["transformer"]["dropout"] == 0.0


class TestPositionalIndex:
    """The two-axis encoding has to match the order `tokenize` emits."""

    @pytest.fixture(scope="class")
    @classmethod
    def layout(cls):
        env = continuousDoubleAuctionEnv({})
        return ObsLayout.from_obs_space(
            env.get_observation_space(env.agents[0])
        )

    @pytest.mark.parametrize("tokenization", TOKENIZATIONS)
    def test_index_length_matches_the_token_count(self, layout, tokenization):
        num_tokens, _ = token_shape(layout, tokenization)
        time_idx, level_idx = positional_index(layout, tokenization)

        assert len(time_idx) == num_tokens
        assert len(level_idx) == num_tokens

    def test_both_is_time_major(self, layout):
        """Token t*(k_rows+1)+level must carry time t and level `level`."""
        stride = layout.k_rows + 1
        time_idx, level_idx = positional_index(layout, "both")

        for t in range(layout.n_hist):
            for level in range(stride):
                i = t * stride + level
                assert int(time_idx[i]) == t
                assert int(level_idx[i]) == level

    def test_time_tokenization_has_no_level_axis(self, layout):
        time_idx, level_idx = positional_index(layout, "time")

        assert list(time_idx) == list(range(layout.n_hist))
        assert int(level_idx.max()) == 0

    def test_level_tokenization_has_no_time_axis(self, layout):
        time_idx, level_idx = positional_index(layout, "level")

        assert int(time_idx.max()) == 0
        assert list(level_idx) == list(range(layout.k_rows + 1))
