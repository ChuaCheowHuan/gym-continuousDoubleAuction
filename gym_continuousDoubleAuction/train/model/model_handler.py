import torch
import torch.nn as nn
import torch.nn.functional as F

from ray.rllib.core.rl_module.rl_module import RLModuleConfig
from ray.rllib.core.rl_module.torch.torch_rl_module import TorchRLModule
from ray.rllib.utils.typing import SampleBatchType

# Custom LSTM RLModule Configuration
class CustomLSTMRLModuleConfig(RLModuleConfig):
    def __init__(self, observation_space, action_space, **kwargs):
        super().__init__(observation_space=observation_space, action_space=action_space, **kwargs)

# Custom LSTM RLModule
class CustomLSTMRLModule(TorchRLModule):
    def __init__(self, config: CustomLSTMRLModuleConfig):
        super().__init__(config)
        
        obs_dim = config.observation_space.shape[0]
        action_dim = config.action_space.n  # for discrete
        
        self.hidden_size = 512
        self.lstm_hidden_size = 256
        
        # Fully connected layers before LSTM
        self.fc1 = nn.Linear(obs_dim, self.hidden_size)
        self.fc2 = nn.Linear(self.hidden_size, self.hidden_size)
        self.fc3 = nn.Linear(self.hidden_size, self.hidden_size)
        
        # LSTM
        self.lstm = nn.LSTM(input_size=self.hidden_size, hidden_size=self.lstm_hidden_size, batch_first=True)
        
        # Post-LSTM dense layers
        self.post_fc1 = nn.Linear(self.lstm_hidden_size, self.hidden_size)
        self.post_fc2 = nn.Linear(self.hidden_size, self.hidden_size)
        self.post_fc3 = nn.Linear(self.hidden_size, self.hidden_size)
        
        # Output layers for policy and value
        self.policy_head = nn.Linear(self.hidden_size, action_dim)
        self.value_head = nn.Linear(self.hidden_size, 1)
    
    def forward_inference(self, batch: SampleBatchType, **kwargs):
        return self._forward(batch)
    
    def forward_exploration(self, batch: SampleBatchType, **kwargs):
        return self._forward(batch)
    
    def forward_train(self, batch: SampleBatchType, **kwargs):
        return self._forward(batch)
    
    def _forward(self, batch):
        x = batch["obs"]
        
        # Handle different batch shapes
        if len(x.shape) == 1:
            x = x.unsqueeze(0)  # [1, obs_dim]
        elif len(x.shape) == 2:
            pass  # [batch, obs_dim] - already correct
        else:
            # For sequence data [batch, seq, obs_dim], flatten to [batch*seq, obs_dim]
            original_shape = x.shape
            x = x.view(-1, original_shape[-1])
        
        # Fully connected before LSTM
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))
        x = F.relu(self.fc3(x))
        
        # Prepare for LSTM: needs [batch, seq_len, feature]
        if len(x.shape) == 2:
            x = x.unsqueeze(1)  # add seq_len=1 -> [batch, seq=1, feature]
        
        # Pass through LSTM
        lstm_out, (h_n, c_n) = self.lstm(x)  # lstm_out: [batch, seq, lstm_hidden]
        lstm_out = lstm_out[:, -1, :]  # take last output in sequence
        
        # Post-LSTM dense layers
        x = F.relu(self.post_fc1(lstm_out))
        x = F.relu(self.post_fc2(x))
        x = F.relu(self.post_fc3(x))
        
        # Output policy logits and value
        logits = self.policy_head(x)
        value = self.value_head(x).squeeze(-1)
        
        return {
            "action_dist_inputs": logits,
            "vf_preds": value
        }