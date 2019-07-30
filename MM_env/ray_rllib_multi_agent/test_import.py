import sys

if "../" not in sys.path:
    sys.path.append("../")

#from exchg.x.y import z
from exchg.exchg import Exchg

class Test_Import():
    def _fun(self):
        print('_fun')
        return 0

TI = Test_Import()
TI._fun()
e = Exchg()
print('e.print_accs:', e.print_accs())
