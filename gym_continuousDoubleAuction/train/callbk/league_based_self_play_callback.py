from collections import defaultdict
from decimal import Decimal

import logging
import numpy as np
import os
import pickle
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
            episode_data_dir: Directory for per-episode step pickles, resolved
                relative to the working directory. Set to None to disable - this
                writes one file per episode containing every step's obs, action,
                reward and info, which at a few thousand steps per episode is a
                substantial amount of I/O and memory during training.
            nav_tolerance: Absolute cash tolerance for the episode-end NAV
                conservation check.
            strict_nav_check: Raise on a conservation violation instead of
                logging one. The `nav_conservation_error` metric is emitted
                either way.

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

        self.episode_data_dir = episode_data_dir
        self.nav_tolerance = nav_tolerance
        self.strict_nav_check = strict_nav_check

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

        # Per-episode step data, keyed by episode ID.
        #
        # This used to be a single shared list plus a single `self.ID`. That is
        # only safe with one env per EnvRunner: with
        # `num_envs_per_env_runner > 1`, episodes on the same runner interleave,
        # so steps from concurrent episodes were appended to one list and
        # written into whichever episode happened to end first - and the first
        # `on_episode_step` after any episode ended hit `None.append`, because
        # `on_episode_end` reset the shared list to None.
        self.store = defaultdict(list)

        # Per-episode activity tallies, keyed by episode ID like `store`, so
        # concurrent episodes under a vectorised runner cannot mix.
        #
        # A plain dict, not defaultdict(lambda: ...): this callback is
        # cloudpickled into every checkpoint, and a lambda default_factory is
        # the kind of thing that survives locally and fails on a restore path
        # nobody exercised. Three ints per live episode - the memory is nothing
        # next to `store`.
        self._activity = {}


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

        logger.debug(
            "episode %s activity: %s agent-steps, %.1f%% pass, %.1f%% rejected",
            episode.id_, agent_steps, 100 * pass_fraction,
            100 * rejection_fraction,
        )

    def _activity_for(self, episode_id) -> dict:
        """The tally for this episode, created if the start hook missed it.

        `on_episode_start` is not guaranteed to have run for every episode a
        worker reports on - a restored run picks up mid-flight - and a counter
        that raises KeyError would take down training for the sake of a metric.
        """
        return self._activity.setdefault(
            episode_id, {"agent_steps": 0, "passes": 0, "rejections": 0}
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

        self.store[episode.id_] = []
        self._activity[episode.id_] = {
            "agent_steps": 0, "passes": 0, "rejections": 0,
        }

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
        # print('on_episode_step')

        last_obs = episode.get_observations(-1)
        last_act = episode.get_actions(-1)
        last_reward = episode.get_rewards(-1)
        last_info = episode.get_infos(-1)
        step_data = {
            'episode_id': episode.id_,
            'obs': last_obs,
            'act': last_act,
            'reward': last_reward,
            'info': last_info,
        }
        self.store[episode.id_].append(step_data)

        # Tally activity as the episode runs. Counted here rather than from
        # `store` at episode end because `store` is only populated when
        # episode_data_dir is set, and these metrics must not depend on the
        # pickle dump being switched on.
        tally = self._activity_for(episode.id_)
        for agent_info in (last_info or {}).values():
            if not isinstance(agent_info, dict):
                continue
            tally["agent_steps"] += 1
            if agent_info.get("is_pass_action"):
                tally["passes"] += 1
            tally["rejections"] += int(agent_info.get("num_rejected_step", 0) or 0)

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

        # Persist this episode's step data, then drop it from the in-memory
        # store. Only this episode's steps are written - previously the whole
        # shared store was pickled, which under vectorised env runners meant
        # each file contained an interleaved mix of concurrent episodes.
        if self.episode_data_dir is not None:
            episode_steps = self.store.get(episode.id_, [])
            os.makedirs(self.episode_data_dir, exist_ok=True)
            path = os.path.join(self.episode_data_dir, f"{episode.id_}.pkl")
            with open(path, 'wb') as f:
                pickle.dump(episode_steps, f)

        # Always release the memory, whether or not we wrote it out.
        self.store.pop(episode.id_, None)

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
        # point is meaningless. Loud by default, downgradable for a run that
        # would rather finish and be inspected afterwards.
        message = (
            f"{report}\n  NAV conservation VIOLATED: difference "
            f"{error:,.2f} exceeds tolerance {self.nav_tolerance:g}"
        )
        logger.error(message)
        if self.strict_nav_check:
            raise AssertionError(message)

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


        # Check relative performance trigger
        if best_candidate and best_return > threshold:
            # Also check if it's better than previous champion (optional but good for progress)
            # best_historical = max([c['return'] for c in self.champion_history]) if self.champion_history else -float('inf')
            
            if self._should_create_champion(best_return, iteration, algorithm):
                 # Pass policy ID directly
                self._create_champion_snapshot_from_policy(
                    algorithm, best_candidate, best_return, iteration)
        
        # Log metrics
        if metrics_logger:
            metrics_logger.log_value(
                "league_size",
                self.num_trainable + self.num_random + self.champion_count,
                window=1,
            )
            metrics_logger.log_value("league_mean_return", league_mean, window=10)
            metrics_logger.log_value("league_std_return", league_std, window=10)
    
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