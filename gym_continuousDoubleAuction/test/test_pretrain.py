"""Offline JEPA pretraining: the loop, the checkpoint, and the guard on it.

The loop itself is small - most of what pretraining needs already existed in
`train/probe/`. What is worth pinning is the part that is new and the part that
is easy to get quietly wrong:

  * the objective actually trains the encoder, and trains *only* the parts it
    should - never the EMA target, whose lagging is the anti-collapse mechanism;
  * a collapse is reported rather than shown as a falling loss, because a
    collapsed JEPA's loss falls all the way to zero;
  * the checkpoint's fingerprint refuses weights from a different architecture,
    which is the same guard `train.py` applies to a restore and for the same
    reason.
"""
import json
import os

import numpy as np
import pytest
import torch

from gym_continuousDoubleAuction.config_loader import group
from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.train import pretrain as pretrain_pkg
from gym_continuousDoubleAuction.train.model.model_handler import (
    build_trainable_module_spec,
)
from gym_continuousDoubleAuction.train.probe import corpus as corpus_module
from gym_continuousDoubleAuction.train.probe import probe as probe_module
from gym_continuousDoubleAuction.train.probe import features as features_module

#: Small enough to stay fast, long enough that the episode split has an episode
#: for train and one for validation.
EPISODES = 4
STEPS = 60


@pytest.fixture(scope="module")
def spaces():
    env = continuousDoubleAuctionEnv({})
    agent_id = env.agents[0]
    return env.get_observation_space(agent_id), env.get_action_space(agent_id)


@pytest.fixture(scope="module")
def spec_block():
    return group("train_config.json", "encoder")["encoder_specs"]["jepa"]


@pytest.fixture(scope="module")
def corpus():
    return corpus_module.from_rollouts(
        num_episodes=EPISODES, max_step=120, num_agents=3, seed=0
    )


@pytest.fixture(scope="module")
def trained(spaces, corpus, spec_block):
    """One short pretraining run, shared by the tests that only read it."""
    obs_space, act_space = spaces
    return pretrain_pkg.pretrain(
        corpus, obs_space, act_space, encoder_spec=spec_block,
        steps=STEPS, batch_size=64, log_every=STEPS // 2, seed=0,
    )


class TestTheLoop:
    def test_the_objective_falls(self, trained):
        _module, report = trained
        assert report.train_loss[-1] < report.train_loss[0]

    def test_it_generalises_to_held_out_episodes(self, trained):
        """The validation split is the only thing separating "the loss fell"
        from "the loss fell on rows it had memorised"."""
        _module, report = trained
        assert report.validation_loss[-1] < report.validation_loss[0]

    def test_the_split_is_by_episode(self, corpus):
        """Adjacent observations share three of their four snapshots, so a
        row-level split would put near-duplicates of a validation row into
        training and the validation curve would mean nothing."""
        train_mask, validation_mask, _ = probe_module.split_masks(
            corpus.episode_index, len(corpus)
        )
        train_episodes = set(corpus.episode_index[train_mask])
        validation_episodes = set(corpus.episode_index[validation_mask])
        assert train_episodes and validation_episodes
        assert not train_episodes & validation_episodes

    def test_only_the_trunk_and_predictor_are_trained(self, spaces, corpus,
                                                      spec_block):
        """The EMA target must move only by EMA. If a gradient reached it, it
        would stop lagging and the asymmetry that discourages collapse would be
        gone."""
        obs_space, act_space = spaces
        module, _report = pretrain_pkg.pretrain(
            corpus, obs_space, act_space, encoder_spec=spec_block,
            steps=10, batch_size=32, log_every=10, seed=0,
        )
        encoder = module.encoder.actor_encoder

        assert all(not p.requires_grad for p in encoder.target_trunk.parameters())
        assert all(p.grad is None for p in encoder.target_trunk.parameters())
        # And the parts that should train did take gradient.
        assert any(p.grad is not None for p in encoder.trunk.parameters())
        assert any(p.grad is not None for p in encoder.predictor.parameters())

    def test_the_latent_does_not_collapse(self, trained):
        """The number that matters. A collapsed encoder's *loss* goes to zero,
        which reads as success."""
        _module, report = trained
        assert not report.collapsed
        assert report.latent_std[-1] > 0.1

    def test_a_collapse_is_reported_not_hidden(self):
        """`collapsed` is what turns a flattering loss into a visible failure,
        and it is what the CLI exits non-zero on."""
        report = pretrain_pkg.PretrainReport(steps=1)
        report.train_loss = [0.5, 0.0001]
        report.validation_loss = [0.5, 0.0001]
        report.latent_std = [0.9, 0.01]

        assert report.collapsed
        assert "COLLAPSED" in report.summary()

    def test_an_encoder_with_no_objective_is_refused(self, spaces, corpus):
        """Pretraining `transformer` would run happily and teach it nothing."""
        obs_space, act_space = spaces
        for encoder_type in ("mlp", "transformer", "lstm"):
            with pytest.raises(ValueError, match="self-supervised"):
                pretrain_pkg.pretrain(
                    corpus, obs_space, act_space, encoder_type=encoder_type,
                    steps=1,
                )

    def test_a_single_episode_still_splits(self, spaces, spec_block):
        """Below three episodes the split falls back to contiguous rows rather
        than refusing - it still bars shuffling, it just cannot promise the
        price-anchor separation an episode split gives."""
        tiny = corpus_module.from_rollouts(
            num_episodes=1, max_step=40, num_agents=2, seed=0
        )
        train, validation, _test = probe_module.split_masks(
            tiny.episode_index, len(tiny)
        )
        assert train.sum() and validation.sum()
        assert np.flatnonzero(train).max() < np.flatnonzero(validation).min()


@pytest.fixture(scope="module")
def saved(spaces, corpus, spec_block, tmp_path_factory):
    """One pretrained checkpoint on disk, plus the module it came from."""
    obs_space, act_space = spaces
    module, _report = pretrain_pkg.pretrain(
        corpus, obs_space, act_space, encoder_spec=spec_block,
        steps=10, batch_size=32, log_every=10, seed=0,
    )
    path = str(tmp_path_factory.mktemp("pretrained"))
    pretrain_pkg.save(module, path, "jepa", spec_block)
    return path, module



class TestTheCheckpoint:

    def test_it_writes_all_three_pieces(self, saved):
        """Two weight formats, for two consumers: `encoder.pt` is what the probe
        loads into a module it built itself, and `rl_module/` is what a training
        run's spec picks up."""
        path, _module = saved
        assert os.path.isfile(os.path.join(path, pretrain_pkg.WEIGHTS_FILE))
        assert os.path.isfile(os.path.join(path, pretrain_pkg.FINGERPRINT_FILE))
        assert os.path.isdir(os.path.join(path, pretrain_pkg.MODULE_SUBDIR))

    def test_the_fingerprint_names_the_architecture(self, saved, spec_block):
        path, _module = saved
        with open(os.path.join(path, pretrain_pkg.FINGERPRINT_FILE)) as handle:
            stored = json.load(handle)
        assert stored["encoder_type"] == "jepa"
        assert stored["encoder_spec"]["d_model"] == spec_block["d_model"]

    def test_loading_reproduces_the_weights(self, saved, spaces, spec_block,
                                            corpus):
        """Round trip: a fresh module plus these weights must encode identically
        to the module they came from."""
        path, source = saved
        obs_space, act_space = spaces
        target = features_module.build_module(
            obs_space, act_space, "jepa", spec_block
        )
        pretrain_pkg.load_into(target, path, "jepa", spec_block)

        assert np.allclose(
            features_module.latents(source, corpus),
            features_module.latents(target, corpus),
        )

    def test_a_mismatched_architecture_is_refused(self, saved, spec_block):
        """The weights are *that* architecture's weights. Loading a d_model 128
        checkpoint into a d_model 256 encoder must fail here, not as a shape
        error several frames away - or, worse, as a partial load."""
        path, _module = saved
        with pytest.raises(ValueError, match="does not match"):
            pretrain_pkg.verify_fingerprint(
                path, "jepa", {**spec_block, "d_model": 256}
            )

    def test_a_different_encoder_type_is_refused(self, saved, spec_block):
        path, _module = saved
        with pytest.raises(ValueError, match="does not match"):
            pretrain_pkg.verify_fingerprint(path, "transformer", spec_block)

    def test_a_directory_that_is_not_a_checkpoint_raises(self, tmp_path,
                                                         spec_block):
        (tmp_path / "unrelated.txt").write_text("not a checkpoint")
        with pytest.raises(FileNotFoundError, match="not a pretrain checkpoint"):
            pretrain_pkg.verify_fingerprint(str(tmp_path), "jepa", spec_block)


class TestTrainingStartsFromIt:
    """The point of pretraining: a real training spec must carry the weights."""

    @staticmethod
    def _trunk(module):
        return list(module.encoder.actor_encoder.trunk.parameters())

    def _built(self, path, spaces, **kwargs):
        obs_space, act_space = spaces
        return build_trainable_module_spec(
            obs_space, act_space, encoder_type="jepa", **kwargs
        ).build()

    def test_a_built_module_carries_the_pretrained_trunk(self, saved, spaces):
        """Two independently built modules must be identical, which they cannot
        be from a random initialisation."""
        path, _module = saved
        first = self._built(path, spaces, pretrained_path=path)
        second = self._built(path, spaces, pretrained_path=path)

        assert all(
            torch.equal(p, q)
            for p, q in zip(self._trunk(first), self._trunk(second))
        )

    def test_it_differs_from_a_fresh_initialisation(self, saved, spaces):
        path, _module = saved
        pretrained = self._built(path, spaces, pretrained_path=path)
        fresh = self._built(path, spaces)

        assert not all(
            torch.equal(p, q)
            for p, q in zip(self._trunk(pretrained), self._trunk(fresh))
        )

    def test_the_critic_starts_from_it_too(self, saved, spaces):
        """`vf_share_layers` is false, so actor and critic are separate
        encoders. Both start from the same representation and diverge during
        PPO - starting only one of them there would be arbitrary."""
        path, _module = saved
        module = self._built(path, spaces, pretrained_path=path)

        assert all(
            torch.equal(p, q)
            for p, q in zip(
                module.encoder.actor_encoder.trunk.parameters(),
                module.encoder.critic_encoder.trunk.parameters(),
            )
        )

    def test_a_mismatched_spec_is_refused_at_build_time(self, saved, spaces,
                                                        spec_block):
        """Before the path reaches any encoder, so the message can still name
        the architectures rather than reporting a shape."""
        path, _module = saved
        obs_space, act_space = spaces
        with pytest.raises(ValueError, match="does not match"):
            build_trainable_module_spec(
                obs_space, act_space, encoder_type="jepa",
                encoder_specs={"jepa": {**spec_block, "d_model": 64}},
                pretrained_path=path,
            )

    def test_mlp_cannot_use_one(self, saved, spaces):
        """It has no self-supervised objective, so nothing could have produced
        those weights."""
        path, _module = saved
        obs_space, act_space = spaces
        with pytest.raises(ValueError, match="no self-supervised objective"):
            build_trainable_module_spec(
                obs_space, act_space, encoder_type="mlp", pretrained_path=path
            )

    def test_the_path_stays_out_of_the_fingerprint(self, saved, spaces):
        """`encoder_spec` is what the fingerprint hashes. A path inside it would
        make the fingerprint depend on where the weights came from, so it could
        never match the one stored beside them."""
        path, _module = saved
        obs_space, act_space = spaces
        spec = build_trainable_module_spec(
            obs_space, act_space, encoder_type="jepa", pretrained_path=path
        )
        assert "pretrained_path" not in spec.model_config.encoder_spec
        assert spec.model_config.pretrained_path == path
