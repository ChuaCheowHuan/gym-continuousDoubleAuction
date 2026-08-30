"""A bankrupt agent is terminated, disarmed, and stops being scored.

doc/15 S2-4. `set_done` recorded bankruptcy in `done_set` and `set_all_done`
then rebuilt the per-agent dictionary as all-`False`, so `terminateds[agent]`
was `False` for every agent on every step. Three consequences, each pinned
below: the agent kept emitting transitions, it kept accruing reward terms, and
its resting orders stayed live and executable in a book it had no capital to
stand behind.
"""
from decimal import Decimal

import pytest

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)


def _env(**overrides):
    config = {"num_of_agents": 4, "max_step": 64, "is_render": False}
    config.update(overrides)
    env = continuousDoubleAuctionEnv(config)
    env.reset(seed=3)
    # `reset(seed=)` seeds the env's generator, not the action spaces:
    # `Space.sample()` has a generator of its own.
    for index, agent in enumerate(env.agents):
        env.action_spaces[agent].seed(3 + index)
    return env


def _step(env):
    actions = {agent: env.action_spaces[agent].sample() for agent in env.agents}
    return env.step(actions)


def _pass_action(env, agent):
    """The do-nothing action: category 0 is the only code with no side."""
    action = env.action_spaces[agent].sample()
    action["category"] = 0
    return action


def _quiet_step(env):
    """Step with every agent passing.

    Used where the assertion is about one agent's own state. Stepping with
    random actions lets another agent fill the orders under test, which changes
    the position being asserted on - and, once the mark is the midpoint,
    changes the NAV that decides whether the agent is bankrupt at all.
    """
    return env.step({agent: _pass_action(env, agent) for agent in env.agents})


def _bankrupt(trader):
    """Put a trader under water in a way that survives `mark_to_mkt`.

    Assigning `acc.nav` directly does not work: `mark_to_mkt` runs before
    `set_step_outputs` and recomputes NAV from cash, escrow and position, so a
    forced value is silently undone on any step where a trade printed - which
    made the first draft of these tests pass only when the tape happened to be
    empty. Flat the position and make the cash side negative instead, so the
    recomputed NAV is the one we asked for.
    """
    acc = trader.acc
    acc.net_position = 0
    acc.VWAP = Decimal(0)
    acc.position_val = Decimal(0)
    acc.cash = -acc.cash_on_hold - Decimal(50)
    acc.cal_nav()
    assert acc.nav <= 0


class TestBankruptAgentIsTerminated:
    def test_terminateds_reports_the_bankrupt_agent(self):
        env = _env()
        _bankrupt(env.traders[0])

        _obs, _rew, terminateds, _trunc, _infos = _quiet_step(env)

        assert terminateds["agent_0"] is True
        assert all(terminateds[a] is False for a in ("agent_1", "agent_2", "agent_3"))
        assert terminateds["__all__"] is False, "one bankruptcy does not end the episode"

    def test_the_terminal_step_still_carries_an_observation_and_a_reward(self):
        """The transition an agent terminates on is still a transition."""
        env = _env()
        _bankrupt(env.traders[0])

        obs, rewards, _term, _trunc, infos = _quiet_step(env)

        assert "agent_0" in obs
        assert "agent_0" in rewards
        assert "agent_0" in infos

    def test_it_stops_being_scored_on_every_later_step(self):
        env = _env()
        _bankrupt(env.traders[0])
        _quiet_step(env)

        obs, rewards, terminateds, truncateds, infos = _quiet_step(env)

        for emitted in (obs, rewards, infos):
            assert "agent_0" not in emitted
        assert "agent_0" not in terminateds, (
            "re-reporting a terminated agent sends a second terminal transition"
        )
        assert "agent_0" not in truncateds

    def test_its_resting_orders_are_pulled(self):
        env = _env()
        env.traders[0].place_order("limit", "bid", 5, 20.0, env.LOB, env.traders)
        env.traders[0].place_order("limit", "ask", 5, 900.0, env.LOB, env.traders)
        resting = [
            order
            for tree in (env.LOB.bids, env.LOB.asks)
            for order in tree.order_map.values()
            if order.trade_id == 0
        ]
        assert len(resting) == 2, "precondition: the agent has orders to lose"

        _bankrupt(env.traders[0])
        _quiet_step(env)

        assert not [
            order
            for tree in (env.LOB.bids, env.LOB.asks)
            for order in tree.order_map.values()
            if order.trade_id == 0
        ], "a terminated agent must not keep executable orders in the book"

    def test_agents_narrows_but_possible_agents_does_not(self):
        env = _env()
        _bankrupt(env.traders[0])
        _quiet_step(env)

        assert env.agents == ["agent_1", "agent_2", "agent_3"]
        assert env.possible_agents == [
            "agent_0", "agent_1", "agent_2", "agent_3",
        ], "possible_agents is the fixed roster"

    def test_reset_restores_the_full_roster(self):
        env = _env()
        _bankrupt(env.traders[0])
        _quiet_step(env)
        assert len(env.agents) == 3

        obs, _infos = env.reset(seed=3)

        assert env.agents == env.possible_agents
        assert set(obs) == set(env.possible_agents)
        assert env.done_set == set()

    def test_all_bankrupt_ends_the_episode(self):
        env = _env()
        for trader in env.traders:
            _bankrupt(trader)

        _obs, _rew, terminateds, _trunc, _infos = _quiet_step(env)

        assert terminateds["__all__"] is True

    def test_a_solvent_episode_terminates_nobody(self):
        """The guard against a fix that terminates too eagerly."""
        env = _env()

        for _ in range(20):
            _obs, _rew, terminateds, truncateds, _infos = _step(env)
            assert terminateds["__all__"] is False
            if truncateds["__all__"]:
                break

        assert env.done_set == set()
        assert env.agents == env.possible_agents


class TestTerminationLeavesTheLedgerIntact:
    def test_cancelling_returns_the_escrow_rather_than_writing_it_off(self):
        """Pulling the orders is a cash/cash_on_hold move, not a loss.

        Asserted on `cancel_all_orders` directly rather than across a step:
        `cash + cash_on_hold` is only invariant absent fills, and a step in
        which the other three agents act at random usually has some.
        """
        env = _env()
        trader = env.traders[0]
        trader.place_order("limit", "bid", 5, 20.0, env.LOB, env.traders)
        assert trader.acc.cash_on_hold == Decimal(100)
        free_plus_held = trader.acc.cash + trader.acc.cash_on_hold
        nav_before = trader.acc.cal_nav()

        cancelled = trader.cancel_all_orders(env.LOB)

        assert cancelled == 1
        assert trader.acc.cash_on_hold == Decimal(0)
        assert trader.acc.cash + trader.acc.cash_on_hold == free_plus_held
        assert trader.acc.cal_nav() == nav_before, "cancelling is NAV-neutral"

    def test_nav_stays_conserved_across_a_termination(self):
        """The ledger invariant the whole simulator rests on.

        A terminated trader keeps its account - it simply stops producing
        transitions - so the system total must still add up.
        """
        env = _env()
        total_before = sum(t.acc.nav for t in env.traders)
        _bankrupt(env.traders[0])
        moved = total_before - sum(t.acc.nav for t in env.traders)

        for _ in range(5):
            _obs, _rew, _term, truncateds, _infos = _step(env)
            if truncateds["__all__"]:
                break

        assert sum(t.acc.nav for t in env.traders) == total_before - moved
