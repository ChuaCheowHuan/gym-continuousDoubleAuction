import sys

if "../" not in sys.path:
    sys.path.append("../")

#from exchg.lib.envs.simple_rooms import SimpleRoomsEnv
#from exchg.lib.envs.cliff_walking import CliffWalkingEnv
#from exchg.lib.simulation import Experiment

from exchg.exchg import Exchg

max_steps = 10
num_of_traders = 3
tape_display_length = 100
init_cash = 1000
e = Exchg(num_of_traders, init_cash, tape_display_length)

for step in range(max_steps):
    actions = []
    for i, trader in enumerate(e.agents):
        action = trader.select_random_action()
        actions.append(action)
    print('\n\n\nSTEP:', step)
    e.step(actions)


sys.exit(0)

"""
before:
(array([68., 54., 53., 50., 38., 37., 33., 31., 29., 28.]),
 array([  92., 1400.,  801., 1302., 1402.,  700., 2002.,  401.,  401., 401.]),
 array([-83., -87., -88., -90., -91., -94., -95., -96., -98.,   0.]),
 array([-201., -501.,  -99., -501., -201., -801., -701., -701., -601., 0.]))

after:
(array([54., 53., 50., 49., 42., 38., 37., 33., 31., 30.]),
 array([ 992.,  801., 1302.,  601.,  201., 1402.,  700., 2002.,  401., 101.]),
 array([-66., -70., -83., -86., -87., -88., -90., -91., -94., -95.]),
 array([ -300.,  -200.,  -200.,  -101.,  -501.,   -99.,  -501.,  -201., -801., -1602.]))

state_diff_list:
[array([-14.,  -1.,  -3.,  -1.,   4.,   1.,   4.,   2.,   2.,   2.]),
 array([  900.,  -599.,   501.,  -701., -1201.,   702., -1302.,  1601., 0.,  -300.]),
 array([ 17.,  17.,   5.,   4.,   4.,   6.,   5.,   5.,   4., -95.]),
 array([  -99.,   301.,  -101.,   400.,  -300.,   702.,   200.,   500., -200., -1602.])]

             transaction_record = {'timestamp': self.time, 'price': traded_price, 'quantity': traded_quantity, 'time': self.time}
             if side == 'bid': # counter_party's side
                 transaction_record['party1'] = [counter_party, 'bid', head_order.order_id, new_book_quantity]
                 transaction_record['party2'] = [quote['trade_id'], 'ask', None, None]
             else:
                 transaction_record['party1'] = [counter_party, 'ask', head_order.order_id, new_book_quantity]
                 transaction_record['party2'] = [quote['trade_id'], 'bid', None, None]

 trades:
 [{'timestamp': 199666, 'price': Decimal('28'), 'quantity': Decimal('499'), 'time': 199666, 'party1': [279, 'bid', 199656, None], 'party2': [293, 'ask', None, None]},
  {'timestamp': 199666, 'price': Decimal('10'), 'quantity': Decimal('101'), 'time': 199666, 'party1': [287, 'bid', 199661, None], 'party2': [293, 'ask', None, None]}]

 order_in_book:
 {'type': 'limit',
  'side': 'bid',
  'quantity': 601,
  'price': Decimal('42'),
  'trade_id': 240,
  'timestamp': 199630,
  'order_id': 199630}
"""
