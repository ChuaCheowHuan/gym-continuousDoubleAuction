"""The NAV conservation audit, as functions of the finished episode (issue #253).

Money is conserved: the traders' NAVs plus the fees they paid the exchange equal the
starting cash. The callback's `on_episode_end` used to hold all of this inline; here the
reading of the env's ledger and the arithmetic are plain functions that can be tested
without RLlib, and the callback keeps the hook, the metrics and the decision to log.
"""
from decimal import Decimal
from typing import Dict, List, NamedTuple, Optional


def fees_configured(env_runner, env) -> bool:
    """Whether the run charges exchange fees, from its env config or the env."""
    rates = []
    config = getattr(getattr(env_runner, "config", None), "env_config", None)
    if isinstance(config, dict):
        rates += [config.get("maker_fee_bps", 0), config.get("taker_fee_bps", 0)]
    env_obj = getattr(env, "unwrapped", env)
    rates += [getattr(env_obj, "maker_fee_bps", 0), getattr(env_obj, "taker_fee_bps", 0)]
    def on(rate):
        try:
            return not isinstance(rate, bool) and Decimal(str(rate)) != 0
        except Exception:       # None, or anything that is not a number
            return False
    return any(on(r) for r in rates)


def ledger_fees(env, env_index, num_agents):
    """The exchange's fee ledger from the finished env's accounts, or None.

    Money is conserved with the fees counted: the traders' NAVs plus what
    they paid the exchange equal the starting cash. An account with no
    `fees_paid` (a test double, an env without fees) paid none.
    """
    envs = getattr(env, "envs", None)
    if envs is not None:
        try:
            env = envs[env_index]
        except (IndexError, TypeError):
            return None
    env = getattr(env, "unwrapped", env)
    traders = getattr(env, "traders", None)
    if not traders or len(traders) != num_agents:
        return None
    try:
        return sum((Decimal(str(getattr(t.acc, "fees_paid", 0))) for t in traders),
                   Decimal(0))
    except AttributeError:
        return None


def ledger_navs(env, env_index, last_info, num_agents) -> Optional[Dict[str, Decimal]]:
    """Every trader's NAV from the finished env's own accounts, or None.

    `env` is what RLlib hands the hook: the vector env on an env runner
    (the episode's env is `env.envs[env_index]`), or a bare env. Its
    vector wrapper resets a finished sub-env on the *next* `step()`
    (`autoreset_mode="next_step"`), so at `on_episode_end` the traders
    still hold this episode's accounts.

    That is an assumption about RLlib, so it is checked rather than
    trusted: every NAV the final step reported must equal the account it
    came from. If any differs, or there are no traders to read (a test
    double, another env), the answer is None and the caller falls back to
    what was reported.
    """
    envs = getattr(env, "envs", None)
    if envs is not None:
        try:
            env = envs[env_index]
        except (IndexError, TypeError):
            return None
    env = getattr(env, "unwrapped", env)
    traders = getattr(env, "traders", None)
    if not traders or len(traders) != num_agents:
        return None

    try:
        navs = {f"agent_{t.ID}": Decimal(str(t.acc.nav)) for t in traders}
    except AttributeError:
        return None
    if len(navs) != num_agents:
        return None

    for agent_key, info in (last_info or {}).items():
        reported = info.get("NAV") if isinstance(info, dict) else None
        if reported is None:
            continue
        if navs.get(agent_key) != Decimal(str(reported)):
            return None
    return navs


def run_parameters(env_runner, env, init_cash, num_agents):
    """`(init_cash, num_agents)` for the episode, from the most specific source that has them.

    The env runner's config first, then the env object (through `unwrapped` when it has
    one). `init_cash` and `num_agents` come in as the fallbacks.
    """
    # 1. The env runner's config
    if hasattr(env_runner, "config"):
        env_config = getattr(env_runner.config, "env_config", {})
        init_cash = env_config.get("init_cash", init_cash)
        num_agents = env_config.get("num_of_agents", num_agents)

    # 2. The env object directly or via unwrapped
    if hasattr(env, "unwrapped"):
        env_obj = env.unwrapped
        if hasattr(env_obj, "init_cash"):
            init_cash = env_obj.init_cash
        if hasattr(env_obj, "num_of_agents"):
            num_agents = env_obj.num_of_agents
    elif hasattr(env, "init_cash"):
        init_cash = env.init_cash
        num_agents = getattr(env, "num_of_agents", num_agents)
    return init_cash, num_agents


class NavTotal(NamedTuple):
    """What the agents' NAVs add up to, and the lines that say where each came from."""
    total: Decimal
    lines: List[str]


def sum_navs(last_info, carried, ledger, num_agents) -> NavTotal:
    """Add up every agent's NAV for the conservation check.

    Decimal all the way: the ledger is Decimal end to end and `info["NAV"]` is its exact
    `str()`, so the comparison stays exact. An agent terminated mid-episode is absent from
    the final step's `info`, so its last reported NAV (`carried`) stands in - but only
    when the finished env's own accounts (`ledger`) cannot be reached, because a
    terminated agent holding a position keeps moving after its last report.
    """
    total = Decimal(0)
    lines = []
    for i in range(num_agents):
        agent_key = f"agent_{i}"
        info = last_info.get(agent_key) if last_info else None
        reported = info.get("NAV") if isinstance(info, dict) else None
        note = ""
        if ledger is not None:
            if reported is None:
                note = " (terminated; marked to the end of the episode)"
            reported = ledger[agent_key]
        elif reported is None:
            reported = carried.get(agent_key)
            if reported is not None:
                note = " (terminated; last reported)"
        if reported is not None:
            nav = Decimal(str(reported))
            total += nav
            lines.append(f"  {agent_key} NAV: {nav:,.2f}{note}")
    return NavTotal(total, lines)


def report(episode_id, nav: NavTotal, fees, total_initial_cash) -> str:
    """The multi-line account of an episode's NAV check that goes to the log."""
    return "\n".join(
        [f"Episode {episode_id} NAV verification"]
        + nav.lines
        + [f"  Total NAV: {nav.total:,.2f}"]
        + ([f"  Exchange fees collected: {fees:,.2f}"] if fees else [])
        + [f"  Expected total initial cash: {total_initial_cash:,.2f}"]
    )
