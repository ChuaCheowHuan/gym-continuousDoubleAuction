"""`market_variety`: the market's rules redrawn at every reset.

With `market_variety` empty (the shipped default) every episode runs under the
configured `matching_rule`, `step_clearing` and fees. With a list of choices for
any of those four keys, each `reset` draws one value per key from the env's own
seeded generator, so agents train across a spread of markets and a seeded reset
repeats its market. None of the four changes the observation or action space.
"""

from decimal import Decimal

import pytest

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.envs.settings import EnvSettings
from gym_continuousDoubleAuction.train.train import TrainConfig

CHOICES = {
    "matching_rule": ["fifo", "pro_rata"],
    "step_clearing": ["sequential", "batch"],
    "maker_fee_bps": [-1, 0],
    "taker_fee_bps": [2, 5],
}


def _env(**kwargs):
    return continuousDoubleAuctionEnv({"num_of_agents": 4, "max_step": 40, **kwargs})


def _market(env):
    return {
        "matching_rule": env.LOB.matching_rule,
        "step_clearing": env.step_clearing,
        "maker_fee_bps": env.traders[0].acc.maker_fee_bps,
        "taker_fee_bps": env.traders[0].acc.taker_fee_bps,
    }


class TestOff:
    def test_the_shipped_default_is_off(self):
        assert EnvSettings.from_config({}).market_variety == {}

    def test_every_episode_keeps_the_configured_market(self):
        env = _env(matching_rule="pro_rata", step_clearing="batch", taker_fee_bps=3)
        for seed in range(5):
            _, infos = env.reset(seed=seed)
            assert _market(env) == {
                "matching_rule": "pro_rata",
                "step_clearing": "batch",
                "maker_fee_bps": 0,
                "taker_fee_bps": 3,
            }
            assert "market" not in infos["agent_0"]

    def test_it_draws_nothing_from_the_generator(self):
        a, b = _env(), _env(market_variety={})
        a.reset(seed=4)
        b.reset(seed=4)
        assert a.last_price == b.last_price


class TestOn:
    def test_a_seeded_reset_repeats_its_market(self):
        env = _env(market_variety=CHOICES)
        env.reset(seed=7)
        first = _market(env)
        env.reset(seed=8)
        env.reset(seed=7)
        assert _market(env) == first

    def test_every_choice_is_drawn(self):
        env = _env(market_variety=CHOICES)
        seen = {key: set() for key in CHOICES}
        for seed in range(40):
            env.reset(seed=seed)
            for key, value in _market(env).items():
                seen[key].add(value)
        assert seen == {key: set(values) for key, values in CHOICES.items()}

    def test_the_draw_reaches_the_book_the_clearing_and_every_account(self):
        env = _env(market_variety=CHOICES)
        _, infos = env.reset(seed=3)
        drawn = infos["agent_0"]["market"]
        assert env.LOB.matching_rule == drawn["matching_rule"]
        assert env.step_clearing == drawn["step_clearing"]
        for trader in env.traders:
            assert trader.acc.maker_fee_bps == Decimal(str(drawn["maker_fee_bps"]))
            assert trader.acc.taker_fee_bps == Decimal(str(drawn["taker_fee_bps"]))
        assert all(info["market"] == drawn for info in infos.values())

    def test_an_unvaried_key_keeps_its_configured_value(self):
        env = _env(market_variety={"matching_rule": ["pro_rata"]}, step_clearing="batch")
        _, infos = env.reset(seed=1)
        assert infos["agent_0"]["market"] == {"matching_rule": "pro_rata"}
        assert env.step_clearing == "batch"

    def test_the_spaces_do_not_change(self):
        plain, varied = _env(), _env(market_variety=CHOICES)
        varied.reset(seed=0)
        assert plain.observation_spaces == varied.observation_spaces
        assert plain.action_spaces == varied.action_spaces

    def test_random_play_conserves_money_across_drawn_markets(self):
        env = _env(market_variety=CHOICES)
        for seed in range(3):
            env.reset(seed=seed)
            while True:
                _, _, dones, truncs, _ = env.step(
                    {a: env.action_spaces[a].sample() for a in env.agents}
                )
                total = env.fees_collected + sum(t.acc.nav for t in env.traders)
                assert total == Decimal(4) * Decimal(env.init_cash)
                if dones["__all__"] or truncs["__all__"]:
                    break


class TestValidation:
    @pytest.mark.parametrize(
        "variety, message",
        [
            ({"n_hist": [1, 2]}, "may only name"),
            ({"matching_rule": []}, "non-empty list"),
            ({"matching_rule": "fifo"}, "non-empty list"),
            ({"matching_rule": ["fifo", "random"]}, "matching_rule"),
            ({"step_clearing": ["instant"]}, "step_clearing"),
            ({"taker_fee_bps": [-1]}, "taker_fee_bps must be >= 0"),
            ({"maker_fee_bps": [-5], "taker_fee_bps": [2, 5]}, "must be >= 0"),
            ([["matching_rule", "fifo"]], "market_variety must be a dict"),
        ],
    )
    def test_a_bad_choice_fails_at_construction(self, variety, message):
        with pytest.raises(ValueError, match=message):
            _env(market_variety=variety)

    def test_a_varied_fee_is_checked_against_the_configured_other(self):
        with pytest.raises(ValueError, match="must be >= 0"):
            _env(market_variety={"maker_fee_bps": [-3]}, taker_fee_bps=2)
        _env(market_variety={"maker_fee_bps": [-2]}, taker_fee_bps=2)


class TestTraining:
    def test_the_train_config_forwards_it(self):
        cfg = TrainConfig(market_variety={"step_clearing": ["sequential", "batch"]})
        assert cfg.env_config["market_variety"] == {"step_clearing": ["sequential", "batch"]}

    def test_the_shipped_training_value_is_off(self):
        assert TrainConfig().market_variety == {}
