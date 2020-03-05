import random
import numpy as np

class Random_agent(object):

    # Select action
    def select_random_action(self):
        side = random.randrange(0, 3, 1) # side: None=0, bid=1, ask=2
        type = random.randrange(0, 4, 1) # type_side: market=0, limit=1, modify=2, cancel=3
        mean = np.random.uniform(-1, 1) # A single value(-100, 100, 1) # size in 100s from 0(min) to 1000(max)
        sigma = np.random.uniform(0, 1) # size in 100s from 0(min) to 1000(max)
        price_code = random.randrange(0, 12, 1) # price code
        act = (side, type, mean, sigma, price_code)
        return act
