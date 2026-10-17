"""Issue #152: reward, episode status, info and liquidation are composed, not inherited.

They were four of the six mixins sharing one `self` with the env. These tests hold the new
shape: the mixins are out of the class hierarchy, each component can be used on its own with
explicit inputs, the env's long-standing attributes still resolve where callers look for
them, and what the two remaining mixins share is declared and true.
"""

import inspect
from types import SimpleNamespace
from decimal import Decimal

import pytest

from gym_continuousDoubleAuction.envs.account.account import Account
from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import continuousDoubleAuctionEnv
from gym_continuousDoubleAuction.envs.exchg import shared_state
from gym_continuousDoubleAuction.envs.exchg.done_helper import EpisodeStatus
from gym_continuousDoubleAuction.envs.exchg.exchg_helper import Exchg_Helper
from gym_continuousDoubleAuction.envs.exchg.info_helper import InfoBuilder
from gym_continuousDoubleAuction.envs.exchg.liquidation_helper import LiquidationEngine
from gym_continuousDoubleAuction.envs.exchg.reward_helper import RewardModel
from gym_continuousDoubleAuction.envs.exchg.venue import Venue


@pytest.fixture
def env():
    e = continuousDoubleAuctionEnv({"num_of_agents": 3, "max_step": 40, "is_render": False})
    e.reset(seed=1)
    return e


class TestTheMixinsAreGone:
    def test_the_exchange_inherits_only_the_state_and_action_mixins(self):
        names = [c.__name__ for c in Exchg_Helper.__mro__]
        for gone in ("Reward_Helper", "Done_Helper", "Info_Helper", "Liquidation_Helper"):
            assert gone not in names
        assert names[:3] == ["Exchg_Helper", "State_Helper", "Action_Helper"]

    def test_the_env_holds_the_four_components(self, env):
        assert isinstance(env.reward_model, RewardModel)
        assert isinstance(env.episode_status, EpisodeStatus)
        assert isinstance(env.info_builder, InfoBuilder)
        assert isinstance(env.liquidation_engine, LiquidationEngine)
        assert env.liquidation_engine.venue is env

    @pytest.mark.parametrize("cls", [RewardModel, EpisodeStatus, InfoBuilder, LiquidationEngine])
    def test_a_component_is_not_a_base_of_anything_it_serves(self, cls):
        assert cls.__bases__ == (object,)


class TestAttributesStillResolveWhereCallersLook:
    def test_reward_coefficients_forward_to_the_model(self, env):
        assert env.order_penalty == env.reward_model.order_penalty
        env.order_penalty = 0.5
        assert env.reward_model.order_penalty == 0.5

    def test_liquidation_settings_forward_to_the_engine(self, env):
        assert env.liquidation == env.liquidation_engine.liquidation
        assert env.maintenance_margin == env.liquidation_engine.maintenance_margin
        assert env.liquidation_horizon == env.liquidation_engine.liquidation_horizon

    def test_done_set_is_the_episode_statuss_and_a_reset_clears_it(self, env):
        env.episode_status.done_set.add("agent_1")
        assert env.done_set == {"agent_1"}
        env.reset(seed=2)
        assert env.done_set == set()

    def test_the_entry_points_the_env_and_tests_call_still_exist(self, env):
        for name in ("set_reward", "set_done", "is_live", "set_all_done", "set_info", "liquidate"):
            assert callable(getattr(env, name))


class TestEachComponentWorksAlone:
    def test_the_reward_model_needs_no_exchange(self):
        class Trader:
            ID = 0
            acc = Account(0, 1000)

        trader = Trader()
        trader.acc.nav = Decimal(1100)
        model = RewardModel(
            order_penalty=0.0,
            trade_penalty=0.0,
            drawdown_penalty=0.0,
            passive_bonus=0.0,
            loss_multiplier=1.0,
            dead_action_penalty=0.0,
        )
        rewards = model.set_reward({}, trader)
        assert rewards["agent_0"] == pytest.approx(0.1)

    def test_a_model_built_without_arguments_reads_the_config_when_built(self):
        from gym_continuousDoubleAuction.config_loader import env_default

        assert RewardModel().order_penalty == env_default("order_penalty")

    def test_episode_status_terminates_a_broke_trader_and_pulls_its_orders(self):
        pulled = []

        class Trader:
            ID = 2
            acc = SimpleNamespace(nav=Decimal(-1))

            def cancel_all_orders(self, LOB):
                pulled.append(LOB)
                return 3

        class FakeVenue:
            LOB = "book"
            stale = False

            def invalidate_snapshot(self):
                self.stale = True

        venue, status = FakeVenue(), EpisodeStatus()
        out = status.set_done({}, Trader(), venue)
        assert out == {"agent_2": True} and status.done_set == {"agent_2"}
        assert pulled == ["book"] and venue.stale
        assert not status.is_live(Trader())

    def test_a_trader_already_out_is_not_terminated_twice(self):
        class Trader:
            ID = 0
            acc = SimpleNamespace(nav=Decimal(-5))

            def cancel_all_orders(self, LOB):
                raise AssertionError("pulled again")

        status = EpisodeStatus()
        status.done_set.add("agent_0")
        assert status.set_done({}, Trader(), SimpleNamespace(LOB=None)) == {}

    def test_set_all_done_takes_its_inputs_and_returns_the_narrowed_agents(self):
        status = EpisodeStatus()
        status.done_set.update({"agent_1"})
        term, trunc, agents = status.set_all_done(
            {"agent_1": True}, ["agent_0", "agent_1"], num_traders=2, t_step=9, episode_horizon=10
        )
        assert agents == ["agent_0"]
        assert term["agent_0"] is False and term["__all__"] is False
        assert trunc["__all__"] is True  # step 10 of 10

    def test_every_trader_out_ends_the_episode(self):
        status = EpisodeStatus()
        status.done_set.update({"agent_0", "agent_1"})
        term, _trunc, agents = status.set_all_done({}, ["agent_0", "agent_1"], 2, 0, 100)
        assert term["__all__"] is True and agents == []

    def test_the_info_builder_uses_only_what_it_is_given(self):
        trader = SimpleNamespace(ID=1, acc=Account(1, 1000))
        infos = InfoBuilder().set_info(
            {},
            trader,
            mark=Decimal(100),
            pass_agents={"agent_1"},
            last_price=101.0,
            best_bid=Decimal(99),
            best_ask=Decimal(102),
            spread=None,
            model_actions=None,
        )
        info = infos["agent_1"]
        assert info["is_pass_action"] is True and info["spread"] is None
        assert info["best_bid"] == 99.0 and info["last_price"] == 101.0
        assert info["unrealised_pnl"] == 0.0 and info["NAV"] == "1000"

    def test_the_liquidation_engine_refuses_a_bad_mode_by_name(self):
        with pytest.raises(ValueError, match="liquidation must be one of"):
            LiquidationEngine(SimpleNamespace(), liquidation="sometimes")
        with pytest.raises(ValueError, match=r"maintenance_margin must be in \[0, 1\)"):
            LiquidationEngine(SimpleNamespace(), maintenance_margin=1.5)

    def test_an_engine_with_liquidation_off_closes_nothing(self):
        # It still takes a bankrupt trader's orders off the book (#172), so it reads the
        # traders; with none to read it does nothing and reports no events.
        engine = LiquidationEngine(SimpleNamespace(traders=[]), liquidation="off")
        assert engine.liquidate() == []


class TestWhatTheTwoRemainingMixinsShareIsDeclared:
    def test_the_declarations_name_real_attributes(self, env):
        # Declared under TYPE_CHECKING, so nothing exists at runtime: read the source.
        source = inspect.getsource(shared_state.SharedState)
        names = [
            line.split(":")[0].strip()
            for line in source.splitlines()
            if line.startswith("        ")
            and not line.startswith("         ")
            and ":" in line
            and not line.strip().startswith(("#", "def ", '"""'))
        ]
        assert len(names) >= 10
        env.step({a: env.action_spaces[a].sample() for a in env.agents})
        missing = [n for n in names if not hasattr(env, n)]
        assert missing == [], f"SharedState declares attributes the env does not have: {missing}"

    def test_both_mixins_derive_from_it(self):
        from gym_continuousDoubleAuction.envs.exchg.action_helper import Action_Helper
        from gym_continuousDoubleAuction.envs.exchg.state_helper import State_Helper

        assert issubclass(State_Helper, shared_state.SharedState)
        assert issubclass(Action_Helper, shared_state.SharedState)

    def test_the_account_mixins_share_a_declared_state_too(self):
        from gym_continuousDoubleAuction.envs.account.account_state import AccountState
        from gym_continuousDoubleAuction.envs.account.calculate import Calculate
        from gym_continuousDoubleAuction.envs.account.cash_processor import Cash_Processor

        assert issubclass(Calculate, AccountState) and issubclass(Cash_Processor, AccountState)

    def test_the_env_satisfies_the_venue_the_components_are_given(self, env):
        env.step({a: env.action_spaces[a].sample() for a in env.agents})
        for name in ("traders", "LOB", "min_tick", "t_step"):
            assert hasattr(env, name), name
        for name in ("mark_price", "mark_to_mkt", "is_live", "invalidate_snapshot"):
            assert callable(getattr(env, name)), name
        assert Venue.__name__ == "Venue"

    def test_invalidating_the_snapshot_marks_it_stale(self, env):
        env.step({a: env.action_spaces[a].sample() for a in env.agents})
        assert env._snapshot_stale is False
        env.invalidate_snapshot()
        assert env._snapshot_stale is True
