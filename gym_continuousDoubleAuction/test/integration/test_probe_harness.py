"""The probe harness against the real env, real encoders and a real checkpoint.

`test_probe.py` covers the harness's arithmetic on synthetic observations.
This file covers the parts that can only break where it meets the rest of the
system: that the corpus reader gets a usable book out of the actual matching
engine, that every registered encoder can be frozen and read, and that a
checkpoint written in RLlib's layout is found and restored with its weights
rather than silently re-initialised.

Kept deliberately small - a handful of steps, no training - because none of
these questions needs a long run to answer.
"""
import os

import numpy as np
import pytest
import torch

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.train.model.encoders import (
    ENCODER_REGISTRY,
    MLP_ENCODER_TYPE,
)
from gym_continuousDoubleAuction.train.probe import corpus as corpus_module
from gym_continuousDoubleAuction.train.probe import features as features_module
from gym_continuousDoubleAuction.train.probe import report as report_module

#: Every encoder a config file may select, plus the mlp pass-through. Fixtures
#: are excluded: they are not architectures anyone would probe.
SHIPPED = [MLP_ENCODER_TYPE] + sorted(
    name for name in ENCODER_REGISTRY if not name.startswith("_")
)

EPISODES = 3
STEPS = 40


@pytest.fixture(scope="module")
def spaces():
    env = continuousDoubleAuctionEnv({})
    agent_id = env.agents[0]
    return env.get_observation_space(agent_id), env.get_action_space(agent_id)


@pytest.fixture(scope="module")
def corpus():
    return corpus_module.from_rollouts(
        num_episodes=EPISODES, max_step=STEPS, num_agents=3, seed=0,
    )


class TestRolloutCorpus:
    def test_collects_every_step_plus_the_reset_observation(self, corpus):
        """The reset observation is a real book state and a valid probe input,
        so the stream is `max_step + 1` long per episode, not `max_step`."""
        assert corpus.num_episodes == EPISODES
        assert len(corpus) == EPISODES * (STEPS + 1)

    def test_the_observation_width_matches_the_env(self, corpus, spaces):
        obs_space, _ = spaces
        assert corpus.obs.shape[1] == obs_space.shape[0]

    def test_the_book_is_not_empty(self, corpus):
        """A corpus of empty books scores every feature set at the floor and
        says nothing. `init_cash` at 0 produces exactly that (S1-4), so this
        is the check that the corpus is worth probing at all."""
        layout = corpus.layout
        sizes = corpus.snapshots[:, layout.k_rows:2 * layout.k_rows]
        assert (sizes > 0).any()

    def test_a_seed_reproduces_the_corpus(self):
        first = corpus_module.from_rollouts(
            num_episodes=1, max_step=STEPS, num_agents=3, seed=7,
        )
        second = corpus_module.from_rollouts(
            num_episodes=1, max_step=STEPS, num_agents=3, seed=7,
        )
        assert np.array_equal(first.obs, second.obs)

    def test_episodes_are_marked_and_ordered(self, corpus):
        boundaries = np.flatnonzero(np.diff(corpus.episode_index))
        assert len(boundaries) == EPISODES - 1
        assert np.array_equal(
            corpus.episode_index, np.sort(corpus.episode_index)
        )


@pytest.mark.parametrize("encoder_type", SHIPPED)
class TestEveryEncoderIsProbeable:
    def test_latents_have_one_row_per_observation(
        self, spaces, corpus, encoder_type
    ):
        obs_space, act_space = spaces
        module = features_module.build_module(obs_space, act_space, encoder_type)
        latents = features_module.latents(module, corpus)
        assert latents.shape[0] == len(corpus)
        assert latents.shape[1] > 0
        assert np.isfinite(latents).all()

    def test_latents_are_deterministic(self, spaces, corpus, encoder_type):
        """Dropout is a spec key on every tokenising encoder. A live one makes
        the score irreproducible rather than wrong, which is worse - the same
        failure `test_eval_forward_is_deterministic` guards on the policy path.
        """
        obs_space, act_space = spaces
        module = features_module.build_module(obs_space, act_space, encoder_type)
        assert np.array_equal(
            features_module.latents(module, corpus),
            features_module.latents(module, corpus),
        )

    def test_probing_does_not_train_the_encoder(
        self, spaces, corpus, encoder_type
    ):
        """The harness freezes what it scores. A probe that nudged the weights
        would make the score depend on how many times it had been run."""
        obs_space, act_space = spaces
        module = features_module.build_module(obs_space, act_space, encoder_type)
        before = {k: v.clone() for k, v in module.state_dict().items()}
        features_module.latents(module, corpus)
        after = module.state_dict()
        for name, tensor in before.items():
            assert torch.equal(tensor, after[name]), name


class TestStatefulEncodersSeeTheirEpisode:
    """A recurrent encoder's latent at step t depends on everything before t
    *within its episode*. Batching its rows the way a stateless encoder's are
    batched would silently score a memory re-initialised at every row - which
    is not the encoder anyone configured, and would look completely normal in
    the report.
    """

    def test_the_latent_moves_along_the_episode(self, spaces, corpus):
        obs_space, act_space = spaces
        module = features_module.build_module(obs_space, act_space, "lstm")
        assert module.is_stateful()

        latents = features_module.latents(module, corpus)
        first = np.flatnonzero(corpus.episode_index == 0)[:5]
        head = latents[first]
        # A collapsed sequence axis would give the same vector at every step.
        assert not np.allclose(head, head[0])

    def test_state_resets_at_every_episode_boundary(self, spaces, corpus):
        """The last episode's latents must not depend on the episodes that
        preceded it in the corpus, so encoding it alone gives the same answer.
        A state carried across a reset would make a row's latent depend on how
        many episodes happened to be collected before it."""
        obs_space, act_space = spaces
        module = features_module.build_module(obs_space, act_space, "lstm")

        rows = np.flatnonzero(corpus.episode_index == corpus.episode_index[-1])
        isolated = corpus_module.ProbeCorpus(
            obs=corpus.obs[rows],
            episode_index=np.zeros(len(rows), dtype=np.int32),
            layout=corpus.layout,
        )
        assert np.allclose(
            features_module.latents(module, corpus)[rows],
            features_module.latents(module, isolated),
        )


@pytest.fixture(scope="module")
def checkpoint(spaces, tmp_path_factory):
    """A module saved in the layout `train.py`'s checkpoints use."""
    obs_space, act_space = spaces
    module = features_module.build_module(obs_space, act_space, "transformer")
    root = tmp_path_factory.mktemp("iter_1")
    path = os.path.join(
        str(root), "learner_group", "learner", "rl_module", "policy_0"
    )
    os.makedirs(path, exist_ok=True)
    module.save_to_path(path)
    return str(root), module


class TestCheckpointRestore:
    def test_finds_the_module_inside_a_checkpoint_directory(self, checkpoint):
        root, _ = checkpoint
        assert features_module.load_module(root, "policy_0") is not None

    def test_restores_the_weights_not_a_fresh_initialisation(
        self, checkpoint, corpus
    ):
        """The failure this rules out is silent: a re-initialised encoder
        produces perfectly good latents and a perfectly plausible score, and
        the report would credit the run's training with its initialisation."""
        root, original = checkpoint
        restored = features_module.load_module(root, "policy_0")
        assert np.allclose(
            features_module.latents(original, corpus),
            features_module.latents(restored, corpus),
        )

    def test_a_missing_module_raises_naming_what_is_there(self, checkpoint):
        """Without the module-directory marker check this fell back to loading
        the checkpoint *root*, and the user got a missing-file error about an
        internal pickle instead of being told which module was not found."""
        root, _ = checkpoint
        with pytest.raises(FileNotFoundError) as excinfo:
            features_module.load_module(root, "policy_9")
        message = str(excinfo.value)
        assert "policy_9" in message
        assert "policy_0" in message

    def test_a_module_directory_may_be_passed_directly(self, checkpoint):
        root, _ = checkpoint
        module_dir = os.path.join(
            root, "learner_group", "learner", "rl_module", "policy_0"
        )
        assert features_module.load_module(module_dir, "policy_0") is not None

    def test_a_directory_that_is_not_a_checkpoint_raises(self, tmp_path):
        (tmp_path / "unrelated.txt").write_text("not a checkpoint")
        with pytest.raises(FileNotFoundError, match="policy_0"):
            features_module.load_module(str(tmp_path), "policy_0")


class TestEndToEnd:
    def test_the_matrix_scores_raw_against_a_real_encoder(self, spaces, corpus):
        obs_space, act_space = spaces
        module = features_module.build_module(
            obs_space, act_space, "transformer"
        )
        features = {
            features_module.RAW_FEATURES: features_module.raw(corpus),
            "transformer": features_module.latents(module, corpus),
        }
        rows = report_module.run(
            corpus, features, ["mid_return", "spread_change"], [1, 5]
        )
        assert rows
        for row in rows:
            scored = [r for r in row.results.values() if r is not None]
            # Identical rows and an identical split for every feature set.
            assert len({(r.n_train, r.n_test) for r in scored}) == 1
            for result in scored:
                assert np.isfinite(result.score)

        rendered = report_module.render(rows, list(features))
        assert "transformer" in rendered and "mid_return" in rendered
