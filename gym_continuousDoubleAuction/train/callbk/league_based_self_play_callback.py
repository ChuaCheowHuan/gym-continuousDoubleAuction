from collections import defaultdict

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

from gym_continuousDoubleAuction.train.policy.policy_handler import (
    CHAMPION_PREFIX,
    POLICY_PREFIX,
    policy_id,
)

# Per-module mean return over the iteration, keyed by ModuleID. This is the
# new-API-stack replacement for the old `hist_stats["policy_<id>_reward"]` /
# `policy_reward_mean`, neither of which exists any more.
MODULE_EPISODE_RETURNS_MEAN = "module_episode_returns_mean"


class SelfPlayCallback(RLlibCallback):
    def __init__(
        self, 
        num_trainable_policies=2, 
        num_random_policies=2, 
        std_dev_multiplier=2.0, 
        max_champions=2, 
        min_iterations_between_champions=2,
        original_opponent_weight=1.0,
        champion_weight=3.0,
        episode_data_dir="episode_data",
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

        Total Agents n = k + m
        """
        super().__init__()

        self.episode_data_dir = episode_data_dir

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
        print(f"\n{'='*40}")
        print(f"Episode {episode.id_} Started - Policy Map:")

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
        for i in range(self.num_trainable + self.num_random):
            agent_id = f"agent_{i}"
            print(f"  {agent_id} -> {mapping_fn(agent_id, episode)}")

        print(f"{'='*40}\n")

        self.store[episode.id_] = []

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
        print(f'on_episode_end:{episode}')

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

        # Try to get parameters from different possible sources
        init_cash = 0
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

        total_initial_cash = float(init_cash) * num_agents

        print(f"DEBUG: env type: {type(env)}")
        print(f"DEBUG: env_runner type: {type(env_runner)}")
        print(f"DEBUG: init_cash derived: {init_cash}")
        print(f"DEBUG: num_agents derived: {num_agents}")
        print(f"DEBUG: total_initial_cash: {total_initial_cash}")

        last_info = episode.get_infos(-1)
        
        print(f"\n{'='*20} Episode {episode.id_} NAV Verification {'='*20}")
        total_nav = 0.0
        for i in range(num_agents):
            agent_key = f"agent_{i}"
            if agent_key in last_info:
                nav_str = last_info[agent_key].get("NAV", "0")
                nav = float(nav_str)
                total_nav += nav
                print(f"  {agent_key} NAV: {nav:,.2f}")
        
        print(f"  Total NAV: {total_nav:,.2f}")
        print(f"  Expected Total Initial Cash: {total_initial_cash:,.2f}")
        
        if abs(total_nav - total_initial_cash) < 1e-6:
            print("  Verification: SUCCESS (Total NAV matches initial cash)")
        else:
            print(f"  Verification: FAILED (Difference: {total_nav - total_initial_cash:,.2f})")
        print(f"{'='*60}\n")

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
            print(
                f"[SelfPlayCallback] '{MODULE_EPISODE_RETURNS_MEAN}' missing or "
                f"empty in result['{ENV_RUNNER_RESULTS}']; skipping champion "
                f"check this iteration. Available keys: "
                f"{sorted(env_runner_results.keys())}"
            )
            return

        iteration = result['training_iteration']
        
        # Filter mostly interesting policies (exclude extremely sparse ones if any)
        # and calculate league statistics
        valid_returns = [v for v in policy_returns.values() if v is not None]
        
        if not valid_returns:
            print("No valid policy returns found this iteration.")
            return

        league_mean = np.mean(valid_returns)
        league_std = np.std(valid_returns)
        
        # Determine dynamic threshold
        # If std is 0 (all same), effectively requires > mean
        threshold = league_mean + (self.std_dev_multiplier * league_std)
        
        print(f"\n{'='*80}")
        print(f"Iteration {iteration} League Stats:")
        print(f"Mean: {league_mean:.2f} | Std: {league_std:.2f} | Threshold: {threshold:.2f}")
        print(f"Policy Returns: {policy_returns}")
        
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
        
        print(f"Best Trainable: {best_candidate} ({best_return:.2f})")
        print(f"{'='*80}\n")
        
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
                print(f"Skipping champion creation: only {iteration - last_champion_iter} iterations "
                      f"since last champion (min: {self.min_iterations_between_champions})")
                return False

        # Check if we need to remove old champion first (rolling window)
        if self.champion_count >= self.max_champions:
            print(f"Max champions ({self.max_champions}) reached, will remove oldest")
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
        
        print(f"\n{'*'*80}")
        print(f"🏆 CREATING CHAMPION SNAPSHOT 🏆")
        print(f"Champion ID: {champion_id}")
        print(f"Source Policy: {source_policy_id}")
        print(f"Return: {return_value:.2f}")
        print(f"Iteration: {iteration}")
        print(f"{'*'*80}\n")
        
        try:
            # Get the source module. Read it from the LearnerGroup, not from
            # `algorithm.get_module()`: the latter returns the EnvRunner's
            # inference-only copy, which omits the value-function head. We want
            # the full module state so the snapshot is complete.
            source_module = algorithm.learner_group._learner.module[source_policy_id]
            source_state = source_module.get_state()

            champion_spec = RLModuleSpec.from_module(source_module)

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

            print(f"✓ Champion {champion_id} created successfully!")
            print(f"✓ League size now: "
                  f"{self.num_trainable + self.num_random + self.champion_count} "
                  f"({self.num_trainable} trainable + {self.num_random} random "
                  f"+ {self.champion_count} champions)")
            print(f"✓ Active champions: {[c['id'] for c in self.champion_history]}\n")
            
        except Exception as e:
            # Roll the pool entry back so matchmaking can never select a module
            # that failed to be created.
            if champion_id in self.available_modules:
                self.available_modules.remove(champion_id)
            print(f"✗ Error creating champion {champion_id}: {e}")
            import traceback
            traceback.print_exc()
    
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

        print(f"\n⚠️  Removing oldest champion: {champion_id} "
              f"(from iteration {oldest['iteration']}, return={oldest['return']:.2f})")

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
            print(f"⚠️  Could not remove module {champion_id} from algorithm: {e}")

        print(f"✓ Champion removed. Active champions: {[c['id'] for c in self.champion_history]}\n")
    
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