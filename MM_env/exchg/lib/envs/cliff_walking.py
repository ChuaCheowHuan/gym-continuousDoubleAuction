import numpy as np
import sys
from gym.envs.toy_text import discrete

### CliffWalkingEnv Environment 
    
class CliffWalkingEnv(discrete.DiscreteEnv):

    metadata = {'render.modes': ['human', 'ansi', 'rgb_array']}
    
    # Make sure that current state stays within environment
    def _limit_coordinates(self, coord):
        coord[0] = min(coord[0], self.shape[0] - 1)
        coord[0] = max(coord[0], 0)
        coord[1] = min(coord[1], self.shape[1] - 1)
        coord[1] = max(coord[1], 0)
        return coord

    def _calculate_transition_prob(self, current, delta):
        new_position = np.array(current) + np.array(delta)
        new_position = self._limit_coordinates(new_position).astype(int)
        
        # Given a coordinate address, coord, find it's corresponding index in another
        # array with self.shape
        new_state = np.ravel_multi_index(tuple(new_position), self.shape)
        #print("new_position=", new_position, "new_state=", new_state)
        
        reward = -100.0 if self._cliff[tuple(new_position)] else -1.0
        is_done = self._cliff[tuple(new_position)] or (tuple(new_position) == (3,11))
        return [(1.0, new_state, reward, is_done)]

    def __init__(self):
      	# 0 to 3 for x, 0 to 11 for y, the x,y is inverted in the graphics
        self.shape = (4, 12)

        nS = np.prod(self.shape)
        nA = 4

        # Cliff Location
        self._cliff = np.zeros(self.shape, dtype=np.bool)
        # 1:-1 means 1 to excluding last index for y
        self._cliff[3, 1:-1] = True

        # Calculate transition probabilities
        P = {}
        for s in range(nS):
        	
            position = np.unravel_index(s, self.shape)
            #print("s", s, "position", position)
            P[s] = { a : [] for a in range(nA) }
            
            #UP = 0, [-1, 0] is refer to as delta in _calculate_transition_prob, x is 				#subtracted by 1
            #RIGHT = 1
            #DOWN = 2
            #LEFT = 3            
            P[s][0] = self._calculate_transition_prob(position, [-1, 0]) 
            P[s][1] = self._calculate_transition_prob(position, [0, 1])
            P[s][2] = self._calculate_transition_prob(position, [1, 0])
            P[s][3] = self._calculate_transition_prob(position, [0, -1])

        # We always start in state (3, 0)
        isd = np.zeros(nS)
        isd[np.ravel_multi_index((3,0), self.shape)] = 1.0

        super(CliffWalkingEnv, self).__init__(nS, nA, P, isd)

    def _convert_state(self, state):
        converted = np.unravel_index(state, self.shape)
        #print("state", state, "converted", converted)
        return np.asarray(list(converted), dtype=np.float32)
    
    def reset(self):
        self.s = np.argmax(self.isd)
        return self._convert_state(self.s)
    
    def step(self, action):
        reward = self.P[self.s][action][0][2]
        done = self.P[self.s][action][0][3]
        info = {'prob':self.P[self.s][action][0][0]}
        self.s = self.P[self.s][action][0][1]
             
        #print("self._convert_state(self.s)", self._convert_state(self.s))
        #if self.s == 47:
        	#print("reward", reward)
        	#print("self._convert_state(self.s)", self._convert_state(self.s))
        return (self._convert_state(self.s), reward, done, info)
    
    def render(self, mode='rgb_array', close=False):
        if close:
            return

        if mode == 'rgb_array':
            maze = np.zeros((4, 12))
            maze[self._cliff] = -1
            maze[np.unravel_index(self.s, self.shape)] = 2.0
            maze[(3,11)] = 0.5
            img = np.array(maze, copy=True)
            return img
        
        else:
            outfile = StringIO() if mode == 'ansi' else sys.stdout

            for s in range(self.nS):
                position = np.unravel_index(s, self.shape)

                if self.s == s:
                    output = " x "
                elif position == (3,11):
                    output = " T "
                elif self._cliff[position]:
                    output = " C "
                else:
                    output = " o "

                if position[1] == 0:
                    output = output.lstrip() 
                if position[1] == self.shape[1] - 1:
                    output = output.rstrip() 
                    output += "\n"

                outfile.write(output)
            outfile.write("\n")
