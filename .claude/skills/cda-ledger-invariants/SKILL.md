---
name: cda-ledger-invariants
description: After any change to envs/orderbook/, envs/account/, envs/agent/trader.py, the matching or clearing regimes, fees or liquidation, or on any report of negative cash, broken NAV conservation or a crossed book, run seeded random play over the market-config grid and check the ledger on every step, before and after the change.
---

# Check the ledger holds under random play

Example tests pin the cases someone thought of. Seeded random play over the whole env found
what they missed: overdrawn agents under both clearing modes (S2-14, S2-15) and a crossed book
that made the next batch raise `KeyError` (`docs/29_fixed_issues.md`). The Hypothesis suite in
`test_orderbook_properties.py` covers the book alone; these properties need the whole env.

## Steps

1. **Before** (only when changing the source): `git stash push -- gym_continuousDoubleAuction/envs`,
   run step 2, `git stash pop`. Keep the table.
2. **Run the scan:**
   `CDA_LOG_LEVEL=WARNING python .claude/skills/cda-ledger-invariants/scripts/scan_ledger.py`
   (defaults: 160 seeds x 80 steps, 4 agents, 3,000 cash, prices 20 to 60; about 2 minutes).
   For a thin-cash stress, add `--seeds 60 --agents 8 --cash 300 --steps 150`.
   It covers `{sequential, batch} x {fees 0, 100 bps} x {liquidation off, market_adl}` and
   checks every step that
   - `sum(NAV) + env.fees_collected == agents x init_cash`, exactly (Decimal);
   - `cash + cash_on_hold >= 0` for every trader whose NAV is positive;
   - `best_bid < best_ask` whenever both sides rest;
   - `step` raises nothing.
   Exit status 1 means some invariant failed; the row names the seeds.
3. **After:** run it again on the changed source and compare the two tables row by row.
4. **A hit:** reproduce the first failing seed alone (`--seeds` is a range from 0, so copy
   `scan()` into a scratch script with that one seed), then follow `cda-verify-finding`. Put the
   failing seed into a unit test so it stays fixed.

## Guardrails

- Seed every action space (the script does: `seed * 1000 + agent index`). Unseeded
  `action_space.sample()` makes a failure unrepeatable.
- Under `market_adl` a trader closed out under water owes the shortfall, so its cash is negative
  by design. The script counts only solvent overdrafts. A first draft that counted every
  negative balance reported 34 to 607 false hits per row.
- 160 seeds takes minutes, not seconds. It is not in the default suite. Run it when the ledger
  changes, and say in the PR that you did.
- Last clean run: 2026-11-08, master `7f35535`, every row 0 at both sizes.
