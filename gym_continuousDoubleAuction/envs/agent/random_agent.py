import random

class Random_agent(object):

    # pass action to step
    def select_random_action(self):
        side = random.randrange(0, 3, 1) # side: None=0, bid=1, ask=2
        type = random.randrange(0, 4, 1) # type_side: market=0, limit=1, modify=2, cancel=3
        size = random.randrange(1, 100, 1) # size in 100s from 0(min) to 1000(max)
        price = random.randrange(1, 10, 1) # price from 1(min) to 10(max)
        #price = random.randrange(0, 11, 1) # price code
        act = (side, type, size, price)
        print('select_random_action act:', act)
        return act

    def select_random_action_price_code(self):
        side = random.randrange(0, 3, 1) # side: None=0, bid=1, ask=2
        type = random.randrange(0, 4, 1) # type_side: market=0, limit=1, modify=2, cancel=3
        size = random.randrange(1, 11, 1) # size in 100s from 0(min) to 1000(max)
        price_code = random.randrange(0, 12, 1) # price code
        act = (side, type, size, price_code)
        print('select_random_action act:', act)
        return act
