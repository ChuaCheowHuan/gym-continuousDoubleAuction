import json
import os

import gym
import ray
from ray.tune import run_experiments
import ray.rllib.agents.a3c as a3c
import ray.rllib.agents.ppo as ppo
from ray.tune.registry import register_env
from mod_op_env import ArrivalSim


#import numpy as np
#from ray.rllib.models import Model, ModelCatalog
#import tensorflow as tf
#import ray.rllib.agents.utils

from sagemaker_rl.ray_launcher import SageMakerRayLauncher

"""
class CustomModel_disc(Model):
    def _lstm(self, Inputs, cell_size):
        s = tf.expand_dims(Inputs, axis=1, name='time_major')  # [time_step, feature] => [time_step, batch, feature]
        lstm_cell = tf.nn.rnn_cell.LSTMCell(cell_size)
        self.init_state = lstm_cell.zero_state(batch_size=1, dtype=tf.float32)
        # time_major means [time_step, batch, feature] while batch major means [batch, time_step, feature]
        outputs, self.final_state = tf.nn.dynamic_rnn(cell=lstm_cell, inputs=s, initial_state=self.init_state, time_major=True)
        lstm_out = tf.reshape(outputs, [-1, cell_size], name='flatten_rnn_outputs')  # joined state representation
        return lstm_out

    #def _build_layers_v2(self, input_dict, num_outputs, options):
    def _build_layers(self, input_dict, num_outputs, options):
        hidden = 8
        cell_size = 4
        #S = input_dict["obs"]
        #S = input_dict
        S = tf.layers.flatten(input_dict)
        #S = tf.layers.flatten(input_dict["obs"])

        with tf.variable_scope(tf.VariableScope(tf.AUTO_REUSE, "shared"),
                               reuse=tf.AUTO_REUSE,
                               auxiliary_name_scope=False):
            last_layer = tf.layers.dense(S, hidden, activation=tf.nn.relu, name="fc1")
        last_layer = tf.layers.dense(last_layer, hidden, activation=tf.nn.relu, name="fc2")
        #last_layer = tf.layers.dense(last_layer, hidden, activation=tf.nn.relu, name="fc3")

        #last_layer = self._lstm(last_layer, cell_size)

        output = tf.layers.dense(last_layer, num_outputs, activation=tf.nn.softmax, name="mu")

        return output, last_layer
"""        
"""    
# Deprecated: see as an alternative models/tf/fcnet_v2.py
class FullyConnectedNetwork(Model):
    #Generic fully connected network.

    #@override(Model)
    def _build_layers(self, inputs, num_outputs, options):
        #Process the flattened inputs.
        #Note that dict inputs will be flattened into a vector. To define a
        #model that processes the components separately, use _build_layers_v2().
        

        hiddens = options.get("fcnet_hiddens")
        activation = get_activation_fn(options.get("fcnet_activation"))

        with tf.name_scope("fc_net"):
            i = 1
            last_layer = inputs
            for size in hiddens:
                # skip final linear layer
                if options.get("no_final_linear") and i == len(hiddens):
                    output = tf.layers.dense(
                        last_layer,
                        num_outputs,
                        kernel_initializer=normc_initializer(1.0),
                        activation=activation,
                        name="fc_out")
                    return output, output

                label = "fc{}".format(i)
                last_layer = tf.layers.dense(
                    last_layer,
                    size,
                    kernel_initializer=normc_initializer(1.0),
                    activation=activation,
                    name=label)
                i += 1

            output = tf.layers.dense(
                last_layer,
                num_outputs,
                kernel_initializer=normc_initializer(0.01),
                activation=None,
                name="fc_out")
            return output, last_layer
"""        
"""
def create_environment(env_config):
    import gym
#     from gym.spaces import Space
    from gym.envs.registration import register

    # This import must happen inside the method so that worker processes import this code
    register(
        id='ArrivalSim-v0',
        entry_point='env:ArrivalSim',
        kwargs= {'price' : 40}
    )
    return gym.make('ArrivalSim-v0')
"""
def create_environment(env_config):
    price = 30.0
    # This import must happen inside the method so that worker processes import this code
    from mod_op_env import ArrivalSim
    return ArrivalSim(price)


class MyLauncher(SageMakerRayLauncher):
    def __init__(self):        
        super(MyLauncher, self).__init__()
        self.num_gpus = int(os.environ.get("SM_NUM_GPUS", 0))
        self.hosts_info = json.loads(os.environ.get("SM_RESOURCE_CONFIG"))["hosts"]
        self.num_total_gpus = self.num_gpus * len(self.hosts_info)
        
    def register_env_creator(self):
        register_env("ArrivalSim-v0", create_environment)
        #ModelCatalog.register_custom_model("model_disc", CustomModel_disc)
        #ModelCatalog.register_custom_model("model_disc", FullyConnectedNetwork)

    def get_experiment_config(self):
        return {
          "training": {
            "env": "ArrivalSim-v0",
            "run": "A3C",
            "stop": {
              "training_iteration": 3,
            },
              
            #"local_dir": "/opt/ml/model/",
            #"checkpoint_freq" : 3,
              
            "config": {
                
              #"model": {"custom_model": "model_disc"},
                
              #"num_workers": max(self.num_total_gpus-1, 1),
              "num_workers": max(self.num_cpus-1, 1),
              "use_gpu_for_workers": False,
              "train_batch_size": 5,
              "sample_batch_size": 1,
              "gpu_fraction": 0.3,
              "optimizer": {
                "grads_per_step": 10
              },
            },
            #"trial_resources": {"cpu": 1, "gpu": 0, "extra_gpu": max(self.num_total_gpus-1, 1), "extra_cpu": 0},
            #"trial_resources": {"cpu": 1, "gpu": 0, "extra_gpu": max(self.num_total_gpus-1, 0),
            #                    "extra_cpu": max(self.num_cpus-1, 1)},
            "trial_resources": {"cpu": 1,
                                "extra_cpu": max(self.num_cpus-1, 1)},              
          }
        }

if __name__ == "__main__":
    #os.environ["LC_ALL"] = "C.UTF-8"
    #os.environ["LANG"] = "C.UTF-8"
    #os.environ["RAY_USE_XRAY"] = "1"
    print(a3c.DEFAULT_CONFIG)
    MyLauncher().train_main()
