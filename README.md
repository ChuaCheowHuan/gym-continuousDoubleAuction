This is **WIP**.

# What's in this repository?
A custom MARL(multi-agent reinforcement learning) environment where multiple
agents trade against one another in a CDA(continuous double auction).

# What is ready?
An example of using RLlib to pit 1 PPO agent against 3 random agents using this
CDA environment is available in CDA_env_disc_RLlib.py

PPO agent is using policy 0 while policies 1 to 3 are used by the random agents
![Agents' performance from Tensorboard:](/pic/agent0and1.png)
![](/pic/agent2and3.png)

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
