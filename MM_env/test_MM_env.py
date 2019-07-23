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

def test(e, expected_result_0, expected_result_1, expected_result_2, expected_result_3):
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
    # test
    #assert(expected_result_0 == result_0)
    #assert(expected_result_0 == result_1)
    #assert(expected_result_1 == result_2)
    #assert(expected_result_2 == result_3)
    print_info(e)

# place initial orders, 4 traders each with 3 bids, 3 asks all in LOB, no trade
def test_1():
    e = create_env()
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
    expected_result_0 = (10000, 0, 0, 10000, 0)
    expected_result_1 = (10000, 0, 0, 10000, 0)
    expected_result_2 = (10000, 0, 0, 10000, 0)
    test(e, expected_result_0, expected_result_0, expected_result_1, expected_result_2)
    return e

# init long position for T0, counter party T0, T1, T2(unfilled)
def test_1_1():
    e = test_1()
    # actions
    action0 = {"type": 'limit', "side": 'bid', "size": 3, "price": 2}
    action1 = {"type": 'limit', "side": 'bid', "size": 4, "price": 3}
    action2 = {"type": 'limit', "side": 'bid', "size": 5, "price": 4}
    action3 = {"type": 'limit', "side": 'bid', "size": 6, "price": 5}
    actions = [action0,action1,action2,action3]
    e.step(actions) # execute actions in 1 step
    # hard coded expected results
    expected_result_0 = (10000, 0, 0, 10000, 0)
    expected_result_0 = (10000, 0, 0, 10000, 0)
    expected_result_1 = (10000, 0, 0, 10000, 0)
    expected_result_2 = (10000, 0, 0, 10000, 0)
    test(e, expected_result_0, expected_result_0, expected_result_1, expected_result_2)
    return e

def test_random():
    num_of_traders = 4
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
