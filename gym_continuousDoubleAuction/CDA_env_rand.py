import sys

if "../" not in sys.path:
    sys.path.append("../")

#from exchg.x.y import z
from envs.continuousDoubleAuction_env import continuousDoubleAuctionEnv

def create_env():
    num_of_traders = 4
    tape_display_length = 100
    tick_size = 1
    init_cash = 10000
    max_step = 100
    e = continuousDoubleAuctionEnv(num_of_traders, init_cash, tick_size, tape_display_length, max_step)
    e.reset()
    return e

# place initial orders, 4 traders each with 3 bids, 3 asks all in LOB, no trade
def test_1(e):
    # bid
    action0 = (3, 3, 2)
    action1 = (3, 4, 5)
    action2 = (3, 5, 8)
    action3 = (3, 6, 11)
    actions = {0:action0,1:action1,2:action2,3:action3} # actions
    e.step(actions) # execute actions in 1 step
    e.render()
    action0 = (3, 3, 3)
    action1 = (3, 4, 6)
    action2 = (3, 5, 9)
    action3 = (3, 6, 12)
    actions = {0:action0,1:action1,2:action2,3:action3} # actions
    e.step(actions) # execute actions in 1 step
    e.render()
    action0 = (3, 3, 4)
    action1 = (3, 4, 7)
    action2 = (3, 5, 10)
    action3 = (3, 6, 13)
    actions = {0:action0,1:action1,2:action2,3:action3} # actions
    e.step(actions) # execute actions in 1 step
    e.render()
    # ask
    action0 = (4, 3, 14)
    action1 = (4, 4, 17)
    action2 = (4, 5, 20)
    action3 = (4, 6, 23)
    actions = {0:action0,1:action1,2:action2,3:action3} # actions
    e.step(actions) # execute actions in 1 step
    e.render()
    action0 = (4, 3, 15)
    action1 = (4, 4, 18)
    action2 = (4, 5, 21)
    action3 = (4, 6, 24)
    actions = {0:action0,1:action1,2:action2,3:action3} # actions
    e.step(actions) # execute actions in 1 step
    e.render()
    action0 = (4, 3, 16)
    action1 = (4, 4, 19)
    action2 = (4, 5, 22)
    action3 = (4, 6, 25)
    actions = {0:action0,1:action1,2:action2,3:action3} # actions
    e.step(actions) # execute actions in 1 step
    e.render()
    return 0

# init long position for T0, counter party T0, T1, T2, T3(unfilled)
def test_1_1(e):
    # actions
    action0 = (3, 50, 27)
    action1 = (0, 4, 3)
    action2 = (0, 5, 4)
    action3 = (0, 6, 5)
    actions = {0:action0,1:action1,2:action2,3:action3} # actions
    e.step(actions) # execute actions in 1 step
    e.render()
    return 0

# init short position for T0, counter party T0, T1, T2, T3(unfilled)
def test_1_2(e):
    # actions
    action0 = (4, 52, 2)
    action1 = (0, 4, 3)
    action2 = (0, 5, 4)
    action3 = (0, 6, 5)
    actions = {0:action0,1:action1,2:action2,3:action3} # actions
    e.step(actions) # execute actions in 1 step
    e.render()
    return 0

def test_1_3(e):
    # actions
    action0 = (0, 41, 2)
    action1 = (3, 10, 5)
    action2 = (0, 6, 4)
    action3 = (4, 6, 5)
    actions = {0:action0,1:action1,2:action2,3:action3} # actions
    e.step(actions) # execute actions in 1 step
    e.render()
    action0 = (4, 41, 5)
    action1 = (0, 11, 3)
    action2 = (0, 14, 4)
    action3 = (0, 4, 5)
    actions = {0:action0,1:action1,2:action2,3:action3} # actions
    e.step(actions) # execute actions in 1 step
    e.render()
    return 0

def test_1_4(e):
    # actions
    action0 = (4, 43, 5)
    action1 = (0, 11, 3)
    action2 = (0, 14, 4)
    action3 = (0, 4, 5)
    actions = {0:action0,1:action1,2:action2,3:action3} # actions
    e.step(actions) # execute actions in 1 step
    e.render()
    return 0

def test_random():
    num_of_traders = 4
    init_cash = 1000000
    tick_size = 1
    tape_display_length = 10
    max_step = 10000
    e = continuousDoubleAuctionEnv(num_of_traders, init_cash, tick_size, tape_display_length, max_step)
    e.reset()
    for step in range(max_step):
        #actions = []
        actions = {}
        for i, trader in enumerate(e.agents):
            #action = trader.select_random_action()
            action = trader.select_random_action_price_code()
            #actions.append(action)
            actions[i] = action
        print('\n\n\nSTEP:', step)
        print('test_random actions:', actions)
        e.step(actions)
        e.render()


if __name__ == "__main__":
    #e = create_env()
    #test_1(e) # place initial orders
    #test_1_1(e)
    #test_1_2(e)
    #test_1_3(e)
    #test_1_4(e)

    test_random()

    sys.exit(0)
