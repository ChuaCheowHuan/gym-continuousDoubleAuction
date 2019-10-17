import random

class Random_agent(object):

    # pass action to step
    def select_random_action(self):
        type_side = random.randrange(0, 5, 1) # type_side: None=0, market_bid=1, market_ask=2, limit_bid=3, limit_ask=4
        size = random.randrange(1, 100, 1) # size in 100s from 0(min) to 1000(max)
        price = random.randrange(1, 10, 1) # price from 1(min) to 100(max)
        #price = random.randrange(0, 11, 1) # price code
        act = (type_side, size, price)
        print('select_random_action act:', act)
        return act

    def select_random_action_price_code(self):
        type_side = random.randrange(0, 5, 1) # type_side: None=0, market_bid=1, market_ask=2, limit_bid=3, limit_ask=4
        size = random.randrange(1, 11, 1) # size in 100s from 0(min) to 1000(max)
        price_code = random.randrange(0, 12, 1) # price code
        act = (type_side, size, price_code)
        print('select_random_action act:', act)
        return act
