import random
import numpy as np

class Random_agent(object):

    def select_random_action(self):
        """
        Select action.

        Return:
            act: The random action for 1 trader(agent).
        """
        # side: None=0, bid=1, ask=2
        side = random.randrange(0, 3, 1) 
        # Order type: market=0, limit=1, modify=2, cancel=3
        ord_type = random.randrange(0, 4, 1) 

        # mean for size distribution.
        mean = np.random.uniform(-1, 1) 
        # sigma for size distribution.
        sigma = np.random.uniform(0, 1) 
        
        # price code
        price_code = random.randrange(0, 12, 1)

        act = (side, ord_type, mean, sigma, price_code)

        return act
