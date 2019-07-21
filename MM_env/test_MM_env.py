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
    expected_result_1 = expected(e, ID=0, action=action1, is_init=True, is_trade=False, unfilled=action1.get('size'))
    expected_result_2 = expected(e, ID=1, action=action2, is_init=True, is_trade=False, unfilled=action2.get('size'))
    expected_result_3 = expected(e, ID=2, action=action3, is_init=True, is_trade=False, unfilled=action3.get('size'))

    e.step(actions) # execute

    result_1 = _acc(e, ID=0) # get results
    result_2 = _acc(e, ID=1) # get results
    result_3 = _acc(e, ID=2) # get results

    assert(expected_result_1 == result_1) # test
    assert(expected_result_2 == result_2) # test
    assert(expected_result_3 == result_3) # test

    print_info(e)

    return e

def test_1_1(e): # create long position for trader 1, short for trader 2
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
               "size": 4,
               "price": 4}
    actions = [action1,action2,action3]
    e.step(actions)
    e.render()
    print_acc(e, 0)
    print_acc(e, 1)
    print_acc(e, 2)

    return e

def test_1_2(e): # close T1 long, counter_party is T0
    action1 = {"type": 'limit',
               "side": 'bid',
               "size": 10,
               "price": 5}
    action2 = {"type": 'limit',
               "side": 'ask',
               "size": 3,
               "price": 5}
    action3 = {"type": 'limit',
               "side": None,
               "size": 4,
               "price": 4}
    actions = [action1,action2,action3]
    print(actions)
    e.step(actions)
    e.render()
    print_acc(e, 0)
    print_acc(e, 1)
    print_acc(e, 2)

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
    e = test_1()
    #e = test_1_1(e)
    #e = test_1_2(e)

    #test_random()

    sys.exit(0)
