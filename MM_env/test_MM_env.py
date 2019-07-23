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
    init_cash = 10000
    max_step = 10
    e = Exchg(num_of_traders, init_cash, tape_display_length, max_step)

    return e

def test(e, expected_result_1, expected_result_2, expected_result_3, expected_result_4):
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
    action1 = {"type": 'limit', "side": 'bid', "size": 3, "price": 2}
    action2 = {"type": 'limit', "side": 'bid', "size": 4, "price": 5}
    action3 = {"type": 'limit', "side": 'bid', "size": 5, "price": 8}
    action4 = {"type": 'limit', "side": 'bid', "size": 6, "price": 11}
    actions = [action1,action2,action3,action4] # actions
    e.step(actions) # execute actions in 1 step
    action1 = {"type": 'limit', "side": 'bid', "size": 3, "price": 3}
    action2 = {"type": 'limit', "side": 'bid', "size": 4, "price": 6}
    action3 = {"type": 'limit', "side": 'bid', "size": 5, "price": 9}
    action4 = {"type": 'limit', "side": 'bid', "size": 6, "price": 12}
    actions = [action1,action2,action3,action4] # actions
    e.step(actions) # execute actions in 1 step
    action1 = {"type": 'limit', "side": 'bid', "size": 3, "price": 4}
    action2 = {"type": 'limit', "side": 'bid', "size": 4, "price": 7}
    action3 = {"type": 'limit', "side": 'bid', "size": 5, "price": 10}
    action4 = {"type": 'limit', "side": 'bid', "size": 6, "price": 13}
    actions = [action1,action2,action3,action4] # actions
    e.step(actions) # execute actions in 1 step

    action1 = {"type": 'limit', "side": 'ask', "size": 3, "price": 14}
    action2 = {"type": 'limit', "side": 'ask', "size": 4, "price": 17}
    action3 = {"type": 'limit', "side": 'ask', "size": 5, "price": 20}
    action4 = {"type": 'limit', "side": 'ask', "size": 6, "price": 23}
    actions = [action1,action2,action3,action4] # actions
    e.step(actions) # execute actions in 1 step
    action1 = {"type": 'limit', "side": 'ask', "size": 3, "price": 15}
    action2 = {"type": 'limit', "side": 'ask', "size": 4, "price": 18}
    action3 = {"type": 'limit', "side": 'ask', "size": 5, "price": 21}
    action4 = {"type": 'limit', "side": 'ask', "size": 6, "price": 24}
    actions = [action1,action2,action3,action4] # actions
    e.step(actions) # execute actions in 1 step
    action1 = {"type": 'limit', "side": 'ask', "size": 3, "price": 16}
    action2 = {"type": 'limit', "side": 'ask', "size": 4, "price": 19}
    action3 = {"type": 'limit', "side": 'ask', "size": 5, "price": 22}
    action4 = {"type": 'limit', "side": 'ask', "size": 6, "price": 25}
    actions = [action1,action2,action3,action4] # actions
    e.step(actions) # execute actions in 1 step

    expected_result_1 = (67, 12, 21, 100, 5)
    expected_result_2 = (85, 15, 0, 100, 0)
    expected_result_3 = (84, 0, 16, 100, -4)
    expected_result_4 = (85, 10, 5, 100, -1)
    test(e, expected_result_1, expected_result_2, expected_result_3, expected_result_4)
    return e

# init long position for T0, counter party T2, T3(unfilled)
def test_1_1():
    e = test_1()
    # actions
    action1 = {"type": 'limit', "side": 'bid', "size": 3, "price": 2}
    action2 = {"type": 'limit', "side": 'bid', "size": 4, "price": 3}
    action3 = {"type": 'limit', "side": 'bid', "size": 5, "price": 4}
    action4 = {"type": 'limit', "side": 'bid', "size": 6, "price": 5}
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

    test_1() # place initial orders
    #test_1_1()
    #test_1_2()
    #test_1_3()
    #test_1_4()


    #test_random()

    sys.exit(0)
