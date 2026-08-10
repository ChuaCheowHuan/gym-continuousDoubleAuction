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
"""
from setuptools import setup, find_packages

setup(
    name="gym_continuousDoubleAuction",
    version="0.1.0",
    description=(
        "A multi-agent continuous double auction (limit order book) environment "
        "for reinforcement learning, with RLlib league-based self-play."
    ),
    packages=find_packages(exclude=["*test", "*test.*", "test.*", "test"]),
    python_requires=">=3.10",
    install_requires=[
        # Kept deliberately narrow: these are what the *environment* needs to
        # import. The RL training stack (ray[rllib], torch) lives in
        # requirements.txt so the env stays usable without it.
        "gymnasium==1.2.2",
        "numpy>=2.5,<3",
        "pandas>=3.0,<4",
        "sortedcontainers>=2.4",
        "tabulate>=0.10",
    ],
    extras_require={
        # pip install -e ".[rllib]"
        "rllib": [
            "ray[rllib]==2.56.1",
            "torch>=2.13.0,<3",
            "tensorboardX>=2.6.5",
        ],
        "plot": ["matplotlib>=3.11,<4", "scikit-learn>=1.9,<2", "scipy>=1.18,<2"],
        "dev": ["pytest>=8"],
    },
)
