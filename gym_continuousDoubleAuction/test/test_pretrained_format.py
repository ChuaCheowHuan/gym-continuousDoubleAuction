"""The shared pretrained-encoder format, tested without cda_jepa.

cda_jepa used to carry these checks in its own `tests/test_pretrain.py`: the
fingerprint merge and the checkpoint writer/loader are gym-CDA code, so a change
here could break them only in another repository's CI (#28). This module pins
them against a test encoder that has a `pretrained_path` field but no
self-supervised objective, so the format is tested independently of the JEPA
encoder.
"""

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pytest
import torch

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.train.model.encoders import (
    encoder_fingerprint,
    encoder_settings,
    fingerprints_match,
    register,
)
from gym_continuousDoubleAuction.train.model.encoders.passthrough import (
    PASSTHROUGH_DEFAULTS,
    PassthroughEncoderConfig,
)
from gym_continuousDoubleAuction.train.model.encoders import pretrained
from gym_continuousDoubleAuction.train.model.model_handler import (
    build_trainable_module_spec,
)
from gym_continuousDoubleAuction.train.probe import features as features_module

TEST_ENCODER = "_pretrained_test"
SPEC = dict(PASSTHROUGH_DEFAULTS)


@dataclass
class _PretrainedPassthroughConfig(PassthroughEncoderConfig):
    """The passthrough fixture, plus the field the format looks for."""

    pretrained_path: Optional[str] = None


@register(TEST_ENCODER, defaults=PASSTHROUGH_DEFAULTS)
def _build(layout, spec: Dict[str, Any], input_dims: List[int]):
    settings = encoder_settings(TEST_ENCODER, spec)
    return _PretrainedPassthroughConfig(input_dims=input_dims, layout=layout, **settings)


@pytest.fixture(scope="module")
def spaces():
    env = continuousDoubleAuctionEnv({})
    agent_id = env.agents[0]
    return env.get_observation_space(agent_id), env.get_action_space(agent_id)


def _build_module(spaces, **kwargs):
    return build_trainable_module_spec(
        *spaces,
        encoder_type=TEST_ENCODER,
        encoder_specs={TEST_ENCODER: SPEC},
        **kwargs,
    ).build()


@pytest.fixture(scope="module")
def saved(spaces, tmp_path_factory):
    module = _build_module(spaces)
    path = str(tmp_path_factory.mktemp("pretrained-format"))
    pretrained.save(module, path, TEST_ENCODER, SPEC)
    return path, module


class TestTheFingerprintIdentifiesTheArchitecture:
    def test_none_and_the_config_block_agree(self):
        assert fingerprints_match(
            encoder_fingerprint(TEST_ENCODER, None),
            encoder_fingerprint(TEST_ENCODER, SPEC),
        )

    def test_omitting_a_key_at_its_default_still_matches(self):
        partial = {k: v for k, v in SPEC.items() if k != "latent_dim"}

        assert encoder_settings(TEST_ENCODER, partial) == encoder_settings(TEST_ENCODER, SPEC)
        assert fingerprints_match(
            encoder_fingerprint(TEST_ENCODER, partial),
            encoder_fingerprint(TEST_ENCODER, SPEC),
        )

    def test_a_real_change_still_does_not_match(self):
        assert not fingerprints_match(
            encoder_fingerprint(TEST_ENCODER, SPEC),
            encoder_fingerprint(TEST_ENCODER, {**SPEC, "latent_dim": 64}),
        )

    def test_a_defaulted_value_is_carried_in_the_hash(self):
        partial = {k: v for k, v in SPEC.items() if k != "latent_dim"}
        keys = dict(encoder_fingerprint(TEST_ENCODER, partial)["encoder_spec"])

        assert "latent_dim" in keys

    def test_an_unbuildable_spec_reports_a_mismatch_rather_than_raising(self):
        assert not fingerprints_match(
            encoder_fingerprint("transformer", SPEC),
            encoder_fingerprint(TEST_ENCODER, SPEC),
        )


class TestTheCheckpoint:
    def test_it_writes_all_three_pieces(self, saved):
        path, _module = saved
        assert os.path.isfile(os.path.join(path, pretrained.WEIGHTS_FILE))
        assert os.path.isfile(os.path.join(path, pretrained.FINGERPRINT_FILE))
        assert os.path.isdir(os.path.join(path, pretrained.MODULE_SUBDIR))

    def test_a_relative_path_writes_all_three_pieces(self, saved, tmp_path, monkeypatch):
        _path, module = saved
        monkeypatch.chdir(tmp_path)
        pretrained.save(module, os.path.join("pretrained", TEST_ENCODER), TEST_ENCODER, SPEC)
        written = tmp_path / "pretrained" / TEST_ENCODER
        assert (written / pretrained.WEIGHTS_FILE).is_file()
        assert (written / pretrained.FINGERPRINT_FILE).is_file()
        assert (written / pretrained.MODULE_SUBDIR).is_dir()

    def test_a_relative_module_path_loads(self, saved, monkeypatch):
        path, _module = saved
        monkeypatch.chdir(path)
        restored = features_module.load_module(pretrained.MODULE_SUBDIR, "policy_0")
        assert restored is not None

    def test_the_fingerprint_names_the_architecture(self, saved):
        path, _module = saved
        with open(os.path.join(path, pretrained.FINGERPRINT_FILE)) as handle:
            stored = json.load(handle)
        assert stored["encoder_type"] == TEST_ENCODER
        assert stored["encoder_spec"]["latent_dim"] == SPEC["latent_dim"]

    def test_loading_reproduces_the_weights(self, saved, spaces):
        path, source = saved
        target = _build_module(spaces)
        pretrained.load_into(target, path, TEST_ENCODER, SPEC)

        source_state = source.encoder.actor_encoder.state_dict()
        target_state = target.encoder.actor_encoder.state_dict()
        assert source_state.keys() == target_state.keys()
        assert all(torch.equal(source_state[key], target_state[key]) for key in source_state)

    def test_a_mismatched_architecture_is_refused(self, saved):
        path, _module = saved
        with pytest.raises(ValueError, match="does not match"):
            pretrained.verify_fingerprint(path, TEST_ENCODER, {**SPEC, "latent_dim": 64})

    def test_a_different_encoder_type_is_refused(self, saved):
        path, _module = saved
        with pytest.raises(ValueError, match="does not match"):
            pretrained.verify_fingerprint(path, "transformer", SPEC)

    def test_a_directory_that_is_not_a_checkpoint_raises(self, tmp_path):
        (tmp_path / "unrelated.txt").write_text("not a checkpoint")
        with pytest.raises(FileNotFoundError, match="not a pretrain checkpoint"):
            pretrained.verify_fingerprint(str(tmp_path), TEST_ENCODER, SPEC)


class TestThePathIsNotArchitecture:
    def test_it_stays_out_of_the_fingerprint(self, saved, spaces):
        path, _module = saved
        spec = build_trainable_module_spec(
            *spaces,
            encoder_type=TEST_ENCODER,
            encoder_specs={TEST_ENCODER: SPEC},
            pretrained_path=path,
        )
        assert "pretrained_path" not in spec.model_config.encoder_spec
        assert spec.model_config.pretrained_path == path

    def test_mlp_cannot_use_one(self, saved, spaces):
        path, _module = saved
        with pytest.raises(ValueError, match="no self-supervised objective"):
            build_trainable_module_spec(*spaces, encoder_type="mlp", pretrained_path=path)
