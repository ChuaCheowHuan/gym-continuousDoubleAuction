"""The two behaviours a return series cannot tell apart.

An agent that stops trading looks the same in its returns whether it *chose*
to pass or whether every order it sent was refused for want of cash. Both
produce a flat, unremarkable line.

The first case is S1-3: `entropy_coeff` is 0.0, so policies can collapse to
always-pass, and such a policy still clears the champion promotion threshold
because 0 beats a negative league mean. The pool then fills with snapshots of
the do-nothing policy while nothing in the logs says so. `pass_action_fraction`
trending to 1.0 says it outright.

The second is a policy quoting past its cash every step. `order_step_placed`
cannot express it: that flag is 0 both for an agent that never tried and for
one whose order was rejected.

See doc/11 2.2 and 4.
"""
import os
import pickle
import sys
from unittest.mock import MagicMock

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import (
    SelfPlayCallback,
)

NUM_AGENTS = 4


class MockEpisode:
    def __init__(self, episode_id, infos=None):
        self.id_ = episode_id
        self._infos = infos or {}

    def get_infos(self, index):
        return self._infos if index == -1 else {}

    # on_episode_step reads these only when the episode record is on;
    # every harness here has it off, so empty is fine.
    def get_observations(self, index):
        return {}

    def get_actions(self, index):
        return {}

    def get_rewards(self, index):
        return {}


def _infos(passes=0, rejections=0, agents=NUM_AGENTS):
    """One step's infos: `passes` agents passed, `rejections` were refused."""
    out = {}
    for i in range(agents):
        out[f"agent_{i}"] = {
            "is_pass_action": i < passes,
            "num_rejected_step": 1 if i < rejections else 0,
        }
    return out


class ActivityHarness:
    """Drives the three episode hooks without RLlib."""

    def __init__(self, **kwargs):
        kwargs.setdefault("episode_data_dir", None)
        self.callback = SelfPlayCallback(
            num_trainable_policies=2, num_random_policies=2, **kwargs
        )
        self.metrics = MagicMock()
        self.env_runner = MagicMock()

    def _hook_args(self, episode):
        return dict(
            episode=episode, env_runner=self.env_runner,
            metrics_logger=self.metrics, env=MagicMock(), env_index=0,
            rl_module=None,
        )

    def start(self, episode_id):
        self.callback.on_episode_start(**self._hook_args(MockEpisode(episode_id)))

    def step(self, episode_id, infos):
        self.callback.on_episode_step(
            **self._hook_args(MockEpisode(episode_id, infos))
        )

    def end(self, episode_id):
        """Only the activity part - the NAV check needs its own scaffolding."""
        self.callback._log_activity(MockEpisode(episode_id), self.metrics)

    def emitted(self, name):
        for call in self.metrics.log_value.call_args_list:
            if call.args and call.args[0] == name:
                return call
        return None


class TestPassActionFraction:

    def test_a_fully_passive_episode_reports_one(self):
        """The S1-3 signature. This is the number that would have made the
        collapse visible instead of leaving it to be inferred."""
        h = ActivityHarness()
        h.start("ep")
        for _ in range(10):
            h.step("ep", _infos(passes=NUM_AGENTS))
        h.end("ep")

        call = h.emitted("pass_action_fraction")
        assert call is not None
        assert call.args[1] == pytest.approx(1.0)
        assert call.kwargs["window"] == 10

    def test_a_fully_active_episode_reports_zero(self):
        h = ActivityHarness()
        h.start("ep")
        for _ in range(10):
            h.step("ep", _infos(passes=0))
        h.end("ep")

        assert h.emitted("pass_action_fraction").args[1] == pytest.approx(0.0)

    def test_the_fraction_is_over_agent_steps(self):
        """Half the agents passing every step is 0.5, whatever the step count -
        a fraction so the number means the same at any num_agents or max_step."""
        h = ActivityHarness()
        h.start("ep")
        for _ in range(7):
            h.step("ep", _infos(passes=2))
        h.end("ep")

        assert h.emitted("pass_action_fraction").args[1] == pytest.approx(0.5)


class TestOrderRejectionFraction:

    def test_rejections_are_counted(self):
        h = ActivityHarness()
        h.start("ep")
        for _ in range(5):
            h.step("ep", _infos(rejections=NUM_AGENTS))
        h.end("ep")

        call = h.emitted("order_rejection_fraction")
        assert call is not None
        assert call.args[1] == pytest.approx(1.0)

    def test_it_is_independent_of_passing(self):
        """The distinction the metric exists for: nobody passed, yet nothing
        reached the book."""
        h = ActivityHarness()
        h.start("ep")
        for _ in range(5):
            h.step("ep", _infos(passes=0, rejections=NUM_AGENTS))
        h.end("ep")

        assert h.emitted("pass_action_fraction").args[1] == pytest.approx(0.0)
        assert h.emitted("order_rejection_fraction").args[1] == pytest.approx(1.0)


class TestBookkeeping:

    def test_an_episode_with_no_infos_emits_nothing(self):
        """0.0 would read as 'nothing passed', a claim about behaviour that an
        episode reporting no agent infos gives no evidence for."""
        h = ActivityHarness()
        h.start("ep")
        h.end("ep")

        assert h.emitted("pass_action_fraction") is None
        assert h.emitted("order_rejection_fraction") is None

    def test_the_tally_is_released_at_episode_end(self):
        """One entry per live episode; a leak here grows with every episode a
        long run plays."""
        h = ActivityHarness()
        h.start("ep")
        h.step("ep", _infos(passes=1))
        assert "ep" in h.callback._activity

        h.end("ep")
        assert "ep" not in h.callback._activity

    def test_concurrent_episodes_do_not_mix(self):
        """Keyed by episode ID: under a vectorised runner two episodes are in
        flight on one worker at once."""
        h = ActivityHarness()
        h.start("a")
        h.start("b")
        for _ in range(4):
            h.step("a", _infos(passes=NUM_AGENTS))   # a: all passing
            h.step("b", _infos(passes=0))            # b: none passing
        h.end("a")
        a_value = h.emitted("pass_action_fraction").args[1]
        h.metrics.reset_mock()
        h.end("b")
        b_value = h.emitted("pass_action_fraction").args[1]

        assert a_value == pytest.approx(1.0)
        assert b_value == pytest.approx(0.0)

    def test_a_step_without_a_start_does_not_raise(self):
        """A restored run picks up mid-flight, so on_episode_start may never
        have run for an episode this worker reports on. A missing counter must
        not take down training for the sake of a metric."""
        h = ActivityHarness()
        h.step("never-started", _infos(passes=NUM_AGENTS))
        h.end("never-started")

        assert h.emitted("pass_action_fraction").args[1] == pytest.approx(1.0)

    def test_it_does_not_depend_on_the_episode_record(self):
        """episode_data_dir=None is a supported configuration, and these
        metrics are counted independently of it - which is why they are
        tallied in the hook rather than derived from the recorded rows."""
        h = ActivityHarness(episode_data_dir=None)
        h.start("ep")
        for _ in range(3):
            h.step("ep", _infos(passes=NUM_AGENTS))
        h.end("ep")

        assert h.callback.episode_data_dir is None
        assert h.emitted("pass_action_fraction").args[1] == pytest.approx(1.0)

    def test_no_metrics_logger_is_tolerated(self):
        h = ActivityHarness()
        h.start("ep")
        h.step("ep", _infos(passes=1))
        h.callback._log_activity(MockEpisode("ep"), None)

        assert "ep" not in h.callback._activity   # still released

    def test_the_callback_still_pickles(self):
        """It is cloudpickled into every checkpoint and every env runner.

        A defaultdict with a lambda factory would pass every test above and
        fail on restore.
        """
        h = ActivityHarness(episode_sample_every=7)
        h.start("ep")
        h.step("ep", _infos(passes=2))

        revived = pickle.loads(pickle.dumps(h.callback))

        # The configuration travels...
        assert revived.episode_sample_every == 7
        assert revived.num_trainable == h.callback.num_trainable

    def test_live_episode_state_does_not_travel(self):
        """What is pickled is the configuration, not the process's live state.

        The unpickling side is a *different process* - an env runner, or a
        restored driver - and a tally for an episode it never ran is not
        bookkeeping it should continue. Emitting a fraction from those counts
        would attribute one runner's behaviour to another's episode.
        """
        h = ActivityHarness()
        h.start("ep")
        h.step("ep", _infos(passes=2))
        assert h.callback._activity["ep"]["passes"] == 2

        revived = pickle.loads(pickle.dumps(h.callback))

        assert revived._activity == {}
        assert revived._episode_recorder is None
        # ...and the original is untouched by having been pickled.
        assert h.callback._activity["ep"]["passes"] == 2

    def test_a_tally_for_an_episode_that_never_ends_is_dropped(self):
        """A force-reset discards in-flight episodes without calling
        on_episode_end, so a dict pruned only there grows for the life of the
        worker (doc/21 §3.2)."""
        h = ActivityHarness()
        limit = h.callback._MAX_LIVE_EPISODES

        for i in range(limit * 2):
            h.start(f"ep_{i}")
            h.step(f"ep_{i}", _infos(passes=1))

        assert len(h.callback._activity) <= limit
        # The oldest went first, the newest is still being counted.
        assert "ep_0" not in h.callback._activity
        assert f"ep_{limit * 2 - 1}" in h.callback._activity


class TestRewardDecomposition:
    """The five signed contributions, reduced to something a run can watch.

    doc/11 §2.4 closed the capture half of this - the terms are in `info` and
    sum exactly to `reward` - and left the aggregation open: "the terms are per
    step and per agent, so a per-episode variance share is a reduction a
    consumer still has to perform". doc/07 §6.4 is the reason it is a variance
    share and not just a mean: what matters is which term is *driving* the
    signal, and a term with a large constant offset drives nothing.
    """

    def _steps(self, h, episode_id, per_step_terms):
        h.start(episode_id)
        for terms in per_step_terms:
            infos = _infos()
            for agent_info in infos.values():
                agent_info["reward_terms"] = terms
            h.step(episode_id, infos)
        h.end(episode_id)

    def test_the_mean_of_each_term_is_reported(self):
        h = ActivityHarness()
        self._steps(h, "ep", [
            {"nav_term": 1.0, "order_penalty": -0.5, "trade_penalty": 0.0,
             "drawdown_penalty": 0.0, "passive_bonus": 0.0},
            {"nav_term": 3.0, "order_penalty": -0.5, "trade_penalty": 0.0,
             "drawdown_penalty": 0.0, "passive_bonus": 0.0},
        ])

        assert h.emitted("reward_term_mean_nav_term").args[1] == pytest.approx(2.0)
        assert h.emitted("reward_term_mean_order_penalty").args[1] == pytest.approx(-0.5)

    def test_a_constant_term_gets_no_variance_share(self):
        """The whole point of a share rather than a magnitude: a penalty that is
        the same every step explains none of the reward's movement, however
        large it is."""
        h = ActivityHarness()
        self._steps(h, "ep", [
            {"nav_term": 0.0, "order_penalty": -100.0, "trade_penalty": 0.0,
             "drawdown_penalty": 0.0, "passive_bonus": 0.0},
            {"nav_term": 4.0, "order_penalty": -100.0, "trade_penalty": 0.0,
             "drawdown_penalty": 0.0, "passive_bonus": 0.0},
        ])

        assert h.emitted("reward_term_var_share_nav_term").args[1] == pytest.approx(1.0)
        assert h.emitted(
            "reward_term_var_share_order_penalty"
        ).args[1] == pytest.approx(0.0)

    def test_the_shares_sum_to_one(self):
        h = ActivityHarness()
        self._steps(h, "ep", [
            {"nav_term": 1.0, "order_penalty": -2.0, "trade_penalty": 0.5,
             "drawdown_penalty": -1.0, "passive_bonus": 0.25},
            {"nav_term": -3.0, "order_penalty": 1.0, "trade_penalty": -0.5,
             "drawdown_penalty": 2.0, "passive_bonus": -0.75},
        ])

        total = sum(
            h.emitted(f"reward_term_var_share_{term}").args[1]
            for term in ("nav_term", "order_penalty", "trade_penalty",
                         "drawdown_penalty", "passive_bonus")
        )
        assert total == pytest.approx(1.0)

    def test_an_episode_with_no_variance_reports_no_share(self):
        """Nothing moved, so there is nothing to attribute. An even split would
        be a claim this episode gives no evidence for, and 0/0 is not a number.
        """
        h = ActivityHarness()
        flat = {term: 1.0 for term in
                ("nav_term", "order_penalty", "trade_penalty",
                 "drawdown_penalty", "passive_bonus")}
        self._steps(h, "ep", [flat, flat, flat])

        assert h.emitted("reward_term_mean_nav_term") is not None
        assert h.emitted("reward_term_var_share_nav_term") is None

    def test_a_missing_decomposition_is_tolerated(self):
        """`info` without `reward_terms` is what a restored run mid-flight, or
        an older checkpoint's env, can hand back."""
        h = ActivityHarness()
        h.start("ep")
        h.step("ep", _infos(passes=1))       # no reward_terms in these infos
        h.end("ep")

        assert h.emitted("reward_term_mean_nav_term").args[1] == pytest.approx(0.0)


class TestEndOfEpisodeAccountState:
    """doc/11 §2.3 and §4 item 2: captured per step, never reduced."""

    def _end(self, h, navs, **fields):
        last_info = {}
        for i, nav in enumerate(navs):
            last_info[f"agent_{i}"] = {
                "NAV": str(nav),
                "drawdown": fields.get("drawdown", 0.1),
                "net_position": fields.get("net_position", -3),
                "num_trades": fields.get("num_trades", 4),
                "num_passive_fills_step": fields.get("passive", 1),
            }
        h.callback._log_episode_account(last_info, h.metrics)

    def test_nav_is_reported_as_a_spread_not_a_single_number(self):
        """The league's whole question is whether one policy is pulling ahead,
        which a mean across agents hides."""
        h = ActivityHarness()
        self._end(h, [100.0, 200.0, 300.0])

        assert h.emitted("episode_nav_mean").args[1] == pytest.approx(200.0)
        assert h.emitted("episode_nav_min").args[1] == pytest.approx(100.0)
        assert h.emitted("episode_nav_max").args[1] == pytest.approx(300.0)

    def test_drawdown_and_inventory_are_reported(self):
        h = ActivityHarness()
        self._end(h, [100.0, 100.0], drawdown=0.25, net_position=-3)

        assert h.emitted("mean_agent_drawdown").args[1] == pytest.approx(0.25)
        # Absolute: a short of 3 is as much inventory risk as a long of 3, and
        # averaging the signed values across agents cancels to roughly zero by
        # construction in a closed market.
        assert h.emitted("mean_abs_net_position").args[1] == pytest.approx(3.0)

    def test_the_maker_ratio_needs_a_trade_to_exist(self):
        """0.0 on an episode with no trades would read as "every fill was
        aggressive", which is a claim about behaviour that did not happen."""
        h = ActivityHarness()
        self._end(h, [100.0], num_trades=0, passive=0)

        assert h.emitted("mean_num_trades").args[1] == pytest.approx(0.0)
        assert h.emitted("maker_fill_ratio") is None

    def test_the_maker_ratio_is_the_passive_share_of_fills(self):
        h = ActivityHarness()
        self._end(h, [100.0, 100.0], num_trades=4, passive=1)

        assert h.emitted("maker_fill_ratio").args[1] == pytest.approx(2 / 8)

    def test_an_empty_info_reports_nothing(self):
        h = ActivityHarness()
        h.callback._log_episode_account({}, h.metrics)

        assert h.emitted("episode_nav_mean") is None
