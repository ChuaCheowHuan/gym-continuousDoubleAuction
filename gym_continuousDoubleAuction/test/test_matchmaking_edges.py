"""Edge cases in league matchmaking (issue #207).

The mapping function picks, for each non-trainable agent, a module from the pool in
proportion to its weight. The shipped weights are positive and the pool is never empty, so
the paths below were never run: an all-zero weight vector divided by its own sum.
"""

import logging
import math

import pytest

from gym_continuousDoubleAuction.train.callbk.league import League


class Ep:
    def __init__(self, id_):
        self.id_ = id_


def _league(num_trainable=2, num_random=2, champions=(), **kwargs):
    defaults = dict(
        std_dev_multiplier=0.5,
        max_champions=4,
        min_iterations_between_champions=1,
        original_opponent_weight=1.0,
        champion_weight=1.0,
        min_champion_trades=0.0,
        promotion_reference="pooled",
    )
    defaults.update(kwargs)
    league = League(num_trainable, num_random, **defaults)
    league.available_modules.extend(champions)
    return league


def _picks(league, n=400, agent="agent_2"):
    fn = League.get_mapping_fn(league)
    return [fn(agent, Ep(f"episode-{i}")) for i in range(n)]


class TestZeroWeights:
    def test_a_pool_whose_total_weight_is_zero_falls_back_to_uniform(self):
        league = _league(
            champions=("champion_1",), champion_weight=0.0, original_opponent_weight=0.0
        )
        picks = set(_picks(league))
        assert picks <= {"policy_2", "policy_3", "champion_1"}
        assert len(picks) == 3  # all of them are reachable

    def test_champions_alone_in_the_pool_at_weight_zero_still_map(self):
        league = _league(num_random=0, champions=("champion_1", "champion_2"), champion_weight=0.0)
        assert set(_picks(league)) == {"champion_1", "champion_2"}

    def test_a_zero_weight_on_one_kind_never_picks_it(self):
        league = _league(champions=("champion_1",), champion_weight=0.0)
        assert "champion_1" not in set(_picks(league))
        league = _league(champions=("champion_1",), original_opponent_weight=0.0)
        assert set(_picks(league)) == {"champion_1"}

    def test_the_fallback_is_said_once(self, caplog):
        league = _league(champion_weight=0.0, original_opponent_weight=0.0)
        with caplog.at_level(logging.WARNING):
            _picks(league, n=20)
        warnings = [r for r in caplog.records if "weight" in r.getMessage()]
        assert len(warnings) == 1


class TestAnEmptyPool:
    def test_no_random_policies_and_no_champions_maps_an_agent_to_its_own(self):
        league = _league(num_random=0)
        fn = League.get_mapping_fn(league)
        assert fn("agent_3", Ep("e")) == "policy_3"

    def test_trainable_agents_always_play_themselves(self):
        league = _league(champions=("champion_1",), champion_weight=1e9)
        fn = League.get_mapping_fn(league)
        assert [fn(f"agent_{i}", Ep("e")) for i in range(2)] == ["policy_0", "policy_1"]


class TestTheDrawIsWhatTheWeightsSay:
    def test_it_is_reproducible_for_an_episode_and_agent(self):
        league = _league(champions=("champion_1",))
        fn = League.get_mapping_fn(league)
        assert fn("agent_2", Ep("same")) == fn("agent_2", Ep("same"))

    def test_the_share_follows_the_weights(self):
        league = _league(num_random=1, champions=("champion_1",), champion_weight=3.0)
        picks = _picks(league, n=800)
        share = picks.count("champion_1") / len(picks)
        assert share == pytest.approx(0.75, abs=0.06)

    def test_a_result_is_a_plain_str(self):
        league = _league(champions=("champion_1",))
        assert type(League.get_mapping_fn(league)("agent_2", Ep("e"))) is str


class TestBadWeightsAreRefusedByName:
    @pytest.mark.parametrize("name", ["champion_weight", "original_opponent_weight"])
    @pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf"), None, "1"])
    def test_a_negative_or_non_finite_weight(self, name, bad):
        with pytest.raises(ValueError, match=name):
            _league(**{name: bad})

    def test_zero_is_allowed(self):
        _league(champion_weight=0.0)
        assert math.isfinite(_league().champion_weight)
