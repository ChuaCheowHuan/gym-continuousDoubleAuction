"""The league: champions, the matchmaking pool, and the champion check (issue #253).

Split out of `SelfPlayCallback`, which had this, the NAV audit, the activity tally and the
recorder hook in one class. `League` owns the state that indexes the champion modules - the
history, the monotonic id counter, the pool - and the decisions about it: whether an
iteration's returns promote a candidate, taking and evicting snapshots, reconciling with a
saved sidecar, and the agent-to-module mapping the runners use. The callback keeps the RLlib
hook signatures and delegates.
"""

from __future__ import annotations

import math
import zlib
from typing import NamedTuple

import numpy as np
from ray.rllib.core import (
    COMPONENT_LEARNER,
    COMPONENT_LEARNER_GROUP,
    COMPONENT_RL_MODULE,
)
from ray.rllib.core.rl_module.rl_module import RLModuleSpec

from gym_continuousDoubleAuction.logging_setup import get_logger
from gym_continuousDoubleAuction.train.callbk import league_stats
from gym_continuousDoubleAuction.train.callbk.activity import MODULE_TRADES_METRIC
from gym_continuousDoubleAuction.train.policy.policy_handler import (
    CHAMPION_PREFIX,
    POLICY_PREFIX,
    policy_id,
)
from gym_continuousDoubleAuction.train.returns import usable_return

logger = get_logger(__name__)

#: The modules the promotion threshold can be computed over (doc/15 S3-12).
PROMOTION_REFERENCES = ("pooled", "excluding_baselines")


class Assessment(NamedTuple):
    """What one iteration's league check found, for the callback to publish."""

    state: dict  # `result["league"]`
    mean: float  # the league mean return
    std: float  # ... and its standard deviation
    promoted: int  # champions added this iteration
    idle: int  # modules that played no episodes


class League:
    def __init__(
        self,
        num_trainable,
        num_random,
        *,
        std_dev_multiplier,
        max_champions,
        min_iterations_between_champions,
        original_opponent_weight,
        champion_weight,
        min_champion_trades,
        promotion_reference,
    ):
        if promotion_reference not in PROMOTION_REFERENCES:
            raise ValueError(
                f"promotion_reference must be one of {PROMOTION_REFERENCES}; "
                f"got {promotion_reference!r}."
            )
        for name, weight in (
            ("champion_weight", champion_weight),
            ("original_opponent_weight", original_opponent_weight),
        ):
            # A weight is a share of the draw: not a count, not negative, not unbounded.
            # Zero is allowed - it removes that kind from the draw (issue #207).
            if (
                isinstance(weight, bool)
                or not isinstance(weight, (int, float))
                or not math.isfinite(weight)
                or weight < 0
            ):
                raise ValueError(f"{name} must be a finite number >= 0; got {weight!r}.")
        self.num_trainable = num_trainable
        self.num_random = num_random
        self.min_champion_trades = min_champion_trades
        self.promotion_reference = promotion_reference
        self._warned_reference_fallback = False

        # Champion snapshotting configuration
        self.std_dev_multiplier = std_dev_multiplier
        # With n modules, no module is more than sqrt(n - 1) population standard
        # deviations above their mean, so a multiplier at or above that can
        # never be cleared and the league would silently never grow. The pool
        # only gets bigger after the first champion, so n at the start is the
        # case that matters.
        ceiling = math.sqrt(max(num_trainable + num_random - 1, 0))
        if std_dev_multiplier >= ceiling:
            logger.warning(
                "std_dev_multiplier=%g can never be cleared by a league of %d "
                "modules (the best any module can do is %.2f standard "
                "deviations above the mean), so no champion will ever be "
                "promoted. Lower it, or add modules.",
                std_dev_multiplier,
                num_trainable + num_random,
                ceiling,
            )
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
        self.available_modules = [policy_id(i) for i in range(self.num_trainable + self.num_random)]

    @classmethod
    def from_flat(cls, flat):
        """A league from the attributes a pre-#253 callback carried, filling in later knobs.

        Knobs added after the checkpoint was written get what that run effectively had: the
        pooled threshold (quiet, nothing changes for it) and no passivity guard (said out
        loud, so the run is not left to find out).
        """
        league = cls.__new__(cls)
        league.__dict__.update(flat)
        if "promotion_reference" not in flat:
            league.promotion_reference = "pooled"
        if "_warned_reference_fallback" not in flat:
            league._warned_reference_fallback = False
        if "min_champion_trades" not in flat:
            league.min_champion_trades = 0.0
            logger.warning(
                "this league callback was saved before the champion passivity "
                "guard existed (doc/15 S3-11), so it runs without one: a policy "
                "that has stopped trading can still be promoted. Start a fresh "
                "run to get min_champion_trades."
            )
        return league

    def assess(self, algorithm, policy_returns, env_runner_results, iteration):
        """Run the champion check on one iteration's returns; promote if it clears.

        Returns an `Assessment`, or None when there were no usable returns.
        """
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
        valid_returns, idle_modules = league_stats.split_returns(policy_returns)

        if not valid_returns:
            logger.warning("No valid policy returns found this iteration.")
            return None

        if idle_modules:
            logger.info(
                "iteration %s: %s played no episodes and are excluded from the league statistics",
                iteration,
                ", ".join(idle_modules),
            )

        reference_returns, reference_used = self.threshold_returns(policy_returns, valid_returns)
        league_mean = np.mean(reference_returns)
        league_std = np.std(reference_returns)

        # Determine dynamic threshold
        # If std is 0 (all same), effectively requires > mean
        threshold = league_mean + (self.std_dev_multiplier * league_std)

        # Check trainable policies for champion status
        trainable_policies = [policy_id(i) for i in range(self.num_trainable)]

        best_candidate, best_return = league_stats.best_trainable(
            policy_returns, trainable_policies
        )

        logger.info(
            "iteration %s league stats: mean=%.2f std=%.2f threshold=%.2f best_trainable=%s (%.2f)",
            iteration,
            league_mean,
            league_std,
            threshold,
            best_candidate,
            best_return,
        )
        logger.debug("iteration %s policy returns: %s", iteration, policy_returns)

        # Iterations since the last champion snapshot. `_should_create_champion`
        # has computed this since it was written and thrown it away every time
        # (doc/11 §2.5); it is the number that says whether the cooldown or the
        # threshold is what is holding the league still. None before the first
        # champion, which is a different state from "0 iterations ago" - so no
        # metric is emitted rather than a misleading zero.
        # Promotions are champions present after the trigger that were not there
        # before. Not the change in `champion_count`: a full league evicts its
        # oldest champion first, so the count is the same either side and a
        # promotion into a full league read as none. A snapshot that raised and
        # rolled back adds no id, so it is still not counted.
        champions_before = {c["id"] for c in self.champion_history}

        # A policy that has stopped trading earns exactly 0, and 0 beats a league
        # of modules that are losing money, so it clears the return threshold
        # (doc/15 S3-11). Refuse it. `None` means the trade counts did not reach
        # the result; that is reported but does not block, because a guard that
        # blocks on missing data would stop the league growing, silently and
        # for good, the way the NaN threshold once did.
        refused_passive = False
        if best_candidate and best_return > threshold and self.min_champion_trades > 0:
            trades = league_stats.candidate_trades(
                env_runner_results, best_candidate, MODULE_TRADES_METRIC
            )
            if trades is None:
                logger.warning(
                    "iteration %s: no %r for %s in the result, so the "
                    "does-it-trade guard could not run; promoting on return "
                    "alone.",
                    iteration,
                    MODULE_TRADES_METRIC,
                    best_candidate,
                )
            elif trades < self.min_champion_trades:
                refused_passive = True
                logger.warning(
                    "iteration %s: %s cleared the return threshold (%.2f > %.2f) "
                    "but traded %.2f times per episode, under the %g required; "
                    "not promoting a policy that has stopped trading.",
                    iteration,
                    best_candidate,
                    best_return,
                    threshold,
                    trades,
                    self.min_champion_trades,
                )

        # Check relative performance trigger
        if best_candidate and best_return > threshold and not refused_passive:
            # Also check if it's better than previous champion (optional but good for progress)
            # best_historical = max([c['return'] for c in self.champion_history]) if self.champion_history else -float('inf')

            if self.should_create(best_return, iteration, algorithm):
                # Pass policy ID directly
                self.create_snapshot(algorithm, best_candidate, best_return, iteration)
                self._evict_over_limit(algorithm)
        promoted = len({c["id"] for c in self.champion_history} - champions_before)

        league_state = {
            "size": self.num_trainable + self.num_random + self.champion_count,
            "mean_return": float(league_mean),
            "std_return": float(league_std),
            "threshold": float(threshold),
            "promoted": promoted,
            "refused_passive": int(refused_passive),
            # Which set the threshold above was computed over, which is not the
            # configured one while that set is too small to be cleared.
            "reference": reference_used,
            "available_modules": len(self.available_modules),
            "idle_modules": len(idle_modules),
            "champions": [c["id"] for c in self.champion_history],
        }
        if self.champion_history:
            league_state["iterations_since_champion"] = (
                iteration - self.champion_history[-1]["iteration"]
            )

        return Assessment(
            state=league_state,
            mean=league_mean,
            std=league_std,
            promoted=promoted,
            idle=len(idle_modules),
        )

    def threshold_returns(self, policy_returns, valid_returns):
        """The returns the promotion threshold is computed over, and which set that is.

        `pooled` is every module that played, the frozen random baselines
        included. `excluding_baselines` leaves them out: a baseline's return is
        what a random agent earns in whatever role it is dealt, which is not
        comparable with a learner's, and with them in a learner can clear the bar
        by trading less rather than better (doc/15 S3-12).

        With n modules nobody is more than sqrt(n - 1) standard deviations above
        the mean, so a set of n <= multiplier^2 + 1 can never promote anyone
        (n = 2 at the start, two trainables and no champion, for the default 1.5).
        Rather than stop the league growing, the threshold falls back to the
        pooled one while the non-baseline set is that small, once warned.
        """
        if self.promotion_reference == "pooled":
            return valid_returns, "pooled"
        baselines = {
            policy_id(i) for i in range(self.num_trainable, self.num_trainable + self.num_random)
        }
        kept = [
            v
            for module_id, v in policy_returns.items()
            if module_id not in baselines and usable_return(v) is not None
        ]
        if math.sqrt(max(len(kept) - 1, 0)) <= self.std_dev_multiplier:
            if not self._warned_reference_fallback:
                self._warned_reference_fallback = True
                logger.warning(
                    "promotion_reference 'excluding_baselines' has %s module(s) to "
                    "compare, and with that few nobody can be more than sqrt(n - 1) = "
                    "%.2f standard deviations above the mean, under the %g needed: "
                    "using the pooled threshold until there are enough champions.",
                    len(kept),
                    math.sqrt(max(len(kept) - 1, 0)),
                    self.std_dev_multiplier,
                )
            return valid_returns, "pooled"
        return kept, "excluding_baselines"

    def should_create(self, return_value, iteration, algorithm):
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

        # Eviction is NOT done here. It used to be, so a full league lost its oldest champion
        # before the snapshot that was to replace it was taken, and a failed snapshot shrank
        # the league for nothing (doc/15 R-8, #178). `assess` evicts once the new champion
        # exists; `algorithm` is kept in the signature for the callers that pass it.
        return True

    def create_snapshot(self, algorithm, source_policy_id, return_value, iteration):
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
        module_added = False

        logger.info(
            "Creating champion snapshot %s from %s (return %.2f, iteration %s)",
            champion_id,
            source_policy_id,
            return_value,
            iteration,
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
                components=(f"{COMPONENT_LEARNER}/{COMPONENT_RL_MODULE}/{source_policy_id}"),
            )[COMPONENT_LEARNER][COMPONENT_RL_MODULE][source_policy_id]

            # The spec only needs the module's shape, not its weights, so it can
            # come from the local EnvRunner copy (always present, even when
            # sampling happens remotely). `inference_only=False` keeps the
            # champion's structure identical to the source module on the
            # Learner, so the state loaded above applies cleanly.
            champion_spec = RLModuleSpec.from_module(algorithm.env_runner.module[source_policy_id])
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
                new_agent_to_module_mapping_fn=League.get_mapping_fn(self),
            )
            module_added = True

            # Copy the trained weights into the champion on the Learner...
            algorithm.set_state(
                {
                    COMPONENT_LEARNER_GROUP: {
                        COMPONENT_LEARNER: {
                            COMPONENT_RL_MODULE: {
                                champion_id: source_state,
                            }
                        }
                    }
                }
            )

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
                self.num_trainable,
                self.num_random,
                self.champion_count,
                [c['id'] for c in self.champion_history],
            )

        except Exception as e:
            # Roll the pool entry back so matchmaking can never select a module
            # that failed to be created.
            if champion_id in self.available_modules:
                self.available_modules.remove(champion_id)
            # `add_module` shipped a frozen copy of the pool, champion included, to every
            # remote env runner, and the module itself now exists with weights that were
            # never copied in. Taking it out again also ships the corrected pool; rolling back
            # the driver's list alone left the runners picking a randomly initialised module
            # the league believed it did not have (doc/15 R-6, #176).
            if module_added:
                try:
                    algorithm.remove_module(
                        module_id=champion_id,
                        new_agent_to_module_mapping_fn=League.get_mapping_fn(self),
                    )
                except Exception as undo_error:
                    logger.warning(
                        "Could not remove the half-created module %s after a failed "
                        "snapshot: %s. Remote runners may still offer it.",
                        champion_id,
                        undo_error,
                    )
            # exc_info carries the traceback that the bare `traceback.print_exc`
            # used to put on stderr, unattached to the message it belonged to.
            logger.error(
                "Error creating champion %s: %s",
                champion_id,
                e,
                exc_info=True,
            )

    def _evict_over_limit(self, algorithm):
        """Drop the oldest champions beyond `max_champions`, after a snapshot succeeded.

        Make-before-break: the new champion is in place first, so the league never has fewer
        champions than it did because a snapshot failed (doc/15 R-8, #178). The cost is one
        extra module for the moment between the two. A failed snapshot leaves the history at
        or under the limit, so this does nothing.
        """
        while len(self.champion_history) > self.max_champions:
            logger.info(
                "Max champions (%s) exceeded, removing the oldest",
                self.max_champions,
            )
            self.remove_oldest(algorithm)

    def remove_oldest(self, algorithm):
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
            # %s, not %.2f: a champion adopted on restore has return None.
            "Removing oldest champion %s (from iteration %s, return %s)",
            champion_id,
            oldest['iteration'],
            oldest['return'],
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
                new_agent_to_module_mapping_fn=League.get_mapping_fn(self),
            )
        except Exception as e:
            # Non-fatal: the champion is already out of the matchmaking pool, so
            # training stays correct - we just keep holding its memory.
            logger.warning(
                "Could not remove module %s from the algorithm: %s",
                champion_id,
                e,
            )

        logger.info(
            "Champion removed. Active champions: %s",
            [c['id'] for c in self.champion_history],
        )

    def state(self):
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

    def restore(self, state, present_modules=None):
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
            present_champions = {m for m in present_modules if m.startswith(CHAMPION_PREFIX)}
            for champion in list(self.champion_history):
                if champion['id'] not in present_champions:
                    self.champion_history.remove(champion)
                    repairs.append(
                        f"dropped {champion['id']}: the restored algorithm has no such module"
                    )
            known = {c['id'] for c in self.champion_history}
            for module_id in sorted(present_champions - known):
                # Ordering within the history decides eviction order, and an
                # orphan's true position is unknowable - it goes last, so a
                # rolling window evicts a champion whose iteration is known first.
                self.champion_history.append(
                    {
                        'id': module_id,
                        'source_policy': None,
                        'iteration': state.get('training_iteration', 0),
                        'return': None,
                    }
                )
                repairs.append(
                    f"adopted {module_id}: present in the checkpoint but missing "
                    f"from the league state (appended as newest)"
                )

        # The pool is derived, so rebuild it rather than repairing it in place.
        pool = [policy_id(i) for i in range(self.num_trainable + self.num_random)] + [
            c['id'] for c in self.champion_history
        ]
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
                int(c['id'][len(CHAMPION_PREFIX) :])
                for c in self.champion_history
                if c['id'][len(CHAMPION_PREFIX) :].isdigit()
            ]
            + [0]
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
    def get_mapping_fn(cls, league):
        """
        Create an agent-to-module mapping function that includes champions.

        Args:
            league: The League whose pool it reads

        Returns:
            Mapping function for use in multi_agent config
        """

        warned_zero_total = []

        def agent_to_module_mapping_fn(agent_id, episode, **kwargs):
            """Assign agents to modules including dynamic champions."""
            agent_num = int(agent_id.split("_")[1])

            # Trainable policies always assigned to their respective agents
            if agent_num < league.num_trainable:
                return policy_id(agent_num)

            # For random/league agents, assign from pool (champions + original randoms)
            # The pool starts AFTER the trainable policies
            # Pool = available_modules[k:]
            candidates = league.available_modules[league.num_trainable :]

            if not candidates:
                # Fallback if the pool is somehow empty
                return policy_id(agent_num)

            # Calculate weights for candidates
            weights = []
            for c in candidates:
                if c.startswith(CHAMPION_PREFIX):
                    # Dynamic champion snapshots
                    weights.append(league.champion_weight)
                elif c.startswith(POLICY_PREFIX):
                    # Original fixed/random policies
                    weights.append(league.original_opponent_weight)
                else:
                    weights.append(1.0)  # Fallback

            # Normalize to probabilities
            weights = np.array(weights, dtype=np.float64)
            total = weights.sum()
            if total <= 0.0:
                # Every candidate has weight zero (both weights 0, or only zero-weight
                # champions left in the pool): the draw has no preference to express, and
                # dividing by the sum gave NaN probabilities and a crash in `rng.choice`
                # (issue #207). Uniform is the neutral reading; say so once per process.
                if not warned_zero_total:
                    warned_zero_total.append(True)
                    logger.warning(
                        "every candidate in the matchmaking pool has weight 0 "
                        "(champion_weight=%s, original_opponent_weight=%s): drawing "
                        "uniformly instead",
                        league.champion_weight,
                        league.original_opponent_weight,
                    )
                probs = np.full(len(weights), 1.0 / len(weights))
            else:
                probs = weights / total

            # Seed from the episode ID and agent index so the assignment is
            # reproducible.
            #
            # Uses zlib.crc32 rather than the builtin hash(): hash() on str is
            # salted by PYTHONHASHSEED, so it differs between processes and
            # between runs. That made the "deterministic selection" this comment
            # promised reproducible only within a single process.
            seed = (zlib.crc32(str(episode.id_).encode("utf-8")) + agent_num) % (2**32)
            rng = np.random.RandomState(seed)
            # Cast to plain str: rng.choice returns np.str_, which compares
            # equal to str but shows up as `np.str_('policy_2')` in logs and
            # checkpoints.
            return str(rng.choice(candidates, p=probs))

        return agent_to_module_mapping_fn
