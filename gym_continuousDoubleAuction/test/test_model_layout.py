"""The model-layout contract (`train/model/layout.py`).

Code outside the model, Continual Backprop included, finds a trunk's output
layer and the heads that read it through `trunk_outputs` instead of this
repository's attribute paths. These tests pin what it returns for every
encoder, so renaming a trunk, a head or the LSTM attribute fails here rather
than silently in a package that relies on it.
"""

import pytest
import torch.nn as nn

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.train.model.encoders import ENCODER_REGISTRY, MLP_ENCODER_TYPE
from gym_continuousDoubleAuction.train.model.layout import TrunkOutput, trunk_outputs
from gym_continuousDoubleAuction.train.model.model_handler import build_trainable_module_spec
from gym_continuousDoubleAuction.train.model.moe_learner import CDAPPOTorchRLModule

#: (trunk name, MLP path, LSTM path, head paths) per encoder and `vf_share_layers`.
#: Transformer-style trunks end in pooling and a LayerNorm, so they report none.
EXPECTED = {
    ("mlp", False): [
        ("actor_encoder", "encoder.actor_encoder.net.mlp", None, ["pi"]),
        ("critic_encoder", "encoder.critic_encoder.net.mlp", None, ["vf"]),
    ],
    ("mlp", True): [("encoder", "encoder.encoder.net.mlp", None, ["pi", "vf"])],
    ("lstm", False): [
        ("actor_encoder", None, "encoder.actor_encoder.lstm", ["pi"]),
        ("critic_encoder", None, "encoder.critic_encoder.lstm", ["vf"]),
    ],
    ("lstm", True): [("encoder", None, "encoder.encoder.lstm", ["pi", "vf"])],
}

ENCODERS = [MLP_ENCODER_TYPE] + sorted(ENCODER_REGISTRY)


@pytest.fixture(scope="module")
def spaces():
    env = continuousDoubleAuctionEnv({})
    agent_id = env.agents[0]
    return env.get_observation_space(agent_id), env.get_action_space(agent_id)


def _build(spaces, encoder_type, share):
    spec = build_trainable_module_spec(*spaces, encoder_type=encoder_type, vf_share_layers=share)
    if spec.module_class is None:
        spec.module_class = CDAPPOTorchRLModule
    return spec.build()


@pytest.mark.parametrize("share", [False, True], ids=["separate", "shared"])
@pytest.mark.parametrize("encoder_type", ENCODERS)
class TestTrunkOutputs:
    def test_every_encoder_reports_the_expected_trunks(self, spaces, encoder_type, share):
        module = _build(spaces, encoder_type, share)
        path = {id(m): name for name, m in module.named_modules()}
        got = [
            (t.name, t.mlp_path, t.lstm_path, [path[id(h)] for h in t.heads])
            for t in trunk_outputs(module)
        ]
        assert got == EXPECTED.get((encoder_type, share), [])

    def test_each_path_names_the_object_returned(self, spaces, encoder_type, share):
        module = _build(spaces, encoder_type, share)
        modules = dict(module.named_modules())
        for t in trunk_outputs(module):
            if t.mlp is not None:
                assert isinstance(t.mlp, nn.Sequential) and modules[t.mlp_path] is t.mlp
            if t.lstm is not None:
                assert isinstance(t.lstm, nn.LSTM) and modules[t.lstm_path] is t.lstm


def test_a_module_without_an_encoder_has_no_trunks():
    assert trunk_outputs(nn.Linear(2, 2)) == []


def test_a_trunk_output_defaults_to_nothing():
    assert TrunkOutput(name="encoder") == TrunkOutput(
        name="encoder",
        mlp=None,
        mlp_path=None,
        lstm=None,
        lstm_path=None,
        heads=[],
        extra_heads=[],
    )


class TestExtraTrunkHeads:
    """A module mixin that adds a head reading a trunk's output declares it in
    `extra_trunk_heads`, so code that resets the trunk's units (Continual
    Backprop) resets that head's input weights too (#338)."""

    @staticmethod
    def _with_aux(spaces, share, declared):
        class AuxMixin:
            extra_trunk_heads = declared

            def setup(self):
                super().setup()
                self.aux_pi = nn.Linear(8, 3)

        spec = build_trainable_module_spec(
            *spaces, encoder_type=MLP_ENCODER_TYPE, vf_share_layers=share
        )
        spec.module_class = type("AuxModule", (AuxMixin, CDAPPOTorchRLModule), {})
        return spec.build()

    @pytest.mark.parametrize("share", [False, True], ids=["separate", "shared"])
    def test_a_declared_head_is_reported_on_its_trunk_only(self, spaces, share):
        declared = {"encoder": ("aux_pi",), "actor_encoder": ("aux_pi",)}
        module = self._with_aux(spaces, share, declared)
        got = {t.name: t.extra_heads for t in trunk_outputs(module)}
        actor = "encoder" if share else "actor_encoder"
        assert got.pop(actor) == [module.aux_pi]
        assert all(heads == [] for heads in got.values())

    def test_declarations_merge_across_the_mro(self):
        class Trunk(nn.Module):
            def __init__(self):
                super().__init__()
                self.net = nn.Module()
                self.net.mlp = nn.Sequential(nn.Linear(2, 8))

        class Base(nn.Module):
            extra_trunk_heads = {"actor_encoder": ("aux_pi",)}

            def __init__(self):
                super().__init__()
                self.encoder = nn.Module()
                self.encoder.actor_encoder = Trunk()
                self.aux_pi, self.aux_q = nn.Linear(8, 3), nn.Linear(8, 1)

        class Mixin:
            extra_trunk_heads = {"actor_encoder": ("aux_q", "aux_pi"), "critic_encoder": ("v",)}

        module = type("Both", (Mixin, Base), {})()
        (actor,) = trunk_outputs(module)
        # Each name once, nearest class first; a trunk the module lacks is skipped.
        assert actor.extra_heads == [module.aux_q, module.aux_pi]

    def test_a_module_that_declares_nothing_has_no_extra_heads(self, spaces):
        module = _build(spaces, MLP_ENCODER_TYPE, False)
        assert all(t.extra_heads == [] for t in trunk_outputs(module))
