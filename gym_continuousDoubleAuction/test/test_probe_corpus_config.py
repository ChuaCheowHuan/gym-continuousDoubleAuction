"""Issue #261: `train.compare` trained each run from the overridden config but
built the shared probe corpus in the default layout, so a comparison across
observation-layout variants probed modules with observations they were not
trained on.
"""

import pytest

from gym_continuousDoubleAuction.config_loader import group
from gym_continuousDoubleAuction.train import compare
from gym_continuousDoubleAuction.train.probe import corpus as corpus_module

SMALL = dict(num_episodes=1, max_step=5, num_agents=2, seed=0)


def _width(**kwargs):
    return corpus_module.from_rollouts(**SMALL, **kwargs).obs.shape[1]


class TestTheCorpusFollowsTheEnvConfig:
    def test_the_default_layout_is_unchanged(self):
        assert _width() == 233

    def test_book_mode_levels_gives_a_levels_corpus(self):
        assert _width(env_config={"book_mode": "levels"}) == 305

    def test_n_hist_changes_the_width(self):
        assert _width(env_config={"n_hist": 2}) == 2 * 48 + 41

    def test_explicit_arguments_beat_the_config(self):
        corpus = corpus_module.from_rollouts(
            num_episodes=1,
            max_step=5,
            num_agents=2,
            seed=0,
            env_config={"num_of_agents": 4, "max_step": 99},
        )
        assert len(corpus) == 6

    def test_the_callers_dict_is_not_modified(self):
        config = {"book_mode": "levels"}
        corpus_module.from_rollouts(**SMALL, env_config=config)
        assert config == {"book_mode": "levels"}


class TestCompareHandsItsConfigToTheCorpus:
    @pytest.fixture
    def seen(self, monkeypatch, tmp_path):
        import ray

        captured = {}

        def fake_corpus(**kwargs):
            captured.update(kwargs)

            class Stub:
                def describe(self):
                    return "stub"

            return Stub()

        monkeypatch.setattr(corpus_module, "from_rollouts", fake_corpus)
        monkeypatch.setattr(ray, "init", lambda **kw: None)
        monkeypatch.setattr(ray, "shutdown", lambda: None)
        monkeypatch.setattr(
            compare, "run_one", lambda *a, **kw: {"encoder": "mlp", "seed": 0, "return": 0.0}
        )
        monkeypatch.setattr(compare, "probe_checkpoint", lambda *a, **kw: None)

        def run(*extra):
            compare.main(
                ["--encoders", "mlp", "--seeds", "0", "--out", str(tmp_path / "out"), *extra]
            )
            return captured

        return run

    def test_a_layout_override_reaches_the_corpus(self, seen):
        assert seen("--set", "book_mode=levels")["env_config"]["book_mode"] == "levels"

    def test_a_fee_override_reaches_the_corpus(self, seen):
        assert seen("--set", "taker_fee_bps=7")["env_config"]["taker_fee_bps"] == 7

    def test_without_an_override_it_is_the_default_config(self, seen):
        assert (
            seen()["env_config"]["book_mode"]
            == group("env_defaults.json", "environment")["book_mode"]
        )
