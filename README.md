# What's in this repository?
This is WIP.

A custom MARL(multi-agent reinforcement learning) environment where multiple
agents trade against one another in a CDA(continuous double auction).

# What is ready?
An example of using RLlib to pit 1 PPO agent against 3 random agents using this
CDA environment is available in CDA_env_disc_RLlib.py

# Dependencies:
1) OpenAI's Gym
2) Ray & RLlib

# Installation:
The environment is installable via pip.
```
cd gym-continuousDoubleAuction
```
```
pip install -e .
```

# TODO:
1) custom RLlib workflow
2) parametric or hybrid action space
3) more documentation

# Acknowledgements:
The orderbook matching engine is adapted from
https://github.com/dyn4mik3/OrderBook
