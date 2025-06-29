from ray.rllib.algorithms.ppo import PPOConfig

config = (
    PPOConfig()
    .environment(env="CartPole-v1")
    .framework("torch")
    .env_runners(num_env_runners=1)
    .training(train_batch_size=300)
)
algo = config.build()



import torch
print("Is CUDA available?:", torch.cuda.is_available())
print("CUDA version (built with):", torch.version.cuda)
print("Current device:", torch.cuda.current_device())
print("Device name:", torch.cuda.get_device_name(torch.cuda.current_device()))
