import sys

if "../" not in sys.path:
    sys.path.append("../")

from envs.continuousDoubleAuction_env import continuousDoubleAuctionEnv

def test_random():
    num_of_traders = 4
    init_cash = 1000000
    tick_size = 1
    tape_display_length = 10
    max_step = 10000
    e = continuousDoubleAuctionEnv(num_of_traders, init_cash, tick_size, tape_display_length, max_step)
    e.reset()
    for step in range(max_step):
        actions = {}
        for i, trader in enumerate(e.agents):
            action = trader.select_random_action()
            actions[i] = action
        e.step(actions)


if __name__ == "__main__":

    test_random()

    sys.exit(0)
