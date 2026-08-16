from decimal import Decimal

import logging
import numpy as np
import zlib

from ray.rllib.callbacks.callbacks import RLlibCallback
from ray.rllib.core import (
    COMPONENT_LEARNER,
    COMPONENT_LEARNER_GROUP,
    COMPONENT_RL_MODULE,
)
from ray.rllib.core.rl_module.rl_module import RLModuleSpec
from ray.rllib.utils.metrics import ENV_RUNNER_RESULTS

from gym_continuousDoubleAuction.config_loader import env_default, group
from gym_continuousDoubleAuction.logging_setup import get_logger
from gym_continuousDoubleAuction.train.episode_record import (
    EpisodeRecorder,
    REWARD_TERMS,
)
from gym_continuousDoubleAuction.train.policy.policy_handler import (
    CHAMPION_PREFIX,
    POLICY_PREFIX,
    policy_id,
)

logger = get_logger(__name__)

# Per-module mean return over the iteration, keyed by ModuleID. This is the
# new-API-stack replacement for the old `hist_stats["policy_<id>_reward"]` /
# `policy_reward_mean`, neither of which exists any more.
MODULE_EPISODE_RETURNS_MEAN = "module_episode_returns_mean"

#: Count of episodes whose NAV conservation check failed, summed over the
#: iteration. This is how a violation reaches the driver.
#:
#: Raising inside `on_episode_end` cannot serve that purpose once sampling is
#: remote. The hook runs on the env runner, so the raise arrives as a
#: `RayTaskError` from `sample()`, and `restart_failed_env_runners` - True by
#: default - makes `EnvRunnerGroup` log it through Ray's own logger and restart
#: the actor: `algo.train()` returns normally and the run carries on training on
#: the ledger the check just condemned (doc/21 §2.1). Worse, the raise loses the
#: evidence: `synchronous_parallel_sample` asks each runner for
#: `(sample(), get_metrics())` in one call, so a `sample()` that throws means
#: `get_metrics()` never runs and that runner's metrics - including this one -
#: are discarded with the error.
#:
#: So the hook reports and returns, and `train._check_nav_conservation` raises
#: on the driver, where an exception genuinely ends the run. `reduce="sum"`
#: with no window makes it a per-iteration count across every runner.
NAV_VIOLATIONS_METRIC = "nav_conservation_violations"


def _new_tally() -> dict:
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
        "term_sum": {term: 0.0 for term in REWARD_TERMS},
        "term_sq": {term: 0.0 for term in REWARD_TERMS},
    }


def _as_float(value):
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


class SelfPlayCallback(RLlibCallback):
    _DISABLED = object()  # distinguishes "not passed" from an explicit None

    def __init__(
        self,
        num_trainable_policies=None,
        num_random_policies=None,
        std_dev_multiplier=None,
        max_champions=None,
        min_iterations_between_champions=None,
        original_opponent_weight=None,
        champion_weight=None,
        episode_data_dir=_DISABLED,
        nav_tolerance=None,
        strict_nav_check=None,
        episode_sample_every=None,
        episode_max_bytes=None,
        episode_rows_per_file=None,
        run_id="",
    ):
        """
        Initialize league-based self-play callback with generalized agent configuration.

        Args:
            num_trainable_policies (k): Number of policies that learn (Agents 0 to k-1)
            num_random_policies (m): Number of initial fixed/random policies (Agents k to n-1)
            std_dev_multiplier: Number of standard deviations above mean to trigger snapshot
            max_champions: Maximum number of champions to maintain (rolling window)
            min_iterations_between_champions: Cooldown iterations between snapshots
            original_opponent_weight: Priority weight for original fixed policies (Agents k to n-1)
            champion_weight: Priority weight for frozen champion policies
            episode_data_dir: Where the per-step episode record is written, as
                Parquet. Must be an absolute path: this object is pickled into
                every env runner, and a relative one would be resolved against
                whatever working directory that worker happened to inherit
                (doc/21 §2.3). None disables the record entirely - and now
                disables the *accumulation* too, which the flag previously did
                not (doc/21 §2.2).
            nav_tolerance: Absolute cash tolerance for the episode-end NAV
                conservation check.
            strict_nav_check: Stop the run on a conservation violation. Acted on
                by the driver, not here - see `NAV_VIOLATIONS_METRIC`. The
                `nav_conservation_error` metric is emitted either way, and it is
                carried on this object only so a restored callback keeps the
                setting.
            episode_sample_every: Record one episode in N. 1 records every one.
            episode_max_bytes: Cap on the episode record each process keeps.
                0 disables the cap.
            episode_rows_per_file: Rows buffered before a Parquet file is
                written. At `num_agents` rows per env step, this is
                `episode_rows_per_file / num_agents` steps per file.
            run_id: Written into every recorded row, so two runs sharing an
                episode directory stay separable.

        Any argument left as None is read from `config/train_config.json`: the
        league knobs from its `league_self_play` group, and the two policy
        counts derived from `num_agents` / `num_trained_agents`. `train.py`
        passes all of them explicitly, so the config lookup is what a direct
        instantiation gets. `episode_data_dir` uses a private sentinel rather
        than None because None is a meaningful value for it - it disables the
        pickles.

        Total Agents n = k + m
        """
        super().__init__()

        league = group("train_config.json", "league_self_play")
        env = group("train_config.json", "environment")

        if num_trainable_policies is None:
            num_trainable_policies = env["num_trained_agents"]
        if num_random_policies is None:
            num_random_policies = env["num_agents"] - env["num_trained_agents"]
        if std_dev_multiplier is None:
            std_dev_multiplier = league["std_dev_multiplier"]
        if max_champions is None:
            max_champions = league["max_champions"]
        if min_iterations_between_champions is None:
            min_iterations_between_champions = league["min_iterations_between_champions"]
        if original_opponent_weight is None:
            original_opponent_weight = league["original_opponent_weight"]
        if champion_weight is None:
            champion_weight = league["champion_weight"]
        if episode_data_dir is self._DISABLED:
            episode_data_dir = league["episode_data_dir"]
        if nav_tolerance is None:
            nav_tolerance = league["nav_tolerance"]
        if strict_nav_check is None:
            strict_nav_check = league["strict_nav_check"]
        if episode_sample_every is None:
            episode_sample_every = league["episode_sample_every"]
        if episode_max_bytes is None:
            episode_max_bytes = league["episode_max_bytes"]
        if episode_rows_per_file is None:
            episode_rows_per_file = league["episode_rows_per_file"]

        self.episode_data_dir = episode_data_dir
        self.nav_tolerance = nav_tolerance
        self.strict_nav_check = strict_nav_check
        self.episode_sample_every = episode_sample_every
        self.episode_max_bytes = episode_max_bytes
        self.episode_rows_per_file = episode_rows_per_file
        self.run_id = run_id

        self.num_trainable = num_trainable_policies
        self.num_random = num_random_policies
        
        # Champion snapshotting configuration
        self.std_dev_multiplier = std_dev_multiplier
        self.max_champions = max_champions
        self.min_iterations_between_champions = min_iterations_between_champions

        # Probabilistic selection configuration
        self.original_opponent_weight = original_opponent_weight
        self.champion_weight = champion_weight
        
        # Champion tracking state
        self.champion_count = 0
        self.champion_id_counter = 0  # Monotonic counter for unique IDs
        self.champion_history = []  # List of dicts with champion metadata
        
        # Initialize available modules: [policy_0...policy_k-1] + [policy_k...policy_n-1]
        self.available_modules = [
            policy_id(i) for i in range(self.num_trainable + self.num_random)
        ]

        # The per-step episode record, or None when it is switched off.
        #
        # Built lazily, per process, by `_recorder()`. It owns a writer thread
        # and a queue, neither of which is state to ship to a worker, so it is
        # dropped from `__getstate__` and rebuilt on the far side. That also
        # makes it correct by construction under `num_env_runners > 0`: each
        # runner gets its own recorder writing its own files, rather than a
        # driver-side object pickled into eight processes that would all open
        # the same paths.
        #
        # This used to be `self.store`, a dict of every step of every live
        # episode, appended to unconditionally - so `--no-episode-data` bought
        # only the I/O and kept the ~34 MB per episode of memory (doc/21 §2.2).
        self._episode_recorder = None

        # Per-episode activity tallies, keyed by episode ID, so concurrent
        # episodes under a vectorised runner cannot mix.
        #
        # A plain dict, not defaultdict(lambda: ...): this callback is
        # cloudpickled into every checkpoint, and a lambda default_factory is
        # the kind of thing that survives locally and fails on a restore path
        # nobody exercised.
        self._activity = {}


    #: How many unfinished episodes' tallies to keep. `on_episode_end` is not
    #: called for episodes a force-reset discards (doc/21 §3.2), so a dict keyed
    #: by episode id and pruned only there grows for the life of the process.
    #: Generous next to any realistic `num_envs_per_env_runner`, and three ints
    #: per entry, so the cap costs nothing and closes the leak.
    _MAX_LIVE_EPISODES = 64

    def __getstate__(self):
        """State to pickle: everything except the per-process live objects.

        RLlib cloudpickles this callback into every env runner and into every
        checkpoint. The recorder holds a thread and a queue and must not travel;
        the live episode tallies belong to whichever process was mid-episode and
        mean nothing on the far side. Both are rebuilt lazily, so the configured
        knobs - which *are* pickled - are all a restored or shipped copy needs.
        """
        state = dict(self.__dict__)
        state["_episode_recorder"] = None
        state["_activity"] = {}
        return state

    def _recorder(self):
        """This process's `EpisodeRecorder`, built on first use, or None.

        Constructed here rather than in `__init__` for two reasons: a recorder
        built on the driver could not be shipped to a worker anyway, and one
        built eagerly would start a writer thread and create a directory in
        every process that merely *constructs* a callback - which the tests, the
        checkpoint restore path and `build_config` all do without ever sampling.
        """
        if self.episode_data_dir is None:
            return None
        if self._episode_recorder is None:
            self._episode_recorder = EpisodeRecorder(
                self.episode_data_dir,
                run_id=self.run_id,
                sample_every=self.episode_sample_every,
                max_bytes=self.episode_max_bytes,
                rows_per_file=self.episode_rows_per_file,
            )
        return self._episode_recorder

    def _log_activity(self, episode, metrics_logger) -> None:
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
        tally = self._activity.pop(episode.id_, None)
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

        metrics_logger.log_value("pass_action_fraction", pass_fraction, window=10)
        metrics_logger.log_value(
            "order_rejection_fraction", rejection_fraction, window=10
        )

        self._log_reward_terms(tally, agent_steps, metrics_logger)

        self._log_maker_ratio(tally, metrics_logger)

        logger.debug(
            "episode %s activity: %s agent-steps, %.1f%% pass, %.1f%% rejected",
            episode.id_, agent_steps, 100 * pass_fraction,
            100 * rejection_fraction,
        )

    #: Trades an agent needs before its maker share is worth reporting. Below
    #: this the ratio is quantised to almost nothing - one passive fill out of
    #: one trade reads as a perfect market maker - so the maximum across agents
    #: would sit at 1.0 for the whole run on noise alone.
    _MIN_TRADES_FOR_MAKER_RATIO = 5

    def _log_maker_ratio(self, tally, metrics_logger) -> None:
        """The most maker-like agent's share of its own fills.

        doc/13 §7's market-making uptake, and the one shape of it that says
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
            if fills["trades"] >= self._MIN_TRADES_FOR_MAKER_RATIO
        ]
        if not ratios:
            return
        metrics_logger.log_value("maker_fill_ratio_max", max(ratios), window=10)

    def _log_reward_terms(self, tally, agent_steps, metrics_logger) -> None:
        """The reward decomposition, reduced to a mean and a variance share.

        doc/07 §6.4 prescribes watching how the five signed contributions split
        the reward's variance; doc/11 §2.4 recorded that the terms were captured
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
                f"reward_term_mean_{term}", mean, window=10,
            )

        total = sum(variances.values())
        if total <= 0.0:
            return
        for term, variance in variances.items():
            metrics_logger.log_value(
                f"reward_term_var_share_{term}", variance / total, window=10,
            )

    def _log_episode_account(self, last_info, metrics_logger) -> None:
        """Per-agent account state at the end of the episode, as metrics.

        doc/11 §2.3 and §4 item 2: every one of these is already in the per-step
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
            nav = _as_float(info.get("NAV"))
            if nav is not None:
                navs.append(nav)
            drawdown = _as_float(info.get("drawdown"))
            if drawdown is not None:
                drawdowns.append(drawdown)
            position = _as_float(info.get("net_position"))
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
                "mean_agent_drawdown", sum(drawdowns) / len(drawdowns), window=10,
            )
        if positions:
            metrics_logger.log_value(
                "mean_abs_net_position", sum(positions) / len(positions), window=10,
            )
        if trades:
            metrics_logger.log_value(
                "mean_num_trades", sum(trades) / len(trades), window=10,
            )

    def _activity_for(self, episode_id) -> dict:
        """The tally for this episode, created if the start hook missed it.

        `on_episode_start` is not guaranteed to have run for every episode a
        worker reports on - a restored run picks up mid-flight - and a counter
        that raises KeyError would take down training for the sake of a metric.
        """
        tally = self._activity.get(episode_id)
        if tally is None:
            self._prune_activity()
            tally = self._activity[episode_id] = _new_tally()
        return tally

    def _prune_activity(self) -> None:
        """Drop the oldest tallies once too many episodes are open at once.

        Insertion-ordered, so "oldest" is the episode that started first. An
        episode discarded by a force-reset never reaches `on_episode_end` and so
        never has its tally popped (doc/21 §3.2); this is what stops that
        turning into a dict that grows for the life of the worker.
        """
        while len(self._activity) >= self._MAX_LIVE_EPISODES:
            episode_id = next(iter(self._activity))
            del self._activity[episode_id]
            logger.debug(
                "dropped the activity tally for episode %s, which never ended "
                "(%s open, limit %s)",
                episode_id, len(self._activity) + 1, self._MAX_LIVE_EPISODES,
            )


    def on_episode_start(
        self,
        *,
        episode,
        env_runner,
        metrics_logger,
        env,
        env_index,
        rl_module,
        **kwargs,
    ) -> None:
        """Callback run right after an Episode has been started."""
        # Report the mapping by CALLING the mapping function this EnvRunner is
        # actually using, taken from its own config.
        #
        # Two reasons not to derive it from `self`. First, the original version
        # reimplemented selection as an unweighted
        # `(hash(episode.id_) + i) % len(candidates)` while the real mapping fn
        # does a weighted `rng.choice`, so the log named opponents that were not
        # the ones playing. Second, and still true after that was fixed: with
        # `num_env_runners > 0` each remote runner holds its own pickled copy of
        # this callback, frozen at worker construction and never updated, so
        # `self.available_modules` out here contains no champions at all. The
        # runner's `config.policy_mapping_fn`, by contrast, is refreshed by
        # `add_module`/`remove_module`, so it is the authoritative one.
        mapping_fn = getattr(env_runner.config, "policy_mapping_fn", None)
        if mapping_fn is None:
            mapping_fn = self.get_mapping_fn(self)

        # Built only when it will be emitted: this runs once per episode per
        # runner, and calling the mapping fn for every agent to format a line
        # nobody sees is work the DEBUG level is meant to avoid.
        if logger.isEnabledFor(logging.DEBUG):
            mapping = ", ".join(
                f"agent_{i} -> {mapping_fn(f'agent_{i}', episode)}"
                for i in range(self.num_trainable + self.num_random)
            )
            logger.debug("episode %s started, policy map: %s", episode.id_, mapping)

        self._prune_activity()
        self._activity[episode.id_] = _new_tally()

    def on_episode_step(
        self,
        *,
        episode,
        env_runner,
        metrics_logger,
        env,
        env_index,
        rl_module,
        **kwargs,
    ) -> None:
        """Called on each episode step (after the action(s) has/have been logged).

        Note that on the new API stack, this callback is also called after the final
        step of an episode, meaning when terminated/truncated are returned as True
        from the `env.step()` call, but is still provided with the non-numpy'ized
        episode object (meaning the data has NOT been converted to numpy arrays yet).

        The exact time of the call of this callback is after `env.step([action])` and
        also after the results of this step (observation, reward, terminated, truncated,
        infos) have been logged to the given `episode` object.

        Args:
            episode: The just stepped SingleAgentEpisode or MultiAgentEpisode object
                (after `env.step()` and after returned obs, rewards, etc.. have been
                logged to the episode object).
            env_runner: Reference to the EnvRunner running the env and episode.
            metrics_logger: The MetricsLogger object inside the `env_runner`. Can be
                used to log custom metrics during env/episode stepping.
            env: The gym.Env or gym.vector.Env object running the started episode.
            env_index: The index of the sub-environment that has just been stepped.
            rl_module: The RLModule used to compute actions for stepping the env. In
                single-agent mode, this is a simple RLModule, in multi-agent mode, this
                is a MultiRLModule.
            kwargs: Forward compatibility placeholder.
        """
        last_info = episode.get_infos(-1)

        # Tally activity as the episode runs, before anything that can be
        # switched off. These metrics must not depend on the episode record
        # being enabled - that is the whole point of counting here rather than
        # reading the recorded rows back at episode end.
        tally = self._activity_for(episode.id_)
        tally["steps"] += 1
        for agent_id, agent_info in (last_info or {}).items():
            if not isinstance(agent_info, dict):
                continue
            tally["agent_steps"] += 1
            if agent_info.get("is_pass_action"):
                tally["passes"] += 1
            tally["rejections"] += int(agent_info.get("num_rejected_step", 0) or 0)

            trades = int(agent_info.get("num_trades_step", 0) or 0)
            if trades:
                fills = tally["per_agent_fills"].setdefault(
                    agent_id, {"trades": 0, "passive": 0}
                )
                fills["trades"] += trades
                fills["passive"] += int(
                    agent_info.get("num_passive_fills_step", 0) or 0
                )

            terms = agent_info.get("reward_terms") or {}
            for term in REWARD_TERMS:
                value = _as_float(terms.get(term))
                if value is None:
                    continue
                tally["term_sum"][term] += value
                tally["term_sq"][term] += value * value

        # The per-step record, if it is on. Nothing above this line touches the
        # observations or actions, so a run with `episode_data_dir` unset now
        # pays neither the I/O nor the memory - which is what the flag always
        # claimed and never did (doc/21 §2.2).
        recorder = self._recorder()
        if recorder is not None:
            # RLlib's own env timestep where it exists, because it is the
            # episode's property rather than this process's: it survives a
            # sample() boundary mid-episode, and it is right even when
            # `on_episode_start` was never seen (a restored run picking up
            # mid-flight) or the tally was evicted. The local count is the
            # fallback for an episode type that does not carry one.
            recorder.record_step(
                episode, getattr(episode, "env_t", None) or tally["steps"]
            )

    def on_episode_end(
        self,
        *,
        episode,
        env_runner,
        metrics_logger,
        env,
        env_index,
        rl_module,
        **kwargs,
    ) -> None:
        logger.debug("episode %s ended", episode.id_)

        # Hand this episode's rows to the recorder's writer thread. The write
        # itself happens off this thread and every failure inside it is a
        # warning, so a full disk can no longer raise into a hook that runs on
        # an env runner - which, with restart_failed_env_runners on, would have
        # meant a killed and restarted worker (doc/21 §2.4).
        recorder = self._recorder()
        if recorder is not None:
            recorder.finish_episode(episode.id_)

        self._log_activity(episode, metrics_logger)

        # Try to get parameters from different possible sources. The starting
        # points are the env's own fallback for init_cash and the league size
        # this callback was built with - not literals.
        init_cash = env_default("init_cash")
        num_agents = self.num_trainable + self.num_random
        
        # 1. Try env_runner.config
        if hasattr(env_runner, "config"):
            env_config = getattr(env_runner.config, "env_config", {})
            init_cash = env_config.get("init_cash", init_cash)
            num_agents = env_config.get("num_of_agents", num_agents)
        
        # 2. Try env object directly or via unwrapped
        if hasattr(env, "unwrapped"):
            env_obj = env.unwrapped
            if hasattr(env_obj, "init_cash"):
                init_cash = env_obj.init_cash
            if hasattr(env_obj, "num_of_agents"):
                num_agents = env_obj.num_of_agents
        elif hasattr(env, "init_cash"):
            init_cash = env.init_cash
            num_agents = getattr(env, "num_of_agents", num_agents)

        # Decimal, not float, all the way through the check: the ledger is
        # Decimal end to end and `info["NAV"]` is its exact `str()`, so parsing
        # it back with Decimal makes the comparison exact. Going through float
        # would reintroduce, at the last step, precisely the representation
        # error the account type exists to avoid.
        total_initial_cash = Decimal(str(init_cash)) * num_agents

        logger.debug(
            "episode %s parameters: env=%s env_runner=%s init_cash=%s "
            "num_agents=%s total_initial_cash=%s",
            episode.id_, type(env), type(env_runner), init_cash, num_agents,
            total_initial_cash,
        )

        last_info = episode.get_infos(-1)

        total_nav = Decimal(0)
        per_agent = []
        for i in range(num_agents):
            agent_key = f"agent_{i}"
            if agent_key in last_info:
                nav = Decimal(last_info[agent_key].get("NAV", "0"))
                total_nav += nav
                per_agent.append(f"  {agent_key} NAV: {nav:,.2f}")

        error = total_nav - total_initial_cash
        # Inclusive: with the comparison exact, "within tolerance" includes the
        # boundary, which is what makes nav_tolerance=0 mean "conservation must
        # be exact" rather than "every episode is a violation". At the default
        # 1e-6 the two forms differ only on an error of exactly 1e-6.
        conserved = abs(error) <= self.nav_tolerance

        # The metric goes out whether or not the invariant held, so a run has a
        # series to look at rather than only the moment it broke. window=1
        # keeps it per-iteration rather than smoothed - an error that appears
        # in one episode out of many must not be averaged away.
        if metrics_logger:
            # float() only at the boundary: the metrics stack reduces with
            # NumPy and will not take a Decimal. The check above has already
            # been decided exactly by this point.
            metrics_logger.log_value(
                "nav_conservation_error", float(abs(error)), window=1
            )
            # Emitted every episode, including the conserved ones, so the key is
            # always present in the result and the driver's check reads a count
            # rather than having to distinguish "no violations" from "the metric
            # never arrived".
            metrics_logger.log_value(
                NAV_VIOLATIONS_METRIC, 0.0 if conserved else 1.0, reduce="sum",
            )
            self._log_episode_account(last_info, metrics_logger)

        report = "\n".join(
            [f"Episode {episode.id_} NAV verification"]
            + per_agent
            + [
                f"  Total NAV: {total_nav:,.2f}",
                f"  Expected total initial cash: {total_initial_cash:,.2f}",
            ]
        )

        if conserved:
            logger.info("%s\n  Conserved (within %g)", report, self.nav_tolerance)
            return

        # A conservation break means the ledger is corrupt: cash has been
        # created or destroyed, so every reward computed from NAV after this
        # point is meaningless.
        #
        # Reported, not raised. This hook runs on the env runner whenever
        # `num_env_runners > 0`, and a raise there is swallowed by RLlib's fault
        # tolerance, restarts the worker, and takes this iteration's metrics
        # down with it - see NAV_VIOLATIONS_METRIC. `strict_nav_check` is acted
        # on by `train._check_nav_conservation`, on the driver, at the end of the
        # iteration: later than a raise here would have been at
        # `num_env_runners=0`, but it is the same answer at every runner count,
        # and it is the only one that works at more than zero.
        message = (
            f"{report}\n  NAV conservation VIOLATED: difference "
            f"{error:,.2f} exceeds tolerance {self.nav_tolerance:g}"
        )
        logger.error(message)

    def on_train_result(self, *, algorithm, metrics_logger=None, result, **kwargs):
        """
        Callback after each training iteration.
        
        Uses relative ranking based on POLICY returns to identify champions.
        snapshots created when return > mean + std_dev_multiplier * std.
        """
        # Per-MODULE returns, keyed by ModuleID.
        #
        # This used to try `policy_reward_mean` and then `custom_metrics`, both
        # of which are old-API-stack only and absent here, before falling back
        # to `agent_episode_returns_mean` with an `agent_X -> policy_X` mapping.
        # That fallback is wrong for the opponent slots: agents k..n-1 play
        # whichever module the pool assigned them that episode, so their return
        # was being filed under `policy_<agent index>` regardless of who
        # actually played. The league mean/std were computed over those
        # mislabelled entries.
        #
        # `module_episode_returns_mean` is already keyed by the real ModuleID
        # (including `champion_*`), so no remapping is needed.
        env_runner_results = result.get(ENV_RUNNER_RESULTS, {})
        policy_returns = env_runner_results.get(MODULE_EPISODE_RETURNS_MEAN)

        if not policy_returns:
            logger.warning(
                "%r missing or empty in result[%r]; skipping the champion check "
                "this iteration. Available keys: %s",
                MODULE_EPISODE_RETURNS_MEAN, ENV_RUNNER_RESULTS,
                sorted(env_runner_results.keys()),
            )
            return

        iteration = result['training_iteration']
        
        # Filter mostly interesting policies (exclude extremely sparse ones if any)
        # and calculate league statistics.
        #
        # NaN, not just None: a module the mapping fn did not draw this
        # iteration played no episodes, and RLlib reports its mean return as
        # NaN. One of those poisons `np.mean`, so the threshold becomes NaN and
        # `best_return > threshold` is False for every candidate - the champion
        # trigger stops firing, silently and permanently. It is self-
        # reinforcing: each champion added to the pool makes it likelier that
        # some baseline goes undrawn. Both GPU runs of 2026-08-15 died this way,
        # at iterations 10 and 12 of 16, having reported healthy league stats
        # right up to the iteration it happened.
        idle_modules = sorted(
            module_id for module_id, value in policy_returns.items()
            if value is None or np.isnan(value)
        )
        valid_returns = [
            v for v in policy_returns.values() if v is not None and not np.isnan(v)
        ]

        if not valid_returns:
            logger.warning("No valid policy returns found this iteration.")
            return

        if idle_modules:
            logger.info(
                "iteration %s: %s played no episodes and are excluded from the "
                "league statistics", iteration, ", ".join(idle_modules),
            )

        league_mean = np.mean(valid_returns)
        league_std = np.std(valid_returns)
        
        # Determine dynamic threshold
        # If std is 0 (all same), effectively requires > mean
        threshold = league_mean + (self.std_dev_multiplier * league_std)
        
        # Check trainable policies for champion status
        trainable_policies = [policy_id(i) for i in range(self.num_trainable)]

        best_candidate = None
        best_return = -float('inf')
        
        for pid in trainable_policies:
            if pid in policy_returns:
                p_ret = policy_returns[pid]
                if p_ret > best_return:
                    best_return = p_ret
                    best_candidate = pid
        
        logger.info(
            "iteration %s league stats: mean=%.2f std=%.2f threshold=%.2f "
            "best_trainable=%s (%.2f)",
            iteration, league_mean, league_std, threshold, best_candidate,
            best_return,
        )
        logger.debug("iteration %s policy returns: %s", iteration, policy_returns)


        # Iterations since the last champion snapshot. `_should_create_champion`
        # has computed this since it was written and thrown it away every time
        # (doc/11 §2.5); it is the number that says whether the cooldown or the
        # threshold is what is holding the league still. None before the first
        # champion, which is a different state from "0 iterations ago" - so no
        # metric is emitted rather than a misleading zero.
        promoted_before = self.champion_count

        # Check relative performance trigger
        if best_candidate and best_return > threshold:
            # Also check if it's better than previous champion (optional but good for progress)
            # best_historical = max([c['return'] for c in self.champion_history]) if self.champion_history else -float('inf')
            
            if self._should_create_champion(best_return, iteration, algorithm):
                 # Pass policy ID directly
                self._create_champion_snapshot_from_policy(
                    algorithm, best_candidate, best_return, iteration)
        
        league_state = {
            "size": self.num_trainable + self.num_random + self.champion_count,
            "mean_return": float(league_mean),
            "std_return": float(league_std),
            "threshold": float(threshold),
            "promoted": max(0, self.champion_count - promoted_before),
            "available_modules": len(self.available_modules),
            "idle_modules": len(idle_modules),
            "champions": [c["id"] for c in self.champion_history],
        }
        if self.champion_history:
            league_state["iterations_since_champion"] = (
                iteration - self.champion_history[-1]["iteration"]
            )

        # Written straight into `result`, and this is the only one of the two
        # channels below that lands in the row for the iteration it describes.
        #
        # Anything logged through `metrics_logger` here appears one iteration
        # late: RLlib hands this hook a `result` it has already compiled, so a
        # value logged now is reduced on the following pass. `champions_promoted`
        # would read 1.0 in the row *after* the promotion. RLlib's own comment at
        # the call site says the callback runs before `Trainable.log_result` "so
        # that the user has a chance to mutate the result", and its TODO beside
        # `metrics_logger` notes there is "probably no point in adding more Stats
        # here" - so mutating is the sanctioned path, not a trick.
        #
        # `progress.jsonl` is the consumer that matters, and it writes the whole
        # result dict, so a reader joining `result["league"]` on
        # `training_iteration` gets values that describe that iteration. A
        # dedicated sub-dict rather than top-level keys, so it cannot collide
        # with the lagged metrics of the same name.
        result["league"] = league_state

        # The metrics channel is kept as well, unchanged, for anything reading
        # RLlib's metrics rather than the result dict - Tune, a Prometheus
        # exporter, `algo.metrics.peek`. Those readers get the one-iteration lag
        # that has always applied to `league_size` and the return statistics.
        if metrics_logger:
            metrics_logger.log_value(
                "league_size",
                self.num_trainable + self.num_random + self.champion_count,
                window=1,
            )
            metrics_logger.log_value("league_mean_return", league_mean, window=10)
            metrics_logger.log_value("league_std_return", league_std, window=10)

            # Promotion as a metric rather than only a log banner (doc/11 §2.5,
            # §4 item 1). Counted from the champion count either side of the
            # trigger rather than from the branch above, so a snapshot that
            # raised and rolled itself back is correctly reported as *not*
            # promoted.
            metrics_logger.log_value(
                "champions_promoted",
                float(max(0, self.champion_count - promoted_before)),
                reduce="sum",
            )
            metrics_logger.log_value(
                "available_modules", float(len(self.available_modules)), window=1,
            )
            metrics_logger.log_value(
                "idle_modules", float(len(idle_modules)), window=1,
            )
            if self.champion_history:
                metrics_logger.log_value(
                    "iterations_since_champion",
                    float(iteration - self.champion_history[-1]["iteration"]),
                    window=1,
                )
    
    def _should_create_champion(self, return_value, iteration, algorithm):
        """
        Decide if we should create a champion snapshot.

        Args:
            return_value: The return value of the best policy
            iteration: Current training iteration
            algorithm: The training algorithm instance (needed to actually drop
                an evicted champion's module)

        Returns:
            True if champion should be created, False otherwise
        """
        # Don't snapshot too frequently
        if self.champion_history:
            last_champion_iter = self.champion_history[-1]['iteration']
            if iteration - last_champion_iter < self.min_iterations_between_champions:
                logger.info(
                    "Skipping champion creation: only %s iterations since the "
                    "last champion (min: %s)",
                    iteration - last_champion_iter,
                    self.min_iterations_between_champions,
                )
                return False

        # Check if we need to remove old champion first (rolling window)
        if self.champion_count >= self.max_champions:
            logger.info(
                "Max champions (%s) reached, removing the oldest",
                self.max_champions,
            )
            self._remove_oldest_champion(algorithm)

        return True

    def _create_champion_snapshot_from_policy(self, algorithm, source_policy_id, return_value, iteration):
        """
        Create a frozen champion snapshot of the best policy.

        Args:
            algorithm: The training algorithm instance
            source_policy_id: ModuleID of the policy to snapshot
            return_value: Performance metric that triggered snapshotting
            iteration: Current training iteration
        """
        # Create unique champion name using monotonic counter
        self.champion_id_counter += 1
        champion_id = f"{CHAMPION_PREFIX}{self.champion_id_counter}"
        
        logger.info(
            "Creating champion snapshot %s from %s (return %.2f, iteration %s)",
            champion_id, source_policy_id, return_value, iteration,
        )


        try:
            # Take the snapshot from the LearnerGroup, not from
            # `algorithm.get_module()`: the latter returns the EnvRunner's
            # inference-only copy, which omits the value-function head. We want
            # the full module state so the snapshot is complete.
            #
            # Read it through `get_state` rather than `learner_group._learner`.
            # That private attribute is only populated when the LearnerGroup is
            # local (`num_learners=0`); with `num_learners > 0` it is None, so
            # touching it raised on every snapshot attempt and - swallowed by
            # the except below - left the league permanently empty while
            # printing an error per iteration. `get_state` works either way.
            source_state = algorithm.learner_group.get_state(
                components=(
                    f"{COMPONENT_LEARNER}/{COMPONENT_RL_MODULE}/{source_policy_id}"
                ),
            )[COMPONENT_LEARNER][COMPONENT_RL_MODULE][source_policy_id]

            # The spec only needs the module's shape, not its weights, so it can
            # come from the local EnvRunner copy (always present, even when
            # sampling happens remotely). `inference_only=False` keeps the
            # champion's structure identical to the source module on the
            # Learner, so the state loaded above applies cleanly.
            champion_spec = RLModuleSpec.from_module(
                algorithm.env_runner.module[source_policy_id]
            )
            champion_spec.inference_only = False

            # Put the champion into the matchmaking pool BEFORE add_module.
            #
            # Ordering is load-bearing. `new_agent_to_module_mapping_fn` below
            # closes over `self`, and `add_module` pickles that closure to ship
            # it to the remote EnvRunners. Pickling snapshots
            # `self.available_modules` as it is at that moment - so appending
            # after the call leaves every remote runner's mapping fn exactly one
            # champion behind, permanently. (With num_env_runners > 0 sampling
            # happens on the remote runners, so that is the mapping that
            # actually decides who plays, not the driver's.)
            self.available_modules.append(champion_id)

            # Add the champion everywhere (Learners + EnvRunners), and update
            # the agent->module mapping fn at the same time.
            #
            # `new_agent_to_module_mapping_fn` matters as soon as
            # num_env_runners > 0: the mapping fn closes over THIS callback
            # instance, but remote EnvRunners hold their own pickled copy that
            # was frozen at worker construction. Without pushing the mapping fn
            # here, champions would be added to the remote workers as modules
            # but never actually selected to play.
            algorithm.add_module(
                module_id=champion_id,
                module_spec=champion_spec,
                new_agent_to_module_mapping_fn=self.get_mapping_fn(self),
            )

            # Copy the trained weights into the champion on the Learner...
            algorithm.set_state({
                COMPONENT_LEARNER_GROUP: {
                    COMPONENT_LEARNER: {
                        COMPONENT_RL_MODULE: {
                            champion_id: source_state,
                        }
                    }
                }
            })

            # ...and then push them out to the EnvRunners, which is where the
            # champion actually acts.
            #
            # This step is load-bearing. Without it the champion playing in the
            # environment stays randomly initialised for the whole run while the
            # trained snapshot sits unused in the LearnerGroup, because:
            #   * `add_module` does sync weights to the EnvRunners, but that
            #     happens before the `set_state` above, so it propagates the
            #     champion's fresh initialisation; and
            #   * the per-iteration sync in `PPO.training_step` passes
            #     `policies=modules_to_update`, i.e. only modules that produced
            #     losses - which by design never includes a frozen champion.
            #
            # Note this deliberately does NOT use
            # `env_runner_group.sync_weights()`. That path carries the
            # LearnerGroup's WEIGHTS_SEQ_NO, and `EnvRunner.set_state` applies
            # incoming module state only when `weights_seq_no == 0` or when the
            # runner is strictly behind. The sequence number only advances on a
            # training update, so a sync issued here - between two updates -
            # arrives with a seq no the runner already has and is dropped
            # silently. Sending the state without a WEIGHTS_SEQ_NO key takes
            # the documented "0 means force" branch instead.
            champion_state = {
                COMPONENT_RL_MODULE: {champion_id: source_state},
            }
            algorithm.env_runner_group.foreach_env_runner(
                lambda env_runner: env_runner.set_state(champion_state),
                local_env_runner=True,
            )
            if algorithm.eval_env_runner_group is not None:
                algorithm.eval_env_runner_group.foreach_env_runner(
                    lambda env_runner: env_runner.set_state(champion_state),
                    local_env_runner=True,
                )

            # Record champion metadata. (`available_modules` was updated before
            # `add_module` above - see the comment there.)
            champion_info = {
                'id': champion_id,
                'source_policy': source_policy_id,
                'iteration': iteration,
                'return': return_value,
            }
            self.champion_history.append(champion_info)
            self.champion_count += 1

            logger.info(
                "Champion %s created. League size now %s (%s trainable + %s "
                "random + %s champions). Active champions: %s",
                champion_id,
                self.num_trainable + self.num_random + self.champion_count,
                self.num_trainable, self.num_random, self.champion_count,
                [c['id'] for c in self.champion_history],
            )

        except Exception as e:
            # Roll the pool entry back so matchmaking can never select a module
            # that failed to be created.
            if champion_id in self.available_modules:
                self.available_modules.remove(champion_id)
            # exc_info carries the traceback that the bare `traceback.print_exc`
            # used to put on stderr, unattached to the message it belonged to.
            logger.error(
                "Error creating champion %s: %s", champion_id, e, exc_info=True,
            )
    
    def _remove_oldest_champion(self, algorithm):
        """
        Remove the oldest champion to maintain the rolling window.

        The module is dropped from the Algorithm entirely, not just from this
        callback's bookkeeping. (An earlier version only removed it from
        `available_modules`, on the basis that RLlib had no clean way to delete
        a module - that is no longer true: `Algorithm.remove_module` exists.
        Leaving them in place leaked one module plus its Learner-side state per
        eviction, for the lifetime of the run.)
        """
        if not self.champion_history:
            return

        # Get oldest champion
        oldest = self.champion_history.pop(0)
        champion_id = oldest['id']

        logger.info(
            "Removing oldest champion %s (from iteration %s, return %.2f)",
            champion_id, oldest['iteration'], oldest['return'],
        )

        # Remove from available modules (won't be assigned to agents anymore).
        # Do this BEFORE remove_module so the mapping fn we hand to RLlib below
        # can no longer return the module we are about to delete.
        if champion_id in self.available_modules:
            self.available_modules.remove(champion_id)

        self.champion_count -= 1

        try:
            algorithm.remove_module(
                module_id=champion_id,
                new_agent_to_module_mapping_fn=self.get_mapping_fn(self),
            )
        except Exception as e:
            # Non-fatal: the champion is already out of the matchmaking pool, so
            # training stays correct - we just keep holding its memory.
            logger.warning(
                "Could not remove module %s from the algorithm: %s",
                champion_id, e,
            )

        logger.info(
            "Champion removed. Active champions: %s",
            [c['id'] for c in self.champion_history],
        )
    
    def league_state(self):
        """Champion bookkeeping as plain JSON-able data.

        `train.save_checkpoint` writes this beside every checkpoint. The
        champion modules themselves are in the checkpoint proper; everything
        that indexes them - the history, the monotonic ID counter, the
        matchmaking pool - exists only inside this object, which survives a
        restore only as long as it stays unpickle-compatible.
        """
        return {
            'champion_id_counter': self.champion_id_counter,
            'champion_count': self.champion_count,
            'champion_history': [dict(c) for c in self.champion_history],
            'available_modules': list(self.available_modules),
            'num_trainable': self.num_trainable,
            'num_random': self.num_random,
        }

    def restore_league_state(self, state, present_modules=None):
        """Reconcile this callback's league bookkeeping with a sidecar and reality.

        Called after a restore, where three sources can disagree: this object
        (RLlib's unpickled copy), `state` (the sidecar `league_state()` wrote at
        save time), and `present_modules` (the champion modules the restored
        algorithm actually has). The sidecar wins over this object, because they
        can only differ if unpickling drifted; the modules win over both, since
        matchmaking may only return a module that exists.

        Args:
            state: a dict from `league_state()`.
            present_modules: ModuleIDs on the restored algorithm, or None when
                they could not be read - in which case membership is taken on
                trust and only the counter is protected.

        Returns:
            A list of human-readable repair descriptions. Empty means the three
            sources agreed and nothing was changed.
        """
        repairs = []

        sidecar_history = [dict(c) for c in state.get('champion_history', [])]
        if [c['id'] for c in sidecar_history] != [c['id'] for c in self.champion_history]:
            repairs.append(
                f"champion history {[c['id'] for c in self.champion_history]} -> "
                f"{[c['id'] for c in sidecar_history]} (taken from the sidecar; the "
                f"unpickled callback disagreed)"
            )
            self.champion_history = sidecar_history

        if present_modules is not None:
            present_champions = {
                m for m in present_modules if m.startswith(CHAMPION_PREFIX)
            }
            for champion in list(self.champion_history):
                if champion['id'] not in present_champions:
                    self.champion_history.remove(champion)
                    repairs.append(
                        f"dropped {champion['id']}: the restored algorithm has no "
                        f"such module"
                    )
            known = {c['id'] for c in self.champion_history}
            for module_id in sorted(present_champions - known):
                # Ordering within the history decides eviction order, and an
                # orphan's true position is unknowable - it goes last, so a
                # rolling window evicts a champion whose iteration is known first.
                self.champion_history.append({
                    'id': module_id,
                    'source_policy': None,
                    'iteration': state.get('training_iteration', 0),
                    'return': None,
                })
                repairs.append(
                    f"adopted {module_id}: present in the checkpoint but missing "
                    f"from the league state (appended as newest)"
                )

        # The pool is derived, so rebuild it rather than repairing it in place.
        pool = [
            policy_id(i) for i in range(self.num_trainable + self.num_random)
        ] + [c['id'] for c in self.champion_history]
        if pool != self.available_modules:
            repairs.append(f"matchmaking pool {self.available_modules} -> {pool}")
            self.available_modules = pool

        if self.champion_count != len(self.champion_history):
            self.champion_count = len(self.champion_history)

        # The counter must never go backwards: a restarted counter re-mints
        # champion IDs that are already in use, and `add_module` would then
        # overwrite a live champion with a new snapshot.
        highest_seen = max(
            [
                int(c['id'][len(CHAMPION_PREFIX):])
                for c in self.champion_history
                if c['id'][len(CHAMPION_PREFIX):].isdigit()
            ] + [0]
        )
        counter = max(
            self.champion_id_counter,
            state.get('champion_id_counter', 0),
            highest_seen,
        )
        if counter != self.champion_id_counter:
            repairs.append(
                f"champion ID counter {self.champion_id_counter} -> {counter} "
                f"(a restarted counter would re-mint existing champion IDs)"
            )
            self.champion_id_counter = counter

        return repairs

    @classmethod
    def get_mapping_fn(cls, callback_instance):
        """
        Create an agent-to-module mapping function that includes champions.
        
        Args:
            callback_instance: Instance of SelfPlayCallback with champion tracking
            
        Returns:
            Mapping function for use in multi_agent config
        """
        def agent_to_module_mapping_fn(agent_id, episode, **kwargs):
            """Assign agents to modules including dynamic champions."""
            agent_num = int(agent_id.split("_")[1])

            # Trainable policies always assigned to their respective agents
            if agent_num < callback_instance.num_trainable:
                return policy_id(agent_num)

            # For random/league agents, assign from pool (champions + original randoms)
            # The pool starts AFTER the trainable policies
            # Pool = available_modules[k:]
            candidates = callback_instance.available_modules[callback_instance.num_trainable:]

            if not candidates:
                # Fallback if the pool is somehow empty
                return policy_id(agent_num)

            # Calculate weights for candidates
            weights = []
            for c in candidates:
                if c.startswith(CHAMPION_PREFIX):
                    # Dynamic champion snapshots
                    weights.append(callback_instance.champion_weight)
                elif c.startswith(POLICY_PREFIX):
                    # Original fixed/random policies
                    weights.append(callback_instance.original_opponent_weight)
                else:
                    weights.append(1.0)  # Fallback

            # Normalize to probabilities
            weights = np.array(weights, dtype=np.float64)
            probs = weights / weights.sum()

            # Seed from the episode ID and agent index so the assignment is
            # reproducible.
            #
            # Uses zlib.crc32 rather than the builtin hash(): hash() on str is
            # salted by PYTHONHASHSEED, so it differs between processes and
            # between runs. That made the "deterministic selection" this comment
            # promised reproducible only within a single process.
            seed = (
                zlib.crc32(str(episode.id_).encode("utf-8")) + agent_num
            ) % (2 ** 32)
            rng = np.random.RandomState(seed)
            # Cast to plain str: rng.choice returns np.str_, which compares
            # equal to str but shows up as `np.str_('policy_2')` in logs and
            # checkpoints.
            return str(rng.choice(candidates, p=probs))

        return agent_to_module_mapping_fn