"""Unit tests for Continual Backprop's algorithm core.

No `Algorithm` and no Ray: everything here works on a plain `nn.Module`, which
is what `cbp.py` importing no RLlib buys. The wiring claims - that the mixin
composes, that the state survives a checkpoint, that it runs inside a real PPO
update - are in `integration/test_cbp_wiring.py`.

What these pin, in the order the algorithm runs:

  * Layer discovery finds the trunk-to-head layer, and does not find the parts
    of the network gradient descent is not training.
  * Each of the three utility measures matches the paper's formula, computed by
    hand rather than by the implementation under test.
  * A replacement zeroes the outgoing weights, resamples the incoming ones, and
    resets the bookkeeping and the optimiser slots.
  * The accumulator is a fractional counter, which is the detail that decides
    whether anything is ever replaced at a realistic replacement rate.
"""
import math

import gymnasium as gym
import numpy as np
import pytest
import torch
import torch.nn as nn

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.train.model.cbp import (
    CBPConfig,
    CBPLayerState,
    ReplaceableLayer,
    activation_stats,
    bias_corrected,
    effective_rank,
    find_replaceable_layers,
    mature_fraction,
    plasticity_metrics,
    select_and_replace,
    update_utility,
)
from gym_continuousDoubleAuction.train.model.encoders import (
    ENCODER_REGISTRY,
    MLP_ENCODER_TYPE,
)
from gym_continuousDoubleAuction.train.model.model_handler import (
    build_trainable_module_spec,
)
from gym_continuousDoubleAuction.train.model.moe_learner import CDAPPOTorchRLModule


@pytest.fixture(scope="module")
def spaces():
    env = continuousDoubleAuctionEnv({})
    agent_id = env.agents[0]
    return env.get_observation_space(agent_id), env.get_action_space(agent_id)


def build_module(spaces, encoder_type=MLP_ENCODER_TYPE, **kwargs):
    obs_space, act_space = spaces
    spec = build_trainable_module_spec(
        obs_space, act_space, encoder_type=encoder_type, **kwargs
    )
    if spec.module_class is None:
        spec.module_class = CDAPPOTorchRLModule
    return spec.build()


def simple_block(fan_in=6, units=5, fan_out=3):
    """A bare `Linear -> Tanh -> Linear`, the shape the algorithm is defined on."""
    seq = nn.Sequential(nn.Linear(fan_in, units), nn.Tanh(), nn.Linear(units, fan_out))
    layer = ReplaceableLayer(
        name="block", incoming=seq[0], outgoing=[seq[2]], activation=seq[1]
    )
    return seq, layer


# --- Layer discovery --------------------------------------------------------

class TestLayerDiscovery:
    """What counts as a replaceable layer, on the real modules."""

    def test_default_network_has_two_layers_per_network(self, spaces):
        """Four layers: two hidden layers each for the policy and the value net.

        This is the regression test for the structural trap. The second hidden
        layer's *outgoing* weights live in the pi/vf head, not in the encoder,
        so a walker that only descends into `encoder` finds one layer per
        network instead of two and silently leaves half the units unreplaceable.
        """
        layers = find_replaceable_layers(build_module(spaces))
        assert len(layers) == 4

        by_name = {layer.name: layer for layer in layers}
        assert set(by_name) == {
            "encoder.actor_encoder.net.mlp.0",
            "encoder.actor_encoder.net.mlp.2",
            "encoder.critic_encoder.net.mlp.0",
            "encoder.critic_encoder.net.mlp.2",
        }
        assert all(layer.num_units == 256 for layer in layers)

    def test_the_last_hidden_layer_consumes_into_the_head(self, spaces):
        """The policy head has 26 outputs and the value head exactly 1."""
        by_name = {l.name: l for l in find_replaceable_layers(build_module(spaces))}

        actor = by_name["encoder.actor_encoder.net.mlp.2"]
        critic = by_name["encoder.critic_encoder.net.mlp.2"]
        assert [out.out_features for out in actor.outgoing] == [26]
        assert [out.out_features for out in critic.outgoing] == [1]

        # The first hidden layer's consumer is still inside the encoder.
        assert [o.out_features
                for o in by_name["encoder.actor_encoder.net.mlp.0"].outgoing] == [256]

    def test_a_shared_trunk_feeds_both_heads(self, spaces):
        """Under `vf_share_layers` one layer has two consumers, not one.

        The utility sums over both and a replacement zeroes both; getting this
        wrong would credit a unit for only half of what it contributes.
        """
        layers = find_replaceable_layers(
            build_module(spaces, vf_share_layers=True)
        )
        assert len(layers) == 2
        last = max(layers, key=lambda layer: layer.name)
        assert sorted(out.out_features for out in last.outgoing) == [1, 26]

    def test_frozen_layers_are_skipped(self, spaces):
        """The `jepa` encoder's EMA target trunk must not be replaceable.

        It is structurally identical to the trunk it mirrors, so discovery finds
        it; it is held under stop-gradient and updated by EMA, so replacing a
        unit there would break the EMA relationship and never be undone, because
        nothing updates it by gradient descent.
        """
        module = build_module(spaces, encoder_type="jepa")
        names = [layer.name for layer in find_replaceable_layers(module)]

        assert names, "the jepa encoder should still contribute its own blocks"
        assert not any("target_trunk" in name for name in names)
        assert any("trunk" in name for name in names)

    @pytest.mark.parametrize(
        "encoder_type", [MLP_ENCODER_TYPE] + sorted(ENCODER_REGISTRY)
    )
    def test_discovery_runs_on_every_encoder(self, spaces, encoder_type):
        """Discovery must never raise, whatever the architecture.

        Finding nothing is a legitimate answer - the `lstm` encoder has no
        two-Linear feed-forward block at all - but raising would take down any
        run that enabled continual backprop with that encoder selected.
        """
        layers = find_replaceable_layers(build_module(spaces, encoder_type))
        for layer in layers:
            assert layer.num_units == layer.incoming.out_features
            assert all(
                out.in_features == layer.num_units for out in layer.outgoing
            )

    def test_an_unknown_scope_raises(self, spaces):
        with pytest.raises(ValueError, match="Unknown scope"):
            find_replaceable_layers(build_module(spaces), scope="everything")


# --- Config -----------------------------------------------------------------

class TestConfig:

    def test_rejects_unknown_settings(self):
        for field, value, message in (
            ("utility", "made_up", "Unknown utility"),
            ("scope", "made_up", "Unknown scope"),
            ("fire_on", "made_up", "Unknown fire_on"),
            ("utility_decay", 1.0, "utility_decay"),
            ("replacement_rate", -1.0, "replacement_rate"),
            ("maturity_threshold", -1, "maturity_threshold"),
        ):
            with pytest.raises(ValueError, match=message):
                CBPConfig(**{field: value})

    def test_from_dict_reads_the_prefixed_keys(self):
        config = CBPConfig.from_dict(
            {"cbp_enabled": True, "cbp_replacement_rate": 0.5, "unrelated": 1}
        )
        assert config.enabled and config.replacement_rate == 0.5

    def test_metrics_only_measures_without_replacing(self):
        config = CBPConfig(enabled=True, metrics_only=True)
        assert config.active and not config.replaces

    def test_off_is_entirely_inert(self):
        assert not CBPConfig().active and not CBPConfig().replaces


# --- The utility measures ---------------------------------------------------

class TestUtility:
    """Each formula against a hand-computed value, not against itself."""

    def setup_method(self):
        torch.manual_seed(0)
        self.seq, self.layer = simple_block()
        self.state = CBPLayerState.zeros(self.layer.num_units)
        self.h = torch.randn(8, self.layer.num_units)

    def _stats(self, config):
        return activation_stats(self.h, self.state, config)

    def test_contribution_utility_matches_nature_equation_1(self):
        config = CBPConfig(utility="contribution", utility_decay=0.5)
        stats = self._stats(config)

        expected_instant = self.h.abs().mean(0) * self.layer.outgoing[0].weight.abs().sum(0)
        corrected = update_utility(self.state, self.layer, stats, config)

        # One step from zero: u = (1 - decay) * instantaneous, then the bias
        # correction divides by (1 - decay^1), which is the same (1 - decay).
        torch.testing.assert_close(self.state.utility, 0.5 * expected_instant)
        torch.testing.assert_close(corrected, expected_instant)

    def test_mean_corrected_subtracts_the_running_mean(self):
        config = CBPConfig(utility="mean_corrected", utility_decay=0.5)
        # A non-zero history, so f_hat is not trivially zero.
        self.state.mean_act = torch.full((self.layer.num_units,), 0.25)
        self.state.age = torch.full((self.layer.num_units,), 3, dtype=torch.long)

        f_hat = bias_corrected(self.state.mean_act, self.state.age, 0.5)
        stats = self._stats(config)
        torch.testing.assert_close(
            stats["dev_abs_mean"], (self.h - f_hat).abs().mean(0)
        )

        expected = stats["dev_abs_mean"] * self.layer.outgoing[0].weight.abs().sum(0)
        update_utility(self.state, self.layer, stats, config)
        # utility = decay * 0 + (1 - decay) * expected
        torch.testing.assert_close(self.state.utility, 0.5 * expected)

    def test_overall_utility_divides_by_the_incoming_magnitude(self):
        """The adaptation term: a unit with small incoming weights adapts faster."""
        config = CBPConfig(utility="overall", utility_decay=0.5)
        stats = self._stats(config)

        expected = (
            stats["dev_abs_mean"]
            * self.layer.outgoing[0].weight.abs().sum(0)
            / self.layer.incoming.weight.abs().sum(1)
        )
        update_utility(self.state, self.layer, stats, config)
        torch.testing.assert_close(self.state.utility, 0.5 * expected)

    def test_outgoing_magnitude_sums_over_every_consumer(self):
        """A shared trunk's unit is credited for both heads, not one."""
        config = CBPConfig(utility="contribution", utility_decay=0.5)
        second = nn.Linear(self.layer.num_units, 2)
        shared = ReplaceableLayer(
            name="shared", incoming=self.layer.incoming,
            outgoing=[self.layer.outgoing[0], second], activation=self.layer.activation,
        )
        stats = self._stats(config)
        expected = stats["abs_mean"] * (
            shared.outgoing[0].weight.abs().sum(0)
            + shared.outgoing[1].weight.abs().sum(0)
        )
        update_utility(self.state, shared, stats, config)
        torch.testing.assert_close(self.state.utility, 0.5 * expected)

    def test_age_advances_before_the_utility_is_corrected(self):
        config = CBPConfig(utility_decay=0.9)
        update_utility(self.state, self.layer, self._stats(config), config)
        assert torch.all(self.state.age == 1)

    def test_bias_correction_leaves_age_zero_alone(self):
        """Age 0 has a zero denominator; those units have no estimate yet."""
        value = torch.tensor([1.0, 2.0])
        age = torch.tensor([0, 2])
        out = bias_corrected(value, age, 0.5)
        assert out[0] == 1.0
        assert out[1] == pytest.approx(2.0 / (1 - 0.25))


# --- Replacement ------------------------------------------------------------

class TestReplacement:

    def setup_method(self):
        torch.manual_seed(0)
        self.seq, self.layer = simple_block()
        self.state = CBPLayerState.zeros(self.layer.num_units)
        self.config = CBPConfig(
            enabled=True, replacement_rate=1.0, maturity_threshold=0
        )

    def _mature(self, ages=10):
        self.state.age = torch.full(
            (self.layer.num_units,), ages, dtype=torch.long
        )

    def test_replacement_zeroes_outgoing_and_resamples_incoming(self):
        self._mature()
        utility = torch.tensor([5.0, 0.1, 5.0, 5.0, 5.0])
        before_in = self.layer.incoming.weight.clone()

        replaced = select_and_replace(
            self.state, self.layer, utility, self.config
        )

        assert replaced == [1]
        assert torch.all(self.layer.outgoing[0].weight[:, 1] == 0.0)
        assert not torch.equal(self.layer.incoming.weight[1], before_in[1])
        # Every other unit is untouched.
        untouched = [0, 2, 3, 4]
        torch.testing.assert_close(
            self.layer.incoming.weight[untouched], before_in[untouched]
        )

    def test_resampled_weights_come_from_the_layers_init_distribution(self):
        """PyTorch's default `nn.Linear` init: U(+/- 1/sqrt(fan_in))."""
        self._mature()
        bound = 1.0 / math.sqrt(self.layer.incoming.in_features)
        select_and_replace(
            self.state, self.layer,
            torch.tensor([0.0, 5.0, 5.0, 5.0, 5.0]), self.config,
        )
        assert torch.all(self.layer.incoming.weight[0].abs() <= bound)
        assert self.layer.incoming.bias[0] == 0.0

    def test_the_replacement_injects_no_new_randomness(self):
        """The exact half of the guarantee.

        Once the outgoing weights are zero, the fresh random incoming weights
        are multiplied by zero and reach the output not at all. What *does* move
        the function is dropping the old unit's contribution, which nothing
        makes zero - it is bounded only by selecting minimum utility. See
        doc/16 section 16.13.
        """
        self._mature()
        x = torch.randn(16, self.layer.incoming.in_features)

        with torch.no_grad():
            self.layer.outgoing[0].weight[:, 2] = 0.0
        after_zeroing = self.seq(x).clone()

        select_and_replace(
            self.state, self.layer,
            torch.tensor([5.0, 5.0, 0.0, 5.0, 5.0]), self.config,
        )
        torch.testing.assert_close(self.seq(x), after_zeroing, rtol=0, atol=0)

    def test_replacement_resets_utility_age_and_mean(self):
        self._mature()
        self.state.utility.fill_(3.0)
        self.state.mean_act.fill_(3.0)
        select_and_replace(
            self.state, self.layer,
            torch.tensor([0.0, 5.0, 5.0, 5.0, 5.0]), self.config,
        )
        assert self.state.utility[0] == 0.0
        assert self.state.mean_act[0] == 0.0
        assert self.state.age[0] == 0

    def test_adam_moments_are_cleared_for_the_replaced_slices(self):
        """arXiv Algorithm 2: an inherited second moment keeps the unit dead."""
        self._mature()
        optimizer = torch.optim.Adam(self.seq.parameters(), lr=0.1)
        self.seq(torch.randn(4, self.layer.incoming.in_features)).sum().backward()
        optimizer.step()

        assert optimizer.state[self.layer.incoming.weight]["exp_avg_sq"].abs().sum() > 0

        select_and_replace(
            self.state, self.layer,
            torch.tensor([0.0, 5.0, 5.0, 5.0, 5.0]), self.config,
            optimizer=optimizer,
        )
        for key in ("exp_avg", "exp_avg_sq"):
            assert torch.all(optimizer.state[self.layer.incoming.weight][key][0] == 0)
            assert torch.all(
                optimizer.state[self.layer.outgoing[0].weight][key][:, 0] == 0
            )

    def test_optimizer_reset_can_be_switched_off(self):
        self._mature()
        optimizer = torch.optim.Adam(self.seq.parameters(), lr=0.1)
        self.seq(torch.randn(4, self.layer.incoming.in_features)).sum().backward()
        optimizer.step()
        config = CBPConfig(
            enabled=True, replacement_rate=1.0, maturity_threshold=0,
            reset_optimizer_state=False,
        )
        select_and_replace(
            self.state, self.layer,
            torch.tensor([0.0, 5.0, 5.0, 5.0, 5.0]), config, optimizer=optimizer,
        )
        assert optimizer.state[self.layer.incoming.weight]["exp_avg_sq"][0].abs().sum() > 0


class TestAccumulator:
    """The fractional counter, which decides whether anything ever fires."""

    def setup_method(self):
        torch.manual_seed(0)
        self.seq, self.layer = simple_block(units=5)
        self.state = CBPLayerState.zeros(5)
        self.state.age = torch.full((5,), 10, dtype=torch.long)
        self.utility = torch.arange(5, dtype=torch.float)

    def test_a_small_rate_replaces_nothing_until_the_counter_fills(self):
        """`rate * n` rounded to an integer would be 0 forever; it accumulates."""
        config = CBPConfig(enabled=True, replacement_rate=0.1, maturity_threshold=0)
        # 5 units * 0.1 = 0.5 per step, so nothing on the first step.
        assert select_and_replace(self.state, self.layer, self.utility, config) == []
        assert self.state.accumulator == pytest.approx(0.5)
        # 1.0 exactly is not > 1.0; the third step is the one that fires.
        assert select_and_replace(self.state, self.layer, self.utility, config) == []
        assert select_and_replace(self.state, self.layer, self.utility, config) == [0]
        assert self.state.accumulator == pytest.approx(0.5)

    def test_at_most_one_unit_is_replaced_per_step(self):
        """Nature Algorithm 1 says `If c > 1`, not `while` - the cap is the spec.

        5 units at a rate of 0.5 accumulates 2.5 in one step, which a `while`
        would spend on two replacements. The cap is what bounds how far a single
        optimiser step can move the function, which is what makes a replacement
        safe to run inside PPO's minibatch loop.
        """
        config = CBPConfig(enabled=True, replacement_rate=0.5, maturity_threshold=0)
        replaced = select_and_replace(self.state, self.layer, self.utility, config)
        assert len(replaced) == 1
        assert self.state.accumulator == pytest.approx(2.5 - 1.0)

    def test_immature_units_are_never_selected(self):
        """A just-replaced unit has zero utility and must still be protected."""
        config = CBPConfig(enabled=True, replacement_rate=1.0, maturity_threshold=5)
        self.state.age = torch.tensor([0, 10, 10, 10, 10])
        # Unit 0 has the lowest utility but is immature.
        for _ in range(3):
            replaced = select_and_replace(
                self.state, self.layer, self.utility, config
            )
            assert 0 not in replaced

    def test_nothing_happens_when_no_unit_is_mature(self):
        config = CBPConfig(enabled=True, replacement_rate=1.0, maturity_threshold=100)
        assert select_and_replace(self.state, self.layer, self.utility, config) == []
        assert self.state.accumulator == 0.0

    def test_metrics_only_never_replaces(self):
        config = CBPConfig(
            enabled=True, metrics_only=True, replacement_rate=1.0,
            maturity_threshold=0,
        )
        before = self.layer.outgoing[0].weight.clone()
        assert select_and_replace(self.state, self.layer, self.utility, config) == []
        torch.testing.assert_close(self.layer.outgoing[0].weight, before)

    def test_replacements_are_counted(self):
        """The metric that tells a working mechanism from one that never fired."""
        config = CBPConfig(enabled=True, replacement_rate=0.5, maturity_threshold=0)
        for _ in range(4):
            select_and_replace(self.state, self.layer, self.utility, config)
        assert self.state.replacements == 4


class TestDeterminism:
    """A seeded run must stay reproducible; `test_seeding.py` pins that."""

    def test_the_same_generator_gives_the_same_weights(self):
        config = CBPConfig(enabled=True, replacement_rate=1.0, maturity_threshold=0)
        results = []
        for _ in range(2):
            torch.manual_seed(0)
            seq, layer = simple_block()
            state = CBPLayerState.zeros(layer.num_units)
            state.age = torch.full((layer.num_units,), 10, dtype=torch.long)
            generator = torch.Generator().manual_seed(1234)
            select_and_replace(
                state, layer, torch.tensor([0.0, 5.0, 5.0, 5.0, 5.0]),
                config, generator=generator,
            )
            results.append(layer.incoming.weight[0].clone())
        torch.testing.assert_close(results[0], results[1])

    def test_replacement_does_not_disturb_the_global_stream(self):
        """A dedicated generator, so an otherwise seeded run does not diverge."""
        config = CBPConfig(enabled=True, replacement_rate=1.0, maturity_threshold=0)
        seq, layer = simple_block()
        state = CBPLayerState.zeros(layer.num_units)
        state.age = torch.full((layer.num_units,), 10, dtype=torch.long)

        torch.manual_seed(99)
        expected = torch.randn(3)

        torch.manual_seed(99)
        select_and_replace(
            state, layer, torch.tensor([0.0, 5.0, 5.0, 5.0, 5.0]), config,
            generator=torch.Generator().manual_seed(7),
        )
        torch.testing.assert_close(torch.randn(3), expected)


# --- State ------------------------------------------------------------------

class TestState:

    def test_round_trips(self):
        state = CBPLayerState.zeros(4)
        state.utility.fill_(1.5)
        state.age = torch.tensor([1, 2, 3, 4])
        state.accumulator = 0.75
        state.replacements = 9

        restored = CBPLayerState.zeros(4)
        restored.set_state(state.get_state())

        torch.testing.assert_close(restored.utility, state.utility)
        torch.testing.assert_close(restored.age, state.age)
        assert restored.accumulator == 0.75
        assert restored.replacements == 9


# --- Metrics ----------------------------------------------------------------

class TestMetrics:

    def test_effective_rank_of_a_rank_one_matrix_is_one(self):
        column = torch.randn(32, 1)
        assert effective_rank(column @ torch.randn(1, 8)) == 1

    def test_effective_rank_rises_with_independent_directions(self):
        torch.manual_seed(0)
        full = effective_rank(torch.randn(256, 16))
        collapsed = effective_rank(
            torch.randn(256, 2) @ torch.randn(2, 16)
        )
        assert collapsed < full

    def test_dead_and_saturated_fractions(self):
        seq, layer = simple_block(units=4)
        config = CBPConfig(dead_unit_threshold=0.1)
        # Two dead units, one saturated.
        h = torch.tensor([[0.0, 0.01, 0.5, 0.95]]).repeat(4, 1)
        state = CBPLayerState.zeros(4)
        stats = activation_stats(h, state, config)
        metrics = plasticity_metrics(
            layer, stats, torch.zeros(4), config
        )
        assert metrics["dead_unit_frac"] == 0.5
        assert metrics["saturated_unit_frac"] == 0.25

    def test_mature_fraction_reports_a_mechanism_that_cannot_fire(self):
        """The metric that distinguishes 'no effect' from 'never ran'."""
        state = CBPLayerState.zeros(4)
        state.age = torch.tensor([1, 2, 300, 400])
        assert mature_fraction(state, CBPConfig(maturity_threshold=100)) == 0.5
        assert mature_fraction(state, CBPConfig(maturity_threshold=10_000)) == 0.0


class TestActivationStats:

    def test_a_time_major_batch_is_flattened_not_sliced(self):
        """A recurrent module gives (B, T, n); every row is an observation."""
        state = CBPLayerState.zeros(3)
        config = CBPConfig()
        h = torch.randn(2, 5, 3)
        stats = activation_stats(h, state, config)
        torch.testing.assert_close(stats["mean"], h.reshape(-1, 3).mean(0))

    def test_nothing_returned_carries_a_gradient(self):
        """The hook must not pin the autograd graph until the next forward."""
        seq, layer = simple_block()
        h = seq[:2](torch.randn(4, layer.incoming.in_features))
        assert h.requires_grad
        stats = activation_stats(h, CBPLayerState.zeros(5), CBPConfig())
        assert not any(value.requires_grad for value in stats.values())


# --- Device placement -------------------------------------------------------

class TestDevicePlacement:
    """State and RNG must live where the parameters live.

    None of this can be *executed* on a CPU-only box, which is the whole reason
    the bugs it covers shipped. What is checkable everywhere is the property
    that actually matters: that the device is derived from the module rather
    than defaulted, and that nothing hardcodes a CPU one. A meta-device module
    gives a non-CPU device to check against without needing a GPU.
    """

    def test_state_is_allocated_on_the_requested_device(self):
        state = CBPLayerState.zeros(4, device=torch.device("meta"))
        assert state.utility.device.type == "meta"
        assert state.mean_act.device.type == "meta"
        assert state.age.device.type == "meta"

    def test_the_learner_derives_the_device_from_the_weights(self):
        """`_cbp_attach` must read the device off the layer, not default it.

        The module is moved to the learner's device by `super().build()` before
        any of this runs, so the weight is authoritative. A default-constructed
        state would sit on the CPU while `h` arrived on CUDA, and
        `activation_stats`'s `h - f_hat` would raise on the first forward pass
        of every GPU run.
        """
        import inspect

        from gym_continuousDoubleAuction.train.model import cbp_learner

        source = inspect.getsource(cbp_learner.CBPLearnerMixin._cbp_attach)
        assert "device=layer.incoming.weight.device" in source, (
            "CBP state must be allocated on the layer's own device"
        )

    def test_the_generator_is_built_on_the_learners_device(self):
        """`uniform_` refuses a generator whose device type differs.

        A CPU generator on a CUDA run does not fail at build time - it fails
        the first time a replacement actually fires, tens of optimiser steps in.
        """
        import inspect

        from gym_continuousDoubleAuction.train.model import cbp_learner

        source = inspect.getsource(cbp_learner.CBPLearnerMixin.build)
        assert "torch.Generator(device=self._cbp_device())" in source

    def test_reinitialise_draws_onto_the_parameters_device(self):
        """The resampled row must be built from the weight, not from scratch."""
        import inspect

        from gym_continuousDoubleAuction.train.model import cbp

        source = inspect.getsource(cbp._reinitialise)
        # `empty_like` inherits device and dtype from the weight; `torch.empty`
        # or `torch.rand` with an explicit shape would not.
        assert "torch.empty_like(weight[index])" in source


class TestDDPUnwrapping:
    """Discovery must see through RLlib's DistributedDataParallel wrapper."""

    class _FakeDDP(nn.Module):
        """Stands in for `TorchDDPRLModule`.

        Same two properties that matter: the real module is a submodule named
        `module`, and no attribute forwarding is defined - so `wrapper.encoder`
        does not resolve, and `named_modules()` prefixes every name with
        `module.`.
        """

        def __init__(self, wrapped):
            super().__init__()
            self.module = wrapped

        def unwrapped(self):
            return self.module

    def test_a_wrapped_module_yields_the_same_layers(self, spaces):
        """Without unwrapping this drops the trunk-to-head layers silently.

        `_trunk_head_layers` reads `encoder`/`pi`/`vf` by attribute, which the
        wrapper does not forward, so it would return nothing and the default
        network would come back with 2 replaceable layers instead of 4 - half
        the mechanism, no error, and healthy-looking metrics.
        """
        module = build_module(spaces)
        plain = find_replaceable_layers(module)
        wrapped = find_replaceable_layers(self._FakeDDP(module))

        assert len(plain) == 4
        assert len(wrapped) == len(plain)

    def test_layer_names_are_unchanged_by_wrapping(self, spaces):
        """Names are checkpoint keys, so they must not depend on `num_learners`.

        `named_modules()` on the wrapper prefixes everything with `module.`. If
        that reached the state dict, a checkpoint from a single-learner run
        could not be restored into a distributed one, or the reverse.
        """
        module = build_module(spaces)
        plain = sorted(l.name for l in find_replaceable_layers(module))
        wrapped = sorted(l.name for l in find_replaceable_layers(self._FakeDDP(module)))

        assert wrapped == plain
        assert not any(name.startswith("module.") for name in wrapped)
