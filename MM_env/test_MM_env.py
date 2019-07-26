import sys

if "../" not in sys.path:
    sys.path.append("../")

#from exchg.x.y import z

from exchg.exchg import Exchg

def total_sys_nav(e):
    sum = 0
    for trader in e.agents:
        sum += trader.acc.nav
    return sum

def print_info(e):
    e.render()
    for trader in e.agents:
        trader.acc.print_acc()
        print('total_sys_nav:', total_sys_nav(e))
    return 0
"""
def _acc(e, ID):
    return (e.agents[ID].acc.cash,
            e.agents[ID].acc.cash_on_hold,
            e.agents[ID].acc.position_val,
            e.agents[ID].acc.nav,
            e.agents[ID].acc.net_position)
"""
def create_env():
    num_of_traders = 4
    tape_display_length = 100
    init_cash = 10000
    max_step = 100
    e = Exchg(num_of_traders, init_cash, tape_display_length, max_step)
    e.reset(tape_display_length)
    return e

def test(e, expected_result_0, expected_result_1, expected_result_2, expected_result_3):
    """
    # get results
    result_0 = _acc(e, ID=0)
    result_1 = _acc(e, ID=1)
    result_2 = _acc(e, ID=2)
    result_3 = _acc(e, ID=3)
    print('expected_result_0:', expected_result_0)
    print('result_0:', result_0)
    print('expected_result_1:', expected_result_1)
    print('result_1:', result_1)
    print('expected_result_2:', expected_result_2)
    print('result_2:', result_2)
    print('expected_result_3:', expected_result_3)
    print('result_3:', result_3)
    #test
    assert(expected_result_0 == result_0)
    assert(expected_result_0 == result_1)
    assert(expected_result_1 == result_2)
    assert(expected_result_2 == result_3)
    """
    print_info(e)
    return 0

# place initial orders, 4 traders each with 3 bids, 3 asks all in LOB, no trade
def test_1(e):
    # bid
    action0 = {"type": 'limit', "side": 'bid', "size": 3, "price": 2}
    action1 = {"type": 'limit', "side": 'bid', "size": 4, "price": 5}
    action2 = {"type": 'limit', "side": 'bid', "size": 5, "price": 8}
    action3 = {"type": 'limit', "side": 'bid', "size": 6, "price": 11}
    actions = [action0,action1,action2,action3] # actions
    e.step(actions) # execute actions in 1 step
    action0 = {"type": 'limit', "side": 'bid', "size": 3, "price": 3}
    action1 = {"type": 'limit', "side": 'bid', "size": 4, "price": 6}
    action2 = {"type": 'limit', "side": 'bid', "size": 5, "price": 9}
    action3 = {"type": 'limit', "side": 'bid', "size": 6, "price": 12}
    actions = [action0,action1,action2,action3] # actions
    e.step(actions) # execute actions in 1 step
    action0 = {"type": 'limit', "side": 'bid', "size": 3, "price": 4}
    action1 = {"type": 'limit', "side": 'bid', "size": 4, "price": 7}
    action2 = {"type": 'limit', "side": 'bid', "size": 5, "price": 10}
    action3 = {"type": 'limit', "side": 'bid', "size": 6, "price": 13}
    actions = [action0,action1,action2,action3] # actions
    e.step(actions) # execute actions in 1 step
    # ask
    action0 = {"type": 'limit', "side": 'ask', "size": 3, "price": 14}
    action1 = {"type": 'limit', "side": 'ask', "size": 4, "price": 17}
    action2 = {"type": 'limit', "side": 'ask', "size": 5, "price": 20}
    action3 = {"type": 'limit', "side": 'ask', "size": 6, "price": 23}
    actions = [action0,action1,action2,action3] # actions
    e.step(actions) # execute actions in 1 step
    action0 = {"type": 'limit', "side": 'ask', "size": 3, "price": 15}
    action1 = {"type": 'limit', "side": 'ask', "size": 4, "price": 18}
    action2 = {"type": 'limit', "side": 'ask', "size": 5, "price": 21}
    action3 = {"type": 'limit', "side": 'ask', "size": 6, "price": 24}
    actions = [action0,action1,action2,action3] # actions
    e.step(actions) # execute actions in 1 step
    action0 = {"type": 'limit', "side": 'ask', "size": 3, "price": 16}
    action1 = {"type": 'limit', "side": 'ask', "size": 4, "price": 19}
    action2 = {"type": 'limit', "side": 'ask', "size": 5, "price": 22}
    action3 = {"type": 'limit', "side": 'ask', "size": 6, "price": 25}
    actions = [action0,action1,action2,action3] # actions
    e.step(actions) # execute actions in 1 step

    expected_result_0 = (10000, 0, 0, 10000, 0)
    expected_result_1 = (10000, 0, 0, 10000, 0)
    expected_result_2 = (10000, 0, 0, 10000, 0)
    expected_result_3 = (10000, 0, 0, 10000, 0)
    test(e, expected_result_0, expected_result_1, expected_result_2, expected_result_3)
    return 0

# init long position for T0, counter party T0, T1, T2, T3(unfilled)
def test_1_1(e):
    # actions
    action0 = {"type": 'limit', "side": 'bid', "size": 50, "price": 27}
    action1 = {"type": 'limit', "side": None, "size": 4, "price": 3}
    action2 = {"type": 'limit', "side": None, "size": 5, "price": 4}
    action3 = {"type": 'limit', "side": None, "size": 6, "price": 5}
    actions = [action0,action1,action2,action3]
    e.step(actions) # execute actions in 1 step
    # hard coded expected results
    expected_result_0 = (10000, 0, 0, 10000, 0)
    expected_result_1 = (10000, 0, 0, 10000, 0)
    expected_result_2 = (10000, 0, 0, 10000, 0)
    expected_result_3 = (10000, 0, 0, 10000, 0)
    test(e, expected_result_0, expected_result_1, expected_result_2, expected_result_3)
    return 0

# init short position for T0, counter party T0, T1, T2, T3(unfilled)
def test_1_2(e):
    # actions
    action0 = {"type": 'limit', "side": 'ask', "size": 52, "price": 2}
    action1 = {"type": 'limit', "side": None, "size": 4, "price": 3}
    action2 = {"type": 'limit', "side": None, "size": 5, "price": 4}
    action3 = {"type": 'limit', "side": None, "size": 6, "price": 5}
    actions = [action0,action1,action2,action3]
    e.step(actions) # execute actions in 1 step
    expected_result_0 = (10000, 0, 0, 10000, 0)
    expected_result_1 = (10000, 0, 0, 10000, 0)
    expected_result_2 = (10000, 0, 0, 10000, 0)
    expected_result_3 = (10000, 0, 0, 10000, 0)
    test(e, expected_result_0, expected_result_1, expected_result_2, expected_result_3)
    return 0

def test_1_3(e):
    # actions
    action0 = {"type": 'limit', "side": None, "size": 41, "price": 2}
    action1 = {"type": 'limit', "side": 'bid', "size": 10, "price": 5}
    action2 = {"type": 'limit', "side": None, "size": 6, "price": 4}
    action3 = {"type": 'limit', "side": 'ask', "size": 6, "price": 5}
    actions = [action0,action1,action2,action3]
    e.step(actions) # execute actions in 1 step
    action0 = {"type": 'limit', "side": 'ask', "size": 41, "price": 5}
    action1 = {"type": 'limit', "side": None, "size": 11, "price": 3}
    action2 = {"type": 'limit', "side": None, "size": 14, "price": 4}
    action3 = {"type": 'limit', "side": None, "size": 4, "price": 5}
    actions = [action0,action1,action2,action3]
    e.step(actions) # execute actions in 1 step
    expected_result_0 = (10000, 0, 0, 10000, 0)
    expected_result_1 = (10000, 0, 0, 10000, 0)
    expected_result_2 = (10000, 0, 0, 10000, 0)
    expected_result_3 = (10000, 0, 0, 10000, 0)
    test(e, expected_result_0, expected_result_1, expected_result_2, expected_result_3)
    return 0

def test_1_4(e):
    # actions
    action0 = {"type": 'limit', "side": 'ask', "size": 43, "price": 5}
    action1 = {"type": 'limit', "side": None, "size": 11, "price": 3}
    action2 = {"type": 'limit', "side": None, "size": 14, "price": 4}
    action3 = {"type": 'limit', "side": None, "size": 4, "price": 5}
    actions = [action0,action1,action2,action3]
    e.step(actions) # execute actions in 1 step
    expected_result_0 = (10000, 0, 0, 10000, 0)
    expected_result_1 = (10000, 0, 0, 10000, 0)
    expected_result_2 = (10000, 0, 0, 10000, 0)
    expected_result_3 = (10000, 0, 0, 10000, 0)
    test(e, expected_result_0, expected_result_1, expected_result_2, expected_result_3)
    return 0

def test_random():
    num_of_traders = 4
    init_cash = 10000
    tape_display_length = 100
    max_step = 10
    e = Exchg(num_of_traders, init_cash, tape_display_length, max_step)
    for step in range(max_step):
        actions = []
        for i, trader in enumerate(e.agents):
            action = trader.select_random_action(e)
            actions.append(action)
        print('\n\n\nSTEP:', step)
        print(actions)
        e.step(actions)
        print_info(e)


if __name__ == "__main__":
    e = create_env()
    test_1(e) # place initial orders
    test_1_1(e)
    #test_1_2(e)
    #test_1_3(e)
    test_1_4(e)

    test_random()

    sys.exit(0)
