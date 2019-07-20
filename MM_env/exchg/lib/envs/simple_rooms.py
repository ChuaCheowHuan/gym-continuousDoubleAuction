import numpy as np

### Interface
class Environment(object):

    def reset(self):
        raise NotImplementedError('Inheriting classes must override reset.')

    def actions(self):
        raise NotImplementedError('Inheriting classes must override actions.')

    def step(self):
        raise NotImplementedError('Inheriting classes must override step')

class ActionSpace(object):
    
    def __init__(self, actions):
        self.actions = actions
        self.n = len(actions)
        
### SimpleRoomsEnv Environment 

class SimpleRoomsEnv(Environment):
    """Define a simple 4-room environment"""
    """actions: 0 - north, 1 - east(Right), 2 - west(Left), 3 - south"""

    def __init__(self):
        super(SimpleRoomsEnv, self).__init__()

        # define state and action space
        self.S = range(16)
        self.action_space = ActionSpace(range(4))

        # define reward structure
        self.R = [0] * len(self.S)
        self.R[15] = 1
        
        # define transitions
        self.P = {}
        self.P[0] = [1, 4]
        self.P[1] = [0, 2, 5]
        self.P[2] = [1, 3, 6]
        self.P[3] = [2, 7]
        self.P[4] = [0, 5, 8]
        self.P[5] = [1, 4]
        self.P[6] = [2, 7]
        self.P[7] = [3, 6, 11]
        self.P[8] = [4, 9, 12]
        self.P[9] = [8, 13]
        self.P[10] = [11, 14]
        self.P[11] = [7, 10, 15]
        self.P[12] = [8, 13]
        self.P[13] = [9, 12, 14]
        self.P[14] = [10, 13, 15]
        self.P[15] = [11, 14]

        self.max_trajectory_length = 50
        self.tolerance = 0.1
        self._rendered_maze = self._render_maze()
        
    def step(self, action):
        s_prev = self.s
        self.s = self.single_step(self.s, action)
        reward = self.single_reward(self.s, s_prev, self.R)
        self.nstep += 1
        self.is_reset = False

        if (reward < -1. * (self.tolerance) or reward > self.tolerance) or self.nstep == self.max_trajectory_length:
            self.reset()

        return (self._convert_state(self.s), reward, self.is_reset, '')
    
    """
    Example:
    If a=0 & s=4, 
    in the 2nd if statement, 
    s-4 = 4-4 = 0, 
    0 is in self.P[4], self.P[4] = [0, 5, 8] is define as transitions under __init__
    therefore, s = s-4 = 0
    """
    def single_step(self, s, a):
        if a < 0 or a > 3:
            raise ValueError('Unknown action', a)
        if a == 0 and (s-4 in self.P[s]):
            s -= 4
        elif a == 1 and (s+1 in self.P[s]):
            s += 1
        elif a == 2 and (s-1 in self.P[s]):
            s -= 1
        elif a == 3 and (s+4 in self.P[s]):
            s += 4
        return s

    def single_reward(self, s, s_prev, rewards):
        if s == s_prev:
            return 0
        return rewards[s]
       
    def reset(self):
        self.nstep = 0
        self.s = 0
        self.is_reset = True
        return self._convert_state(self.s)
    
    def _convert_state(self, s):
        converted = np.zeros(len(self.S), dtype=np.float32)
        # Mark start state with index 0 as 1
        converted[s] = 1
        return converted
    
    def _get_render_coords(self, s):
        return (int(s / 4) * 4, (s % 4) * 4)
    
    def _render_maze(self):
        # draw background and grid lines
        maze = np.zeros((17, 17))
        for x in range(0, 17, 4):
            maze[x, :] = 0.5
        for y in range(0, 17, 4):
            maze[:, y] = 0.5

        # draw reward and transitions
        for s in range(16):
            if self.R[s] != 0:
                x, y = self._get_render_coords(s)
                maze[x+1:x+4, y+1:y+4] = self.R[s]
            if self.single_step(s, 0) == s:
                x, y = self._get_render_coords(s)
                maze[x, y:y+5] = -1
            if self.single_step(s, 1) == s:
                x, y = self._get_render_coords(s)
                maze[x:x+5, y+4] = -1
            if self.single_step(s, 2) == s:
                x, y = self._get_render_coords(s)
                maze[x:x+5, y] = -1
            if self.single_step(s, 3) == s:
                x, y = self._get_render_coords(s)
                maze[x+4, y:y+4] = -1
        return maze

    def render(self, mode = 'rgb_array'):
        assert mode == 'rgb_array', 'Unknown mode: %s' % mode
        img = np.array(self._rendered_maze, copy=True)

        # draw current agent location
        x, y = self._get_render_coords(self.s)
        img[x+1:x+4, y+1:y+4] = 2.0
        return img

