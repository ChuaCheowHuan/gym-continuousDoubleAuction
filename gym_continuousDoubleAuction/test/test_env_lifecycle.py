"""The bare env has to be a working env, and an episode has to be `max_step` long.

Two defects that survived a 487-test suite because nothing asserted the thing
each is about - the suite exercised the env's *parts* thoroughly and never the
shape of a whole default episode.

**R1.** `config/env_defaults.json` shipped `init_cash: 0`, and
`Trader._order_approved` refuses on `nav <= 0` before it inspects anything
else. So `continuousDoubleAuctionEnv({})` - the form `gymnasium.make(
"continuousDoubleAuction-v0")` produces and the one doc/01 documents - placed
no order ever, put every agent in `done_set` on the first pass, and reported
`terminateds["__all__"]` after a single step. CI missed it because its only
bare-env job is `CDA_rand.py`, which supplies its own `init_cash` from
`cli_defaults.json` and so overrides the value that breaks it. These tests read
the checked-in file deliberately: a fixture supplying its own cash would
reproduce exactly the blind spot.

**R3.** `set_all_done` compared `t_step > max_step - 1`, but `step()` increments
`t_step` *after* the flags are computed, so truncation arrived one step late and
every episode ran `max_step + 1` steps. Nothing caught it because the existing
loops all stop on `truncateds["__all__"]` without counting. `train_batch_size`
is defined as `max_step * num_episodes_per_iter`, so the count is the contract.
"""
import pytest

from gym_continuousDoubleAuction.config_loader import env_default
from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)

#: Enough for a random policy to cross the spread repeatedly at the default
#: five agents; small enough to stay a unit test.
_TRADE_PROBE_STEPS = 64


def _run(env, limit):
    """Step `env` with sampled actions until it ends. Returns (steps, trades)."""
    steps = trades = 0
    while steps < limit:
        _obs, _rew, terminateds, truncateds, infos = env.step(
            {a: env.action_spaces[a].sample() for a in env.agents}
        )
        steps += 1
        trades += sum(i["num_trades_step"] for i in infos.values())
        if terminateds.get("__all__") or truncateds.get("__all__"):
            break
    return steps, trades


class TestBareEnvIsTradable:
    """`continuousDoubleAuctionEnv({})` against the checked-in defaults."""

    def test_default_init_cash_is_positive(self):
        """The precondition every other behaviour here rests on.

        Asserted separately from the behaviour so a regression names its own
        cause: `_order_approved` gates on NAV, so a zero here disables the
        entire order path and the failures below would all be downstream noise.
        """
        assert env_default("init_cash") > 0

    def test_bare_env_trades(self):
        env = continuousDoubleAuctionEnv({})
        env.reset()
        _steps, trades = _run(env, _TRADE_PROBE_STEPS)
        assert trades > 0, (
            "the default env placed no trades - every order was refused, which "
            "is what init_cash <= 0 does via Trader._order_approved"
        )

    def test_bare_env_survives_its_first_step(self):
        """The symptom that made the old default unusable, pinned directly."""
        env = continuousDoubleAuctionEnv({})
        env.reset()
        _obs, _rew, terminateds, truncateds, _infos = env.step(
            {a: env.action_spaces[a].sample() for a in env.agents}
        )
        assert not terminateds["__all__"]
        assert not truncateds["__all__"]
        assert env.done_set == set(), (
            f"agents went bankrupt on step 1: {sorted(env.done_set)}"
        )

    def test_bare_env_runs_to_its_configured_horizon(self):
        env = continuousDoubleAuctionEnv({})
        env.reset()
        steps, _trades = _run(env, env.max_step + 5)
        assert steps == env.max_step


class TestEpisodeLength:
    """An episode is exactly `max_step` calls to `step()`."""

    @pytest.mark.parametrize("max_step", [1, 2, 5, 10, 64])
    def test_truncation_lands_on_max_step(self, max_step):
        env = continuousDoubleAuctionEnv({
            "max_step": max_step, "num_of_agents": 3, "is_render": False,
        })
        env.reset()
        steps, _trades = _run(env, max_step + 5)
        assert steps == max_step

    def test_the_last_step_is_the_truncated_one(self, ):
        """Truncation is reported *on* the final step, not after it.

        The distinction the off-by-one turned on: a caller that stops when
        `truncateds["__all__"]` is set must have taken `max_step` steps at that
        point, not `max_step + 1`.
        """
        max_step = 8
        env = continuousDoubleAuctionEnv({
            "max_step": max_step, "num_of_agents": 3, "is_render": False,
        })
        env.reset()
        for step in range(1, max_step + 1):
            _obs, _rew, _term, truncateds, _infos = env.step(
                {a: env.action_spaces[a].sample() for a in env.agents}
            )
            assert truncateds["__all__"] is (step == max_step), (
                f"step {step} of {max_step} reported "
                f"truncateds['__all__']={truncateds['__all__']}"
            )
