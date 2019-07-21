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
    print('nav:', e.agents[0].nav)
    print('net_position:', e.agents[ID].net_position)

def test_1():
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
    e.render()
    print_acc(e, 0)
    print_acc(e, 1)
    print_acc(e, 2)
    e.step(actions)
    e.render()
    print_acc(e, 0)
    print_acc(e, 1)
    print_acc(e, 2)

    test_1_1(e)
    
def test_1_1(e):

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
    e.render()
    print_acc(e, 0)
    print_acc(e, 1)
    print_acc(e, 2)
    e.step(actions)
    e.render()
    print_acc(e, 0)
    print_acc(e, 1)
    print_acc(e, 2)

def test_random():
    num_of_traders = 3
    init_cash = 1000
    tape_display_length = 100
    max_step = 10
    e = Exchg(num_of_traders, init_cash, tape_display_length, max_step)
    for step in range(max_step):
        actions = []
        for i, trader in enumerate(e.agents):
            action = trader.select_random_action()
            actions.append(action)
        print('\n\n\nSTEP:', step)
        e.step(actions)

if __name__ == "__main__":
    test_1()
    #test_random()
    sys.exit(0)
