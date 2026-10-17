"""JEPA's objective runs only where an optimiser step follows (issue #185).

With `vf_share_layers: true` the value-function pass PPO runs to compute advantages
(`compute_values`, in the learner connector) goes through the same JEPA encoder as the policy,
in training mode with gradients on. The encoder cannot tell it is not about to be optimised, so
it ran the whole mask-and-predict objective and took an EMA step of the target trunk: one more
EMA step per module per iteration than optimiser steps (8 against 6 over one measured
iteration), and a draw from the global torch RNG that shifted a seeded run's random stream.
"""

import itertools

import pytest
import torch

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.test.test_encoder_architectures import (
    build_module,
    sample_batch,
)
from gym_continuousDoubleAuction.train.model.encoders import jepa as jepa_module


@pytest.fixture(scope="module")
def spaces():
    env = continuousDoubleAuctionEnv({})
    agent = env.agents[0]
    return env.get_observation_space(agent), env.get_action_space(agent)


def _shared_module(spaces, **spec):
    module = build_module(spaces, "jepa", spec={"ema_decay": 0.9, **spec}, vf_share_layers=True)
    module.train()
    encoder = getattr(module.encoder, "encoder", None) or module.encoder.actor_encoder
    return module, encoder


def _target(encoder):
    return [p.detach().clone() for p in encoder.target_trunk.parameters()]


class TestTheValuePassDoesNotRunTheObjective:
    def test_it_takes_no_ema_step_even_with_gradients_on(self, spaces):
        module, encoder = _shared_module(spaces)
        batch = sample_batch(spaces[0], n=8, module=module)
        before = _target(encoder)

        module.compute_values(batch)  # grad enabled, training mode: as the connector calls it

        assert all(torch.equal(b, a) for b, a in zip(before, encoder.target_trunk.parameters()))

    def test_it_leaves_no_stats_for_the_next_loss_to_pick_up(self, spaces):
        module, encoder = _shared_module(spaces)
        module.compute_values(sample_batch(spaces[0], n=8, module=module))
        assert encoder.take_jepa_stats() is None

    def test_the_global_torch_rng_is_not_advanced(self, spaces):
        module, _ = _shared_module(spaces)
        batch = sample_batch(spaces[0], n=8, module=module)
        torch.manual_seed(123)
        before = torch.get_rng_state().clone()

        module.compute_values(batch)

        assert torch.equal(before, torch.get_rng_state())

    def test_the_objective_is_back_on_afterwards(self, spaces):
        module, encoder = _shared_module(spaces)
        module.compute_values(sample_batch(spaces[0], n=8, module=module))
        assert encoder.objective_enabled is True

    def test_and_back_on_if_the_pass_raises(self, spaces, monkeypatch):
        module, encoder = _shared_module(spaces)

        def boom(self, *a, **k):
            raise RuntimeError("boom")

        monkeypatch.setattr(type(module).__mro__[1], "compute_values", boom)
        with pytest.raises(RuntimeError):
            module.compute_values({})
        assert encoder.objective_enabled is True

    def test_a_training_forward_still_takes_exactly_one_ema_step(self, spaces, monkeypatch):
        module, encoder = _shared_module(spaces)
        calls = []
        original = jepa_module.TorchJEPAEncoder._update_target
        monkeypatch.setattr(
            jepa_module.TorchJEPAEncoder,
            "_update_target",
            lambda self: (calls.append(1), original(self))[1],
        )

        module._forward_train(sample_batch(spaces[0], n=8, module=module))

        assert len(calls) == 1


class TestMaskSamplingHasItsOwnGenerator:
    def test_a_training_forward_does_not_touch_the_global_rng(self, spaces):
        module, _ = _shared_module(spaces)
        batch = sample_batch(spaces[0], n=8, module=module)
        torch.manual_seed(7)
        before = torch.get_rng_state().clone()

        module._forward_train(batch)

        assert torch.equal(before, torch.get_rng_state())

    def test_the_masks_still_vary_from_forward_to_forward(self, spaces):
        _, encoder = _shared_module(spaces)
        draws = {
            tuple(
                jepa_module.sample_mask(
                    encoder._num_tokens,
                    encoder.layout,
                    encoder.tokenization,
                    encoder.mask_axis,
                    encoder.mask_ratio,
                    generator=encoder._mask_rng(),
                ).tolist()
            )
            for _ in range(20)
        }
        assert len(draws) > 1, "a generator that never advances would mask the same tokens forever"

    def test_a_fresh_process_with_the_same_seed_draws_the_same_masks(self, spaces, monkeypatch):
        """Modeled by resetting the per-process counter: same seed, same build order."""

        def first_mask():
            monkeypatch.setattr(jepa_module, "_MASK_STREAMS", itertools.count(1))
            torch.manual_seed(5)
            _, encoder = _shared_module(spaces)
            return jepa_module.sample_mask(
                encoder._num_tokens,
                encoder.layout,
                encoder.tokenization,
                encoder.mask_axis,
                encoder.mask_ratio,
                generator=encoder._mask_rng(),
            ).tolist()

        assert first_mask() == first_mask()

    def test_two_encoders_in_one_process_do_not_share_a_mask_stream(self, spaces):
        _, first = _shared_module(spaces)
        _, second = _shared_module(spaces)
        assert first._mask_rng().initial_seed() != second._mask_rng().initial_seed()
