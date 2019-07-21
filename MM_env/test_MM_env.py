import sys

if "../" not in sys.path:
    sys.path.append("../")

#from exchg.lib.envs.simple_rooms import SimpleRoomsEnv
#from exchg.lib.envs.cliff_walking import CliffWalkingEnv
#from exchg.lib.simulation import Experiment

from exchg.exchg import Exchg

def print_acc(e, ID):
    print('\nID:', ID)
    print('cash:', e.agents[ID].cash)
    print('cash_on_hold:', e.agents[ID].cash_on_hold)
    print('position_val:', e.agents[ID].position_val)
    print('nav:', e.agents[ID].nav)
    print('net_position:', e.agents[ID].net_position)
    print('\n')

def print_info(e):
    e.render()
    for trader in e.agents:
        print_acc(e, trader.ID)

def _acc(e, ID):
    return (e.agents[ID].cash,
            e.agents[ID].cash_on_hold,
            e.agents[ID].position_val,
            e.agents[ID].nav,
            e.agents[ID].net_position)

def expected(e, ID, action, is_init, is_trade, unfilled):
    trader = e.agents[ID]
    cash = trader.cash
    cash_on_hold = trader.cash_on_hold
    position_val = trader.position_val
    nav = trader.nav
    net_position = trader.net_position

    type = action.get('type')
    side = action.get('side')
    trade_price = action.get('price')
    trade_size = action.get('size')

    if side == None:
        return (cash, cash_on_hold, position_val, nav, net_position)

    # expected after processing order:
    if is_init: # init_party
        if is_trade:
            if net_position > 0: # long
                if side == 'bid':
                    position_val = (net_position + trade_size) * trade_price
                else: # ask
                    if net_position >= trade_size: # still net long or neutral
                        cash += trade_size * trade_price # covered part goes to cash
                        position_val = (net_position - trade_size) * trade_price # update remaining position_val
                    else: # net position changes to short
                        cash += net_position * trade_price # covered part goes to cash
                        position_val = (trade_size - net_position) * trade_price # update remaining position_val
            elif net_position < 0: # short
                if side == 'ask':
                    position_val = (abs(net_position) + trade_size) * trade_price
                else: # bid
                    if net_position >= trade_size: # still net long or neutral
                        cash += trade_size * trade_price # covered part goes to cash
                        position_val = (abs(net_position) - trade_size) * trade_price # update remaining position_val
                    else: # net position changes to short
                        cash += net_position * trade_price # covered part goes to cash
                        position_val = (trade_size - abs(net_position)) * trade_price # update remaining position_val
            else: # neutral
                if side == 'bid':
                    cash -= trade_size * trade_price
                    position_val = trade_size * trade_price
                else: # ask
                    cash -= trade_size * trade_price
                    position_val = trade_size * trade_price
            # deal with unfilled
            cash -= unfilled * trade_price # reduce cash
            cash_on_hold += unfilled * trade_price # increase cash_on_hold
        else: # no trade, order goes in LOB
            cash -= unfilled * trade_price # reduce cash
            cash_on_hold += unfilled * trade_price # increase cash_on_hold
    else: # counter_party, therefore trade must have occured
        if net_position > 0: # long
            if side == 'bid':
                position_val = (net_position + trade_size) * trade_price
            else: # ask
                if net_position >= trade_size: # still net long or neutral
                    cash += trade_size * trade_price # covered part goes to cash
                    position_val = (net_position - trade_size) * trade_price # update remaining position_val
                else: # net position changes to short
                    cash += net_position * trade_price # covered part goes to cash
                    position_val = (trade_size - net_position) * trade_price # update remaining position_val
        elif net_position < 0: # short
            if side == 'ask':
                position_val = (abs(net_position) + trade_size) * trade_price
            else: # bid
                if net_position >= trade_size: # still net long or neutral
                    cash += trade_size * trade_price # covered part goes to cash
                    position_val = (abs(net_position) - trade_size) * trade_price # update remaining position_val
                else: # net position changes to short
                    cash += net_position * trade_price # covered part goes to cash
                    position_val = (trade_size - abs(net_position)) * trade_price # update remaining position_val
        else: # neutral
            if side == 'bid':
                cash -= trade_size * trade_price
                position_val = trade_size * trade_price
            else: # ask
                cash -= trade_size * trade_price
                position_val = trade_size * trade_price
        # deal with unfilled
        cash -= unfilled * trade_price # reduce cash
        cash_on_hold += unfilled * trade_price # increase cash_on_hold

    return (cash, cash_on_hold, position_val, nav, net_position)

def test_1(): # place initial orders
    num_of_traders = 3
    tape_display_length = 100
    init_cash = 100
    max_step = 10
    e = Exchg(num_of_traders, init_cash, tape_display_length, max_step)

    action1 = {"type": 'limit',
               "side": 'bid',
               "size": 2,
               "price": 3}
    action2 = {"type": 'limit',
               "side": 'bid',
               "size": 3,
               "price": 4}
    action3 = {"type": 'limit',
               "side": 'ask',
               "size": 4,
               "price": 5}
    actions = [action1,action2,action3]

    # compute before step execution
    #expected_result_1 = expected(e, ID=0, action=action1, is_init=True, is_trade=False, unfilled=action1.get('size'))
    #expected_result_2 = expected(e, ID=1, action=action2, is_init=True, is_trade=False, unfilled=action2.get('size'))
    #expected_result_3 = expected(e, ID=2, action=action3, is_init=True, is_trade=False, unfilled=action3.get('size'))

    expected_result_1 = (94, 6, 0, 100, 0)
    expected_result_2 = (88, 12, 0, 100, 0)
    expected_result_3 = (80, 20, 0, 100, 0)

    e.step(actions) # execute

    result_1 = _acc(e, ID=0) # get results
    result_2 = _acc(e, ID=1) # get results
    result_3 = _acc(e, ID=2) # get results

    assert(expected_result_1 == result_1) # test
    assert(expected_result_2 == result_2) # test
    assert(expected_result_3 == result_3) # test

    print_info(e)

    return e

def test_1_1(e): # create long position for T0 with unfilled, short position for T2(counter_party)
    action1 = {"type": 'limit',
               "side": 'bid',
               "size": 7,
               "price": 6}
    action2 = {"type": 'limit',
               "side": None,
               "size": 3,
               "price": 4}
    action3 = {"type": 'limit',
               "side": None,
               "size": 4,
               "price": 5}
    actions = [action1,action2,action3]

    # initial after 1st insert:
    #expected_result_1 = (94, 6, 0, 100, 0)
    #expected_result_2 = (88, 12, 0, 100, 0)
    #expected_result_3 = (80, 20, 0, 100, 0)

    expected_result_1 = (56, 24, 20, 100, 4)
    expected_result_2 = (88, 12, 0, 100, 0)
    expected_result_3 = (80, 0, 20, 100, -4)

    e.step(actions) # execute

    result_1 = _acc(e, ID=0) # get results
    result_2 = _acc(e, ID=1) # get results
    result_3 = _acc(e, ID=2) # get results

    print('result_1:', result_1)
    print('expected_result_1:', expected_result_1)
    print('result_2:', result_2)
    print('expected_result_2:', expected_result_2)
    print('result_3:', result_3)
    print('expected_result_3:', expected_result_3)

    assert(expected_result_1 == result_1) # test
    assert(expected_result_2 == result_2) # test
    assert(expected_result_3 == result_3) # test

    print_info(e)

    return e

def test_1_2(e): # create long position for T0, short position for T2(counter_party) with unfilled
    action1 = {"type": 'limit',
               "side": 'bid',
               "size": 2,
               "price": 6}
    action2 = {"type": 'limit',
               "side": None,
               "size": 3,
               "price": 4}
    action3 = {"type": 'limit',
               "side": None,
               "size": 4,
               "price": 5}
    actions = [action1,action2,action3]

    # initial after 1st insert:
    #expected_result_1 = (94, 6, 0, 100, 0)
    #expected_result_2 = (88, 12, 0, 100, 0)
    #expected_result_3 = (80, 20, 0, 100, 0)

    expected_result_1 = (84, 6, 10, 100, 2)
    expected_result_2 = (88, 12, 0, 100, 0)
    expected_result_3 = (80, 10, 10, 100, -2)

    e.step(actions)

    result_1 = _acc(e, ID=0) # get results
    result_2 = _acc(e, ID=1) # get results
    result_3 = _acc(e, ID=2) # get results

    print('result_1:', result_1)
    print('expected_result_1:', expected_result_1)
    print('result_2:', result_2)
    print('expected_result_2:', expected_result_2)
    print('result_3:', result_3)
    print('expected_result_3:', expected_result_3)

    assert(expected_result_1 == result_1) # test
    assert(expected_result_2 == result_2) # test
    assert(expected_result_3 == result_3) # test

    print_info(e)

    return e

# create short position for T2 with unfilled, long position for T1(counter_party)
def test_1_3(e):
    action1 = {"type": 'limit',
               "side": None,
               "size": 2,
               "price": 3}
    action2 = {"type": 'limit',
               "side": None,
               "size": 3,
               "price": 4}
    action3 = {"type": 'limit',
               "side": 'ask',
               "size": 10,
               "price": 4}
    actions = [action1,action2,action3]

    # initial after 1st insert:
    #expected_result_1 = (94, 6, 0, 100, 0)
    #expected_result_2 = (88, 12, 0, 100, 0)
    #expected_result_3 = (80, 20, 0, 100, 0)

    expected_result_1 = (94, 6, 0, 100, 0)
    expected_result_2 = (88, 0, 12, 100, 3)
    expected_result_3 = (40, 48, 12, 100, -3)

    e.step(actions)

    result_1 = _acc(e, ID=0) # get results
    result_2 = _acc(e, ID=1) # get results
    result_3 = _acc(e, ID=2) # get results

    print('result_1:', result_1)
    print('expected_result_1:', expected_result_1)
    print('result_2:', result_2)
    print('expected_result_2:', expected_result_2)
    print('result_3:', result_3)
    print('expected_result_3:', expected_result_3)

    assert(expected_result_1 == result_1) # test
    assert(expected_result_2 == result_2) # test
    assert(expected_result_3 == result_3) # test

    print_info(e)

    return e

# create short position for T2, long position for T1(counter_party) with unfilled
def test_1_4(e):
    """
    action1 = {"type": 'limit',
               "side": 'bid',
               "size": 2,
               "price": 3}
    action2 = {"type": 'limit',
               "side": 'bid',
               "size": 3,
               "price": 4}
    action3 = {"type": 'limit',
               "side": 'ask',
               "size": 4,
               "price": 5}
    """

    action1 = {"type": 'limit',
               "side": None,
               "size": 2,
               "price": 3}
    action2 = {"type": 'limit',
               "side": None,
               "size": 3,
               "price": 4}
    action3 = {"type": 'limit',
               "side": 'ask',
               "size": 2,
               "price": 4}
    actions = [action1,action2,action3]

    # initial after 1st insert:
    #expected_result_1 = (94, 6, 0, 100, 0)
    #expected_result_2 = (88, 12, 0, 100, 0)
    #expected_result_3 = (80, 20, 0, 100, 0)

    expected_result_1 = (94, 6, 0, 100, 0)
    expected_result_2 = (88, 4, 8, 100, 2)
    expected_result_3 = (72, 20, 8, 100, -2)

    e.step(actions)

    result_1 = _acc(e, ID=0) # get results
    result_2 = _acc(e, ID=1) # get results
    result_3 = _acc(e, ID=2) # get results

    print('result_1:', result_1)
    print('expected_result_1:', expected_result_1)
    print('result_2:', result_2)
    print('expected_result_2:', expected_result_2)
    print('result_3:', result_3)
    print('expected_result_3:', expected_result_3)

    assert(expected_result_1 == result_1) # test
    assert(expected_result_2 == result_2) # test
    assert(expected_result_3 == result_3) # test

    print_info(e)

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
        e.render()
        print_acc(e, 0)
        print_acc(e, 1)
        print_acc(e, 2)


if __name__ == "__main__":

    e = test_1() # place initial orders


    # ********** create positions, single counter_party **********

    # create long position for T0 with unfilled, short position for T2(counter_party)
    #e1 = test_1_1(e)
    # create long position for T0, short position for T2(counter_party) with unfilled
    #e2 = test_1_2(e)
    # create short position for T2 with unfilled, long position for T1(counter_party)
    #e3 = test_1_3(e)
    # create short position for T2, long position for T1(counter_party) with unfilled
    e4 = test_1_4(e)


    # ********** close positions, single counter_party **********



    # ********** create positions, more than one counter_party **********
    # ********** close positions, more than one counter_party **********


    #test_random()

    sys.exit(0)
