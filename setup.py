"""
Packaging for gym-continuousDoubleAuction.

Install (editable, for development):
    pip install -r requirements.txt
    pip install -e .

The env registers itself with gymnasium on import of the top-level package, so
after installing you can do either of:

    import gym_continuousDoubleAuction            # triggers register()
    env = gymnasium.make("continuousDoubleAuction-v0")

    from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
        continuousDoubleAuctionEnv)
    env = continuousDoubleAuctionEnv({"num_of_agents": 8, ...})

For RLlib the second form is what you want, registered via tune.register_env -
see gym_continuousDoubleAuction/train/train.py.

------------------------------------------------------------------------------
The config tree ships inside the wheel
------------------------------------------------------------------------------
`config/` is checked in at the repo root, which is where `config_loader.
config_dir()` looks first and where every doc path points. That location is not
inside the package, so it was not in the built distribution at all: a wheel
built from this tree carried zero JSON files, and because the config reads are
default arguments evaluated at class-definition time (`Exchg_Helper`,
`Reward_Helper`, `Action_Helper`, `State_Helper`, `Trader`, `Account`), an
installed copy raised `FileNotFoundError` on *import* rather than on use.

`_BuildPyWithConfig` stages the root `config/*.json` into
`gym_continuousDoubleAuction/config/` at build time, and `package_data` puts it
in the distribution - which is exactly the second location `config_dir()`
already searched and never found. Nothing moves and no path in the docs
changes. The staged copy is a build artefact, is git-ignored, and is never
preferred in-tree because `config_dir()` checks the repo root first.
"""
import os
import shutil

from setuptools import setup, find_packages
from setuptools.command.build_py import build_py as _build_py

_HERE = os.path.abspath(os.path.dirname(__file__))
_PACKAGE = "gym_continuousDoubleAuction"

#: Canonical config tree (repo root) and the in-package copy built from it.
_CONFIG_SRC = os.path.join(_HERE, "config")
_CONFIG_DST = os.path.join(_HERE, _PACKAGE, "config")


def _stage_config():
    """Copy `config/*.json` into the package so the build can include it.

    Rebuilt from scratch each time rather than updated in place, so a file
    deleted from the canonical tree cannot survive in the staged one and end up
    shipped. Silently does nothing when the source is absent, which is the case
    when building from an unpacked sdist that already carries the staged copy.
    """
    if not os.path.isdir(_CONFIG_SRC):
        return
    shutil.rmtree(_CONFIG_DST, ignore_errors=True)
    os.makedirs(_CONFIG_DST, exist_ok=True)
    for name in os.listdir(_CONFIG_SRC):
        if name.endswith(".json"):
            shutil.copy2(os.path.join(_CONFIG_SRC, name),
                         os.path.join(_CONFIG_DST, name))


class _BuildPyWithConfig(_build_py):
    """`build_py`, with the config tree staged into the package first."""

    def run(self):
        _stage_config()
        super().run()


setup(
    name="gym_continuousDoubleAuction",
    version="0.1.0",
    description=(
        "A multi-agent continuous double auction (limit order book) environment "
        "for reinforcement learning, with RLlib league-based self-play."
    ),
    packages=find_packages(exclude=["*test", "*test.*", "test.*", "test"]),
    package_data={_PACKAGE: ["config/*.json"]},
    cmdclass={"build_py": _BuildPyWithConfig},
    # Only 3.12 is CI-tested (see .github/workflows/tests.yml). >=3.10 is not
    # claimed: numpy stopped shipping 3.10/3.11 wheels partway through its 2.x
    # series, which is exactly what broke the old 3.11 CI job.
    python_requires=">=3.12",
    install_requires=[
        # What `import gym_continuousDoubleAuction.envs` actually needs. This
        # list used to be "deliberately narrow" on the stated reasoning that
        # the env stays usable without the RL stack - which was not true of the
        # code: `continuousDoubleAuction_env` subclasses `MultiAgentEnv`, so
        # ray[rllib] is a hard import. It was reachable only via an extra, so
        # `pip install gym_continuousDoubleAuction` produced a package that
        # could not be imported. The list now matches the imports.
        "gymnasium==1.2.2",
        # See requirements.txt for why the floor is 2.2, not 2.5: numpy has no
        # 3.10 wheels from 2.3.0 onward, and no 3.11 wheels from 2.5.0 onward.
        "numpy>=2.2,<3",
        "pandas>=3.0,<4",
        "sortedcontainers>=2.4",
        "tabulate>=0.10",
        # Base class of the env. Pinned to the same release requirements.txt
        # pins, because Ray 2.56.x hard-pins gymnasium==1.2.2 and the two
        # cannot be bumped independently.
        "ray[rllib]==2.56.1",
        # `six.moves.cStringIO` in envs/orderbook/{orderbook,orderlist}.py.
        # A Python-2 shim that `io.StringIO` replaces, but envs/orderbook/ is
        # off-limits to changes (doc/15 S3-4), so the dependency is declared
        # rather than removed. It had been resolving only by accident, as a
        # transitive dependency of pandas.
        "six>=1.16",
    ],
    extras_require={
        # pip install -e ".[rllib]"
        #
        # ray[rllib] moved to install_requires above; this keeps its name and
        # stays valid to install, and now carries the rest of the *training*
        # stack - what train/ needs beyond what the env needs.
        "rllib": [
            "torch>=2.13.0,<3",
            "tensorboardX>=2.6.5",
        ],
        "plot": ["matplotlib>=3.11,<4", "scipy>=1.18,<2"],
        "dev": ["pytest>=8"],
    },
)
