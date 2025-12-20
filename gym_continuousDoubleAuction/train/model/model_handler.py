import torch
import torch.nn as nn
from ray.rllib.core.rl_module.rl_module import RLModule
from ray.rllib.core.rl_module.torch import TorchRLModule

# Custom RLModule for PyTorch
class CustomRLModule(RLModule):
    def __init__(self, config):
        super().__init__(config)
        self.obs_dim = config.observation_space.shape[0]
        self.num_actions = config.action_space.n

        # Define a simple neural network
        self.network = nn.Sequential(
            nn.Linear(self.obs_dim, 8),
            nn.ReLU(),
            nn.Linear(8, 4),
            nn.ReLU(),
            nn.Linear(4, self.num_actions)
        )

        # Value head for PPO
        self.value_branch = nn.Linear(8, 1)
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