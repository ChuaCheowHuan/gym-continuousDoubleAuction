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
SHIPPED_ENCODERS = [e for e in ALL_ENCODERS if not e.startswith("_") and e != MLP_ENCODER_TYPE]


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

    obs = np.stack([[obs_space.sample() for _ in range(seq_len)] for _ in range(n)])
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
        assert torch.allclose(source.compute_values(batch), target.compute_values(batch))

    @pytest.mark.parametrize("vf_share_layers", [False, True])
    def test_vf_share_layers_is_honoured(self, spaces, encoder_type, vf_share_layers):
        module = build_module(spaces, encoder_type, vf_share_layers=vf_share_layers)

        has_critic = getattr(module.encoder, "critic_encoder", None) is not None
        assert has_critic is (not vf_share_layers)

    def test_non_inference_attributes_contract(self, spaces, encoder_type):
        """The base list for every encoder; an encoder may only *extend* it.

        `vf` and the critic encoder are training-only for all of them. An
        encoder that carries its own training-only submodules - cda-jepa's
        `jepa`, whose EMA target trunk and predictor exist solely to compute the
        auxiliary loss - appends them, so an inference-only copy and every champion
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

        extra = attributes[len(base) :]
        assert extra == [], (
            f"{encoder_type} declared extra non-inference attributes "
            f"{extra}; only encoders with training-only submodules should."
        )

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
            p.grad
            for name, p in module.named_parameters()
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
        f"{encoder_type!r} is selectable but has no encoder_specs block in train_config.json."
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

    docs/29 S2-10. The shipped `lstm` encoder was `tokenize -> Linear ->
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
            batch[Columns.OBS] = (
                obs.unsqueeze(1).expand(1, batch[Columns.OBS].shape[1], obs.shape[-1]).contiguous()
            )
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
                row = shuffled[0, start : start + layout.k_rows]
                shuffled[0, start : start + layout.k_rows] = row[permutation]

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
            obs[0, i * layout.snapshot_dim : (i + 1) * layout.snapshot_dim].clone()
            for i in range(layout.n_hist)
        ]
        for i, snapshot in enumerate(reversed(snapshots)):
            reversed_obs[0, i * layout.snapshot_dim : (i + 1) * layout.snapshot_dim] = snapshot

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
        module = build_module(spaces, self.ENCODER, spec={"tokenization": tokenization})

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
        return ObsLayout.from_obs_space(env.get_observation_space(env.agents[0]))

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
        module = build_module(spaces, self.ENCODER, spec={"hidden_dim": 64, "num_layers": 2})

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
        perturbed[Columns.STATE_IN] = tree.map_structure(lambda t: t + 1.0, batch[Columns.STATE_IN])
        shifted = module.forward_train(perturbed)[Columns.ACTION_DIST_INPUTS]

        assert not torch.allclose(zeroed, shifted)

    def test_tokenizer_is_the_structured_one(self, spaces):
        """The whole point of the structured LSTM: the per-step embedding reads
        the book grid rather than the raw flat observation."""
        from gym_continuousDoubleAuction.train.model.encoders.token_embed import (
            TorchTokenEmbedEncoder,
        )

        module = build_module(spaces, self.ENCODER)

        assert isinstance(module.encoder.actor_encoder.tokenizer, TorchTokenEmbedEncoder)

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

        gate_grads = [p.grad for name, p in module.named_parameters() if ".gate." in name]
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

    #: `top_k` for the aux-loss tests, and the term's mathematical floor: the
    #: routing fractions sum to `top_k`, so uniform load gives exactly this.
    TOP_K = 2

    def test_aux_loss_does_not_scale_with_the_stack(self, spaces):
        """`aux_loss_coeff` must mean the same thing whatever the stack is.

        The term is averaged over MoE blocks, not summed (`moe_learner.py`,
        `torch.stack(aux_terms).mean()`). Summed - which is what Switch
        Transformer does, and what this did first - it scales with `num_layers`
        and doubles when `vf_share_layers` is false, since the critic's blocks
        route separately and count too. A coefficient tuned at one depth would
        then apply different pressure at another, silently, and comparing MoE
        configs of different depths would confound depth with how hard the gate
        was pushed.

        **Why this compares configurations instead of checking a band.** It
        used to be parametrised over the six (depth, sharing) combinations with
        `approx(2.0, abs=0.5)` asserted independently in each - an absolute band
        around the floor, on a quantity set by the *unseeded* random
        initialisation of the gate. That is flaky by construction, and it duly
        failed in CI at 2.566. Measured over 1,500 unseeded builds the term has
        mean 2.14 and reaches past 2.5 about once in 1,500, worst at
        `num_layers=1` where there are fewest blocks to average over. It is not
        a regression from any particular change: at the commit before the
        observation layout grew, the same measurement gave a *higher* rate
        (4 of 600 draws past 2.5) and a maximum of 2.694.

        The band was also the wrong instrument. The claim in the docstring is
        that the value does not move *across* configurations, and that is what
        is asserted now: the six are built from one seed and compared with each
        other. Summing gives a ratio near 8 against a measured spread of 1.03 -
        1.06, so this is a far sharper test than the band ever was, and it is
        deterministic.
        """
        obs_space, _ = spaces

        losses = {}
        for vf_share_layers in (False, True):
            for num_layers in (1, 2, 4):
                # Seeded so the assertion is about the architecture rather than
                # about which weights this process happened to draw; forked so
                # the suite's global stream is left where it was found, since
                # other tests rely on it varying.
                with torch.random.fork_rng(devices=[]):
                    torch.manual_seed(0)
                    module = build_module(
                        spaces,
                        self.ENCODER,
                        spec={"num_layers": num_layers, "top_k": self.TOP_K},
                        vf_share_layers=vf_share_layers,
                    )
                    out = module.forward_train(sample_batch(obs_space, module=module))
                losses[(num_layers, vf_share_layers)] = float(out[MOE_AUX_LOSS].detach())

        lowest = min(losses.values())
        highest = max(losses.values())

        # The floor, which no routing can go below.
        assert lowest >= self.TOP_K, f"aux loss {lowest} is below the floor {self.TOP_K}: {losses}"
        # Near it, for an untrained gate. Summing would put even the
        # two-block case at ~4.3.
        assert highest < 1.5 * self.TOP_K, (
            f"aux loss {highest} is far above the floor {self.TOP_K}: {losses}"
        )
        # The property this test exists for. Summed, the deepest unshared
        # configuration is eight blocks against one and the ratio is ~8.
        assert highest / lowest < 1.25, (
            f"the aux loss varies {highest / lowest:.2f}x across the stack, so "
            f"it is not being averaged over blocks: {losses}"
        )

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
            spaces,
            "transformer",
            spec={"vf_share_layers": True},
            vf_share_layers=False,
        )

        assert getattr(module.encoder, "critic_encoder", None) is None

    def test_lr_override_is_reported_for_the_algorithm_config(self):
        assert training_overrides("transformer", {"lr": 3e-4}) == {"lr": 3e-4}

    def test_a_misspelled_common_key_still_raises(self, spaces):
        with pytest.raises(ValueError, match="Unknown key"):
            build_module(spaces, "transformer", spec={"learning_rate": 1e-4})
