"""The per-episode activity tally, its metrics, and the small readers around it (issue #253).

Split out of the league callback. `ActivityLog` holds the tallies of the episodes in flight
on this process and turns a finished episode's tally into metrics; it needs nothing from the
callback but the mark-out horizons, so it can be built and tested alone.
"""

import math

from gym_continuousDoubleAuction.logging_setup import get_logger
from gym_continuousDoubleAuction.train.episode_record import REWARD_TERMS
from gym_continuousDoubleAuction.train.performance import PerformanceTally

logger = get_logger(__name__)

#: Per-module mean trades per episode, logged by the env runners at episode end
#: and read by the driver's champion check (docs/29 S3-11). Nested under the
#: module id: `result["env_runners"][MODULE_TRADES_METRIC]["policy_0"]`.
MODULE_TRADES_METRIC = "module_trades_per_episode"

#: Prefix of the per-module risk-adjusted metrics (docs/29 S3-9): one metric per
#: name in `performance.METRICS`, e.g. `module_sharpe`, each nested under the
#: module id like `MODULE_TRADES_METRIC` and meaned over the iteration's episodes.
MODULE_PERFORMANCE_PREFIX = "module_"


def new_tally() -> dict:
    """A fresh per-episode tally.

    Running sums rather than a retained series: the variance share in
    `_log_reward_terms` needs only the first two moments, and an episode is
    `max_step` x `num_agents` agent-steps - keeping them all to compute five
    numbers at the end is the memory cost docs/11 §5.2.2 is about.
    """
    return {
        # Env steps and agent-steps are different denominators: the fractions
        # are per agent-step, while the episode record is keyed by env step.
        "steps": 0,
        "agent_steps": 0,
        "passes": 0,
        "rejections": 0,
        # modify/cancel actions that found no order to act on. The third
        # silent no-op beside a pass and a refusal (docs/29 S4-14).
        "unmatched": 0,
        # Agent-steps on which at least one observation element was clipped to
        # the declared bounds (docs/29 S4-15). A bound that is wrong for the
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
        # terminal step onward (docs/29 S2-4), and the check used to read only
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

    `info["NAV"]` is a string by design (docs/11 §2.6) and `spread` is None on a
    one-sided book, so both cases are ordinary here rather than exceptional.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class ActivityLog:
    """The tallies of the episodes in flight on this process, and the metrics they become."""

    #: How many unfinished episodes' tallies to keep. `on_episode_end` is not
    #: called for episodes a force-reset discards (docs/11 §5.3.2), so a dict keyed
    #: by episode id and pruned only there grows for the life of the process.
    #: Generous next to any realistic `num_envs_per_env_runner`, and three ints
    #: per entry, so the cap costs nothing and closes the leak.
    MAX_LIVE_EPISODES = 64

    #: Trades an agent needs before its maker share is worth reporting. Below
    #: this the ratio is quantised to almost nothing - one passive fill out of
    #: one trade reads as a perfect market maker - so the maximum across agents
    #: would sit at 1.0 for the whole run on noise alone.
    MIN_TRADES_FOR_MAKER_RATIO = 5

    def __init__(self, markout_horizons=()):
        self.markout_horizons = tuple(markout_horizons)
        self.max_live = self.MAX_LIVE_EPISODES
        # A plain dict, not defaultdict(lambda: ...): the callback holding this is
        # cloudpickled into every checkpoint, and a lambda default_factory is the kind of
        # thing that survives locally and fails on a restore path nobody exercised.
        self.tallies = {}

    def start(self, episode_id) -> None:
        """A new episode: drop old tallies if too many are open, and begin this one's."""
        self.prune()
        self.tallies[episode_id] = new_tally()

    def record_step(self, episode_id, last_info) -> dict:
        """Add one env step's per-agent infos to the episode's tally, and return the tally.

        Counted before anything that can be switched off. These metrics must not depend on
        the episode record being enabled - that is the whole point of counting here rather
        than reading the recorded rows back at episode end.
        """
        tally = self.tally_for(episode_id)
        tally["steps"] += 1
        for agent_id, agent_info in (last_info or {}).items():
            if not isinstance(agent_info, dict):
                continue
            tally["agent_steps"] += 1
            nav = agent_info.get("NAV")
            if nav is not None:
                tally["last_nav"][agent_id] = nav
                tally["performance"].setdefault(
                    agent_id, PerformanceTally(self.markout_horizons)
                ).update(
                    nav,
                    agent_info.get("net_position"),
                    realised=agent_info.get("realised_pnl"),
                    unrealised=agent_info.get("unrealised_pnl"),
                    fill_qty=agent_info.get("fill_qty_step"),
                    fill_value=agent_info.get("fill_value_step"),
                    mid=market_mid(agent_info),
                )
            if agent_info.get("is_pass_action"):
                tally["passes"] += 1
            tally["rejections"] += int(agent_info.get("num_rejected_step", 0) or 0)
            tally["unmatched"] += int(agent_info.get("num_unmatched_step", 0) or 0)
            if int(agent_info.get("num_obs_clipped_step", 0) or 0) > 0:
                tally["clipped_steps"] += 1

            trades = int(agent_info.get("num_trades_step", 0) or 0)
            if trades:
                fills = tally["per_agent_fills"].setdefault(agent_id, {"trades": 0, "passive": 0})
                fills["trades"] += trades
                fills["passive"] += int(agent_info.get("num_passive_fills_step", 0) or 0)

            terms = agent_info.get("reward_terms") or {}
            for term in REWARD_TERMS:
                value = as_float(terms.get(term))
                if value is None:
                    continue
                tally["term_sum"][term] += value
                tally["term_sq"][term] += value * value
        return tally

    def log_episode(self, episode, metrics_logger) -> None:
        """Emit the episode's pass and rejection fractions, then drop the tally.

        `pass_action_fraction` is the metric S1-3 needs. A league whose policies
        collapse to always-pass still clears the promotion threshold, because 0
        beats a negative mean, so the pool fills with snapshots of the
        do-nothing policy and the returns series looks unremarkable while it
        happens. A fraction trending to 1.0 says it outright.

        `order_rejection_fraction` separates the other case returns cannot
        distinguish: an agent that is not trading because it chose not to, from
        one whose every order is refused for want of cash.

        Fractions rather than counts, so the numbers mean the same thing at any
        `num_agents` or `max_step`. window=10 matches the league metrics: a
        single episode's fraction is noisy, and the question is the trend.
        """
        tally = self.tallies.pop(episode.id_, None)
        if not tally or not metrics_logger:
            return

        agent_steps = tally["agent_steps"]
        if agent_steps <= 0:
            # An episode reporting no agent infos at all. Emitting 0.0 here
            # would read as "nothing passed", which is a claim about behaviour
            # this episode gives no evidence for.
            return

        pass_fraction = tally["passes"] / agent_steps
        rejection_fraction = tally["rejections"] / agent_steps
        unmatched_fraction = tally["unmatched"] / agent_steps
        clip_fraction = tally["clipped_steps"] / agent_steps

        metrics_logger.log_value("pass_action_fraction", pass_fraction, window=10)
        metrics_logger.log_value("order_rejection_fraction", rejection_fraction, window=10)
        # A modify or cancel that named no resting order. Together the three
        # fractions bound how much of the league's activity is a no-op: an
        # agent whose policy has drifted to "cancel" at every step scores
        # exactly like one that passes, and neither the return series nor
        # pass_action_fraction would say so.
        metrics_logger.log_value("unmatched_action_fraction", unmatched_fraction, window=10)
        # Share of agent-steps whose observation hit a declared bound. The
        # bounds are measured claims (docs/16 section 16.22); this is the
        # number that says whether the market has since escaped them.
        metrics_logger.log_value("obs_clip_fraction", clip_fraction, window=10)

        self.log_reward_terms(tally, agent_steps, metrics_logger)

        self.log_maker_ratio(tally, metrics_logger)

        self.log_module_trades(episode, tally, metrics_logger)

        self.log_module_performance(episode, tally, metrics_logger)

        logger.debug(
            "episode %s activity: %s agent-steps, %.1f%% pass, %.1f%% rejected, %.1f%% unmatched",
            episode.id_,
            agent_steps,
            100 * pass_fraction,
            100 * rejection_fraction,
            100 * unmatched_fraction,
        )

    def log_module_trades(self, episode, tally, metrics_logger) -> None:
        """Each module's trades in this episode, for the champion check.

        The check runs on the driver, which sees only the compiled result, so
        the counts have to travel as a metric. Keyed by module rather than
        agent because a trainable slot always plays its own module, and the
        champion check asks about a module. An agent that never traded is
        logged as 0 rather than left out: absence reads as "not measured", and
        0 is exactly the measurement the guard is after.

        `reduce="mean"` with no window takes the mean over the episodes of one
        iteration and starts again, so the number describes the iteration whose
        policy is being promoted, not a trailing window that spans the last one.
        """
        module_for = getattr(episode, "module_for", None)
        if module_for is None:
            return
        for agent_id in set(tally["last_nav"]) | set(tally["per_agent_fills"]):
            module_id = module_for(agent_id)
            if module_id is None:
                continue
            trades = tally["per_agent_fills"].get(agent_id, {}).get("trades", 0)
            metrics_logger.log_value(
                (MODULE_TRADES_METRIC, module_id),
                float(trades),
                reduce="mean",
            )

    def log_module_performance(self, episode, tally, metrics_logger) -> None:
        """Each module's risk-adjusted performance in this episode (docs/29 S3-9).

        Per module, like the trade counts, because the question is "how does this
        policy compare", and meaned over the iteration's episodes. A metric that is
        undefined for an agent's episode (a Sharpe with no variance: it never
        traded) is left out rather than logged as 0, which would read as a
        measurement; the mean is over the episodes where it exists. When two
        agents played one module in an episode their values are averaged first, so
        an episode counts once.
        """
        module_for = getattr(episode, "module_for", None)
        if module_for is None:
            return
        per_module = {}
        for agent_id, perf in tally["performance"].items():
            module_id = module_for(agent_id)
            if module_id is None:
                continue
            for name, value in perf.summary().items():
                if value is not None and math.isfinite(value):
                    per_module.setdefault((name, module_id), []).append(value)
        for (name, module_id), values in per_module.items():
            metrics_logger.log_value(
                (MODULE_PERFORMANCE_PREFIX + name, module_id),
                sum(values) / len(values),
                reduce="mean",
            )

    def log_maker_ratio(self, tally, metrics_logger) -> None:
        """The most maker-like agent's share of its own fills.

        docs/13 §7's market-making uptake, and the one shape of it that says
        anything. The *aggregate* maker share is a tautology in a closed double
        auction: `process_acc` runs once per side of every trade, both sides
        increment `num_trades_step`, and only the passive side increments
        `num_passive_fills_step` - so summed over all agents it is exactly 0.5
        in every episode regardless of behaviour. A real 3-iteration run
        reported 0.5000 three times, which is what exposed it.

        The maximum across agents does carry information: 0.5 everywhere means
        nobody is specialising, while one agent at 0.9 against the others'
        0.3 is a policy that has learnt to quote and wait. It is reported only
        for agents with enough fills to distinguish that from noise.

        Nothing is emitted when no agent qualifies. 0.0 would read as "everyone
        crossed the spread", which is a claim about behaviour an episode with no
        trades gives no evidence for.
        """
        ratios = [
            fills["passive"] / fills["trades"]
            for fills in tally["per_agent_fills"].values()
            if fills["trades"] >= self.MIN_TRADES_FOR_MAKER_RATIO
        ]
        if not ratios:
            return
        metrics_logger.log_value("maker_fill_ratio_max", max(ratios), window=10)

    def log_reward_terms(self, tally, agent_steps, metrics_logger) -> None:
        """The reward decomposition, reduced to a mean and a variance share.

        docs/07 §6.4 prescribes watching how the five signed contributions split
        the reward's variance; docs/11 §2.4 recorded that the terms were captured
        per step in `info` and never aggregated, so the split could only be
        computed after the fact from a file. These two metrics are that
        aggregation, and they are what makes "the drawdown penalty is now 80% of
        the signal" a thing a run says while it is happening.

        The variance is taken from running sums rather than a retained series:
        an episode is thousands of agent-steps and holding all of them to
        compute one number at the end is exactly the memory cost §2.2 was about.
        `E[x²] - E[x]²` can go slightly negative on a near-constant term through
        cancellation, so it is clamped - a negative variance is arithmetic, not
        a finding.

        The shares are normalised across the five terms, so they sum to 1 and
        answer "which term is driving the reward" rather than "how big is the
        reward", which the means already answer. An episode where every term is
        constant has no variance to split and reports no share at all, rather
        than dividing by zero or claiming an even split.
        """
        variances = {}
        for term in REWARD_TERMS:
            mean = tally["term_sum"][term] / agent_steps
            variance = max(0.0, tally["term_sq"][term] / agent_steps - mean * mean)
            variances[term] = variance
            metrics_logger.log_value(
                f"reward_term_mean_{term}",
                mean,
                window=10,
            )

        total = sum(variances.values())
        if total <= 0.0:
            return
        for term, variance in variances.items():
            metrics_logger.log_value(
                f"reward_term_var_share_{term}",
                variance / total,
                window=10,
            )

    def log_episode_account(self, last_info, metrics_logger) -> None:
        """Per-agent account state at the end of the episode, as metrics.

        docs/11 §2.3 and §4 item 2: every one of these is already in the per-step
        `info`, and none of it was reduced into anything a run could watch. The
        end of the episode is the right moment for the state ones - NAV,
        drawdown, inventory are terminal quantities, not averages over a
        trajectory - and the two counters are per-episode totals by
        construction.

        Aggregated across agents rather than emitted per agent, because the
        league reassigns opponents every episode: a metric named for `agent_3`
        would be a different policy each time, which is the same mislabelling
        `module_episode_returns_mean` exists to avoid.
        """
        navs, drawdowns, positions, trades = [], [], [], []
        for info in (last_info or {}).values():
            if not isinstance(info, dict):
                continue
            nav = as_float(info.get("NAV"))
            if nav is not None:
                navs.append(nav)
            drawdown = as_float(info.get("drawdown"))
            if drawdown is not None:
                drawdowns.append(drawdown)
            position = as_float(info.get("net_position"))
            if position is not None:
                positions.append(abs(position))
            # `num_trades` is the episode total. Deliberately not paired here
            # with `num_passive_fills_step`, which is a *per-step* counter that
            # `exchg_helper` zeroes every step - `maker_fill_ratio` is computed
            # from the running tally instead, where both sides span the same
            # part of the episode.
            trades.append(float(info.get("num_trades") or 0))

        if navs:
            metrics_logger.log_value("episode_nav_mean", sum(navs) / len(navs), window=10)
            metrics_logger.log_value("episode_nav_min", min(navs), window=10)
            metrics_logger.log_value("episode_nav_max", max(navs), window=10)
        if drawdowns:
            metrics_logger.log_value(
                "mean_agent_drawdown",
                sum(drawdowns) / len(drawdowns),
                window=10,
            )
        if positions:
            metrics_logger.log_value(
                "mean_abs_net_position",
                sum(positions) / len(positions),
                window=10,
            )
        if trades:
            metrics_logger.log_value(
                "mean_num_trades",
                sum(trades) / len(trades),
                window=10,
            )

    def tally_for(self, episode_id) -> dict:
        """The tally for this episode, created if the start hook missed it.

        `on_episode_start` is not guaranteed to have run for every episode a
        worker reports on - a restored run picks up mid-flight - and a counter
        that raises KeyError would take down training for the sake of a metric.
        """
        tally = self.tallies.get(episode_id)
        if tally is None:
            self.prune()
            tally = self.tallies[episode_id] = new_tally()
        return tally

    def prune(self) -> None:
        """Drop the oldest tallies once too many episodes are open at once.

        Insertion-ordered, so "oldest" is the episode that started first. An
        episode discarded by a force-reset never reaches `on_episode_end` and so
        never has its tally popped (docs/11 §5.3.2); this is what stops that
        turning into a dict that grows for the life of the worker.
        """
        while len(self.tallies) >= self.max_live:
            episode_id = next(iter(self.tallies))
            del self.tallies[episode_id]
            logger.debug(
                "dropped the activity tally for episode %s, which never ended (%s open, limit %s)",
                episode_id,
                len(self.tallies) + 1,
                self.max_live,
            )
