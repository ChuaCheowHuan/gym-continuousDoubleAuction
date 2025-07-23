import torch
import torch.nn as nn
import torch.nn.functional as F

from ray.rllib.core.rl_module.rl_module import RLModuleConfig
from ray.rllib.core.rl_module.torch.torch_rl_module import TorchRLModule
from ray.rllib.utils.typing import SampleBatchType

# Custom RLModule for PyTorch
class CustomLSTMRLModule(TorchRLModule):
    def __init__(self, config):
        super().__init__(config)
        self.obs_dim = config.observation_space.shape[0]
        self.num_actions = config.action_space.n
        
        # Define a simple neural network
        self.network = nn.Sequential(
            nn.Linear(self.obs_dim, 64),
            nn.ReLU(),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, self.num_actions)
        )
        
        # Value head for PPO
        self.value_branch = nn.Linear(32, 1)
        self._last_value = None
        
    def forward_train(self, batch, **kwargs):
        obs = batch["obs"].float()
        features = self.network[:-1](obs)  # Get features before final layer
        action_logits = self.network[-1](features)
        self._last_value = self.value_branch(features).squeeze(-1)
        return {"action_dist_inputs": action_logits}
    
    def forward_inference(self, batch, **kwargs):
        obs = batch["obs"].float()
        features = self.network[:-1](obs)
        action_logits = self.network[-1](features)
        return {"action_dist_inputs": action_logits}
    
    def forward_exploration(self, batch, **kwargs):
        return self.forward_inference(batch, **kwargs)
    
    def get_state(self):
        return {}  # No recurrent state in this model
    
    def set_state(self, state):
        pass  # No state to set
    
    def get_train_action_dist_cls(self):
        from ray.rllib.models.torch.torch_distributions import TorchCategorical
        return TorchCategorical
    
    def get_inference_action_dist_cls(self):
        from ray.rllib.models.torch.torch_distributions import TorchCategorical
        return TorchCategorical



# import torch

# from ray.rllib.core.columns import Columns
# from ray.rllib.core.rl_module.torch import TorchRLModule


# class CustomLSTMRLModule(TorchRLModule):
#     """A simple VPG (vanilla policy gradient)-style RLModule for testing purposes.

#     Use this as a minimum, bare-bones example implementation of a custom TorchRLModule.
#     """

#     def setup(self):
#         """Use this method to create all the model components that you require.

#         Feel free to access the following useful properties in this class:
#         - `self.model_config`: The config dict for this RLModule class,
#         which should contain flexible settings, for example: {"hiddens": [256, 256]}.
#         - `self.observation|action_space`: The observation and action space that
#         this RLModule is subject to. Note that the observation space might not be the
#         exact space from your env, but that it might have already gone through
#         preprocessing through a connector pipeline (for example, flattening,
#         frame-stacking, mean/std-filtering, etc..).
#         - `self.inference_only`: If True, this model should be built only for inference
#         purposes, in which case you may want to exclude any components that are not used
#         for computing actions, for example a value function branch.
#         """
#         input_dim = self.observation_space.shape[0]
#         hidden_dim = self.model_config["hidden_dim"]
#         output_dim = self.action_space.n

#         self._policy_net = torch.nn.Sequential(
#             torch.nn.Linear(input_dim, hidden_dim),
#             torch.nn.ReLU(),
#             torch.nn.Linear(hidden_dim, output_dim),
#         )

#     def _forward(self, batch, **kwargs):
#         # Push the observations from the batch through our `self._policy_net`.
#         action_logits = self._policy_net(batch[Columns.OBS])
#         # Return parameters for the (default) action distribution, which is
#         # `TorchCategorical` (due to our action space being `gym.spaces.Discrete`).
#         return {Columns.ACTION_DIST_INPUTS: action_logits}

#         # If you need more granularity between the different forward behaviors during
#         # the different phases of the module's lifecycle, implement three different
#         # forward methods. Thereby, it is recommended to put the inference and
#         # exploration versions inside a `with torch.no_grad()` context for better
#         # performance.
#         # def _forward_train(self, batch):
#         #    ...
#         #
#         # def _forward_inference(self, batch):
#         #    with torch.no_grad():
#         #        return self._forward_train(batch)
#         #
#         # def _forward_exploration(self, batch):
#         #    with torch.no_grad():
#         #        return self._forward_train(batch)



# import gymnasium as gym
# from ray.rllib.core.rl_module.torch import TorchRLModule
# from ray.rllib.core.models.specs.specs_dict import SpecDict
# from ray.rllib.core.models.specs.specs import TensorSpec
# from ray.rllib.utils.annotations import override
# import torch
# import torch.nn as nn
# from typing import Dict

# class CustomRLModule(TorchRLModule):
#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, **kwargs)

#     @override(TorchRLModule)
#     def setup(self):
#         # Observation space: Box(40,)
#         input_dim = self.observation_space.shape[0]  # 40
#         hidden_dim = self.model_config.get("hidden_dim", 256)

#         # Define shared backbone
#         self.encoder = nn.Sequential(
#             nn.Linear(input_dim, hidden_dim),
#             nn.ReLU(),
#             nn.Linear(hidden_dim, hidden_dim),
#             nn.ReLU(),
#         )

#         # Now handle each action component
#         self.action_heads = nn.ModuleDict()
#         self.action_spec = {}

#         action_space = self.action_space
#         assert isinstance(action_space, gym.spaces.Tuple)

#         output_start = 0
#         for i, space in enumerate(action_space.spaces):
#             if isinstance(space, gym.spaces.Discrete):
#                 self.action_heads[f"discrete_{i}"] = nn.Linear(hidden_dim, space.n)
#                 self.action_spec[f"action_logits_{i}"] = TensorSpec(
#                     "b, d", d=space.n, framework="torch"
#                 )
#                 output_start += space.n
#             elif isinstance(space, gym.spaces.Box):
#                 assert len(space.shape) == 1 and space.shape[0] == 1
#                 # Output mean (tanh for -1 to 1, sigmoid for 0 to 1)
#                 self.action_heads[f"continuous_{i}"] = nn.Linear(hidden_dim, 1)
#                 self.action_spec[f"action_mean_{i}"] = TensorSpec(
#                     "b, d", d=1, framework="torch"
#                 )
#             else:
#                 raise ValueError(f"Unsupported action space: {space}")

#         # Optional: value function
#         self.value_head = nn.Linear(hidden_dim, 1)

#     @override(TorchRLModule)
#     def _forward(self, batch, **kwargs):
#         obs = batch["obs"]
#         feats = self.encoder(obs)

#         outputs = {}

#         action_idx = 0
#         for i, space in enumerate(self.action_space.spaces):
#             if isinstance(space, gym.spaces.Discrete):
#                 logits = self.action_heads[f"discrete_{i}"](feats)
#                 outputs[f"action_logits_{i}"] = logits
#             elif isinstance(space, gym.spaces.Box):
#                 mean = self.action_heads[f"continuous_{i}"](feats)
#                 if space.low.item() == -1.0 and space.high.item() == 1.0:
#                     mean = torch.tanh(mean)
#                 elif space.low.item() == 0.0 and space.high.item() == 1.0:
#                     mean = torch.sigmoid(mean)
#                 outputs[f"action_mean_{i}"] = mean

#         # Value head
#         vf = self.value_head(feats)
#         outputs["state_value"] = vf.squeeze(-1)

#         return outputs