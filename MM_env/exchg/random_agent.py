import random
import numpy as np

class Random_agent(object):
    #def __init__():

    # pass action to step
    def select_random_action(self, ID):
        #type = np.random.randint(0, 1, size=1) # type, draw 1 int, 0(market) to 1(limit)
        type = random.choice(['market','limit'])
        #type = random.choice(['limit'])
        #side = np.random.randint(-1, 1, size=1) # side, draw 1 int, -1(ask), 0(None), 1(bid)
        side = random.choice(['bid',None,'ask'])
        size = random.randrange(1, 100, 100) # size in 100s from 0(min) to 1000(max)
        price = random.randrange(1, 10, 1) # price from 1(min) to 100(max)
        action = {"ID": ID,
                  "type": type,
                  "side": side,
                  "size": size,
                  "price": price}
        return action
