from collections import defaultdict

import numpy as np
import pprint

from ray.rllib.callbacks.callbacks import RLlibCallback
from ray.rllib.core.rl_module.rl_module import RLModuleSpec
from ray.rllib.utils.metrics import ENV_RUNNER_RESULTS


class SelfPlayCallback(RLlibCallback):
    # def __init__(self, win_rate_threshold):
    def __init__(self):
        super().__init__()
        # 0=RandomPolicy, 1=1st main policy snapshot,
        # 2=2nd main policy snapshot, etc..
        # self.current_opponent = 0

        # self.win_rate_threshold = win_rate_threshold

        # # Report the matchup counters (who played against whom?).
        # self._matching_stats = defaultdict(int)

        self.ID = None

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
        """Callback run right after an Episode has been started.

        This method gets called after a SingleAgentEpisode or MultiAgentEpisode instance
        has been reset with a call to `env.reset()` by the EnvRunner.

        1) Single-/MultiAgentEpisode created: `on_episode_created()` is called.
        2) Respective sub-environment (gym.Env) is `reset()`.
        3) Single-/MultiAgentEpisode starts: This callback is called.
        4) Stepping through sub-environment/episode commences.

        Args:
            episode: The just started (after `env.reset()`) SingleAgentEpisode or
                MultiAgentEpisode object.
            env_runner: Reference to the EnvRunner running the env and episode.
            metrics_logger: The MetricsLogger object inside the `env_runner`. Can be
                used to log custom metrics during env/episode stepping.
            env: The gym.Env or gym.vector.Env object running the started episode.
            env_index: The index of the sub-environment that is about to be reset
                (within the vector of sub-environments of the BaseEnv).
            rl_module: The RLModule used to compute actions for stepping the env. In
                single-agent mode, this is a simple RLModule, in multi-agent mode, this
                is a MultiRLModule.
            kwargs: Forward compatibility placeholder.
        """
        print('on_episode_start')
        self.ID = episode.id_

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
        print('on_episode_step')

        self.ID = episode.id_

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
        # # Compute the win rate for this episode and log it with a window of 100.
        # main_agent = 0 if episode.module_for(0) == "main" else 1
        # rewards = episode.get_rewards()
        # if main_agent in rewards:
        #     main_won = rewards[main_agent][-1] == 1.0
        #     metrics_logger.log_value(
        #         "win_rate",
        #         main_won,
        #         reduce="mean",
        #         window=100,
        #     )
        last_obs = episode.get_observations(-1)
        last_act = episode.get_actions(-1)
        last_reward = episode.get_rewards(-1)
        last_info = episode.get_infos(-1)

        print(f'on_episode_end:{episode}')

        print(f'last_obs:{last_obs}')  
        print(f'last_act:{last_act}')        
        print(f'last_reward:{last_reward}')        
        print(f'last_info:{last_info}')        

    def on_train_result(self, *, algorithm, metrics_logger=None, result, **kwargs):
        # win_rate = result[ENV_RUNNER_RESULTS]["win_rate"]
        # print(f"Iter={algorithm.iteration} win-rate={win_rate} -> ", end="")
        # # If win rate is good -> Snapshot current policy and play against
        # # it next, keeping the snapshot fixed and only improving the "main"
        # # policy.
        # if win_rate > self.win_rate_threshold:
        #     self.current_opponent += 1
        #     new_module_id = f"main_v{self.current_opponent}"
        #     print(f"adding new opponent to the mix ({new_module_id}).")

        #     # Re-define the mapping function, such that "main" is forced
        #     # to play against any of the previously played modules
        #     # (excluding "random").
        #     def agent_to_module_mapping_fn(agent_id, episode, **kwargs):
        #         # agent_id = [0|1] -> policy depends on episode ID
        #         # This way, we make sure that both modules sometimes play
        #         # (start player) and sometimes agent1 (player to move 2nd).
        #         opponent = "main_v{}".format(
        #             np.random.choice(list(range(1, self.current_opponent + 1)))
        #         )
        #         if hash(episode.id_) % 2 == agent_id:
        #             self._matching_stats[("main", opponent)] += 1
        #             return "main"
        #         else:
        #             return opponent

        #     main_module = algorithm.get_module("main")
        #     algorithm.add_module(
        #         module_id=new_module_id,
        #         module_spec=RLModuleSpec.from_module(main_module),
        #         new_agent_to_module_mapping_fn=agent_to_module_mapping_fn,
        #     )
        #     # TODO (sven): Maybe we should move this convenience step back into
        #     #  `Algorithm.add_module()`? Would be less explicit, but also easier.
        #     algorithm.set_state(
        #         {
        #             "learner_group": {
        #                 "learner": {
        #                     "rl_module": {
        #                         new_module_id: main_module.get_state(),
        #                     }
        #                 }
        #             }
        #         }
        #     )
        # else:
        #     print("not good enough; will keep learning ...")

        # # +2 = main + random
        # result["league_size"] = self.current_opponent + 2

        # print(f"Matchups:\n{self._matching_stats}")
        policy_0_module = algorithm.get_module("policy_0")
        policy_1_module = algorithm.get_module("policy_1")
        policy_2_module = algorithm.get_module("policy_2")
        policy_3_module = algorithm.get_module("policy_3")

        print(f'on_train_result:{result}')
        pprint.pprint(result, indent=4, width=40, depth=3)
        print(f'algorithm:{algorithm}')
        
        print(f'agent_0_module:{policy_0_module}')        
        print(f'agent_1_module:{policy_1_module}')
        print(f'agent_2_module:{policy_2_module}')
        print(f'agent_3_module:{policy_3_module}')

        # Access agent_episode_returns_mean
        agent_returns = result['env_runners']['agent_episode_returns_mean']

        # Find the agent with max return
        best_agent = max(agent_returns, key=agent_returns.get)
        max_value = agent_returns[best_agent]        
        print(f"Top-performing agent: {best_agent} with return {max_value}")

        if max_value >= 0:



            # Hard coded to test copying weights
            best_agent = 'agent_0'



            agent_id = int(best_agent.split('_')[1])
            best_policy = 'policy_' + str(agent_id)
            


            # Hard coded to test copying weights
            trainable_list = [0,1]
            

            
            # Check if best policy is trainable            
            if agent_id in trainable_list:
                # Copy to all other trainable policies (excluding the best policy itself)
                for target_id in trainable_list:
                    if target_id != agent_id:  # Ensure best and target are different
                        target_policy = 'policy_' + str(target_id)
                        
                        best_module = algorithm.get_module(best_policy)
                        target_module = algorithm.get_module(target_policy)
                        
                        def set_weights(algorithm, target_policy, best_module):
                            # Copy weights
                            algorithm.set_state(
                                {
                                    "learner_group": {
                                        "learner": {
                                            "rl_module": {
                                                target_policy: best_module.get_state(),
                                            }
                                        }
                                    }
                                }
                            )
                        
                        set_weights(algorithm, target_policy, best_module)
                        print(f"Copied weights from {best_policy} to {target_policy}")
            else:
                print(f"Skipping weight copy: {best_policy} is not trainable")