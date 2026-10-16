from decimal import Decimal

import logging

from ray.rllib.callbacks.callbacks import RLlibCallback
from ray.rllib.utils.metrics import ENV_RUNNER_RESULTS

from gym_continuousDoubleAuction.config_loader import env_default, group
from gym_continuousDoubleAuction.logging_setup import get_logger, set_iteration
from gym_continuousDoubleAuction.train.episode_record import (
    EpisodeRecorder,
    SAMPLE_END_DRAIN_S,
)
from gym_continuousDoubleAuction.train.callbk import league_stats, nav_audit
from gym_continuousDoubleAuction.train.callbk.league import League
from gym_continuousDoubleAuction.train.callbk.activity import (
    MODULE_TRADES_METRIC,
    ActivityLog,
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

#: Episodes whose NAV conservation could not be checked: fees are on and the
#: finished env's accounts could not be read, so the sum is short by the fees
#: and any answer would be a guess. Counted apart from violations (a skip is
#: not a pass) so a run that is never being checked is visible.
NAV_UNCHECKED_METRIC = "nav_conservation_unchecked"

#: The modules the promotion threshold can be computed over (doc/15 S3-12).
PROMOTION_REFERENCES = ("pooled", "excluding_baselines")


#: The attributes a callback saved before the league was an object (issue #253) carried.
_LEAGUE_ATTRIBUTES = (
    "num_trainable",
    "num_random",
    "std_dev_multiplier",
    "max_champions",
    "min_iterations_between_champions",
    "original_opponent_weight",
    "champion_weight",
    "min_champion_trades",
    "promotion_reference",
    "champion_count",
    "champion_id_counter",
    "champion_history",
    "available_modules",
    "_warned_reference_fallback",
)


def _delegated(component: str, name: str) -> property:
    """A read-write property forwarding `name` to `self.<component>`."""
    return property(
        lambda self: getattr(getattr(self, component), name),
        lambda self, value: setattr(getattr(self, component), name, value),
    )


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
        min_champion_trades=None,
        promotion_reference=None,
        markout_horizons=None,
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
            min_champion_trades: Mean trades per episode, over the iteration, that
                a trainable policy needs to be promoted. A policy that has
                collapsed to always-pass earns exactly 0, which beats a league of
                money-losing modules, so it would otherwise clear the return
                threshold (doc/15 S3-11). 0 disables the guard.
            promotion_reference: Which modules the promotion threshold is computed
                over: "pooled" (all of them, baselines included) or
                "excluding_baselines" (trainable modules and champions). See
                `_threshold_returns` and doc/15 S3-12.
            markout_horizons: Steps ahead at which a fill's adverse-selection
                mark-out is measured, one `module_markout_<h>` metric each (see
                `train/performance.py`). Empty switches mark-outs off.
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
        if min_champion_trades is None:
            min_champion_trades = league["min_champion_trades"]
        if promotion_reference is None:
            promotion_reference = league["promotion_reference"]
        if markout_horizons is None:
            markout_horizons = league["markout_horizons"]
        markout_horizons = tuple(int(h) for h in markout_horizons)
        if any(h < 1 for h in markout_horizons):
            raise ValueError(
                f"markout_horizons must be positive step counts; got {markout_horizons}."
            )
        if episode_sample_every is None:
            episode_sample_every = league["episode_sample_every"]
        if episode_max_bytes is None:
            episode_max_bytes = league["episode_max_bytes"]
        if episode_rows_per_file is None:
            episode_rows_per_file = league["episode_rows_per_file"]

        self.episode_data_dir = episode_data_dir
        self.nav_tolerance = nav_tolerance
        self.strict_nav_check = strict_nav_check
        self.activity = ActivityLog(markout_horizons)
        self.episode_sample_every = episode_sample_every
        self.episode_max_bytes = episode_max_bytes
        self.episode_rows_per_file = episode_rows_per_file
        self.run_id = run_id

        # The champions, the matchmaking pool and the champion check (issue #253).
        self.league = League(
            num_trainable_policies,
            num_random_policies,
            std_dev_multiplier=std_dev_multiplier,
            max_champions=max_champions,
            min_iterations_between_champions=min_iterations_between_champions,
            original_opponent_weight=original_opponent_weight,
            champion_weight=champion_weight,
            min_champion_trades=min_champion_trades,
            promotion_reference=promotion_reference,
        )

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
        state["activity"] = ActivityLog(self.activity.markout_horizons)
        return state

    def __setstate__(self, state):
        """Restore, filling in knobs a callback pickled before they existed lacks.

        A resumed run takes its callback from the checkpoint, not from the
        config (`Algorithm.from_checkpoint`), so a checkpoint written before a
        knob existed holds a callback without it. The league's knobs are filled
        in by `League.from_flat`; a callback saved before the league was an
        object (issue #253) has them as attributes of its own.
        """
        # Saved before the activity log was its own object: its tallies and the mark-out
        # horizons were attributes of the callback (issue #253).
        if "league" not in state:
            # Saved before the league was its own object: its settings and champion
            # state were attributes of the callback.
            state = dict(state)
            league_state = {name: state.pop(name) for name in _LEAGUE_ATTRIBUTES if name in state}
            state["league"] = League.from_flat(league_state)
        if "activity" not in state:
            state = dict(state)
            state.pop("_activity", None)
            state["activity"] = ActivityLog(state.pop("markout_horizons", ()))
        self.__dict__.update(state)

    # ---- the league: the callback keeps the names its tests, the checkpoint code and the
    # ---- mapping function reach it by ----

    num_trainable = _delegated("league", "num_trainable")
    num_random = _delegated("league", "num_random")
    std_dev_multiplier = _delegated("league", "std_dev_multiplier")
    max_champions = _delegated("league", "max_champions")
    min_iterations_between_champions = _delegated("league", "min_iterations_between_champions")
    original_opponent_weight = _delegated("league", "original_opponent_weight")
    champion_weight = _delegated("league", "champion_weight")
    min_champion_trades = _delegated("league", "min_champion_trades")
    promotion_reference = _delegated("league", "promotion_reference")
    champion_count = _delegated("league", "champion_count")
    champion_id_counter = _delegated("league", "champion_id_counter")
    champion_history = _delegated("league", "champion_history")
    available_modules = _delegated("league", "available_modules")
    _warned_reference_fallback = _delegated("league", "_warned_reference_fallback")

    def _threshold_returns(self, policy_returns, valid_returns):
        return self.league.threshold_returns(policy_returns, valid_returns)

    def _should_create_champion(self, return_value, iteration, algorithm):
        return self.league.should_create(return_value, iteration, algorithm)

    def _create_champion_snapshot_from_policy(
        self, algorithm, source_policy_id, return_value, iteration
    ):
        return self.league.create_snapshot(algorithm, source_policy_id, return_value, iteration)

    def _remove_oldest_champion(self, algorithm):
        return self.league.remove_oldest(algorithm)

    def league_state(self):
        """Champion bookkeeping as plain JSON-able data (see `League.state`)."""
        return self.league.state()

    def restore_league_state(self, state, present_modules=None):
        """Reconcile the league with a sidecar and reality (see `League.restore`)."""
        return self.league.restore(state, present_modules)

    @classmethod
    def get_mapping_fn(cls, callback_instance):
        """The agent-to-module mapping for `callback_instance`'s league (see `League`)."""
        return League.get_mapping_fn(callback_instance.league)

    # ---- the activity log: the callback keeps the names its tests and metrics use ----

    markout_horizons = property(
        lambda self: self.activity.markout_horizons,
        lambda self, value: setattr(self.activity, "markout_horizons", tuple(value)),
    )
    _activity = property(lambda self: self.activity.tallies)
    _MAX_LIVE_EPISODES = property(lambda self: self.activity.max_live)
    _MIN_TRADES_FOR_MAKER_RATIO = property(lambda self: self.activity.MIN_TRADES_FOR_MAKER_RATIO)

    def _log_activity(self, episode, metrics_logger) -> None:
        self.activity.log_episode(episode, metrics_logger)

    def _log_module_trades(self, episode, tally, metrics_logger) -> None:
        self.activity.log_module_trades(episode, tally, metrics_logger)

    def _log_module_performance(self, episode, tally, metrics_logger) -> None:
        self.activity.log_module_performance(episode, tally, metrics_logger)

    def _log_episode_account(self, last_info, metrics_logger) -> None:
        self.activity.log_episode_account(last_info, metrics_logger)

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

        self.activity.start(episode.id_)

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
        # Tallied before anything that can be switched off (see `ActivityLog.record_step`).
        tally = self.activity.record_step(episode.id_, episode.get_infos(-1))

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
            recorder.record_step(episode, getattr(episode, "env_t", None) or tally["steps"])

    _fees_configured = staticmethod(nav_audit.fees_configured)

    _ledger_fees = staticmethod(nav_audit.ledger_fees)

    _ledger_navs = staticmethod(nav_audit.ledger_navs)

    def on_sample_end(self, *, env_runner=None, metrics_logger=None, samples=None, **kwargs):
        """Get the episodes finished so far onto disk.

        Without this the episode record's tail below `episode_rows_per_file` is
        written only by an `atexit` handler, which Ray does not reliably run
        when it stops an env runner (issue #245). The recorder is used only if
        it already exists: a runner that has not recorded anything has nothing
        to write and should not build a writer thread to find that out.
        """
        try:
            recorder = self._episode_recorder
            if recorder is not None:
                try:
                    recorder.flush_finished(wait=SAMPLE_END_DRAIN_S)
                except Exception:
                    logger.warning("episode record: the end-of-sample flush failed", exc_info=True)
        finally:
            # The iteration tag on a remote runner is only as fresh as the last broadcast,
            # and a runner the broadcast missed kept the previous iteration, so its lines
            # carried a plausible number that was wrong (issue #220). Clearing it when
            # this sample ends makes "not told" read as `-`, which looks wrong. Only a
            # remote runner: the local one shares the driver's process, and the driver
            # sets that tag itself for its own lines.
            if getattr(env_runner, "worker_index", 0):
                set_iteration(None)

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

        # Before `_log_activity`, which pops the tally: the NAV check below
        # needs the last NAV of any agent that terminated mid-episode, and
        # asking for it afterwards would silently build a fresh empty tally.
        carried_nav = dict((self.activity.tallies.get(episode.id_) or {}).get("last_nav", {}))

        self._log_activity(episode, metrics_logger)

        # Try to get parameters from different possible sources. The starting
        # points are the env's own fallback for init_cash and the league size
        # this callback was built with - not literals.
        init_cash = env_default("init_cash")
        num_agents = self.num_trainable + self.num_random

        init_cash, num_agents = nav_audit.run_parameters(env_runner, env, init_cash, num_agents)

        # Decimal, not float, all the way through the check: the ledger is
        # Decimal end to end and `info["NAV"]` is its exact `str()`, so parsing
        # it back with Decimal makes the comparison exact. Going through float
        # would reintroduce, at the last step, precisely the representation
        # error the account type exists to avoid.
        total_initial_cash = Decimal(str(init_cash)) * num_agents

        logger.debug(
            "episode %s parameters: env=%s env_runner=%s init_cash=%s "
            "num_agents=%s total_initial_cash=%s",
            episode.id_,
            type(env),
            type(env_runner),
            init_cash,
            num_agents,
            total_initial_cash,
        )

        last_info = episode.get_infos(-1)

        # An agent terminated mid-episode is absent from the final step's
        # `info`, so fall back to the last NAV it did report. Without this the
        # sum is short by exactly that agent's NAV and every episode containing
        # a bankruptcy reads as a conservation violation - which would halt a
        # strict run for a ledger that is perfectly intact.
        carried = carried_nav

        # The carried NAV is only exact if the terminated agent holds no
        # position. `set_done` pulls a bankrupt trader's resting orders but not
        # its inventory, and `mark_to_mkt` keeps marking every trader, so its
        # real NAV goes on moving after its last report while the survivors on
        # the other side of that position move the opposite way. Summing the
        # frozen value against the survivors' live ones is short by
        # `position * price move since termination` - measured at up to 578,800
        # on an intact ledger, which halted a strict run on iteration 1. So the
        # finished env's own accounts are preferred wherever they can be
        # reached, and the carry is the fallback.
        ledger = self._ledger_navs(env, env_index, last_info, num_agents)

        nav = nav_audit.sum_navs(last_info, carried, ledger, num_agents)
        total_nav = nav.total

        # Fees leave the traders for the exchange, so they are part of the sum.
        # They are only readable from the env's own accounts. Without those
        # (the carry fallback) and with fees configured, the sum is short by
        # exactly the fees and any comparison would misreport a ledger that is
        # intact, so the check is skipped and says so rather than guessing.
        fees = self._ledger_fees(env, env_index, num_agents) if ledger is not None else None
        if fees is None:
            if self._fees_configured(env_runner, env):
                logger.warning(
                    "episode %s: exchange fees are on but the env's accounts could "
                    "not be read, so NAV conservation was not checked.",
                    episode.id_,
                )
                if metrics_logger:
                    metrics_logger.log_value(NAV_VIOLATIONS_METRIC, 0.0, reduce="sum")
                    metrics_logger.log_value(NAV_UNCHECKED_METRIC, 1.0, reduce="sum")
                return
            fees = Decimal(0)
        error = total_nav + fees - total_initial_cash
        # Inclusive: with the comparison exact, "within tolerance" includes the
        # boundary, which is what makes nav_tolerance=0 mean "conservation must
        # be exact" rather than "every episode is a violation". At the default
        # 1e-6 the two forms differ only on an error of exactly 1e-6.
        conserved = abs(error) <= self.nav_tolerance

        # The metric goes out whether or not the invariant held, so a run has a
        # series to look at rather than only the moment it broke. Reduced by
        # max, per iteration: an error that appears in one episode out of many
        # must not be averaged away - or overwritten, which is what `window=1`
        # did, keeping only the last episode's value.
        if metrics_logger:
            # float() only at the boundary: the metrics stack reduces with
            # NumPy and will not take a Decimal. The check above has already
            # been decided exactly by this point.
            metrics_logger.log_value("nav_conservation_error", float(abs(error)), reduce="max")
            # Emitted every episode, including the conserved ones, so the key is
            # always present in the result and the driver's check reads a count
            # rather than having to distinguish "no violations" from "the metric
            # never arrived".
            metrics_logger.log_value(
                NAV_VIOLATIONS_METRIC,
                0.0 if conserved else 1.0,
                reduce="sum",
            )
            # Each agent's own last info, not the last env step's: an agent
            # bankrupted earlier is not part of that step, and leaving it out
            # hid exactly the loss `episode_nav_min` exists to show.
            self._log_episode_account(episode.get_infos(-1, env_steps=False), metrics_logger)

        report = nav_audit.report(episode.id_, nav, fees, total_initial_cash)

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
                MODULE_EPISODE_RETURNS_MEAN,
                ENV_RUNNER_RESULTS,
                sorted(env_runner_results.keys()),
            )
            return

        iteration = result['training_iteration']

        assessment = self.league.assess(algorithm, policy_returns, env_runner_results, iteration)
        if assessment is None:
            return
        league_state = assessment.state
        league_mean, league_std = assessment.mean, assessment.std
        promoted, idle = assessment.promoted, assessment.idle

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
            # §4 item 1). Counted from the league's champions either side of
            # the trigger rather than from the branch above, so a snapshot that
            # raised and rolled itself back is correctly reported as *not*
            # promoted.
            metrics_logger.log_value(
                "champions_promoted",
                float(promoted),
                reduce="sum",
            )
            metrics_logger.log_value(
                "available_modules",
                float(len(self.available_modules)),
                window=1,
            )
            metrics_logger.log_value(
                "idle_modules",
                float(idle),
                window=1,
            )
            if self.champion_history:
                metrics_logger.log_value(
                    "iterations_since_champion",
                    float(iteration - self.champion_history[-1]["iteration"]),
                    window=1,
                )

    @staticmethod
    def _candidate_trades(env_runner_results, module_id):
        """The module's mean trades per episode this iteration, or None if absent."""
        return league_stats.candidate_trades(env_runner_results, module_id, MODULE_TRADES_METRIC)
