import random
import numpy as np

class Random_agent(object):

    def select_random_action(self):
        """
        Select action.

        Return:
            act: The random action for 1 trader(agent).
        """

        side = random.randrange(0, 3, 1) # side: None=0, bid=1, ask=2
        type = random.randrange(0, 4, 1) # type_side: market=0, limit=1, modify=2, cancel=3
        mean = np.random.uniform(-1, 1) # mean for size distribution
        sigma = np.random.uniform(0, 1) # sigma for size distribution
        price_code = random.randrange(0, 12, 1) # price code

        act = (side, type, mean, sigma, price_code)

        return act
