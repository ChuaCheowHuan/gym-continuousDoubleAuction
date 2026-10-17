"""An observation width that fits two book modes is never guessed (issue #187).

An observation is `n_hist` snapshots plus a private block. A snapshot is 48 floats in `grid`
mode and 66 in `levels`, so some widths fit both: `grid` with `n_hist` 11 and `levels` with
`n_hist` 8 are both 569 floats. `ObsLayout.from_obs_space` used to read such a width as the
process default (`grid`), and `build_encoder_config` and the probe never said which mode the
run was in, so a `levels` run with `n_hist` 8 got a `grid` layout of 11 snapshots.
"""

import gymnasium as gym
import numpy as np
import pytest

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.train.model.action_mask import mask_slice
from gym_continuousDoubleAuction.train.model.encoders.obs_layout import (
    AmbiguousObsLayout,
    ObsLayout,
)

AMBIGUOUS = 569  # 11 x 48 + 41 (grid) == 8 x 66 + 41 (levels)


def _space(width):
    return gym.spaces.Box(-np.inf, np.inf, shape=(width,), dtype=np.float32)


class TestAmbiguousWidths:
    def test_a_width_that_fits_both_modes_is_refused_without_a_mode(self):
        with pytest.raises(AmbiguousObsLayout, match=r"grid.*levels|levels.*grid") as caught:
            ObsLayout.from_obs_space(_space(AMBIGUOUS))
        assert "book_mode" in str(caught.value)
        assert isinstance(caught.value, ValueError)

    @pytest.mark.parametrize("mode, n_hist", [("grid", 11), ("levels", 8)])
    def test_the_named_mode_decides(self, mode, n_hist):
        layout = ObsLayout.from_obs_space(_space(AMBIGUOUS), book_mode=mode)
        assert (layout.book_mode, layout.n_hist) == (mode, n_hist)

    def test_a_width_that_fits_one_mode_needs_no_mode(self):
        env = continuousDoubleAuctionEnv({"num_of_agents": 2, "is_render": False})
        layout = ObsLayout.from_obs_space(env.get_observation_space(env.agents[0]))
        assert layout.book_mode == "grid" and layout.n_hist == env.n_hist

    def test_a_levels_only_width_is_read_as_levels_without_a_mode(self):
        env = continuousDoubleAuctionEnv(
            {"num_of_agents": 2, "is_render": False, "book_mode": "levels", "n_hist": 3}
        )
        layout = ObsLayout.from_obs_space(env.get_observation_space(env.agents[0]))
        assert (layout.book_mode, layout.n_hist) == ("levels", 3)

    def test_the_action_mask_does_not_depend_on_the_mode(self):
        """Its offset comes from the tail of the vector, so an ambiguous width must not
        cost a run its mask (`mask_slice` swallows a layout error and applies none)."""
        assert mask_slice(_space(AMBIGUOUS)) is not None
        assert mask_slice(_space(AMBIGUOUS)) == mask_slice(_space(AMBIGUOUS), book_mode="levels")
        assert mask_slice(_space(AMBIGUOUS)) == mask_slice(_space(AMBIGUOUS), book_mode="grid")


class TestTheRunsModeReachesTheEncoder:
    @staticmethod
    def _spaces(mode, n_hist):
        env = continuousDoubleAuctionEnv(
            {"num_of_agents": 2, "is_render": False, "book_mode": mode, "n_hist": n_hist}
        )
        agent = env.agents[0]
        return env.get_observation_space(agent), env.get_action_space(agent)

    def test_the_spec_carries_the_mode_and_the_encoder_builds_with_it(self):
        from gym_continuousDoubleAuction.train.model.model_handler import (
            build_trainable_module_spec,
        )

        obs_space, act_space = self._spaces("levels", 8)
        assert obs_space.shape[0] == AMBIGUOUS
        spec = build_trainable_module_spec(
            obs_space, act_space, encoder_type="transformer", book_mode="levels"
        )
        assert spec.model_config.book_mode == "levels"
        module = spec.build()
        assert module.encoder.actor_encoder.layout.book_mode == "levels"
        assert module.encoder.actor_encoder.layout.n_hist == 8

    def test_without_the_mode_an_ambiguous_run_fails_by_name_at_build(self):
        from gym_continuousDoubleAuction.train.model.model_handler import (
            build_trainable_module_spec,
        )

        obs_space, act_space = self._spaces("levels", 8)
        spec = build_trainable_module_spec(obs_space, act_space, encoder_type="transformer")
        with pytest.raises(AmbiguousObsLayout):
            spec.build()

    def test_the_train_config_mode_is_what_the_policy_builder_passes(self):
        from gym_continuousDoubleAuction.train.config import TrainConfig
        from gym_continuousDoubleAuction.train.train import build_config

        cfg = TrainConfig(book_mode="levels", n_hist=8, encoder_type="transformer")
        ppo = build_config(cfg)
        ppo = ppo[0] if isinstance(ppo, tuple) else ppo
        spec = ppo.rl_module_spec.rl_module_specs["policy_0"]
        assert spec.model_config.book_mode == "levels"


class TestTheProbe:
    @staticmethod
    def _parquet(tmp_path, width):
        import pyarrow as pa
        import pyarrow.parquet as pq

        rows = 6
        table = pa.table(
            {
                "obs": [list(np.zeros(width, dtype=np.float32)) for _ in range(rows)],
                "episode_id": ["e"] * rows,
                "step": list(range(rows)),
                "agent_id": ["agent_0"] * rows,
            }
        )
        pq.write_table(table, tmp_path / "episodes.parquet")
        return str(tmp_path)

    def test_an_ambiguous_parquet_is_refused_without_a_mode(self, tmp_path):
        from gym_continuousDoubleAuction.train.probe import corpus

        with pytest.raises(AmbiguousObsLayout):
            corpus.from_parquet(self._parquet(tmp_path, AMBIGUOUS))

    @pytest.mark.parametrize("mode, n_hist", [("grid", 11), ("levels", 8)])
    def test_a_named_mode_reads_it(self, tmp_path, mode, n_hist):
        from gym_continuousDoubleAuction.train.probe import corpus

        got = corpus.from_parquet(self._parquet(tmp_path, AMBIGUOUS), book_mode=mode)
        assert (got.layout.book_mode, got.layout.n_hist) == (mode, n_hist)

    def test_the_encoders_are_built_against_the_corpus_layout_not_the_default_env(self, tmp_path):
        from gym_continuousDoubleAuction.train.probe import __main__ as probe_main
        from gym_continuousDoubleAuction.train.probe import corpus

        got = corpus.from_parquet(self._parquet(tmp_path, AMBIGUOUS), book_mode="levels")
        assert probe_main.env_config_for(got) == {"book_mode": "levels", "n_hist": 8}


class TestEncodersAreBuiltInTheCorpusMode:
    """Review of #187: naming the mode to `from_parquet` is not enough if the module built
    afterwards is not told it. A `levels` corpus at the ambiguous width must go all the way
    through the probe and pretraining."""

    @staticmethod
    def _corpus(rows=24):
        from gym_continuousDoubleAuction.train.model.encoders.obs_layout import ObsLayout
        from gym_continuousDoubleAuction.train.probe.corpus import ProbeCorpus

        layout = ObsLayout.from_obs_space(_space(AMBIGUOUS), book_mode="levels")
        rng = np.random.default_rng(0)
        return ProbeCorpus(
            obs=rng.normal(size=(rows, AMBIGUOUS)).astype(np.float32),
            episode_index=np.repeat(np.arange(rows // 6), 6).astype(np.int32),
            layout=layout,
        )

    def test_the_probe_builds_and_runs_an_encoder_on_a_levels_corpus(self):
        from gym_continuousDoubleAuction.train.probe import __main__ as probe_main

        features = probe_main.build_features(self._corpus(), ["transformer"])

        assert features["transformer"].shape[0] == 24

    def test_pretraining_builds_the_encoder_in_the_corpus_mode(self):
        from gym_continuousDoubleAuction.train.pretrain import pretrain
        from gym_continuousDoubleAuction.train.probe import __main__ as probe_main

        corpus = self._corpus()
        env = continuousDoubleAuctionEnv({**probe_main.env_config_for(corpus), "num_of_agents": 2})
        agent = env.agents[0]

        module, _report = pretrain(
            corpus,
            env.get_observation_space(agent),
            env.get_action_space(agent),
            encoder_type="jepa",
            steps=2,
            batch_size=8,
        )

        assert module is not None

    def test_the_helpers_pass_the_mode_to_the_spec(self):
        from gym_continuousDoubleAuction.train.probe import features

        env = continuousDoubleAuctionEnv(
            {"num_of_agents": 2, "is_render": False, "book_mode": "levels", "n_hist": 8}
        )
        agent = env.agents[0]
        module = features.build_module(
            env.get_observation_space(agent),
            env.get_action_space(agent),
            "transformer",
            book_mode="levels",
        )
        assert module.encoder.actor_encoder.layout.book_mode == "levels"
