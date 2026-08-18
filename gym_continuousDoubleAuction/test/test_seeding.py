"""`reset(seed=...)` has to actually seed the episode.

doc/15 S3-5. The env drew from three separate sources of randomness and every
one of them went to the *global* `np.random`: the price anchor in `reset`,
order sizes in `Action_Helper._set_size`, and the queueing order in
`rand_exec_seq`, which called `sklearn.utils.shuffle(actions, random_state=None)`
- sklearn's `None` meaning its own global `np.random.mtrand._rand`. So
`reset(seed=...)` forwarded the seed to `gymnasium.Env`, which set
`self._np_random`, which nothing read. Two episodes with the same seed and the
same actions diverged.

Training runs were reproducible anyway, by accident rather than by design:
RLlib's `EnvRunner.__init__` calls `update_global_seed_if_necessary`, which
seeds global `random` and `np.random` from `config.seed + worker_index`. That
covered all three sources - but only once per worker (so episode N cannot be
reproduced without replaying 1..N-1), only if `run.seed` is set (it is `null`
in the checked-in config), and only until a restarted env runner re-seeds from
the same value and rewinds its stream mid-run.

These tests deliberately do not touch global `np.random`. That is the point: if
they passed only because something seeded the global stream, they would pass
just as well against the code this is fixing.
"""
import numpy as np
import pytest

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)

ENV_CONFIG = {
    "num_of_agents": 4,
    "init_cash": 1000000,
    "max_step": 120,
    "is_render": False,
}

#: Long enough that all three randomness sources have been drawn from many
#: times, and that a book has formed and traded.
_STEPS = 120


def _trajectory(seed, action_seed=7, steps=_STEPS):
    """Run an episode under `seed`, holding the *actions* fixed across runs.

    The actions come from a `RandomState` local to this call, so the only thing
    that can differ between two trajectories is the env's own randomness -
    which is exactly what `seed` is supposed to pin.
    """
    env = continuousDoubleAuctionEnv(dict(ENV_CONFIG))
    env.reset(seed=seed)

    action_rng = np.random.RandomState(action_seed)
    record = []
    for _ in range(steps):
        actions = {}
        for agent_id in env.agents:
            space = env.action_spaces[agent_id]
            space.seed(int(action_rng.randint(0, 2**31 - 1)))
            actions[agent_id] = space.sample()
        _obs, rewards, _term, _trunc, infos = env.step(actions)
        record.append((
            env.last_price,
            tuple(round(float(r), 9) for r in rewards.values()),
            tuple(infos[a]["NAV"] for a in env.agents),
            tuple(infos[a]["net_position"] for a in env.agents),
        ))
    return record


class TestResetSeedIsHonoured:

    def test_same_seed_gives_the_same_episode(self):
        assert _trajectory(seed=123) == _trajectory(seed=123)

    def test_different_seeds_give_different_episodes(self):
        """Otherwise the test above would pass on an env with no randomness."""
        assert _trajectory(seed=123) != _trajectory(seed=456)

    def test_the_price_anchor_is_seeded(self):
        """The one draw that happens in `reset` itself, before any step."""
        anchors = []
        for _ in range(2):
            env = continuousDoubleAuctionEnv(dict(ENV_CONFIG))
            env.reset(seed=2024)
            anchors.append(env.last_price)
        assert anchors[0] == anchors[1]

    def test_seed_none_does_not_reset_the_stream(self):
        """The Gymnasium contract: an env that has a generator keeps it.

        Consecutive episodes of one env must differ, or every episode of a
        training run would be a replay of the first.
        """
        env = continuousDoubleAuctionEnv(dict(ENV_CONFIG))
        env.reset(seed=99)
        first = env.last_price
        anchors = set()
        for _ in range(12):
            env.reset()
            anchors.add(env.last_price)
        assert len(anchors) > 1, (
            f"12 unseeded resets all produced last_price={first}; the stream "
            f"is being re-seeded when it should be continuing"
        )

    def test_global_numpy_is_not_the_source(self):
        """Seeding the global stream must not change a seeded episode.

        This is the regression that matters. Before the fix the env read global
        `np.random`, so this assertion fails - and it fails in the direction
        that hides the bug, because a globally seeded process looks perfectly
        reproducible.
        """
        np.random.seed(1)
        under_one_global_seed = _trajectory(seed=321)
        np.random.seed(2)
        under_another = _trajectory(seed=321)
        assert under_one_global_seed == under_another


class TestExecutionOrderIsSeeded:
    """`rand_exec_seq` decides who reaches the book first, so who gets filled."""

    def _orders(self, seed, calls=40):
        env = continuousDoubleAuctionEnv(dict(ENV_CONFIG))
        env.reset(seed=seed)
        actions = [{"ID": f"agent_{i}"} for i in range(8)]
        return [
            tuple(a["ID"] for a in env.rand_exec_seq(list(actions), None))
            for _ in range(calls)
        ]

    def test_shuffle_follows_the_env_seed(self):
        assert self._orders(seed=5) == self._orders(seed=5)

    def test_shuffle_actually_shuffles(self):
        orders = self._orders(seed=5)
        assert len(set(orders)) > 1, "the queueing order never changed"

    def test_shuffle_is_a_permutation(self):
        expected = {f"agent_{i}" for i in range(8)}
        for order in self._orders(seed=5, calls=10):
            assert set(order) == expected
            assert len(order) == len(expected)

    def test_explicit_seed_pins_one_shuffle(self):
        """The `seed` parameter, which had been accepted and never honoured."""
        env = continuousDoubleAuctionEnv(dict(ENV_CONFIG))
        env.reset(seed=1)
        actions = [{"ID": f"agent_{i}"} for i in range(8)]
        first = env.rand_exec_seq(list(actions), 42)
        second = env.rand_exec_seq(list(actions), 42)
        assert [a["ID"] for a in first] == [a["ID"] for a in second]

    def test_shuffle_does_not_reorder_in_place(self):
        """`sklearn.utils.shuffle` returned a new list; so must this."""
        env = continuousDoubleAuctionEnv(dict(ENV_CONFIG))
        env.reset(seed=1)
        actions = [{"ID": f"agent_{i}"} for i in range(8)]
        before = list(actions)
        env.rand_exec_seq(actions, None)
        assert actions == before


class TestSklearnIsGone:

    def test_the_env_package_does_not_import_sklearn(self):
        """A ~30MB dependency in every EnvRunner, to shuffle <= num_agents dicts.

        Checked by parsing each module's import statements rather than by
        catching ImportError, because sklearn is installed here - the claim is
        that the env no longer reaches for it, not that it is unavailable. And
        by AST rather than by grepping the text, because the comment recording
        why the call was removed names it too.
        """
        import ast
        from pathlib import Path

        import gym_continuousDoubleAuction.envs as envs_pkg

        offenders = []
        for path in Path(envs_pkg.__file__).parent.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                if any(n.split(".")[0] == "sklearn" for n in names):
                    offenders.append(f"{path.name}:{node.lineno}")

        assert not offenders, f"sklearn imported at {offenders}"
