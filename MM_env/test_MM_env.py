import sys

if "../" not in sys.path:
    sys.path.append("../")

#from exchg.lib.envs.simple_rooms import SimpleRoomsEnv
#from exchg.lib.envs.cliff_walking import CliffWalkingEnv
#from exchg.lib.simulation import Experiment

from exchg.exchg import Exchg

def print_acc(e, ID):
    print('\nID:', ID)
    print('cash:', e.agents[ID].acc.cash)
    print('cash_on_hold:', e.agents[ID].acc.cash_on_hold)
    print('position_val:', e.agents[ID].acc.position_val)
    print('nav:', e.agents[ID].acc.nav)
    print('net_position:', e.agents[ID].acc.net_position)
    print('\n')

def print_info(e):
    e.render()
    for trader in e.agents:
        print_acc(e, trader.ID)

def _acc(e, ID):
    return (e.agents[ID].acc.cash,
            e.agents[ID].acc.cash_on_hold,
            e.agents[ID].acc.position_val,
            e.agents[ID].acc.nav,
            e.agents[ID].acc.net_position)

def create_env():
    num_of_traders = 4
    tape_display_length = 100
    init_cash = 100
    max_step = 10
    e = Exchg(num_of_traders, init_cash, tape_display_length, max_step)

    return e

def test(e, actions, expected_result_1, expected_result_2, expected_result_3, expected_result_4):
    e.step(actions) # execute actions in 1 step

    # get results
    result_1 = _acc(e, ID=0)
    result_2 = _acc(e, ID=1)
    result_3 = _acc(e, ID=2)
    result_4 = _acc(e, ID=3)

    print('expected_result_1:', expected_result_1)
    print('result_1:', result_1)
    print('expected_result_2:', expected_result_2)
    print('result_2:', result_2)
    print('expected_result_3:', expected_result_3)
    print('result_3:', result_3)
    print('expected_result_4:', expected_result_4)
    print('result_4:', result_4)
    # test
    #assert(expected_result_1 == result_1)
    #assert(expected_result_2 == result_2)
    #assert(expected_result_3 == result_3)
    #assert(expected_result_4 == result_4)
    print_info(e)

# place initial orders
def test_1():
    e = create_env()
    # actions
    action1 = {"type": 'limit', "side": 'bid', "size": 6, "price": 2}
    action2 = {"type": 'limit', "side": 'bid', "size": 5, "price": 3}
    action3 = {"type": 'limit', "side": 'ask', "size": 4, "price": 4}
    action4 = {"type": 'limit', "side": 'ask', "size": 3, "price": 5}
    actions = [action1,action2,action3,action4]
    # hard coded expected results
    expected_result_1 = (88, 12, 0, 100, 0)
    expected_result_2 = (85, 15, 0, 100, 0)
    expected_result_3 = (84, 16, 0, 100, 0)
    expected_result_4 = (85, 15, 0, 100, 0)

    test(e, actions, expected_result_1, expected_result_2, expected_result_3, expected_result_4)

    return e

# init long position for T0, counter party T2, T3(unfilled)
def test_1_1():
    e = test_1()
    """
    # actions
    action1 = {"type": 'limit', "side": 'bid', "size": 6, "price": 2}
    action2 = {"type": 'limit', "side": 'bid', "size": 5, "price": 3}
    action3 = {"type": 'limit', "side": 'ask', "size": 4, "price": 4}
    action4 = {"type": 'limit', "side": 'ask', "size": 3, "price": 5}
    # hard coded expected results
    expected_result_1 = (88, 12, 0, 100, 0)
    expected_result_2 = (85, 15, 0, 100, 0)
    expected_result_3 = (84, 16, 0, 100, 0)
    expected_result_4 = (85, 15, 0, 100, 0)
    """
    # actions
    action1 = {"type": 'limit', "side": 'bid', "size": 5, "price": 6}
    action2 = {"type": 'limit', "side": None, "size": 5, "price": 3}
    action3 = {"type": 'limit', "side": None, "size": 4, "price": 4}
    action4 = {"type": 'limit', "side": None, "size": 3, "price": 5}
    actions = [action1,action2,action3,action4]
    # hard coded expected results
    expected_result_1 = (67, 12, 21, 100, 5)
    expected_result_2 = (85, 15, 0, 100, 0)
    expected_result_3 = (84, 0, 16, 100, -4)
    expected_result_4 = (85, 10, 5, 100, -1)

    test(e, actions, expected_result_1, expected_result_2, expected_result_3, expected_result_4)

    return e

def test_random():
    num_of_traders = 3
    init_cash = 1000
    tape_display_length = 10
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

    #test_1() # place initial orders
    test_1_1()
    #test_1_2()
    #test_1_3()
    #test_1_4()


    #test_random()

    sys.exit(0)
