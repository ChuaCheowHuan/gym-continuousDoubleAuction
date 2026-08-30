"""The two documented entry points that did not work.

Both failed in the same way: invisible to every job that runs from a checkout,
because nothing in the test suite or the CI packaging job exercised them.

**doc/15 S2-12.** `setup.py`'s own docstring documents
`gymnasium.make("continuousDoubleAuction-v0")`. It raised `TypeError: action
space does not inherit from gymnasium.spaces.Space, actual type: NoneType` -
only the plural `observation_spaces` / `action_spaces` were set, and
`PassiveEnvChecker` reads the singular ones inherited from `MultiAgentEnv`.

**doc/15 S3-21.** `visualize/` had no `__init__.py`, so `find_packages()`
omitted it and no built wheel carried it - while doc/01 documents
`python -m gym_continuousDoubleAuction.visualize.run_all` as an entry point.
The packaging half is asserted in CI, where a wheel actually exists; what is
checkable here is that the package is importable and declared.
"""
import gymnasium as gym
import pytest
from setuptools import find_packages

import gym_continuousDoubleAuction  # noqa: F401  (registers the env)
from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)


class TestGymnasiumMake:
    def test_the_registered_id_constructs(self):
        env = gym.make("continuousDoubleAuction-v0")
        assert env is not None

    def test_it_resets_and_steps(self):
        env = gym.make("continuousDoubleAuction-v0")
        obs, _infos = env.reset(seed=0)
        inner = env.unwrapped

        assert set(obs) == set(inner.agents)

        for _ in range(4):
            actions = {a: inner.action_spaces[a].sample() for a in inner.agents}
            obs, _rew, _term, _trunc, _infos = env.step(actions)

        assert obs

    def test_the_singular_spaces_are_a_single_agent_s(self):
        """RLlib marks them @OldAPIStack and defines them that way."""
        env = continuousDoubleAuctionEnv({"num_of_agents": 3, "is_render": False})
        first = env.agents[0]

        assert env.observation_space == env.observation_spaces[first]
        assert env.action_space == env.action_spaces[first]

    def test_the_plural_spaces_are_still_the_per_agent_dicts(self):
        """The pair RLlib's new API stack reads must be undisturbed."""
        env = continuousDoubleAuctionEnv({"num_of_agents": 3, "is_render": False})

        assert set(env.observation_spaces) == set(env.agents)
        assert set(env.action_spaces) == set(env.agents)

    def test_metadata_uses_the_gymnasium_key(self):
        """`render.modes` is the pre-gymnasium spelling and made `make` warn."""
        assert "render_modes" in continuousDoubleAuctionEnv.metadata
        assert "render.modes" not in continuousDoubleAuctionEnv.metadata


class TestVisualizeIsAPackage:
    def test_it_is_importable(self):
        import gym_continuousDoubleAuction.visualize  # noqa: F401

    def test_its_entry_point_module_imports(self):
        pytest.importorskip("matplotlib")
        import gym_continuousDoubleAuction.visualize.run_all  # noqa: F401

    def test_find_packages_lists_it(self):
        """What a wheel actually carries, without building one.

        `find_packages` is what `setup.py` calls, and it lists only directories
        with an `__init__.py`. Run from the repo root, as setup.py is.
        """
        import pathlib

        root = pathlib.Path(
            gym_continuousDoubleAuction.__file__
        ).resolve().parent.parent
        packages = find_packages(
            where=str(root),
            exclude=["*test", "*test.*", "test.*", "test"],
        )

        assert "gym_continuousDoubleAuction.visualize" in packages
