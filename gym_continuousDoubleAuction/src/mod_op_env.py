# new
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
# end new


from enum import Enum
import math

import gym
from gym import error, spaces, utils, wrappers
from gym.utils import seeding
from gym.envs.registration import register
from gym.spaces import Discrete, Box

import numpy as np


def sigmoid_price_fun(x, maxcust, gamma):
    return maxcust / (1 + math.exp(gamma * max(0, x)))


class Actions(Enum):
    DECREASE_PRICE = 0
    INCREASE_PRICE = 1
    HOLD = 2


PRICE_ADJUSTMENT = {
    Actions.DECREASE_PRICE: -0.25,
    Actions.INCREASE_PRICE: 0.25,
    Actions.HOLD: 0
}


class ArrivalSim(gym.Env):
    """ Simple environment for price optimising RL learner. """

    def __init__(self, price):
        """
        Parameters
        ----------
        price : float
            The initial price to use.
        """
        super().__init__()

        self.price = price
        self.revenue = 0
        self.action_space = Discrete(3)  # [0, 1, 2]  #increase or decrease
        # original obs space:
        #self.observation_space = Box(0.0, 1000.0, shape=(1,1), dtype=np.float32)
        # obs space initially suggested:
        #self.observation_space = Box(0.0, 1000.0, shape=(1,1), dtype=np.float32)
        # obs space suggested in this edit:
        self.observation_space = spaces.Box(np.array([0.0]), np.array([1000.0]), dtype=np.float32)

    def step(self, action):
        """ Enacts the specified action in the environment.

        Returns the new price, reward, whether we're finished and an empty dict for compatibility with Gym's
        interface. """

        self._take_action(Actions(action))

        next_state = self.price
        print('(self.price).shape =', (self.price).shape)
        #next_state = self.observation_space.sample()

        reward = self._get_reward()
        done = False

        if next_state < 0 or reward == 0:
            done = True
        
        print(next_state, reward, done, {})

        return np.array(next_state), reward, done, {}

    def reset(self):
        """ Resets the environment, selecting a random initial price. Returns the price. """
        #self.observation_space.value = np.random.rand()
        #return self.observation_space.sample()
        
        self.price = np.random.rand(1)
        
        print('reset -> (self.price).shape = ', (self.price).shape)

        return self.price

    def _take_action(self, action):
#         self.observation_space.value += PRICE_ADJUSTMENT[action]
        #print('price b =', self.price)
        print('price b =', self.price[0])
        #print('price b =', self.price[[0]])
        #self.price += PRICE_ADJUSTMENT[action]
        self.price[0] += PRICE_ADJUSTMENT[action]
        #self.price[[0]] += PRICE_ADJUSTMENT[action]
        #print('price a =', self.price)
        print('price a =', self.price[0])
        #print('price a =', self.price[[0]])

    #def _get_reward(self, price):
    def _get_reward(self):
#         price = self.observation_space.value
#         return max(np.random.poisson(sigmoid_price_fun(price, 50, 0.5)) * price, 0)
        #self.revenue = max(np.random.poisson(sigmoid_price_fun(self.price, 50, 0.5)) * self.price, 0)
        #return max(np.random.poisson(sigmoid_price_fun(self.price, 50, 0.5)) * self.price, 0)
        self.revenue = max(np.random.poisson(sigmoid_price_fun(self.price[0], 50, 0.5)) * self.price[0], 0)
        return max(np.random.poisson(sigmoid_price_fun(self.price[0], 50, 0.5)) * self.price[0], 0)

#     def render(self, mode='human'):
#         super().render(mode)

def testEnv():
    """
    register(
        id='ArrivalSim-v0',
        entry_point='env:ArrivalSim',
        kwargs= {'price' : 40.0}
    )
    env = gym.make('ArrivalSim-v0')
    """
    env = ArrivalSim(30.0)

    val = env.reset()
    print('val.shape = ', val.shape)

    for _ in range(5):
        print('env.observation_space =', env.observation_space)
        act = env.action_space.sample()
        print('\nact =', act)
        next_state, reward, done, _ = env.step(act)  # take a random action
        print('next_state = ', next_state)
    env.close()



if __name__ =='__main__':

    testEnv()
