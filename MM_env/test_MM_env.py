import sys

if "../" not in sys.path:
    sys.path.append("../")

#from exchg.x.y import z
from exchg.exchg import Exchg

def create_env():
    num_of_traders = 4
    tape_display_length = 100
    tick_size = 1
    init_cash = 10000
    max_step = 100
    e = Exchg(num_of_traders, init_cash, tick_size, tape_display_length, max_step)
    e.reset()
    return e

# place initial orders, 4 traders each with 3 bids, 3 asks all in LOB, no trade
def test_1(e):
    # bid
    action0 = {"type_side": 3, "size": 3, "price": 2}
    action1 = {"type_side": 3, "size": 4, "price": 5}
    action2 = {"type_side": 3, "size": 5, "price": 8}
    action3 = {"type_side": 3, "size": 6, "price": 11}
    actions = {0:action0,1:action1,2:action2,3:action3} # actions
    e.step(actions) # execute actions in 1 step
    e.render()
    action0 = {"type_side": 3, "size": 3, "price": 3}
    action1 = {"type_side": 3, "size": 4, "price": 6}
    action2 = {"type_side": 3, "size": 5, "price": 9}
    action3 = {"type_side": 3, "size": 6, "price": 12}
    actions = {0:action0,1:action1,2:action2,3:action3} # actions
    e.step(actions) # execute actions in 1 step
    e.render()
    action0 = {"type_side": 3, "size": 3, "price": 4}
    action1 = {"type_side": 3, "size": 4, "price": 7}
    action2 = {"type_side": 3, "size": 5, "price": 10}
    action3 = {"type_side": 3, "size": 6, "price": 13}
    actions = {0:action0,1:action1,2:action2,3:action3} # actions
    e.step(actions) # execute actions in 1 step
    e.render()
    # ask
    action0 = {"type_side": 4, "size": 3, "price": 14}
    action1 = {"type_side": 4, "size": 4, "price": 17}
    action2 = {"type_side": 4, "size": 5, "price": 20}
    action3 = {"type_side": 4, "size": 6, "price": 23}
    actions = {0:action0,1:action1,2:action2,3:action3} # actions
    e.step(actions) # execute actions in 1 step
    e.render()
    action0 = {"type_side": 4, "size": 3, "price": 15}
    action1 = {"type_side": 4, "size": 4, "price": 18}
    action2 = {"type_side": 4, "size": 5, "price": 21}
    action3 = {"type_side": 4, "size": 6, "price": 24}
    actions = {0:action0,1:action1,2:action2,3:action3} # actions
    e.step(actions) # execute actions in 1 step
    e.render()
    action0 = {"type_side": 4, "size": 3, "price": 16}
    action1 = {"type_side": 4, "size": 4, "price": 19}
    action2 = {"type_side": 4, "size": 5, "price": 22}
    action3 = {"type_side": 4, "size": 6, "price": 25}
    actions = {0:action0,1:action1,2:action2,3:action3} # actions
    e.step(actions) # execute actions in 1 step
    e.render()
    return 0

# init long position for T0, counter party T0, T1, T2, T3(unfilled)
def test_1_1(e):
    # actions
    action0 = {"type_side": 3, "size": 50, "price": 27}
    action1 = {"type_side": 0, "size": 4, "price": 3}
    action2 = {"type_side": 0, "size": 5, "price": 4}
    action3 = {"type_side": 0, "size": 6, "price": 5}
    actions = {0:action0,1:action1,2:action2,3:action3} # actions
    e.step(actions) # execute actions in 1 step
    e.render()
    return 0

# init short position for T0, counter party T0, T1, T2, T3(unfilled)
def test_1_2(e):
    # actions
    action0 = {"type_side": 4, "size": 52, "price": 2}
    action1 = {"type_side": 0, "size": 4, "price": 3}
    action2 = {"type_side": 0, "size": 5, "price": 4}
    action3 = {"type_side": 0, "size": 6, "price": 5}
    actions = {0:action0,1:action1,2:action2,3:action3} # actions
    e.step(actions) # execute actions in 1 step
    e.render()
    return 0

def test_1_3(e):
    # actions
    action0 = {"type_side": 0, "size": 41, "price": 2}
    action1 = {"type_side": 3, "size": 10, "price": 5}
    action2 = {"type_side": 0, "size": 6, "price": 4}
    action3 = {"type_side": 4, "size": 6, "price": 5}
    actions = {0:action0,1:action1,2:action2,3:action3} # actions
    e.step(actions) # execute actions in 1 step
    e.render()
    action0 = {"type_side": 4, "size": 41, "price": 5}
    action1 = {"type_side": 0, "size": 11, "price": 3}
    action2 = {"type_side": 0, "size": 14, "price": 4}
    action3 = {"type_side": 0, "size": 4, "price": 5}
    actions = {0:action0,1:action1,2:action2,3:action3} # actions
    e.step(actions) # execute actions in 1 step
    e.render()
    return 0

def test_1_4(e):
    # actions
    action0 = {"type_side": 4, "size": 43, "price": 5}
    action1 = {"type_side": 0, "size": 11, "price": 3}
    action2 = {"type_side": 0, "size": 14, "price": 4}
    action3 = {"type_side": 0, "size": 4, "price": 5}
    actions = {0:action0,1:action1,2:action2,3:action3} # actions
    e.step(actions) # execute actions in 1 step
    e.render()
    return 0

def test_random():
    num_of_traders = 4
    init_cash = 10000
    tick_size = 1
    tape_display_length = 100
    max_step = 50
    e = Exchg(num_of_traders, init_cash, tick_size, tape_display_length, max_step)
    for step in range(max_step):
        #actions = []
        actions = {}
        for i, trader in enumerate(e.agents):
            action = trader.select_random_action(trader.ID)
            #actions.append(action)
            actions[i] = action
        print('\n\n\nSTEP:', step)
        print('test_random actions:', actions)
        e.step(actions)
        e.render()


if __name__ == "__main__":
    e = create_env()
    test_1(e) # place initial orders
    test_1_1(e)
    #test_1_2(e)
    test_1_3(e)
    #test_1_4(e)

    test_random()

    sys.exit(0)
