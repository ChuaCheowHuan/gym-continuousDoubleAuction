import sys

if "../" not in sys.path:
    sys.path.append("../")

#from exchg.x.y import z
from exchg.exchg import Exchg

def create_env():
    num_of_traders = 4
    tape_display_length = 100
    init_cash = 10000
    max_step = 100
    e = Exchg(num_of_traders, init_cash, tape_display_length, max_step)
    e.reset()
    return e

# place initial orders, 4 traders each with 3 bids, 3 asks all in LOB, no trade
def test_1(e):
    # bid
    action0 = {"ID": 0, "type": 'limit', "side": 'bid', "size": 3, "price": 2}
    action1 = {"ID": 1, "type": 'limit', "side": 'bid', "size": 4, "price": 5}
    action2 = {"ID": 2, "type": 'limit', "side": 'bid', "size": 5, "price": 8}
    action3 = {"ID": 3, "type": 'limit', "side": 'bid', "size": 6, "price": 11}
    actions = [action0,action1,action2,action3] # actions
    e.step(actions) # execute actions in 1 step
    e.render()
    action0 = {"ID": 0, "type": 'limit', "side": 'bid', "size": 3, "price": 3}
    action1 = {"ID": 1, "type": 'limit', "side": 'bid', "size": 4, "price": 6}
    action2 = {"ID": 2, "type": 'limit', "side": 'bid', "size": 5, "price": 9}
    action3 = {"ID": 3, "type": 'limit', "side": 'bid', "size": 6, "price": 12}
    actions = [action0,action1,action2,action3] # actions
    e.step(actions) # execute actions in 1 step
    e.render()
    action0 = {"ID": 0, "type": 'limit', "side": 'bid', "size": 3, "price": 4}
    action1 = {"ID": 1, "type": 'limit', "side": 'bid', "size": 4, "price": 7}
    action2 = {"ID": 2, "type": 'limit', "side": 'bid', "size": 5, "price": 10}
    action3 = {"ID": 3, "type": 'limit', "side": 'bid', "size": 6, "price": 13}
    actions = [action0,action1,action2,action3] # actions
    e.step(actions) # execute actions in 1 step
    e.render()
    # ask
    action0 = {"ID": 0, "type": 'limit', "side": 'ask', "size": 3, "price": 14}
    action1 = {"ID": 1, "type": 'limit', "side": 'ask', "size": 4, "price": 17}
    action2 = {"ID": 2, "type": 'limit', "side": 'ask', "size": 5, "price": 20}
    action3 = {"ID": 3, "type": 'limit', "side": 'ask', "size": 6, "price": 23}
    actions = [action0,action1,action2,action3] # actions
    e.step(actions) # execute actions in 1 step
    e.render()
    action0 = {"ID": 0, "type": 'limit', "side": 'ask', "size": 3, "price": 15}
    action1 = {"ID": 1, "type": 'limit', "side": 'ask', "size": 4, "price": 18}
    action2 = {"ID": 2, "type": 'limit', "side": 'ask', "size": 5, "price": 21}
    action3 = {"ID": 3, "type": 'limit', "side": 'ask', "size": 6, "price": 24}
    actions = [action0,action1,action2,action3] # actions
    e.step(actions) # execute actions in 1 step
    e.render()
    action0 = {"ID": 0, "type": 'limit', "side": 'ask', "size": 3, "price": 16}
    action1 = {"ID": 1, "type": 'limit', "side": 'ask', "size": 4, "price": 19}
    action2 = {"ID": 2, "type": 'limit', "side": 'ask', "size": 5, "price": 22}
    action3 = {"ID": 3, "type": 'limit', "side": 'ask', "size": 6, "price": 25}
    actions = [action0,action1,action2,action3] # actions
    e.step(actions) # execute actions in 1 step
    e.render()
    return 0

# init long position for T0, counter party T0, T1, T2, T3(unfilled)
def test_1_1(e):
    # actions
    action0 = {"ID": 0, "type": 'limit', "side": 'bid', "size": 50, "price": 27}
    action1 = {"ID": 1, "type": 'limit', "side": None, "size": 4, "price": 3}
    action2 = {"ID": 2, "type": 'limit', "side": None, "size": 5, "price": 4}
    action3 = {"ID": 3, "type": 'limit', "side": None, "size": 6, "price": 5}
    actions = [action0,action1,action2,action3]
    e.step(actions) # execute actions in 1 step
    e.render()
    return 0

# init short position for T0, counter party T0, T1, T2, T3(unfilled)
def test_1_2(e):
    # actions
    action0 = {"ID": 0, "type": 'limit', "side": 'ask', "size": 52, "price": 2}
    action1 = {"ID": 1, "type": 'limit', "side": None, "size": 4, "price": 3}
    action2 = {"ID": 2, "type": 'limit', "side": None, "size": 5, "price": 4}
    action3 = {"ID": 3, "type": 'limit', "side": None, "size": 6, "price": 5}
    actions = [action0,action1,action2,action3]
    e.step(actions) # execute actions in 1 step
    e.render()
    return 0

def test_1_3(e):
    # actions
    action0 = {"ID": 0, "type": 'limit', "side": None, "size": 41, "price": 2}
    action1 = {"ID": 1, "type": 'limit', "side": 'bid', "size": 10, "price": 5}
    action2 = {"ID": 2, "type": 'limit', "side": None, "size": 6, "price": 4}
    action3 = {"ID": 3, "type": 'limit', "side": 'ask', "size": 6, "price": 5}
    actions = [action0,action1,action2,action3]
    e.step(actions) # execute actions in 1 step
    e.render()
    action0 = {"ID": 0, "type": 'limit', "side": 'ask', "size": 41, "price": 5}
    action1 = {"ID": 1, "type": 'limit', "side": None, "size": 11, "price": 3}
    action2 = {"ID": 2, "type": 'limit', "side": None, "size": 14, "price": 4}
    action3 = {"ID": 3, "type": 'limit', "side": None, "size": 4, "price": 5}
    actions = [action0,action1,action2,action3]
    e.step(actions) # execute actions in 1 step
    e.render()
    return 0

def test_1_4(e):
    # actions
    action0 = {"ID": 0, "type": 'limit', "side": 'ask', "size": 43, "price": 5}
    action1 = {"ID": 1, "type": 'limit', "side": None, "size": 11, "price": 3}
    action2 = {"ID": 2, "type": 'limit', "side": None, "size": 14, "price": 4}
    action3 = {"ID": 3, "type": 'limit', "side": None, "size": 4, "price": 5}
    actions = [action0,action1,action2,action3]
    e.step(actions) # execute actions in 1 step
    e.render()
    return 0

def test_random():
    num_of_traders = 4
    init_cash = 10000
    tape_display_length = 100
    max_step = 50
    e = Exchg(num_of_traders, init_cash, tape_display_length, max_step)
    for step in range(max_step):
        actions = []
        for trader in e.agents:
            action = trader.select_random_action(trader.ID)
            actions.append(action)
        print('\n\n\nSTEP:', step)
        print('actions:', actions)
        e.step(actions)
        e.render()


if __name__ == "__main__":
    e = create_env()
    test_1(e) # place initial orders
    test_1_1(e)
    #test_1_2(e)
    #test_1_3(e)
    test_1_4(e)

    test_random()

    sys.exit(0)
