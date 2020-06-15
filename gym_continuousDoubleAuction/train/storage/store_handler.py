import numpy as np
import ray
#from gym_continuousDoubleAuction.train.helper.helper import str_to_arr

@ray.remote(num_cpus=0.25, num_gpus=0.25)
class storage():
    """
    A remote object running as a ray detached actor on a separate process.
    """
    def __init__(self, num_agents):
        self.num_agents = num_agents
        self.prefix = "agt_"
        self.storage = self.create_storage(self.num_agents)
        self.eps_counter = 0

    def create_storage(self, num_agents):
        """
        Global storage.
        """
        storage = {}
        for i in range(self.num_agents):
            storage[self.prefix + str(i)] = {"step": {"obs": [],
                                                      "act": [],
                                                      "reward": [],
                                                      "NAV": [],
                                                      "num_trades": []},
                                             "eps":  {"policy_reward": [],
                                                      "reward": [],
                                                      "NAV": [],
                                                      "num_trades": []}}
        return storage

    def store(self, agt_id, step_or_eps, key, data):
        """
        agt_id: int
        step_or_eps: string
        key: string
        data: steps (in a list) or episodic data (a numeric value)
        """
        self.storage[self.prefix + str(agt_id)][step_or_eps][key].append(data)

    def store_agt_step(self, agt_id, obs, act, reward, NAV, num_trades):
        self.store(agt_id, "step", "obs", obs)     # a dictionary
        self.store(agt_id, "step", "act", act)
        self.store(agt_id, "step", "reward", reward)
        self.store(agt_id, "step", "NAV", NAV)
        self.store(agt_id, "step", "num_trades", num_trades)

    def store_agt_eps(self, agt_id, reward, NAV, num_trades):
        self.store(agt_id, "eps", "reward", reward)
        self.store(agt_id, "eps", "NAV", NAV)
        self.store(agt_id, "eps", "num_trades", num_trades)

    def store_agt_train(self, agt_id, policy_reward):
        self.store(agt_id, "eps", "policy_reward", policy_reward)

    def get_storage(self):
        return self.storage

    def inc_eps_counter(self):
        self.eps_counter += 1

    def get_eps_counter(self):
        return self.eps_counter

    def get_obs_from_agt(self, agt_id, depth):
        """
        Get bid_size, bid_price, ask_size, ask_price for all steps.
        """
        agt_key = "agt_" + str(agt_id)
        obs = self.storage[agt_key]["step"]["obs"]
        bid_size = np.empty((0, depth), float)
        bid_price = np.empty((0, depth), float)
        ask_size = np.empty((0, depth), float)
        ask_price = np.empty((0, depth), float)
        for eps_obs in obs:
            for step_obs in eps_obs:      # 4 rows in 1 step_obs
                bid_size_row = step_obs[0]
                bid_price_row = step_obs[1]
                ask_size_row = step_obs[2]
                ask_price_row = step_obs[3]
                bid_size = np.vstack((bid_size, bid_size_row))
                bid_price = np.vstack((bid_price, bid_price_row))
                ask_size = np.vstack((ask_size, ask_size_row))
                ask_price = np.vstack((ask_price, ask_price_row))

        return np.transpose(bid_size), np.transpose(bid_price), np.transpose(ask_size), np.transpose(ask_price)     # shape(depth_lvl, steps)
