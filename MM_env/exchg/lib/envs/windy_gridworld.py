import numpy as np
import sys
from gym.envs.toy_text import discrete

### WindyGridworldEnv Environment 

class WindyGridworldEnv(discrete.DiscreteEnv):

    metadata = {'render.modes': ['human', 'ansi', 'rgb_array']}

    def _limit_coordinates(self, coord):
        coord[0] = min(coord[0], self.shape[0] - 1)
        coord[0] = max(coord[0], 0)
        coord[1] = min(coord[1], self.shape[1] - 1)
        coord[1] = max(coord[1], 0)
        return coord

    def _calculate_transition_prob(self, current, delta, winds):
        new_position = np.array(current) + np.array(delta) + np.array([-1, 0]) * winds[tuple(current)]
        new_position = self._limit_coordinates(new_position).astype(int)
        new_state = np.ravel_multi_index(tuple(new_position), self.shape)
        is_done = tuple(new_position) == (3, 7)
        
        #print("new_state", new_state)
        
        return [(1.0, new_state, -1.0, is_done)]

    def __init__(self):
        self.shape = (7, 10)

        nS = np.prod(self.shape)
        nA = 4

        # Wind strength
        self.winds = np.zeros(self.shape)
        self.winds[:,[3,4,5,8]] = 1
        self.winds[:,[6,7]] = 2

        # Calculate transition probabilities
        P = {}
        for s in range(nS):
            position = np.unravel_index(s, self.shape)
            P[s] = { a : [] for a in range(nA) }
            #UP = 0
            #RIGHT = 1
            #DOWN = 2
            #LEFT = 3
            P[s][0] = self._calculate_transition_prob(position, [-1, 0], self.winds)
            P[s][1] = self._calculate_transition_prob(position, [0, 1], self.winds)
            P[s][2] = self._calculate_transition_prob(position, [1, 0], self.winds)
            P[s][3] = self._calculate_transition_prob(position, [0, -1], self.winds)

        # We always start in state (3, 0)
        isd = np.zeros(nS)
        isd[np.ravel_multi_index((3,0), self.shape)] = 1.0

        super(WindyGridworldEnv, self).__init__(nS, nA, P, isd)

    def render(self, mode='rgb_array', close=False):
        if close:
            return

        if mode == 'rgb_array':
            maze = np.zeros(self.shape)
            maze[:,[3,4,5,8]] = -0.5
            maze[:,[6,7]] = -1
            maze[np.unravel_index(self.s, self.shape)] = 2.0
            maze[(3,7)] = 0.5
            img = np.array(maze, copy=True)
            return img
       
        else:        
            outfile = StringIO() if mode == 'ansi' else sys.stdout

            for s in range(self.nS):
                position = np.unravel_index(s, self.shape)
                # print(self.s)
                if self.s == s:
                    output = " x "
                elif position == (3,7):
                    output = " T "
                else:
                    output = " o "

                if position[1] == 0:
                    output = output.lstrip()
                if position[1] == self.shape[1] - 1:
                    output = output.rstrip()
                    output += "\n"

                outfile.write(output)
            outfile.write("\n")