"""The observation reports a cost basis that is still a price.

`Account._size_decrease` rolls realised P&L into the remaining lot's basis.
That roll is load-bearing and stays: on the short side `position_val` is
`2*raw_val - mkt_val`, so removing it would move NAV. But it leaves `VWAP`
free to go negative - long 2 @ 100, sell 1 @ 250 gives -50 - and
`set_private_state` guarded on `vwap > 0`, falling through to `0.0`, which is
the encoding for *flat*. An agent holding an open position was told it held
none, on a measured 5.0% of open-position agent-steps.

`entry_vwap` is the price actually paid for the lots still held. It is
maintained by the three methods that open or reset a position and deliberately
untouched by `_size_decrease`, so it stays positive whenever a position exists.
"""
from decimal import Decimal

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.envs.exchg.state_helper import PRIVATE_FIELDS
from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook
from gym_continuousDoubleAuction.envs.agent.trader import Trader

VWAP_VS_MID = PRIVATE_FIELDS.index("vwap_vs_mid")


class TestEntryVwapTracksTheRealBasis:
    def setup_method(self):
        self.book = OrderBook()
        self.a = Trader(ID=1, cash=1_000_000)
        self.b = Trader(ID=2, cash=1_000_000)
        self.c = Trader(ID=3, cash=1_000_000)
        self.agents = [self.a, self.b, self.c]

    def test_it_starts_at_zero(self):
        assert self.a.acc.entry_vwap == Decimal(0)

    def test_opening_sets_it_to_the_traded_price(self):
        self.b.place_order('limit', 'ask', 2, 100, self.book, self.agents)
        self.a.place_order('limit', 'bid', 2, 100, self.book, self.agents)

        assert self.a.acc.entry_vwap == Decimal(100)

    def test_adding_to_a_position_averages_it(self):
        self.b.place_order('limit', 'ask', 2, 100, self.book, self.agents)
        self.a.place_order('limit', 'bid', 2, 100, self.book, self.agents)
        self.b.place_order('limit', 'ask', 2, 200, self.book, self.agents)
        self.a.place_order('limit', 'bid', 2, 200, self.book, self.agents)

        assert self.a.acc.net_position == 4
        assert self.a.acc.entry_vwap == Decimal(150)

    def test_a_profitable_partial_close_leaves_it_alone(self):
        """The case that produced a negative `VWAP`."""
        self.b.place_order('limit', 'ask', 2, 100, self.book, self.agents)
        self.a.place_order('limit', 'bid', 2, 100, self.book, self.agents)

        self.c.place_order('limit', 'bid', 1, 250, self.book, self.agents)
        self.a.place_order('limit', 'ask', 1, 250, self.book, self.agents)

        assert self.a.acc.net_position == 1
        assert self.a.acc.VWAP == Decimal(-50), "the ledger's rolled basis"
        assert self.a.acc.entry_vwap == Decimal(100), "what was actually paid"

    def test_going_flat_clears_it(self):
        self.b.place_order('limit', 'ask', 2, 100, self.book, self.agents)
        self.a.place_order('limit', 'bid', 2, 100, self.book, self.agents)
        self.c.place_order('limit', 'bid', 2, 120, self.book, self.agents)
        self.a.place_order('limit', 'ask', 2, 120, self.book, self.agents)

        assert self.a.acc.net_position == 0
        assert self.a.acc.entry_vwap == Decimal(0)

    def test_a_flip_rebases_on_the_new_position(self):
        self.b.place_order('limit', 'ask', 2, 100, self.book, self.agents)
        self.a.place_order('limit', 'bid', 2, 100, self.book, self.agents)
        # Sell 5 into a bid at 120: closes 2 long, opens 3 short, both at 120.
        self.c.place_order('limit', 'bid', 5, 120, self.book, self.agents)
        self.a.place_order('limit', 'ask', 5, 120, self.book, self.agents)

        assert self.a.acc.net_position == -3
        assert self.a.acc.entry_vwap == Decimal(120)

    def test_a_later_open_does_not_inherit_an_earlier_roll(self):
        """`entry_vwap` rolls from its own previous value, not from `VWAP`."""
        self.b.place_order('limit', 'ask', 2, 100, self.book, self.agents)
        self.a.place_order('limit', 'bid', 2, 100, self.book, self.agents)
        self.c.place_order('limit', 'bid', 1, 250, self.book, self.agents)
        self.a.place_order('limit', 'ask', 1, 250, self.book, self.agents)
        assert self.a.acc.VWAP == Decimal(-50)

        # Add one more lot at 200 on top of the surviving lot bought at 100.
        self.b.place_order('limit', 'ask', 1, 200, self.book, self.agents)
        self.a.place_order('limit', 'bid', 1, 200, self.book, self.agents)

        assert self.a.acc.net_position == 2
        assert self.a.acc.entry_vwap == Decimal(150), "(100 + 200) / 2"


class TestTheObservationSaysWhatItMeans:
    def _env(self):
        env = continuousDoubleAuctionEnv(
            {"num_of_agents": 3, "max_step": 50, "is_render": False}
        )
        env.reset(seed=2)
        return env

    def test_an_open_position_is_never_reported_as_flat(self):
        env = self._env()
        x, y, z = env.traders
        y.place_order('limit', 'ask', 2, 100.0, env.LOB, env.traders)
        x.place_order('limit', 'bid', 2, 100.0, env.LOB, env.traders)
        z.place_order('limit', 'bid', 1, 250.0, env.LOB, env.traders)
        x.place_order('limit', 'ask', 1, 250.0, env.LOB, env.traders)
        env.mark_to_mkt()

        assert x.acc.net_position != 0, "precondition: a position is open"
        private = env.set_private_state(x)

        assert private[VWAP_VS_MID] != 0.0

    def test_a_flat_agent_is_reported_as_flat(self):
        """The guard against a fix that makes the sentinel unreachable."""
        env = self._env()

        private = env.set_private_state(env.traders[0])

        assert env.traders[0].acc.net_position == 0
        assert private[VWAP_VS_MID] == 0.0

    def test_no_open_position_reports_flat_over_a_long_rollout(self):
        env = continuousDoubleAuctionEnv(
            {"num_of_agents": 4, "max_step": 400, "is_render": False}
        )
        env.reset(seed=11)
        # `reset(seed=)` seeds the env's generator, not the action spaces:
        # `Space.sample()` has a generator of its own. Seeding both is what
        # makes the thresholds below a fact rather than a coin toss.
        for index, agent in enumerate(env.agents):
            env.action_spaces[agent].seed(11 + index)

        open_steps = 0
        for _ in range(400):
            actions = {a: env.action_spaces[a].sample() for a in env.agents}
            _obs, _rew, terminateds, truncateds, _infos = env.step(actions)
            for trader in env.traders:
                if trader.acc.net_position != 0:
                    open_steps += 1
                    assert trader.acc.entry_vwap > 0, (
                        "an open position always has a price it was opened at"
                    )
            if terminateds.get("__all__") or truncateds.get("__all__"):
                break

        assert open_steps > 100, "precondition: positions were actually opened"

    def test_the_ledger_is_untouched_by_the_new_field(self):
        env = self._env()
        total = sum(t.acc.nav for t in env.traders)
        x, y, z = env.traders

        y.place_order('limit', 'ask', 2, 100.0, env.LOB, env.traders)
        x.place_order('limit', 'bid', 2, 100.0, env.LOB, env.traders)
        z.place_order('limit', 'bid', 1, 250.0, env.LOB, env.traders)
        x.place_order('limit', 'ask', 1, 250.0, env.LOB, env.traders)
        env.mark_to_mkt()

        assert sum(t.acc.nav for t in env.traders) == total
