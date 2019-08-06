import numpy as np

class Running_Stats(object):
    # This class which computes global stats is adapted & modified from:
    # https://github.com/openai/baselines/blob/master/baselines/common/running_mean_std.py
    # https://en.wikipedia.org/wiki/Algorithms_for_calculating_variance#Parallel_algorithm
    def __init__(self, epsilon=1e-4, shape=()):
        self.mean = np.zeros(shape, 'float64')
        self.var = np.ones(shape, 'float64')
        self.std = np.ones(shape, 'float64')
        self.count = epsilon

    def update(self, x):
        batch_mean = np.mean(x, axis=0)
        batch_var = np.var(x, axis=0)
        batch_count = x.shape[0]
        self.update_from_moments(batch_mean, batch_var, batch_count)

    def update_from_moments(self, batch_mean, batch_var, batch_count):
        delta = batch_mean - self.mean

        new_mean = self.mean + delta * batch_count / (self.count + batch_count)
        m_a = self.var * self.count
        m_b = batch_var * batch_count
        M2 = m_a + m_b + np.square(delta) * self.count * batch_count / (self.count + batch_count)
        new_var = M2 / (self.count + batch_count)

        self.mean = new_mean
        self.var = new_var
        self.std = np.maximum(np.sqrt(self.var), 1e-6)
        #self.std = np.sqrt(np.maximum(self.var, 1e-2))
        self.count = batch_count + self.count

"""
# Usage examples:

running_stats_s = Running_Stats()

buffer_s_ = running_stats_fun(running_stats_s_, buffer_s_, s_CLIP, True)

# pre-train updating of s_ to running_stats_s_ object to get prepare for normalization
def state_next_normalize(sample_size, running_stats_s_):
  buffer_s_ = []
  s = env.reset()
  for i in range(sample_size):
    a = env.action_space.sample()
    s_, r, done, _ = env.step(a)
    buffer_s_.append(s_)
  running_stats_s_.update(np.array(buffer_s_))

# normalize & clip a running buffer
# used on extrinsic reward (buffer_r), intrinsic reward (buffer_r_i) & next state(s_)
def running_stats_fun(run_stats, buf, clip, clip_state):
    run_stats.update(np.array(buf))
    buf = (np.array(buf) - run_stats.mean) / run_stats.std
    if clip_state == True:
      buf = np.clip(buf, -clip, clip)
    return buf
"""
