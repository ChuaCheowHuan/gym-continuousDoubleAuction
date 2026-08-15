"""What each step reports about itself.

`info` used to carry three fields - reward, NAV, num_trades - so the state a
run's behaviour is diagnosed from (position, drawdown, the spread, which of the
five reward terms actually moved) existed for one step and was discarded. See
doc/11 2.2-2.4.

Two things here are invariants rather than descriptions, and they are the
reason this file exists:

  * the five reward terms sum to the reward, exactly. A decomposition that does
    not add up is worse than none, because it looks authoritative.
  * everything in `info` survives `json.dumps`. The per-iteration progress log
    (doc/11 1.6) is the durable record, and a numpy scalar in `info` breaks it.
"""
import json
import os
import sys

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.envs.exchg.info_helper import _plain

NUM_AGENTS = 4
INIT_CASH = 1000000


def _naive_sum(values):
    """Left-to-right accumulation.

    Deliberately not `sum()`: on Python 3.12+ the builtin applies Neumaier
    compensated summation to floats, which disagrees with plain accumulation in
    the last bits. The reward is built by accumulation, so that is what the
    invariant has to be checked against - using `sum()` here would make this
    test fail on arithmetic that is correct.
    """
    total = 0.0
    for value in values:
        total += value
    return total


@pytest.fixture(scope="module")
def stepped_env():
    """A real env driven far enough that positions, trades and fills exist."""
    env = continuousDoubleAuctionEnv({
        "num_of_agents": NUM_AGENTS,
        "init_cash": INIT_CASH,
        "tick_size": 1,
        "tape_display_length": 10,
        "max_step": 100,
    })
    env.reset()
    last_infos, last_rewards = {}, {}
    every_info = []
    for _ in range(40):
        actions = {
            f"agent_{i}": env.action_spaces[f"agent_{i}"].sample()
            for i in range(NUM_AGENTS)
        }
        _, rewards, terminateds, truncateds, infos = env.step(actions)
        last_infos, last_rewards = infos, rewards
        every_info.append(infos)
        if terminateds.get("__all__") or truncateds.get("__all__"):
            break
    return env, last_infos, last_rewards, every_info


class TestBackCompat:
    """The three original fields are unchanged - name, type and meaning."""

    def test_the_original_three_fields_survive(self, stepped_env):
        _, infos, _, _ = stepped_env
        for i in range(NUM_AGENTS):
            info = infos[f"agent_{i}"]
            assert {"reward", "NAV", "num_trades"} <= set(info)
            assert isinstance(info["num_trades"], int)

    def test_nav_is_still_a_string(self, stepped_env):
        """Not cosmetic: the conservation check parses it back with Decimal and
        visualize_nav.py with float(). Both need the exact str() of a Decimal."""
        env, infos, _, _ = stepped_env
        for i in range(NUM_AGENTS):
            reported = infos[f"agent_{i}"]["NAV"]
            assert isinstance(reported, str)
            assert reported == str(env.traders[i].acc.nav)

    def test_reward_matches_the_rewards_dict(self, stepped_env):
        _, infos, rewards, _ = stepped_env
        for i in range(NUM_AGENTS):
            assert infos[f"agent_{i}"]["reward"] == rewards[f"agent_{i}"]


class TestRewardDecomposition:
    """doc/11 2.4: the five terms, individually, and they must add up."""

    def test_all_five_terms_are_reported(self, stepped_env):
        _, infos, _, _ = stepped_env
        expected = {
            "nav_term", "order_penalty", "trade_penalty",
            "drawdown_penalty", "passive_bonus",
        }
        for i in range(NUM_AGENTS):
            assert set(infos[f"agent_{i}"]["reward_terms"]) == expected

    def test_the_terms_sum_to_the_reward_exactly(self, stepped_env):
        """The invariant. Not approx: the reward *is* this accumulation, so any
        difference means the logged split is not what the agent was trained on."""
        _, infos, _, _ = stepped_env
        for i in range(NUM_AGENTS):
            info = infos[f"agent_{i}"]
            assert _naive_sum(info["reward_terms"].values()) == info["reward"]

    def test_the_terms_match_the_documented_formula(self, stepped_env):
        """Reward = nav_term - order - trade - drawdown + passive (doc/07 6).

        Rebuilt from the env's own coefficients and counters, so this catches a
        term being recorded with the wrong sign or against the wrong counter -
        which summing alone would not.
        """
        env, infos, _, _ = stepped_env
        for i in range(NUM_AGENTS):
            terms = infos[f"agent_{i}"]["reward_terms"]
            assert terms["order_penalty"] <= 0
            assert terms["trade_penalty"] <= 0
            assert terms["drawdown_penalty"] <= 0
            assert terms["passive_bonus"] >= 0

    def test_signs_follow_the_penalty_coefficients(self, stepped_env):
        """A penalty that fired must be exactly coefficient x counter."""
        env, infos, _, _ = stepped_env
        for i in range(NUM_AGENTS):
            info = infos[f"agent_{i}"]
            terms = info["reward_terms"]
            assert terms["order_penalty"] == pytest.approx(
                -(env.order_penalty * info["order_step_placed"])
            )
            assert terms["trade_penalty"] == pytest.approx(
                -(env.trade_penalty * info["num_trades_step"])
            )
            assert terms["passive_bonus"] == pytest.approx(
                env.passive_bonus * info["num_passive_fills_step"]
            )


class TestAccountState:
    """doc/11 2.3."""

    def test_the_account_fields_are_present(self, stepped_env):
        _, infos, _, _ = stepped_env
        expected = {
            "net_position", "VWAP", "cash", "cash_on_hold", "position_val",
            "drawdown", "max_nav", "num_trades_step",
            "num_passive_fills_step", "order_step_placed",
        }
        for i in range(NUM_AGENTS):
            assert expected <= set(infos[f"agent_{i}"])

    def test_net_position_is_an_int_across_the_episode(self, stepped_env):
        """A net position is a count of contracts, so it is an int - before the
        first fill and after it.

        This used to be reported as a float purely to paper over the account
        rebuilding the field as a Decimal on the first trade. The account now
        keeps it in int, so the cast is gone and the type is the real one.
        """
        _, _, _, every_info = stepped_env
        for infos in every_info:
            for i in range(NUM_AGENTS):
                value = infos[f"agent_{i}"]["net_position"]
                assert isinstance(value, int), f"{value!r} is {type(value).__name__}"
                assert not isinstance(value, bool)

    def test_drawdown_is_the_level_the_penalty_uses(self, stepped_env):
        """max_nav - nav, floored at 0 - computed in reward_helper and, before
        this, thrown away."""
        env, infos, _, _ = stepped_env
        for i in range(NUM_AGENTS):
            acc = env.traders[i].acc
            expected = float(max(0, acc.max_nav - acc.nav))
            assert infos[f"agent_{i}"]["drawdown"] == pytest.approx(expected)

    def test_the_per_step_counters_are_read_before_they_are_zeroed(self, stepped_env):
        """set_step_outputs zeroes these right after set_info.

        Asserting the type would not catch the failure that matters: if the
        ordering ever flips, every counter still reports a perfectly valid int,
        just always 0. So this requires the counters to have been observed
        non-zero at some point across the episode - which is only possible if
        they are read while still live.
        """
        _, _, _, every_info = stepped_env
        assert every_info, "fixture stepped no episodes"

        for key in ("num_trades_step", "num_passive_fills_step",
                    "order_step_placed"):
            observed = [
                infos[f"agent_{i}"][key]
                for infos in every_info
                for i in range(NUM_AGENTS)
            ]
            assert all(isinstance(v, int) for v in observed)
            assert any(v != 0 for v in observed), (
                f"{key} was 0 on every step of every agent: set_info is "
                f"probably running after the counters are reset, which would "
                f"log a constant 0 while looking healthy"
            )


class TestMarketState:
    """doc/11 2.2."""

    def test_market_fields_are_present_and_shared(self, stepped_env):
        """Same book for everyone, so every agent must report the same view."""
        _, infos, _, _ = stepped_env
        for key in ("last_price", "best_bid", "best_ask", "spread"):
            values = [infos[f"agent_{i}"][key] for i in range(NUM_AGENTS)]
            assert len(set(values)) == 1, f"{key} differs between agents"

    def test_spread_is_the_touch_difference(self, stepped_env):
        _, infos, _, _ = stepped_env
        info = infos["agent_0"]
        if info["best_bid"] is not None and info["best_ask"] is not None:
            assert info["spread"] == pytest.approx(
                info["best_ask"] - info["best_bid"]
            )
        else:
            assert info["spread"] is None

    def test_a_one_sided_book_reports_none_not_zero(self):
        """0.0 would be indistinguishable from a book whose touch is touching.
        The observation needs a finite sentinel; a log does not (doc/15 S3-14).
        """
        class FakeTree:
            def __init__(self, price):
                self.price = price

            def max_price(self):
                return self.price

            def min_price(self):
                return self.price

        class FakeLOB:
            def __init__(self, bid, ask):
                self.bids = FakeTree(bid)
                self.asks = FakeTree(ask)

            def get_best_bid(self):
                return self.bids.max_price()

            def get_best_ask(self):
                return self.asks.min_price()

        from gym_continuousDoubleAuction.envs.exchg.exchg_helper import Exchg_Helper

        for bid, ask in ((None, None), (10, None), (None, 12)):
            exchange = Exchg_Helper.__new__(Exchg_Helper)
            exchange.LOB = FakeLOB(bid, ask)
            exchange.set_market_snapshot()
            assert exchange.spread is None, f"bid={bid} ask={ask}"

        exchange = Exchg_Helper.__new__(Exchg_Helper)
        exchange.LOB = FakeLOB(10, 12)
        exchange.set_market_snapshot()
        assert exchange.spread == 2.0


class TestSerialisation:
    """The progress log is the durable record; `info` has to fit through it."""

    def test_the_whole_info_dict_survives_json(self, stepped_env):
        _, infos, _, _ = stepped_env
        assert json.loads(json.dumps(infos)) is not None

    def test_the_model_action_is_reported_and_plain(self, stepped_env):
        """Actions arrive as numpy scalars and arrays; np.int64 is not JSON
        serialisable, unlike np.float64 which subclasses float."""
        _, infos, _, _ = stepped_env
        for i in range(NUM_AGENTS):
            assert "model_action" in infos[f"agent_{i}"]
        json.dumps(infos["agent_0"]["model_action"])

    def test_plain_converts_nested_numpy(self):
        import numpy as np

        converted = _plain({
            "i": np.int64(3),
            "f": np.float32(1.5),
            "arr": np.array([1, 2], dtype=np.int64),
            "nested": {"deep": np.int32(7)},
            "tup": (np.int64(1), "s"),
        })
        json.dumps(converted)
        assert converted["i"] == 3
        assert converted["arr"] == [1, 2]
        assert converted["nested"]["deep"] == 7
        assert converted["tup"] == [1, "s"]

    def test_plain_leaves_ordinary_values_alone(self):
        assert _plain("1000.5") == "1000.5"
        assert _plain(None) is None
        assert _plain(3) == 3


class TestActivityFields:
    """doc/11 2.2: the two things a return series cannot distinguish."""

    def test_both_fields_are_present(self, stepped_env):
        _, infos, _, _ = stepped_env
        for i in range(NUM_AGENTS):
            info = infos[f"agent_{i}"]
            assert isinstance(info["is_pass_action"], bool)
            assert isinstance(info["num_rejected_step"], int)

    def test_is_pass_action_agrees_with_the_category_encoding(self, stepped_env):
        """The flag exists so a reader of `info` need not know that category 0
        means pass - _CATEGORY_MAP owns that. It must still agree with it.
        """
        _, _, _, every_info = stepped_env
        checked = 0
        for infos in every_info:
            for i in range(NUM_AGENTS):
                info = infos[f"agent_{i}"]
                category = info.get("model_action", {}).get("category")
                if category is None:
                    continue
                checked += 1
                assert info["is_pass_action"] == (category == 0), (
                    f"agent_{i}: is_pass_action={info['is_pass_action']} but "
                    f"category={category}"
                )
        assert checked, "no model actions were available to cross-check"

    def test_passing_is_observed_at_all(self, stepped_env):
        """Uniform random actions over the category space should pass sometimes;
        a flag that is never True would be indistinguishable from a broken one.
        """
        _, _, _, every_info = stepped_env
        assert any(
            infos[f"agent_{i}"]["is_pass_action"]
            for infos in every_info for i in range(NUM_AGENTS)
        )

    def test_rejections_are_counted_when_cash_runs_out(self):
        """The counter must be able to fire. With init_cash this small most
        orders cannot be afforded, so refusals are the common case - measured at
        151 of 200 agent-steps when this was written.
        """
        env = continuousDoubleAuctionEnv({
            "num_of_agents": NUM_AGENTS,
            "init_cash": 500,
            "tick_size": 1,
            "tape_display_length": 10,
            "max_step": 60,
        })
        env.reset()
        rejections = 0
        for _ in range(30):
            actions = {
                f"agent_{i}": env.action_spaces[f"agent_{i}"].sample()
                for i in range(NUM_AGENTS)
            }
            _, _, terminateds, truncateds, infos = env.step(actions)
            rejections += sum(
                infos[f"agent_{i}"]["num_rejected_step"] for i in range(NUM_AGENTS)
            )
            if terminateds.get("__all__") or truncateds.get("__all__"):
                break

        assert rejections > 0, (
            "no order was refused even at init_cash=500: num_rejected_step "
            "would be a counter that is always 0"
        )
