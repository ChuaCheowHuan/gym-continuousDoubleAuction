"""The per-episode activity tally and the small readers around it (issue #253).

Split out of the league callback: these are plain functions of an `info` dict, with no
callback state, so they can be tested alone.
"""

from gym_continuousDoubleAuction.train.episode_record import REWARD_TERMS


def new_tally() -> dict:
    """A fresh per-episode tally.

    Running sums rather than a retained series: the variance share in
    `_log_reward_terms` needs only the first two moments, and an episode is
    `max_step` x `num_agents` agent-steps - keeping them all to compute five
    numbers at the end is the memory cost doc/21 §2.2 is about.
    """
    return {
        # Env steps and agent-steps are different denominators: the fractions
        # are per agent-step, while the episode record is keyed by env step.
        "steps": 0,
        "agent_steps": 0,
        "passes": 0,
        "rejections": 0,
        # modify/cancel actions that found no order to act on. The third
        # silent no-op beside a pass and a refusal (doc/15 S4-14).
        "unmatched": 0,
        # Agent-steps on which at least one observation element was clipped to
        # the declared bounds (doc/15 S4-15). A bound that is wrong for the
        # market shows here, not as a silent saturation.
        "clipped_steps": 0,
        # Per agent, because the maker share summed over *all* agents is a
        # tautology: `process_acc` runs once per side of every trade, both
        # sides increment `num_trades_step`, and only the passive side
        # increments `num_passive_fills_step` - so the aggregate is exactly 0.5
        # in every episode of a closed double auction, whatever anyone did.
        # What carries information is whether one agent is specialising as a
        # maker, which is a statement about the spread across agents.
        #
        # Accumulated here rather than read from the last step's info, because
        # both are *per-step* counters that `exchg_helper` zeroes on every step.
        # Only `num_trades` is cumulative, so pairing it with a step counter
        # would divide an episode's trades by one step's passive fills.
        "per_agent_fills": {},
        # The last NAV string each agent reported, carried forward so the
        # conservation check can still add up after an agent stops reporting.
        # A bankrupt agent is terminated and drops out of `info` from its
        # terminal step onward (doc/15 S2-4), and the check used to read only
        # `get_infos(-1)` - so a terminated agent's NAV silently vanished from
        # the total and the ledger looked broken when it was not. Kept as the
        # exact `str()` of the Decimal, which is the whole reason `info["NAV"]`
        # is a string.
        "last_nav": {},
        "term_sum": {term: 0.0 for term in REWARD_TERMS},
        "term_sq": {term: 0.0 for term in REWARD_TERMS},
        # Per agent, O(1) each: Sharpe, drawdown and the rest of S3-9.
        "performance": {},
    }


def market_mid(info):
    """The midpoint of the best quotes in an agent's `info`, else the last price, else None."""
    bid, ask = as_float(info.get("best_bid")), as_float(info.get("best_ask"))
    if bid and ask and bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    last = as_float(info.get("last_price"))
    return last if last and last > 0 else None


def as_float(value):
    """float(value), or None if it is absent or not a number.

    `info["NAV"]` is a string by design (doc/11 §2.6) and `spread` is None on a
    one-sided book, so both cases are ordinary here rather than exceptional.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
