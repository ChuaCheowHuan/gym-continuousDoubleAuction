from ray.rllib.policy.policy import Policy
# from ray.rllib.agents.ppo.ppo_tf_policy import PPOTFPolicy

from gym.spaces import Box
import numpy as np
import random
import tree  # pip install dm_tree

from ray.rllib.policy.policy import Policy
from ray.rllib.policy.sample_batch import SampleBatch
from ray.rllib.utils.annotations import override
from ray.rllib.utils.typing import ModelWeights

def make_RandomPolicy(_seed):

    class RandomPolicy(Policy):
        """Hand-coded policy that returns random actions."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)

            # Whether for compute_actions, the bounds given in action_space
            # should be ignored (default: False). This is to test action-clipping
            # and any Env's reaction to bounds breaches.
            if self.config.get("ignore_action_bounds", False) and isinstance(
                self.action_space, Box
            ):
                self.action_space_for_sampling = Box(
                    -float("inf"),
                    float("inf"),
                    shape=self.action_space.shape,
                    dtype=self.action_space.dtype,
                )
            else:
                self.action_space_for_sampling = self.action_space

        @override(Policy)
        def init_view_requirements(self):
            super().init_view_requirements()
            # Disable for_training and action attributes for SampleBatch.INFOS column
            # since it can not be properly batched.
            vr = self.view_requirements[SampleBatch.INFOS]
            vr.used_for_training = False
            vr.used_for_compute_actions = False

        @override(Policy)
        def compute_actions(
            self,
            obs_batch,
            state_batches=None,
            prev_action_batch=None,
            prev_reward_batch=None,
            **kwargs
        ):
            # Alternatively, a numpy array would work here as well.
            # e.g.: np.array([random.choice([0, 1])] * len(obs_batch))
            return [self.action_space_for_sampling.sample() for _ in obs_batch], [], {}

        @override(Policy)
        def learn_on_batch(self, samples):
            """No learning."""
            return {}

        @override(Policy)
        def compute_log_likelihoods(
            self,
            actions,
            obs_batch,
            state_batches=None,
            prev_action_batch=None,
            prev_reward_batch=None,
        ):
            return np.array([random.random()] * len(obs_batch))

        @override(Policy)
        def get_weights(self) -> ModelWeights:
            """No weights to save."""
            return {}

        @override(Policy)
        def set_weights(self, weights: ModelWeights) -> None:
            """No weights to set."""
            pass

        @override(Policy)
        def _get_dummy_batch_from_view_requirements(self, batch_size: int = 1):
            return SampleBatch(
                {
                    SampleBatch.OBS: tree.map_structure(
                        lambda s: s[None], self.observation_space.sample()
                    ),
                }
            )

def make_RandomPolicy_0(_seed):

    class RandomPolicy(Policy):
        """
        A hand-coded policy that returns random actions in the env (doesn't learn).
        """

        def __init__(self, observation_space, action_space, config):
            self.observation_space = observation_space
            self.action_space = action_space
            self.action_space.seed(_seed)

            # Can be called from within a Policy to make sure RNNs automatically
            # update their internal state-related view requirements.
            # Changes the `self.view_requirements` dict.
            self._model_init_state_automatically_added = True

        def compute_actions(self,
                            obs_batch,
                            state_batches,
                            prev_action_batch=None,
                            prev_reward_batch=None,
                            info_batch=None,
                            episodes=None,
                            **kwargs):
            """Compute actions on a batch of observations."""
            return [self.action_space.sample() for _ in obs_batch], [], {}

        def learn_on_batch(self, samples):
            """No learning."""
            #return {}
            pass

        def get_weights(self):
            pass

        def set_weights(self, weights):
            pass

    return RandomPolicy

def gen_policy(i, obs_space, act_space):
    """
    Each policy can have a different configuration (including custom model)
    """

    config = {"model": {"custom_model": "model_disc"},
              "gamma": 0.99,}
    return (None, obs_space, act_space, config)

def set_agents_policies(policies, obs_space, act_space, num_agents, num_trained_agent):
    """
    Set 1st policy as PPO & override all other policies as RandomPolicy with
    different seed.
    """

    # set all agents to use random policy
    for i in range(num_agents):
        policies["policy_{}".format(i)] = (make_RandomPolicy(i), obs_space, act_space, {})

    # set trained agents to use None (PPOTFPolicy)
    for i in range(num_trained_agent):
        #policies["policy_{}".format(i)] = (PPOTFPolicy, obs_space, act_space, {})
        policies["policy_{}".format(i)] = (None, obs_space, act_space, {})

    print('policies:', policies)
    return 0

def create_train_policy_list(num_trained_agent, prefix):
    """
    Storage for train_policy_list for declaring train poilicies in trainer config.
    """
    
    storage = []
    for i in range(0, num_trained_agent):
        storage.append(prefix + str(i))

    print("train_policy_list = ", storage)
    return storage
