"""Seeded random play over a grid of market configs, checking the ledger every step.

    python .claude/skills/cda-ledger-invariants/scripts/scan_ledger.py [--seeds 160] [--steps 80]

For each of {sequential, batch} x {fees 0, 100 bps} x {liquidation off, market_adl} it plays
`--seeds` seeded episodes with uniformly random actions and checks, after every step:

1. sum(NAV) + env.fees_collected == agents x init_cash, exactly (Decimal);
2. cash + cash_on_hold >= 0 for every trader whose NAV is positive (a trader closed out
   under water owes the shortfall: that is its bankruptcy, not an overdraft);
3. best bid < best ask whenever both sides rest;
4. nothing raises out of `step`.

Prints one row per config: agent-steps checked, hits per invariant, the seeds that hit and the
worst value. Exit status is 1 if any invariant failed. Run it before and after a change to the
book, the accounts, fees or liquidation (stash the source to get "before").
"""

from __future__ import annotations

import argparse
import itertools
import sys
import traceback
from decimal import Decimal

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)

GRID = {
    "step_clearing": ["sequential", "batch"],
    "fees": [(0, 0), (100, 100)],
    "liquidation": ["off", "market_adl"],
}


def _config(step_clearing, fees, liquidation, agents, cash):
    maker, taker = fees
    return {
        "num_of_agents": agents,
        "init_cash": cash,
        "max_step": 10**6,
        "initial_price_min": 20,
        "initial_price_max": 60,
        "step_clearing": step_clearing,
        "maker_fee_bps": maker,
        "taker_fee_bps": taker,
        "liquidation": liquidation,
    }


def scan(cfg, seeds, steps):
    hits = {"nav": 0, "cash": 0, "crossed": 0, "raised": 0}
    bad_seeds, worst_cash, agent_steps, first_error = set(), Decimal(0), 0, None
    for seed in range(seeds):
        env = continuousDoubleAuctionEnv(cfg)
        env.reset(seed=seed)
        for i, agent_id in enumerate(env.agents):
            env.action_spaces[agent_id].seed(seed * 1000 + i)
        start = Decimal(cfg["init_cash"]) * cfg["num_of_agents"]
        for _ in range(steps):
            actions = {a: env.action_spaces[a].sample() for a in env.agents}
            try:
                _o, _r, term, trunc, _i = env.step(actions)
            except Exception:  # noqa: BLE001 - every exception is a finding here
                hits["raised"] += 1
                bad_seeds.add(seed)
                first_error = first_error or traceback.format_exc(limit=3)
                break
            agent_steps += len(env.traders)
            total = sum((t.acc.nav for t in env.traders), Decimal(0)) + env.fees_collected
            if total != start:
                hits["nav"] += 1
                bad_seeds.add(seed)
            for t in env.traders:
                free = t.acc.cash + t.acc.cash_on_hold
                # A trader closed out under water (NAV <= 0) legitimately owes cash: the
                # loss beyond its equity is the bankruptcy. Only a solvent overdraft counts.
                if free < 0 and t.acc.nav > 0:
                    hits["cash"] += 1
                    bad_seeds.add(seed)
                    worst_cash = min(worst_cash, free)
            bid, ask = env.LOB.get_best_bid(), env.LOB.get_best_ask()
            if bid is not None and ask is not None and bid >= ask:
                hits["crossed"] += 1
                bad_seeds.add(seed)
            if term.get("__all__") or trunc.get("__all__"):
                break
    return agent_steps, hits, sorted(bad_seeds), worst_cash, first_error


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--seeds", type=int, default=160)
    p.add_argument("--steps", type=int, default=80)
    p.add_argument("--agents", type=int, default=4)
    p.add_argument("--cash", type=int, default=3000)
    args = p.parse_args(argv)

    failed = False
    print("clearing    fees  liquidation  agent-steps  nav  cash<0  crossed  raised  worst  seeds")
    for clearing, fees, liq in itertools.product(*GRID.values()):
        cfg = _config(clearing, fees, liq, args.agents, args.cash)
        n, hits, seeds, worst, err = scan(cfg, args.seeds, args.steps)
        failed |= any(hits.values())
        print(
            f"{clearing:<11} {fees[1]:>4}  {liq:<11}  {n:>11}  {hits['nav']:>3}  {hits['cash']:>6}"
            f"  {hits['crossed']:>7}  {hits['raised']:>6}  {worst:>5}  {seeds[:8]}"
        )
        if err:
            print("    first exception:\n    " + err.replace("\n", "\n    "))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
