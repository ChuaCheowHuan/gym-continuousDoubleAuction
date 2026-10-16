"""Issue #278: a stateful module's log-probability has the wrong shape when
two agents share it in one step.

RLlib's `TorchMultiDistribution.logp` squeezes a trailing 1 off a `Discrete`
value. For an `lstm` module run at inference the logits are `(B, 1, n)` and that
trailing 1 is the time axis, so `(B, 1)` becomes `(B,)` and broadcasts against
the distribution's `(B, 1)` batch shape to `(B, B)`.
"""

import pytest
import torch
from ray.rllib.core.distribution.torch.torch_distribution import (
    TorchCategorical,
    TorchDiagGaussian,
    TorchMultiDistribution,
)

from gym_continuousDoubleAuction.train.model.action_dist import time_rank_safe


def _multi(batch, time):
    """A Dict-like distribution: one Discrete head, one Box head."""
    shape = (batch, time) if time else (batch,)
    cat = TorchCategorical(logits=torch.zeros(*shape, 3))
    gauss = TorchDiagGaussian(loc=torch.zeros(*shape, 1), scale=torch.ones(*shape, 1))
    return TorchMultiDistribution([cat, gauss])


def _value(batch, time):
    shape = (batch, time) if time else (batch,)
    return [torch.zeros(*shape, dtype=torch.long), torch.zeros(*shape, 1)]


def _safe(batch, time):
    dist = _multi(batch, time)
    dist.__class__ = time_rank_safe(TorchMultiDistribution)
    return dist


class TestTheBugIsReal:
    def test_rllib_returns_a_square_for_two_agents_with_a_time_rank(self):
        """If this stops failing RLlib fixed it and `action_dist` can go."""
        logp = _multi(2, 1).logp(_value(2, 1))
        assert tuple(logp.shape) == (2, 2)


class TestTheSafeDistribution:
    @pytest.mark.parametrize("batch", [1, 2, 5])
    def test_a_time_rank_of_one_keeps_batch_and_time(self, batch):
        logp = _safe(batch, 1).logp(_value(batch, 1))
        assert tuple(logp.shape) == (batch, 1)

    @pytest.mark.parametrize("batch", [1, 2, 5])
    def test_no_time_rank_is_a_vector(self, batch):
        logp = _safe(batch, 0).logp(_value(batch, 0))
        assert tuple(logp.shape) == (batch,)

    def test_a_training_sequence_is_batch_by_time(self):
        logp = _safe(4, 20).logp(_value(4, 20))
        assert tuple(logp.shape) == (4, 20)

    def test_values_are_the_sum_of_the_heads(self):
        d = _safe(2, 1)
        v = _value(2, 1)
        expected = d._flat_child_distributions[0].logp(v[0]) + d._flat_child_distributions[1].logp(
            v[1]
        ).reshape(2, 1)
        assert torch.allclose(d.logp(v), expected.reshape(2, 1))

    def test_the_old_squeeze_case_still_works(self):
        """A `(B, 1)` value for a `(B,)` batch is the case the RLlib line is for."""
        cat = TorchCategorical(logits=torch.zeros(4, 3))
        d = TorchMultiDistribution([cat])
        d.__class__ = time_rank_safe(TorchMultiDistribution)
        out = d.logp([torch.zeros(4, 1, dtype=torch.long)])
        assert tuple(out.shape) == (4,)


class TestTheWrapper:
    def test_it_is_cached(self):
        assert time_rank_safe(TorchMultiDistribution) is time_rank_safe(TorchMultiDistribution)

    def test_it_is_idempotent(self):
        once = time_rank_safe(TorchMultiDistribution)
        assert time_rank_safe(once) is once

    def test_it_keeps_the_name(self):
        assert time_rank_safe(TorchMultiDistribution).__name__ == "TorchMultiDistribution"

    def test_another_distribution_is_left_alone(self):
        assert time_rank_safe(TorchCategorical) is TorchCategorical

    def test_a_non_class_is_left_alone(self):
        assert time_rank_safe(None) is None
