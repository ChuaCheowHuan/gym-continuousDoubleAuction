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

    # on_episode_step reads these for the pickle store; empty is fine.
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
        """Keyed by episode ID, like `store`: under a vectorised runner two
        episodes are in flight at once."""
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

    def test_it_does_not_depend_on_the_pickle_store(self):
        """episode_data_dir=None is a supported configuration, and these
        metrics are counted independently of that dump."""
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
        """It is cloudpickled into every checkpoint. A defaultdict with a lambda
        factory would pass every test above and fail on restore."""
        h = ActivityHarness()
        h.start("ep")
        h.step("ep", _infos(passes=2))

        revived = pickle.loads(pickle.dumps(h.callback))
        assert revived._activity["ep"]["passes"] == 2
