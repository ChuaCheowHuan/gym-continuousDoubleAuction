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
from ray.rllib.core.models.base import ACTOR, ENCODER_OUT

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
from gym_continuousDoubleAuction.train.model.encoders import jepa as jepa_module
from gym_continuousDoubleAuction.train.model.encoders.jepa import (
    MASK_AXES,
    sample_mask,
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
from gym_continuousDoubleAuction.train.model.jepa_learner import (
    JEPA_AUX_LOSS,
    JEPA_WORLD_LOSS,
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


@pytest.fixture(scope="module")
def layout_for_spaces(spaces):
    """The shipped `ObsLayout`, for tests that work on the grid directly."""
    obs_space, _ = spaces
    return ObsLayout.from_obs_space(obs_space)


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
        """The base list for every encoder; an encoder may only *extend* it.

        `vf` and the critic encoder are training-only for all of them. An
        encoder that carries its own training-only submodules - `jepa`, whose
        EMA target trunk and predictor exist solely to compute the auxiliary
        loss - appends them, so an inference-only copy and every champion
        snapshot drop them rather than carrying a second encoder they never
        run.

        Asserted as prefix-plus-extension rather than as one fixed list,
        because a fixed list would make adding any such encoder look like a
        regression in every other one.
        """
        module = build_module(spaces, encoder_type, vf_share_layers=False)
        attributes = module.get_non_inference_attributes()

        base = ["vf", "encoder.critic_encoder"]
        assert attributes[: len(base)] == base

        extra = attributes[len(base):]
        if encoder_type != "jepa":
            assert extra == [], (
                f"{encoder_type} declared extra non-inference attributes "
                f"{extra}; only encoders with training-only submodules should."
            )
        else:
            # `world_model` is off by default, and a submodule that does not
            # exist must not be declared - `setup` would then try to delete it.
            assert extra == [
                "encoder.actor_encoder.target_trunk",
                "encoder.actor_encoder.predictor",
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

@pytest.mark.parametrize("encoder_type", SHIPPED_ENCODERS)
class TestEncodersReadTheGridAsAGrid:
    """No selectable encoder may be blind to the order of the book grid.

    doc/15 S2-10. The shipped `lstm` encoder was `tokenize -> Linear ->
    LayerNorm -> mean`, and a mean of per-token linear projections is a linear
    function of the token *sum*: permutation-invariant across both axes.
    Measured on the real observation space, permuting the book levels moved its
    latent by 1.8e-07 and reversing time by 1.2e-07 - float32 noise. Its 44 book
    tokens collapsed to their per-field mean before anything nonlinear, so the
    encoder discarded exactly the structure its own docstring says it preserves,
    and any lstm-vs-transformer comparison was measuring something else.

    The `encoder` group exists to answer "which architecture reads this market
    better". An architecture that cannot see where a level sits, or which
    snapshot came first, is not answering it - so this belongs in the contract
    every encoder meets rather than in one encoder's own tests.

    Note what *does not* catch this: positional embeddings alone. Under a linear
    projection and a mean they are an input-independent constant and the
    invariance survives them untouched. Only a comparison of latents can tell.
    """

    def _latent(self, module, obs_space, obs):
        """The actor latent for one observation, stateful module or not.

        A stateful module takes `(B, T, obs)` and a STATE_IN tree, so the
        observation is repeated across the time axis rather than reshaped -
        a recurrent encoder must be covered by this contract too, and it is the
        one the finding is about.
        """
        batch = sample_batch(obs_space, n=1, module=module)
        if module.is_stateful():
            batch[Columns.OBS] = obs.unsqueeze(1).expand(
                1, batch[Columns.OBS].shape[1], obs.shape[-1]
            ).contiguous()
        else:
            batch[Columns.OBS] = obs

        out = module.encoder(batch)
        latent = out[ENCODER_OUT]
        return latent[ACTOR] if isinstance(latent, dict) else latent

    def _observation(self, obs_space):
        return torch.from_numpy(np.stack([obs_space.sample()]))

    def test_permuting_book_levels_changes_the_latent(self, spaces, encoder_type):
        obs_space, _ = spaces
        module = build_module(spaces, encoder_type)
        module.eval()
        layout = ObsLayout.from_obs_space(obs_space)

        obs = self._observation(obs_space)
        shuffled = obs.clone()
        permutation = torch.randperm(layout.k_rows)
        for snapshot in range(layout.n_hist):
            base = snapshot * layout.snapshot_dim
            for field in range(layout.book_rows):
                start = base + field * layout.k_rows
                row = shuffled[0, start:start + layout.k_rows]
                shuffled[0, start:start + layout.k_rows] = row[permutation]

        with torch.no_grad():
            before = self._latent(module, obs_space, obs)
            after = self._latent(module, obs_space, shuffled)

        assert float((before - after).abs().max()) > 1e-4, (
            f"{encoder_type} is invariant to the order of the book's levels"
        )

    def test_reversing_the_history_changes_the_latent(self, spaces, encoder_type):
        obs_space, _ = spaces
        module = build_module(spaces, encoder_type)
        module.eval()
        layout = ObsLayout.from_obs_space(obs_space)
        if layout.n_hist < 2:
            pytest.skip("a one-frame stack has no time order to destroy")

        obs = self._observation(obs_space)
        reversed_obs = obs.clone()
        snapshots = [
            obs[0, i * layout.snapshot_dim:(i + 1) * layout.snapshot_dim].clone()
            for i in range(layout.n_hist)
        ]
        for i, snapshot in enumerate(reversed(snapshots)):
            reversed_obs[0, i * layout.snapshot_dim:(i + 1) * layout.snapshot_dim] = snapshot

        with torch.no_grad():
            before = self._latent(module, obs_space, obs)
            after = self._latent(module, obs_space, reversed_obs)

        assert float((before - after).abs().max()) > 1e-4, (
            f"{encoder_type} is invariant to the order of the history stack"
        )


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

    @pytest.mark.parametrize("num_layers", [1, 2, 4])
    @pytest.mark.parametrize("vf_share_layers", [False, True])
    def test_aux_loss_does_not_scale_with_the_stack(
        self, spaces, num_layers, vf_share_layers
    ):
        """`aux_loss_coeff` must mean the same thing whatever the stack is.

        The term is averaged over MoE blocks, not summed. Summed - which is
        what Switch Transformer does, and what this did first - it scales with
        `num_layers` and doubles when `vf_share_layers` is false, since the
        critic's blocks route separately and count too. A coefficient tuned at
        one depth would then apply different pressure at another, silently, and
        comparing MoE configs of different depths would confound depth with how
        hard the gate was pushed.

        The floor is `top_k`, reached at perfectly uniform routing, so an
        untrained gate sits just above it in every configuration.
        """
        obs_space, _ = spaces
        module = build_module(
            spaces, self.ENCODER,
            spec={"num_layers": num_layers, "top_k": 2},
            vf_share_layers=vf_share_layers,
        )

        out = module.forward_train(sample_batch(obs_space, module=module))

        assert float(out[MOE_AUX_LOSS].detach()) == pytest.approx(2.0, abs=0.5)

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


# --- JEPA --------------------------------------------------------------------

class TestJEPA:
    """The latent-prediction objective and the collapse metrics.

    What is worth pinning is not that it runs - `TestEveryEncoder` covers the
    encoder contract for it automatically - but the handful of properties that
    decide whether the objective is doing anything: that the policy latent is
    unaffected by masking, that the loss carries gradient to the online trunk
    and *not* to the EMA target, and that a collapse is visible in a metric
    rather than only in a loss that reads as success.
    """

    def test_the_policy_latent_ignores_the_mask(self, spaces):
        """The agent acts on everything it was given.

        Masking exists only for the auxiliary loss. If it reached the policy
        latent, the agent would be acting on a random subset of the book and
        PPO's ratio would compare log-probs computed under different masks.
        """
        obs_space, _ = spaces
        module = build_module(spaces, "jepa")
        batch = sample_batch(obs_space, n=6, module=module)

        module.train()
        with torch.no_grad():
            first = module.encoder(batch)[ENCODER_OUT][ACTOR]
            second = module.encoder(batch)[ENCODER_OUT][ACTOR]

        # Two training forwards draw two different masks; the latent must not
        # move between them.
        assert torch.allclose(first, second, atol=1e-6)

    def test_the_objective_runs_only_in_train_mode(self, spaces):
        """`eval()` must produce no stats at all.

        Mask sampling is stochastic, so an objective that ran on the inference
        path would put noise into PPO's ratio rather than raise - the failure
        `test_eval_forward_is_deterministic` exists to catch.
        """
        obs_space, _ = spaces
        module = build_module(spaces, "jepa")
        batch = sample_batch(obs_space, n=4, module=module)
        encoder = module.encoder.actor_encoder

        module.eval()
        with torch.no_grad():
            module.encoder(batch)
        assert encoder.take_jepa_stats() is None

        module.train()
        module.encoder(batch)
        assert encoder.take_jepa_stats() is not None

    def test_the_aux_loss_reaches_fwd_out_and_carries_gradient(self, spaces):
        obs_space, _ = spaces
        module = build_module(spaces, "jepa")
        module.train()
        out = module._forward_train(sample_batch(obs_space, n=6, module=module))

        assert JEPA_AUX_LOSS in out
        assert out[JEPA_AUX_LOSS].requires_grad

        out[JEPA_AUX_LOSS].backward()
        trunk = module.encoder.actor_encoder.trunk
        assert any(
            p.grad is not None and p.grad.abs().sum() > 0
            for p in trunk.parameters()
        ), "the online trunk took no gradient from the objective"

    def test_the_target_trunk_takes_no_gradient(self, spaces):
        """It is an EMA copy, not a trained one. If it learned by gradient it
        would stop being a lagging target, and the asymmetry that discourages
        collapse would be gone."""
        obs_space, _ = spaces
        module = build_module(spaces, "jepa")
        module.train()
        out = module._forward_train(sample_batch(obs_space, n=6, module=module))
        out[JEPA_AUX_LOSS].backward()

        target = module.encoder.actor_encoder.target_trunk
        assert all(not p.requires_grad for p in target.parameters())
        assert all(p.grad is None for p in target.parameters())

    def test_the_target_trails_the_online_trunk(self, spaces):
        """One EMA step per training forward, and it must actually move."""
        obs_space, _ = spaces
        module = build_module(spaces, "jepa")
        encoder = module.encoder.actor_encoder

        # Push the online trunk somewhere the target is not.
        with torch.no_grad():
            for parameter in encoder.trunk.parameters():
                parameter.add_(1.0)

        before = next(encoder.target_trunk.parameters()).clone()
        module.train()
        module.encoder(sample_batch(obs_space, n=4, module=module))
        after = next(encoder.target_trunk.parameters())

        assert not torch.equal(before, after), "the target never moved"
        # It trails: one step of decay 0.996 closes 0.4% of a gap of 1.0.
        assert (after - before).abs().max() < 0.1

    def test_stats_are_cleared_when_taken(self, spaces):
        """Taking rather than reading. A stale auxiliary loss silently added to
        a later batch's gradient would be invisible; a None is not."""
        obs_space, _ = spaces
        module = build_module(spaces, "jepa")
        module.train()
        module.encoder(sample_batch(obs_space, n=4, module=module))

        encoder = module.encoder.actor_encoder
        assert encoder.take_jepa_stats() is not None
        assert encoder.take_jepa_stats() is None

    def test_collapse_is_visible_in_latent_std(self, spaces):
        """The metric that exists because the loss cannot tell.

        A collapsed JEPA maps every observation to the same latent, which makes
        the prediction *perfect* - loss near zero, which reads as success.
        `latent_std` goes to zero at the same time, and is the only signal that
        distinguishes the two.

        The collapse is forced on the ONLINE path, because that is what the
        statistic now measures. It used to be read off the no-grad `target`,
        which is doc/15 S2-9: a zeroed *target* trunk made the number fall
        while the thing being trained was perfectly healthy, and - worse - the
        hinge built from it carried no gradient at all.
        """
        obs_space, _ = spaces
        module = build_module(spaces, "jepa", spec={"ema_decay": 1.0})
        encoder = module.encoder.actor_encoder

        # A predictor whose weights are all zero emits the same vector for
        # every input, which is exactly what a collapsed online path does.
        with torch.no_grad():
            for parameter in encoder.predictor.parameters():
                parameter.zero_()

        module.train()
        module.encoder(sample_batch(obs_space, n=8, module=module))
        stats = encoder.take_jepa_stats()

        assert float(stats["latent_std"]) < 0.1, (
            "a collapsed encoder must show a near-zero latent_std"
        )
        # And the hinge pushes back, so the reported aux loss is NOT near zero
        # even though the prediction problem became trivial.
        assert float(stats["aux_loss"].detach()) > float(stats["predict_loss"])

    def test_the_variance_hinge_actually_carries_a_gradient(self, monkeypatch, spaces):
        """doc/15 S2-9, isolated so only the hinge can explain the result.

        The hinge was computed from `target`, built under `torch.no_grad()` by
        a trunk with `requires_grad_(False)`. `loss + coeff * penalty` still
        backpropagates - through `loss` - so nothing raised, and the term
        described everywhere as the only active defence against collapse was a
        constant.

        Asserting that "a gradient reaches the trunk" does not catch that: one
        reaches it from the prediction loss either way. So the same batch and
        the same mask are run twice, differing only in `variance_coeff`. If the
        hinge is in the graph the gradients must differ; if it is a constant
        they are identical, because a constant's derivative is zero however
        large the coefficient in front of it.

        `VARIANCE_TARGET` is raised so the hinge is off its `relu` floor on a
        healthy encoder. Collapsing the encoder instead would not do: the
        obvious way is to zero the predictor, and a zeroed predictor has a zero
        Jacobian back to the trunk.
        """
        monkeypatch.setattr(jepa_module, "VARIANCE_TARGET", 100.0)

        obs_space, _ = spaces
        # ema_decay 1.0 freezes the target, so the EMA step `_forward` takes
        # cannot make the second pass differ for a reason of its own.
        module = build_module(spaces, "jepa", spec={"ema_decay": 1.0})
        encoder = module.encoder.actor_encoder
        module.train()
        batch = sample_batch(obs_space, n=8, module=module)

        def gradients_with(coeff):
            encoder.variance_coeff = coeff
            # `sample_mask` draws from the global RNG, so re-seeding is what
            # makes the two passes see the same mask.
            torch.manual_seed(0)
            module.encoder(batch)
            stats = encoder.take_jepa_stats()
            encoder.zero_grad(set_to_none=True)
            stats["aux_loss"].backward()
            return (
                {
                    name: parameter.grad.clone()
                    for name, parameter in encoder.trunk.named_parameters()
                    if parameter.grad is not None
                },
                float(stats["aux_loss"].detach()),
                float(stats["predict_loss"]),
            )

        without, aux_off, predict_off = gradients_with(0.0)
        with_hinge, aux_on, _predict_on = gradients_with(50.0)

        assert without, "precondition: the prediction loss reaches the trunk"
        assert aux_off == pytest.approx(predict_off, rel=1e-6), (
            "precondition: at coeff 0 the aux loss is the prediction loss"
        )
        assert aux_on > aux_off, "precondition: the hinge is off its floor"

        assert any(
            not torch.allclose(without[name], with_hinge[name])
            for name in without
        ), (
            "the trunk's gradient is unchanged by variance_coeff, so the "
            "variance hinge is a constant again"
        )

    def test_the_target_branch_stays_detached(self, spaces):
        """The guard on the other side: gradients must not reach the target."""
        obs_space, _ = spaces
        module = build_module(spaces, "jepa", spec={"ema_decay": 1.0})
        encoder = module.encoder.actor_encoder

        module.train()
        module.encoder(sample_batch(obs_space, n=8, module=module))
        stats = encoder.take_jepa_stats()

        encoder.zero_grad(set_to_none=True)
        stats["aux_loss"].backward()

        assert all(
            parameter.grad is None or not torch.any(parameter.grad != 0)
            for parameter in encoder.target_trunk.parameters()
        ), "the target branch is an EMA copy and must never be trained"

    @pytest.mark.parametrize("mask_axis", MASK_AXES)
    def test_every_mask_axis_builds_and_runs(self, spaces, mask_axis):
        obs_space, _ = spaces
        module = build_module(spaces, "jepa", spec={"mask_axis": mask_axis})
        module.train()
        out = module._forward_train(sample_batch(obs_space, n=4, module=module))
        assert torch.isfinite(out[JEPA_AUX_LOSS])

    @pytest.mark.parametrize("mask_axis", MASK_AXES)
    def test_a_mask_never_hides_everything_or_nothing(self, layout_for_spaces, mask_axis):
        """An empty mask leaves the objective nothing to predict; a full one
        leaves the context encoder no input. Both are silent degeneracies."""
        layout = layout_for_spaces
        for ratio in (0.01, 0.5, 0.99):
            for tokenization in TOKENIZATIONS:
                total = token_shape(layout, tokenization)[0]
                masked = sample_mask(total, layout, tokenization, mask_axis, ratio)
                assert 0 < len(masked) < total, (tokenization, mask_axis, ratio)
                assert len(set(masked.tolist())) == len(masked), "duplicate indices"

    def test_an_out_of_range_mask_ratio_raises(self, spaces):
        for ratio in (0.0, 1.0, -0.1, 1.5):
            with pytest.raises(ValueError, match="mask_ratio"):
                build_module(spaces, "jepa", spec={"mask_ratio": ratio})

    def test_unknown_mask_axis_raises(self, spaces):
        with pytest.raises(ValueError, match="mask_axis"):
            build_module(spaces, "jepa", spec={"mask_axis": "diagonal"})

    def test_unknown_spec_key_raises(self, spaces):
        with pytest.raises(ValueError, match="Unknown key"):
            build_module(spaces, "jepa", spec={"mask_rate": 0.5})

    def test_a_dense_encoder_produces_no_jepa_loss(self, spaces):
        """The plumbing is inert for every other architecture."""
        obs_space, _ = spaces
        module = build_module(spaces, "transformer")
        module.train()
        out = module._forward_train(sample_batch(obs_space, n=4, module=module))
        assert JEPA_AUX_LOSS not in out


class TestJEPAWorldModel:
    """`z_hat_{t+1} = P(z_t, a_t)`, the action-conditioned term.

    Off by default, so most of what matters is that turning it on adds a term
    that reaches the loss - and that leaving it off, or running on a batch
    without `Columns.NEXT_OBS`, adds nothing rather than raising. PPO's batch
    carries no NEXT_OBS, so every path except the connector-fed training one
    has to keep working.
    """

    @staticmethod
    def _batch(obs_space, act_space, n=6, with_next=True):
        rng = np.random.default_rng(0)
        obs_space.seed(int(rng.integers(1 << 30)))
        act_space.seed(int(rng.integers(1 << 30)))

        batch = {
            Columns.OBS: torch.from_numpy(
                np.stack([obs_space.sample() for _ in range(n)])
            )
        }
        if with_next:
            batch[Columns.NEXT_OBS] = torch.from_numpy(
                np.stack([obs_space.sample() for _ in range(n)])
            )
            sampled = [act_space.sample() for _ in range(n)]
            batch[Columns.ACTIONS] = {
                key: torch.from_numpy(np.stack([a[key] for a in sampled]))
                for key in act_space.spaces
            }
        return batch

    def test_off_by_default(self, spaces):
        module = build_module(spaces, "jepa")
        assert module.encoder.actor_encoder.world_model is None

    def test_the_term_reaches_fwd_out_and_carries_gradient(self, spaces):
        obs_space, act_space = spaces
        module = build_module(spaces, "jepa", spec={"world_model": True})
        module.train()

        out = module._forward_train(self._batch(obs_space, act_space))

        assert JEPA_WORLD_LOSS in out
        assert out[JEPA_WORLD_LOSS].requires_grad

        out[JEPA_WORLD_LOSS].backward()
        world = module.encoder.actor_encoder.world_model
        assert any(
            p.grad is not None and p.grad.abs().sum() > 0
            for p in world.parameters()
        )

    def test_a_batch_without_next_obs_is_not_an_error(self, spaces):
        """PPO's own batch has none, and `compute_values` runs on one. Raising
        on a key PPO never promised would break every path but training."""
        obs_space, act_space = spaces
        module = build_module(spaces, "jepa", spec={"world_model": True})
        module.train()

        out = module._forward_train(
            self._batch(obs_space, act_space, with_next=False)
        )

        assert JEPA_WORLD_LOSS not in out
        # The masked objective still ran; only the world-model term is absent.
        assert JEPA_AUX_LOSS in out

    def test_the_target_takes_no_gradient(self, spaces):
        """The world model's target comes from the EMA trunk, same as the
        masked objective's. A gradient reaching it would end the asymmetry."""
        obs_space, act_space = spaces
        module = build_module(spaces, "jepa", spec={"world_model": True})
        module.train()

        out = module._forward_train(self._batch(obs_space, act_space))
        out[JEPA_WORLD_LOSS].backward()

        target = module.encoder.actor_encoder.target_trunk
        assert all(p.grad is None for p in target.parameters())

    def test_the_prediction_depends_on_the_action(self, spaces):
        """Otherwise it is not action-conditioned at all - it would be
        predicting the next book from the current one and ignoring what the
        agent did, which is a different and much less interesting model."""
        obs_space, act_space = spaces
        module = build_module(spaces, "jepa", spec={"world_model": True})
        module.eval()
        world = module.encoder.actor_encoder.world_model

        batch = self._batch(obs_space, act_space, n=4)
        latent = torch.zeros(4, module.encoder.actor_encoder.config.d_model)

        actions = batch[Columns.ACTIONS]
        other = dict(actions)
        # A different category is a different order type entirely.
        other["category"] = (actions["category"] + 1) % 9

        with torch.no_grad():
            assert not torch.allclose(
                world(latent, actions), world(latent, other)
            )

    def test_the_policy_latent_is_unchanged_by_it(self, spaces):
        """The world model is an auxiliary term, not a change to what the agent
        acts on."""
        obs_space, act_space = spaces
        plain = build_module(spaces, "jepa")
        with_world = build_module(spaces, "jepa", spec={"world_model": True})
        with_world.encoder.actor_encoder.trunk.load_state_dict(
            plain.encoder.actor_encoder.trunk.state_dict()
        )
        with_world.encoder.actor_encoder.pool.load_state_dict(
            plain.encoder.actor_encoder.pool.state_dict()
        )
        if plain.encoder.actor_encoder.private_token is not None:
            with_world.encoder.actor_encoder.private_token.load_state_dict(
                plain.encoder.actor_encoder.private_token.state_dict()
            )

        batch = self._batch(obs_space, act_space, n=4)
        plain.eval()
        with_world.eval()
        with torch.no_grad():
            assert torch.allclose(
                plain.encoder(batch)[ENCODER_OUT][ACTOR],
                with_world.encoder(batch)[ENCODER_OUT][ACTOR],
                atol=1e-6,
            )

    def test_an_action_space_missing_a_component_raises(self, spaces):
        """The space is config-derived, so it can change under this."""
        import gymnasium as gym

        obs_space, act_space = spaces
        trimmed = gym.spaces.Dict({
            k: v for k, v in act_space.spaces.items() if k != "price_offset"
        })
        with pytest.raises(ValueError, match="missing"):
            build_trainable_module_spec(
                obs_space, trimmed, encoder_type="jepa",
                encoder_specs={"jepa": {"world_model": True}},
            ).build()


class TestJEPAReviewRegressions:
    """Findings from the review of the branch that introduced this encoder.

    Each one built, trained and reported plausible numbers while being wrong,
    which is why they are pinned individually rather than left to the contract
    tests above.
    """

    def test_an_inference_only_module_builds(self, spaces):
        """Champions are inference-only copies, so this failed a `jepa` league
        at its first snapshot.

        Two causes, both silent. `get_non_inference_attributes` read
        `self.encoder` unguarded, and RLlib calls it from `__init__` before
        `setup()` has created it - `RLModuleSpec.build` catches AttributeError
        to fall back to a deprecated constructor, so the real error was
        swallowed and resurfaced as a complaint about `RLModuleConfig`. Then
        RLlib's own stripping loop, for a dotted path whose target *exists*,
        traverses to the leaf and calls `delattr` on the **module** rather than
        the leaf's parent.
        """
        obs_space, act_space = spaces
        spec = build_trainable_module_spec(
            obs_space, act_space, encoder_type="jepa"
        )
        spec.inference_only = True

        module = spec.build()
        encoder = module.encoder.actor_encoder
        for part in ("target_trunk", "predictor"):
            assert getattr(encoder, part, None) is None, part

    def test_the_world_model_is_declared_only_when_it_exists(self, spaces):
        """It is an attribute set to None when off, so `hasattr` alone would
        declare a submodule that is not there - and `setup` would then try to
        delete it."""
        off = build_module(spaces, "jepa", vf_share_layers=False)
        on = build_module(
            spaces, "jepa", spec={"world_model": True}, vf_share_layers=False
        )

        assert "encoder.actor_encoder.world_model" not in (
            off.get_non_inference_attributes()
        )
        assert "encoder.actor_encoder.world_model" in (
            on.get_non_inference_attributes()
        )

    def test_an_inference_only_module_is_smaller(self, spaces):
        """The point of declaring them: a champion should not carry a second
        encoder it never runs."""
        obs_space, act_space = spaces
        full = build_trainable_module_spec(
            obs_space, act_space, encoder_type="jepa",
            encoder_specs={"jepa": {"world_model": True}},
        ).build()

        spec = build_trainable_module_spec(
            obs_space, act_space, encoder_type="jepa",
            encoder_specs={"jepa": {"world_model": True}},
        )
        spec.inference_only = True
        stripped = spec.build()

        assert sum(p.numel() for p in stripped.parameters()) < 0.5 * sum(
            p.numel() for p in full.parameters()
        )

    def test_only_one_branch_runs_the_objective(self, spaces):
        """`vf_share_layers` is false by default, so the critic gets its own
        encoder - and only the actor's stats are ever collected. The critic's
        copy would run a mask pass, a target pass, the predictor and the world
        model on every training forward, have all of it discarded, and hold the
        autograd graph until the next forward overwrote it."""
        obs_space, _ = spaces
        module = build_module(spaces, "jepa", vf_share_layers=False)
        module.train()
        module._forward_train(sample_batch(obs_space, n=4, module=module))

        assert module.encoder.actor_encoder.objective_enabled
        assert not module.encoder.critic_encoder.objective_enabled
        assert module.encoder.critic_encoder._jepa_stats is None

    def test_evaluation_does_not_step_the_ema(self, spaces):
        """The objective only exists in train mode, so evaluating it runs in
        train mode too - under `no_grad`, with no optimiser step to follow. An
        EMA step there makes the trained weights a function of how often
        validation ran and how much data it covered."""
        obs_space, _ = spaces
        module = build_module(spaces, "jepa")
        encoder = module.encoder.actor_encoder
        module.train()
        batch = sample_batch(obs_space, n=4, module=module)

        before = next(encoder.target_trunk.parameters()).clone()
        with torch.no_grad():
            for _ in range(5):
                encoder(batch)
        assert torch.equal(before, next(encoder.target_trunk.parameters()))

        encoder(batch)
        assert not torch.equal(before, next(encoder.target_trunk.parameters()))

    @pytest.mark.parametrize("mask_axis", MASK_AXES)
    @pytest.mark.parametrize("n_hist", [1, 2, 3, 4])
    def test_a_mask_leaves_context_at_every_n_hist(self, mask_axis, n_hist):
        """`time` masking clamped against `n_hist - 1`, which bounds SNAPSHOTS
        and not tokens: at `n_hist` 1 it masked the whole sequence, leaving the
        context encoder no input. `n_hist: 1` is a setting the `lstm` block
        explicitly recommends, so it was reachable."""
        layout = ObsLayout(
            n_hist=n_hist, book_rows=4, k_rows=10, extra_dim=2, private_dim=9
        )
        for tokenization in TOKENIZATIONS:
            total = token_shape(layout, tokenization)[0]
            if total < 2:
                continue  # refused at construction; see the next test
            for ratio in (0.01, 0.5, 0.99):
                masked = sample_mask(
                    total, layout, tokenization, mask_axis, ratio
                )
                assert 0 < len(masked) < total, (
                    tokenization, mask_axis, ratio, len(masked), total
                )

    def test_a_single_token_sequence_is_refused(self, spaces):
        """One token cannot be both hidden and visible, so the contract
        `sample_mask` documents is unsatisfiable there. Refuse it at build
        rather than return a degenerate mask."""
        import gymnasium as gym

        _obs_space, act_space = spaces
        layout = group("tunable_constants.json", "observation_layout")
        snapshot = layout["book_rows"] * layout["k_rows"] + layout["extra_dim"]
        one_frame = gym.spaces.Box(
            -np.inf, np.inf,
            shape=(snapshot + layout["private_dim"],), dtype=np.float32,
        )

        with pytest.raises(ValueError, match="at least two"):
            build_trainable_module_spec(
                one_frame, act_space, encoder_type="jepa",
                encoder_specs={"jepa": {"tokenization": "time"}},
            ).build()
