"""
Run the CDA environment with uniformly-random agents, no learning involved.

This is the quickest way to check the environment and matching engine still
work end to end:

    python -m gym_continuousDoubleAuction.CDA_env_rand
    python gym_continuousDoubleAuction/CDA_env_rand.py --steps 500 --agents 4

Previously this script was broken in three separate ways and had been for a
while (it failed identically on the older Ray/gymnasium pin):

  * it called the env with six positional args, but the constructor takes a
    single config dict;
  * it iterated `env.agents` expecting Trader objects, when that attribute is a
    list of agent-ID strings;
  * it keyed the action dict by integer index rather than agent ID.

Actions are now sampled from the env's own action space, so this stays valid if
the action space changes again.
"""
import argparse
import sys

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)


def run_random(num_agents=4, max_step=1000, init_cash=1_000_000, is_render=False,
               seed=None):
    """Step the env with random actions until it terminates or runs out of steps.

    Returns:
        The number of steps actually taken.
    """
    env = continuousDoubleAuctionEnv({
        "num_of_agents": num_agents,
        "init_cash": init_cash,
        "tick_size": 1,
        "tape_display_length": 10,
        "max_step": max_step,
        "is_render": is_render,
    })

    env.reset(seed=seed)
    if seed is not None:
        for agent_id in env.agents:
            env.action_spaces[agent_id].seed(seed)

    steps = 0
    for _ in range(max_step):
        actions = {
            agent_id: env.action_spaces[agent_id].sample()
            for agent_id in env.agents
        }
        _obs, _rewards, terminateds, truncateds, _infos = env.step(actions)
        steps += 1

        if terminateds.get("__all__", False) or truncateds.get("__all__", False):
            break

    return steps


def main(argv=None):
    p = argparse.ArgumentParser(description="Random-agent CDA simulation.")
    p.add_argument("--agents", type=int, default=4)
    p.add_argument("--steps", type=int, default=1000)
    p.add_argument("--init-cash", type=int, default=1_000_000)
    p.add_argument("--render", action="store_true")
    p.add_argument("--seed", type=int, default=None)
    args = p.parse_args(argv)

    steps = run_random(
        num_agents=args.agents,
        max_step=args.steps,
        init_cash=args.init_cash,
        is_render=args.render,
        seed=args.seed,
    )
    print(f"CDA_env_rand: completed {steps} steps with {args.agents} random agents.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
