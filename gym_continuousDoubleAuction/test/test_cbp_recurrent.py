"""Continual Backprop on an LSTM core (docs/29 S3-32, docs/25 section 3.4).

The `lstm` encoder has no two-Linear block in it, so under the original
`feedforward` scope Continual Backprop found nothing to replace there and
`cbp_enabled` trained exactly like CBP off. The `recurrent` scope covers the
hidden units of the top LSTM layer.

What these pin, on a plain `nn.LSTM` plus a head Linear (no Ray, no RLlib):

  * which parameters are a unit's incoming weights and which its outgoing ones,
    since PyTorch scatters a unit's four gates across a stacked matrix;
  * that a replacement leaves the new unit inert, which is the property the
    whole mechanism rests on, checked on the *output* of the network and not
    only on the weights;
  * that the function moves only by the old unit's contribution being dropped;
  * that Adam's moments are cleared for exactly the entries that were reset.

And, on the real `lstm` module, that the discovery finds the right layers under
each scope and leaves every other encoder where it was.
"""

import pytest
import torch
import torch.nn as nn

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.test.test_cbp import build_module
from gym_continuousDoubleAuction.train.model.cbp import (
    SCOPES,
    CBPConfig,
    CBPLayerState,
    RecurrentLayer,
    find_replaceable_layers,
    select_and_replace,
    update_utility,
)
from gym_continuousDoubleAuction.train.model.cbp_learner import CBPLearnerMixin

H, N_IN, N_OUT, LAYERS = 4, 5, 3, 2


class TinyNet(nn.Module):
    """A two-layer LSTM and a head, the shape of the `lstm` encoder in small."""

    def __init__(self):
        super().__init__()
        self.lstm = nn.LSTM(N_IN, H, num_layers=LAYERS, batch_first=True)
        self.head = nn.Linear(H, N_OUT)

    def forward(self, x):
        out, _ = self.lstm(x)
        return self.head(out)


@pytest.fixture
def net():
    torch.manual_seed(0)
    return TinyNet()


@pytest.fixture
def layer(net):
    return RecurrentLayer("lstm", net.lstm, [net.head], layer_index=LAYERS - 1)


@pytest.fixture
def x():
    torch.manual_seed(1)
    return torch.randn(3, 6, N_IN)


def _rows(index):
    return [g * H + index for g in range(4)]


class TestWhichParametersAreAUnit:
    def test_a_unit_is_the_top_layers_hidden_unit(self, layer):
        assert layer.num_units == H
        assert layer.hook_target is layer.lstm

    def test_incoming_is_the_four_gate_rows_of_both_matrices(self, layer, net):
        ih = net.lstm.weight_ih_l1.detach().abs()
        hh = net.lstm.weight_hh_l1.detach().abs()
        for i in range(H):
            expected = ih[_rows(i)].sum() + hh[_rows(i)].sum()
            assert layer.incoming_abs_sum()[i] == pytest.approx(float(expected), rel=1e-5)

    def test_outgoing_is_the_recurrent_column_and_the_head_column(self, layer, net):
        hh = net.lstm.weight_hh_l1.detach().abs()
        head = net.head.weight.detach().abs()
        for i in range(H):
            expected = hh[:, i].sum() + head[:, i].sum()
            assert layer.outgoing_abs_sum()[i] == pytest.approx(float(expected), rel=1e-5)

    def test_the_lower_layer_is_not_covered(self, layer, net):
        """Only the top layer's activation is the module's output."""
        assert layer.layer_index == LAYERS - 1
        assert layer._p("weight_ih") is net.lstm.weight_ih_l1

    def test_a_bidirectional_lstm_is_refused(self):
        lstm = nn.LSTM(N_IN, H, bidirectional=True)
        with pytest.raises(ValueError, match="unidirectional"):
            RecurrentLayer("x", lstm, [nn.Linear(2 * H, 1)])


def _replace(layer, net, index, optimizer=None, seed=0):
    """Force a replacement of `index` and return the CBP state."""
    state = CBPLayerState.zeros(H)
    state.age[:] = 10
    state.accumulator = 2.0
    corrected = torch.full((H,), 5.0)
    corrected[index] = 0.0
    config = CBPConfig(enabled=True, scope="recurrent", maturity_threshold=1, replacement_rate=0.5)
    generator = torch.Generator().manual_seed(seed)
    replaced = select_and_replace(
        state, layer, corrected, config, generator=generator, optimizer=optimizer
    )
    assert replaced == [index]
    return state


class TestAReplacement:
    def test_outgoing_is_zeroed_and_incoming_resampled(self, layer, net):
        index = 2
        before_ih = net.lstm.weight_ih_l1.detach().clone()
        _replace(layer, net, index)

        assert torch.all(net.lstm.weight_hh_l1[:, index] == 0)
        assert torch.all(net.head.weight[:, index] == 0)
        for row in _rows(index):
            assert not torch.equal(net.lstm.weight_ih_l1[row], before_ih[row])
            assert net.lstm.bias_ih_l1[row] == 0 and net.lstm.bias_hh_l1[row] == 0
        bound = 1.0 / H**0.5
        assert net.lstm.weight_ih_l1[_rows(index)].abs().max() <= bound

    def test_no_other_unit_is_touched(self, layer, net):
        index = 1
        ih = net.lstm.weight_ih_l1.detach().clone()
        hh = net.lstm.weight_hh_l1.detach().clone()
        head = net.head.weight.detach().clone()
        _replace(layer, net, index)

        others = [i for i in range(H) if i != index]
        other_rows = [r for i in others for r in _rows(i)]
        assert torch.equal(net.lstm.weight_ih_l1[other_rows], ih[other_rows])
        # Other units' rows of weight_hh differ only in the replaced column.
        assert torch.equal(net.lstm.weight_hh_l1[other_rows][:, others], hh[other_rows][:, others])
        assert torch.equal(net.head.weight[:, others], head[:, others])

    def test_the_new_unit_is_inert(self, layer, net, x):
        """The property the mechanism rests on, on the network's output: with
        nothing reading `h_i`, resampling its incoming weights again changes
        nothing."""
        index = 2
        _replace(layer, net, index)
        out = net(x).detach().clone()

        with torch.no_grad():
            for row in _rows(index):
                net.lstm.weight_ih_l1[row] = torch.randn(H)
                net.lstm.weight_hh_l1[row, [j for j in range(H) if j != index]] = torch.randn(H - 1)

        assert torch.allclose(net(x), out, atol=1e-6)

    def test_the_function_moves_only_by_the_old_units_contribution(self, layer, net, x):
        """After a replacement the output equals the old network with that
        unit's outgoing weights zeroed: nothing else changed."""
        index = 0
        reference = TinyNet()
        reference.load_state_dict(net.state_dict())
        with torch.no_grad():
            reference.lstm.weight_hh_l1[:, index] = 0.0
            reference.head.weight[:, index] = 0.0
        _replace(layer, net, index)

        assert torch.allclose(net(x), reference(x), atol=1e-6)

    def test_age_utility_and_accumulator_are_reset(self, layer, net):
        index = 3
        state = CBPLayerState.zeros(H)
        state.age[:] = 10
        state.utility[:] = 1.0
        state.mean_act[:] = 1.0
        state.accumulator = 2.0
        corrected = torch.full((H,), 5.0)
        corrected[index] = 0.0
        select_and_replace(
            state,
            layer,
            corrected,
            CBPConfig(enabled=True, scope="recurrent", maturity_threshold=1, replacement_rate=0.5),
            generator=torch.Generator().manual_seed(0),
        )
        assert state.age[index] == 0 and state.utility[index] == 0
        assert state.mean_act[index] == 0 and state.age[0] == 10
        assert state.replacements == 1


class TestAdamIsToldWhatWasReset:
    def test_exactly_the_reset_entries_lose_their_moments(self, layer, net, x):
        index = 1
        optimizer = torch.optim.Adam(net.parameters(), lr=1e-3)
        net(x).sum().backward()
        optimizer.step()
        for slots in optimizer.state.values():
            for key in ("exp_avg", "exp_avg_sq"):
                slots[key].fill_(1.0)

        _replace(layer, net, index, optimizer=optimizer)

        ih = optimizer.state[net.lstm.weight_ih_l1]["exp_avg"]
        hh = optimizer.state[net.lstm.weight_hh_l1]["exp_avg"]
        bias = optimizer.state[net.lstm.bias_ih_l1]["exp_avg_sq"]
        head = optimizer.state[net.head.weight]["exp_avg_sq"]
        rows = _rows(index)
        others = [r for i in range(H) if i != index for r in _rows(i)]

        assert torch.all(ih[rows] == 0) and torch.all(ih[others] == 1)
        assert torch.all(hh[rows] == 0) and torch.all(hh[:, index] == 0)
        assert torch.all(hh[others][:, [j for j in range(H) if j != index]] == 1)
        assert torch.all(bias[rows] == 0) and torch.all(bias[others] == 1)
        assert torch.all(head[:, index] == 0)
        assert torch.all(head[:, [j for j in range(H) if j != index]] == 1)


class TestTheUtilityCountsTheRecurrentPath:
    def test_a_unit_only_the_recurrence_reads_is_not_worth_zero(self, layer, net):
        """Zero the head's column for unit 0: it is still read by the other
        units through `weight_hh`, so its utility is not 0."""
        with torch.no_grad():
            net.head.weight[:, 0] = 0.0
        state = CBPLayerState.zeros(H)
        stats = {"abs_mean": torch.ones(H), "dev_abs_mean": torch.ones(H), "mean": torch.zeros(H)}
        utility = update_utility(
            state, layer, stats, CBPConfig(enabled=True, utility="contribution")
        )
        assert utility[0] > 0


class TestTheHookSeesTheSequence:
    def test_an_lstm_returns_a_tuple_and_the_hook_takes_the_sequence(self, layer, net, x):
        mixin = CBPLearnerMixin.__new__(CBPLearnerMixin)
        mixin._cbp_config = CBPConfig(enabled=True, scope="recurrent")
        mixin._cbp_state = {"m": {layer.name: CBPLayerState.zeros(H)}}
        mixin._cbp_stats, mixin._cbp_activations, mixin._cbp_updates = {}, {}, 1
        handle = layer.hook_target.register_forward_hook(mixin._cbp_hook("m", layer))
        try:
            net(x)
        finally:
            handle.remove()

        stats = mixin._cbp_stats[("m", layer.name)]
        assert stats["abs_mean"].shape == (H,)
        assert not any(v.requires_grad for v in stats.values())


@pytest.fixture(scope="module")
def spaces():
    env = continuousDoubleAuctionEnv({})
    agent_id = env.agents[0]
    return env.get_observation_space(agent_id), env.get_action_space(agent_id)


class TestDiscoveryOnTheRealEncoders:
    def test_recurrent_is_a_scope_and_unknown_ones_are_refused(self):
        assert "recurrent" in SCOPES
        assert CBPConfig(scope="recurrent").scope == "recurrent"
        with pytest.raises(ValueError, match="Unknown scope"):
            CBPConfig(scope="attention")

    def test_the_lstm_encoder_has_nothing_under_feedforward(self, spaces):
        module = build_module(spaces, encoder_type="lstm")
        assert find_replaceable_layers(module, "feedforward") == []

    def test_separate_trunks_give_one_layer_each(self, spaces):
        module = build_module(spaces, encoder_type="lstm", vf_share_layers=False)
        layers = find_replaceable_layers(module, "recurrent")
        assert [layer.name for layer in layers] == [
            "encoder.actor_encoder.lstm",
            "encoder.critic_encoder.lstm",
        ]
        assert all(layer.num_units == 256 for layer in layers)
        assert [len(layer.outgoing) for layer in layers] == [1, 1]

    def test_a_shared_trunk_feeds_both_heads(self, spaces):
        module = build_module(spaces, encoder_type="lstm", vf_share_layers=True)
        (layer,) = find_replaceable_layers(module, "recurrent")
        assert layer.name == "encoder.encoder.lstm"
        assert len(layer.outgoing) == 2

    @pytest.mark.parametrize("encoder_type", ["mlp", "transformer", "moe_transformer"])
    def test_every_other_encoder_is_unchanged_by_the_scope(self, spaces, encoder_type):
        module = build_module(spaces, encoder_type=encoder_type)
        feedforward = [l.name for l in find_replaceable_layers(module, "feedforward")]
        recurrent = [l.name for l in find_replaceable_layers(module, "recurrent")]
        assert feedforward == recurrent and feedforward

    def test_the_hook_target_is_the_lstm_itself(self, spaces):
        module = build_module(spaces, encoder_type="lstm")
        for layer in find_replaceable_layers(module, "recurrent"):
            assert isinstance(layer.hook_target, nn.LSTM)
