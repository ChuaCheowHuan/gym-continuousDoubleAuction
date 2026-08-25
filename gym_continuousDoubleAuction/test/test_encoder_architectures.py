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
import tree
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
    common_settings,
    training_overrides,
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
from gym_continuousDoubleAuction.train.model.moe_learner import (
    MOE_AUX_LOSS,
    MOE_EXPERT_FRACTIONS,
)

#: Time steps per sequence in a stateful forward batch. Arbitrary - RLlib pads
#: to max_seq_len in a real run, but a manual forward accepts any length.
SEQ_LEN = 3

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
    # Only the `mlp` path leaves module_class None, for RLlib to fill in from
    # the algorithm's default spec. Custom encoders set it themselves, and
    # overwriting that would silently swap CDAPPOTorchRLModule back out - taking
    # the MoE auxiliary loss with it.
    if module_spec.module_class is None:
        module_spec.module_class = DefaultPPOTorchRLModule
    return module_spec.build()


def sample_batch(obs_space, n=4, seed=0, module=None, seq_len=SEQ_LEN):
    """A forward batch shaped for `module`, stateful or not.

    A stateless module takes `(B, obs)`. A stateful one takes `(B, T, obs)` plus
    a `STATE_IN` tree, because RLlib's connectors add the time dimension and
    thread the recurrent state through - so a test that only ever builds the
    stateless shape silently cannot cover a recurrent encoder at all.
    """
    rng = np.random.default_rng(seed)
    obs_space.seed(int(rng.integers(1 << 30)))

    if module is None or not module.is_stateful():
        obs = np.stack([obs_space.sample() for _ in range(n)])
        return {Columns.OBS: torch.from_numpy(obs)}

    obs = np.stack(
        [[obs_space.sample() for _ in range(seq_len)] for _ in range(n)]
    )
    # Initial states come back unbatched; give every sequence its own copy.
    state_in = tree.map_structure(
        lambda s: s.unsqueeze(0).expand(n, *s.shape).contiguous(),
        module.get_initial_state(),
    )
    return {Columns.OBS: torch.from_numpy(obs), Columns.STATE_IN: state_in}


# --- The contract, for every encoder ----------------------------------------

@pytest.mark.parametrize("encoder_type", ALL_ENCODERS)
class TestEveryEncoder:
    def test_produces_usable_policy_and_value_outputs(self, spaces, encoder_type):
        obs_space, _ = spaces
        module = build_module(spaces, encoder_type)
        batch = sample_batch(obs_space, module=module)

        out = module.forward_train(batch)
        values = module.compute_values(batch)

        # A recurrent module keeps the time axis, so it emits one value per
        # (sequence, timestep) rather than one per row.
        expected_values = (4, SEQ_LEN) if module.is_stateful() else (4,)

        assert out[Columns.ACTION_DIST_INPUTS].shape[0] == 4
        assert tuple(values.shape) == expected_values
        assert torch.isfinite(out[Columns.ACTION_DIST_INPUTS]).all()
        assert torch.isfinite(values).all()

    def test_state_out_is_emitted_only_when_stateful(self, spaces, encoder_type):
        """A recurrent module must return the state the connectors carry
        forward; a stateless one must not pretend to have any."""
        obs_space, _ = spaces
        module = build_module(spaces, encoder_type)

        out = module.forward_train(sample_batch(obs_space, module=module))

        assert (Columns.STATE_OUT in out) is module.is_stateful()

    def test_inference_forward_works(self, spaces, encoder_type):
        """The rollout path, which is a different method from the train one."""
        obs_space, _ = spaces
        module = build_module(spaces, encoder_type)

        out = module.forward_inference(sample_batch(obs_space, module=module))

        assert torch.isfinite(out[Columns.ACTION_DIST_INPUTS]).all()

    def test_state_round_trips(self, spaces, encoder_type):
        """Checkpointing and champion snapshots both depend on this."""
        obs_space, _ = spaces
        source = build_module(spaces, encoder_type)
        target = build_module(spaces, encoder_type)
        batch = sample_batch(obs_space, module=source)

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
        batch = sample_batch(obs_space, module=module)

        first = module.forward_train(batch)[Columns.ACTION_DIST_INPUTS]
        second = module.forward_train(batch)[Columns.ACTION_DIST_INPUTS]

        assert torch.equal(first, second)

    def test_gradients_reach_the_encoder(self, spaces, encoder_type):
        """An encoder detached from the loss would train silently as a constant."""
        obs_space, _ = spaces
        module = build_module(spaces, encoder_type)
        batch = sample_batch(obs_space, module=module)

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


# --- LSTM specifics ----------------------------------------------------------

class TestLSTM:
    ENCODER = "lstm"

    def test_is_stateful(self, spaces):
        """Nothing else in this class means anything if this is False."""
        assert build_module(spaces, self.ENCODER).is_stateful()

    def test_gets_the_stateful_actor_critic_wrapper(self, spaces):
        """`ActorCriticEncoderConfig.build` dispatches on isinstance of
        `RecurrentEncoderConfig`, which is why the config derives from it
        rather than wrapping one."""
        module = build_module(spaces, self.ENCODER)

        assert type(module.encoder).__name__ == "TorchStatefulActorCriticEncoder"

    def test_inference_only_is_forced_off(self, spaces):
        """`DefaultPPORLModule.setup` does this for a recurrent base config.

        Without it the critic's states are never collected during sampling and
        `compute_values` has nothing to run on.
        """
        assert build_module(spaces, self.ENCODER).inference_only is False

    def test_actor_and_critic_have_separate_states(self, spaces):
        module = build_module(spaces, self.ENCODER, vf_share_layers=False)

        state = module.get_initial_state()

        assert set(state) == {"actor", "critic"}
        assert set(state["actor"]) == {"h", "c"}

    def test_initial_state_is_shaped_by_the_spec(self, spaces):
        module = build_module(
            spaces, self.ENCODER, spec={"hidden_dim": 64, "num_layers": 2}
        )

        h = module.get_initial_state()["actor"]["h"]

        assert tuple(h.shape) == (2, 64)

    def test_state_out_matches_state_in(self, spaces):
        """The connectors feed STATE_OUT back in as the next STATE_IN."""
        obs_space, _ = spaces
        module = build_module(spaces, self.ENCODER)
        batch = sample_batch(obs_space, module=module)

        state_out = module.forward_train(batch)[Columns.STATE_OUT]

        assert tree.map_structure(lambda t: tuple(t.shape), state_out) == (
            tree.map_structure(lambda t: tuple(t.shape), batch[Columns.STATE_IN])
        )

    def test_memory_actually_carries(self, spaces):
        """Different incoming state must change the output.

        An LSTM wired up so that STATE_IN never reached it would still train,
        still emit STATE_OUT, and simply have no memory - which no shape check
        would catch.
        """
        obs_space, _ = spaces
        module = build_module(spaces, self.ENCODER)
        module.eval()
        batch = sample_batch(obs_space, module=module)

        zeroed = module.forward_train(batch)[Columns.ACTION_DIST_INPUTS]
        perturbed = dict(batch)
        perturbed[Columns.STATE_IN] = tree.map_structure(
            lambda t: t + 1.0, batch[Columns.STATE_IN]
        )
        shifted = module.forward_train(perturbed)[Columns.ACTION_DIST_INPUTS]

        assert not torch.allclose(zeroed, shifted)

    def test_tokenizer_is_the_structured_one(self, spaces):
        """The whole point of the structured LSTM: the per-step embedding reads
        the book grid rather than the raw flat observation."""
        from gym_continuousDoubleAuction.train.model.encoders.token_embed import (
            TorchTokenEmbedEncoder,
        )

        module = build_module(spaces, self.ENCODER)

        assert isinstance(
            module.encoder.actor_encoder.tokenizer, TorchTokenEmbedEncoder
        )

    def test_max_seq_len_reaches_the_model_config(self, spaces):
        """It configures RLlib's connectors, not the encoder, so it has to be
        lifted out of the encoder spec onto the top-level model config."""
        obs_space, act_space = spaces
        spec = build_trainable_module_spec(
            obs_space,
            act_space,
            encoder_type=self.ENCODER,
            encoder_specs={self.ENCODER: {"max_seq_len": 7}},
        )

        assert spec.model_config.max_seq_len == 7

    def test_max_seq_len_defaults_even_when_the_spec_omits_it(self, spaces):
        """Merged against the encoder's declared defaults, not read raw, so an
        omitted key does not silently fall back to DefaultModelConfig's."""
        from gym_continuousDoubleAuction.train.model.encoders.lstm import (
            LSTM_DEFAULTS,
        )

        obs_space, act_space = spaces
        spec = build_trainable_module_spec(
            obs_space, act_space, encoder_type=self.ENCODER, encoder_specs={}
        )

        assert spec.model_config.max_seq_len == LSTM_DEFAULTS["max_seq_len"]

    def test_zero_layers_raises(self, spaces):
        with pytest.raises(ValueError, match="num_layers"):
            build_module(spaces, self.ENCODER, spec={"num_layers": 0})

    def test_unknown_spec_key_raises(self, spaces):
        with pytest.raises(ValueError, match="Unknown key"):
            build_module(spaces, self.ENCODER, spec={"hidden_size": 64})


# --- Mixture-of-experts specifics --------------------------------------------

class TestMoETransformer:
    ENCODER = "moe_transformer"

    def test_the_feedforward_is_a_mixture(self, spaces):
        from gym_continuousDoubleAuction.train.model.encoders.moe import (
            MoEFeedForward,
        )

        module = build_module(spaces, self.ENCODER)

        for block in module.encoder.actor_encoder.blocks:
            assert isinstance(block.ff, MoEFeedForward)

    def test_the_aux_loss_reaches_fwd_out(self, spaces):
        """`ActorCriticEncoder` drops every key but ENCODER_OUT, so the module
        has to collect the stats itself - this is what proves it does."""
        obs_space, _ = spaces
        module = build_module(spaces, self.ENCODER)

        out = module.forward_train(sample_batch(obs_space, module=module))

        assert MOE_AUX_LOSS in out
        assert torch.isfinite(out[MOE_AUX_LOSS])

    def test_the_aux_loss_carries_gradient(self, spaces):
        """It learns through the mean gate probability. Detached, it would be a
        logged number that trains nothing."""
        obs_space, _ = spaces
        module = build_module(spaces, self.ENCODER)

        out = module.forward_train(sample_batch(obs_space, module=module))
        out[MOE_AUX_LOSS].backward()

        gate_grads = [
            p.grad for name, p in module.named_parameters() if ".gate." in name
        ]
        assert gate_grads
        assert any(g is not None and g.abs().sum() > 0 for g in gate_grads)

    def test_routing_fractions_sum_to_top_k(self, spaces):
        """Each token is dispatched to exactly `top_k` experts."""
        obs_space, _ = spaces
        module = build_module(spaces, self.ENCODER, spec={"top_k": 2})

        out = module.forward_train(sample_batch(obs_space, module=module))

        assert float(out[MOE_EXPERT_FRACTIONS].sum()) == pytest.approx(2.0, abs=1e-4)

    def test_stats_are_cleared_when_taken(self, spaces):
        """Taking rather than reading: a stale aux loss silently added to a
        later batch would be invisible, a None is not.

        Driven through the encoder directly, because by the time
        `forward_train` returns the module has already taken them - which the
        next test is what pins.
        """
        obs_space, _ = spaces
        module = build_module(spaces, self.ENCODER)
        encoder = module.encoder.actor_encoder

        encoder(sample_batch(obs_space))

        assert encoder.take_moe_stats() is not None
        assert encoder.take_moe_stats() is None

    def test_the_module_consumes_the_stats_it_forwards(self, spaces):
        """Nothing may be left staged behind `forward_train`, or the next batch
        could pick up this one's auxiliary loss."""
        obs_space, _ = spaces
        module = build_module(spaces, self.ENCODER)

        module.forward_train(sample_batch(obs_space, module=module))

        assert module.encoder.actor_encoder.take_moe_stats() is None
        assert module.encoder.critic_encoder.take_moe_stats() is None

    def test_a_dense_encoder_produces_no_aux_loss(self, spaces):
        """The module and learner are wired unconditionally, so they must be
        inert for everything that is not an MoE."""
        obs_space, _ = spaces
        module = build_module(spaces, "transformer")

        out = module.forward_train(sample_batch(obs_space, module=module))

        assert MOE_AUX_LOSS not in out
        assert module.encoder.actor_encoder.take_moe_stats() is None

    def test_a_single_expert_raises(self, spaces):
        """A one-expert mixture is a dense feed-forward with a gate bolted on."""
        with pytest.raises(ValueError, match="num_experts"):
            build_module(spaces, self.ENCODER, spec={"num_experts": 1})

    def test_top_k_above_num_experts_raises(self, spaces):
        with pytest.raises(ValueError, match="top_k"):
            build_module(spaces, self.ENCODER, spec={"num_experts": 4, "top_k": 5})

    def test_num_experts_is_respected(self, spaces):
        module = build_module(spaces, self.ENCODER, spec={"num_experts": 6})

        assert len(module.encoder.actor_encoder.blocks[0].ff.experts) == 6

    def test_unknown_spec_key_raises(self, spaces):
        with pytest.raises(ValueError, match="Unknown key"):
            build_module(spaces, self.ENCODER, spec={"n_experts": 4})

    def test_balanced_routing_gives_the_minimum_aux_loss(self, spaces):
        """The term is minimised at uniform load, which is the only reason it
        pushes the gate away from collapse. Its floor is `top_k`."""
        from gym_continuousDoubleAuction.train.model.encoders.moe import (
            MoEFeedForward,
        )

        moe = MoEFeedForward(d_model=8, ff_dim=8, num_experts=4, top_k=2)
        # A gate with zero weights routes every token identically and uniformly.
        torch.nn.init.zeros_(moe.gate.weight)

        _, stats = moe(torch.randn(3, 5, 8))

        assert float(stats["aux_loss"].detach()) == pytest.approx(2.0, abs=1e-4)


# --- Common spec keys --------------------------------------------------------

class TestCommonSpecKeys:
    """`lr` and `vf_share_layers` are accepted in every encoder's spec block.

    Both defaults in the `ppo` group were chosen for the MLP. Holding an
    attention stack to a learning rate tuned for a 2x256 tanh net measures the
    learning rate rather than the architecture, and `vf_share_layers: false`
    doubles a transformer where it barely costs an MLP anything.
    """

    @pytest.mark.parametrize("encoder_type", SHIPPED_ENCODERS)
    def test_every_encoder_accepts_them(self, encoder_type):
        settings = common_settings(encoder_type, {"lr": 1e-4, "vf_share_layers": True})

        assert settings == {"lr": 1e-4, "vf_share_layers": True}

    @pytest.mark.parametrize("encoder_type", SHIPPED_ENCODERS)
    def test_unset_means_inherit(self, encoder_type):
        """Null must not override the ppo group with a None."""
        assert common_settings(encoder_type, {}) == {}
        assert training_overrides(encoder_type, {}) == {}

    def test_they_do_not_leak_into_the_encoder_config(self, spaces):
        """A builder splats its own settings, so a common key reaching it would
        be an unexpected keyword rather than a silent no-op."""
        module = build_module(spaces, "transformer", spec={"lr": 1e-4})

        assert not hasattr(module.encoder.actor_encoder.config, "lr")

    def test_vf_share_layers_override_takes_effect(self, spaces):
        """The ppo group ships false; an encoder setting true must win."""
        module = build_module(
            spaces, "transformer", spec={"vf_share_layers": True},
            vf_share_layers=False,
        )

        assert getattr(module.encoder, "critic_encoder", None) is None

    def test_lr_override_is_reported_for_the_algorithm_config(self):
        assert training_overrides("transformer", {"lr": 3e-4}) == {"lr": 3e-4}

    def test_a_misspelled_common_key_still_raises(self, spaces):
        with pytest.raises(ValueError, match="Unknown key"):
            build_module(spaces, "transformer", spec={"learning_rate": 1e-4})
