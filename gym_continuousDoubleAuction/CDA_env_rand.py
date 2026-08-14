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

from gym_continuousDoubleAuction.config_loader import cli_default
from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.logging_setup import configure as configure_logging
from gym_continuousDoubleAuction.logging_setup import get_logger

logger = get_logger("gym_continuousDoubleAuction.CDA_env_rand")


def _cli(key):
    """A default for this script, from `config/cli_defaults.json`."""
    return cli_default("cda_env_rand", key)


def run_random(num_agents=None, max_step=None, init_cash=None, is_render=None,
               seed=None):
    """Step the env with random actions until it terminates or runs out of steps.

    Any argument left as None is read from `config/cli_defaults.json` ->
    cda_env_rand. Keys this script does not set at all - tick_size,
    tape_display_length, the sizing and reward coefficients - fall back to
    `config/env_defaults.json` inside the env.

    Returns:
        The number of steps actually taken.
    """
    if num_agents is None:
        num_agents = _cli("num_agents")
    if max_step is None:
        max_step = _cli("max_step")
    if init_cash is None:
        init_cash = _cli("init_cash")
    if is_render is None:
        is_render = _cli("is_render")

    env = continuousDoubleAuctionEnv({
        "num_of_agents": num_agents,
        "init_cash": init_cash,
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
    # Defaults come from config/cli_defaults.json -> cda_env_rand.
    p.add_argument("--agents", type=int, default=_cli("num_agents"))
    p.add_argument("--steps", type=int, default=_cli("max_step"))
    p.add_argument("--init-cash", type=int, default=_cli("init_cash"))
    p.add_argument("--render", action="store_true", default=_cli("is_render"))
    p.add_argument("--seed", type=int, default=_cli("seed"))
    p.add_argument(
        "--log-level",
        type=str,
        default=_cli("log_level"),
        help="Level for this package's logging. null in cli_defaults.json "
             "means the logging group of tunable_constants.json decides.",
    )
    args = p.parse_args(argv)

    # The env's per-step render writes at DEBUG, so --render without a level
    # would produce nothing at all. Asking for the render is asking for the
    # output it produces; an explicit --log-level still wins.
    configure_logging(args.log_level or ("DEBUG" if args.render else None),
                      force=True)

    steps = run_random(
        num_agents=args.agents,
        max_step=args.steps,
        init_cash=args.init_cash,
        is_render=args.render,
        seed=args.seed,
    )
    logger.info(
        "completed %s steps with %s random agents.", steps, args.agents,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
