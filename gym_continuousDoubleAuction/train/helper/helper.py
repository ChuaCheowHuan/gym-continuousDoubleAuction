import numpy as np
import re

def str_to_arr(a_str):
    """
    Remove letters from string & convert string to array. 
    """
    letters = '] ['
    regex_str = '[' + letters + ']'
    a_str = re.sub(regex_str, ' ', a_str)
    a_arr = np.fromstring(a_str, dtype=float, sep=' ')
    return a_arr
