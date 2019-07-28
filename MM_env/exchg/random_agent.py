import random
import numpy as np

class Random_agent(object):

    # pass action to step
    def select_random_action(self, ID):
        #type = np.random.randint(0, 1, size=1) # type, draw 1 int, 0(market) to 1(limit)
        #type = random.choice(['market','limit'])
        type = random.choice(['limit'])
        #side = np.random.randint(-1, 1, size=1) # side, draw 1 int, -1(ask), 0(None), 1(bid)
        side = random.choice(['bid',None,'ask'])
        size = random.randrange(1, 100, 100) # size in 100s from 0(min) to 1000(max)
        price = random.randrange(1, 10, 1) # price from 1(min) to 100(max)
        action = {"ID": ID,
                  "type": type,
                  "side": side,
                  "size": size,
                  "price": price}
        return action

"""
hidden_layer = tf.layers.dense(self.s, num_hidden, tf.nn.relu, kernel_initializer = a_w, name='a_hidden', trainable=trainable)
# tanh [-1,1]
mu = tf.layers.dense(hidden_layer, A_DIM, tf.nn.tanh, kernel_initializer = a_w, name='mu', trainable=trainable)
# softplus [0,inf)
sigma = tf.layers.dense(hidden_layer, A_DIM, tf.nn.softplus, kernel_initializer = a_w, name='sigma', trainable=trainable) + 1e-4
norm_dist = tf.distributions.Normal(loc=mu, scale=sigma)



hidden_layer = tf.layers.dense(self.s, num_hidden, tf.nn.relu, kernel_initializer = a_w, name='a_hidden', trainable=trainable)
logits = tf.layers.dense(hidden_layer, A_DIM, tf.nn.softmax, kernel_initializer = a_w, name='mu', trainable=trainable)
# tanh [-1,1]
mu = tf.layers.dense(hidden_layer, A_DIM, tf.nn.tanh, kernel_initializer = a_w, name='mu', trainable=trainable)
# softplus [0,inf)
sigma = tf.layers.dense(hidden_layer, A_DIM, tf.nn.softplus, kernel_initializer = a_w, name='sigma', trainable=trainable) + 1e-4
norm_dist = tf.distributions.Normal(loc=mu, scale=sigma)



# Let mean vector and co-variance be:
mu = [1., 2] # number of variables is 2 since mu is 1x2
cov = [[ 1,  3/5],[ 3/5,  2]] # cov is 2x2 since number of variables is 2

#Multivariate Normal distribution
gaussian = tf.contrib.distributions.MultivariateNormalFullCovariance(
           loc=mu,
           covariance_matrix=cov)

# Generate a mesh grid to plot the distributions
X, Y = tf.meshgrid(tf.range(-3, 3, 0.1), tf.range(-3, 3, 0.1))
idx = tf.concat([tf.reshape(X, [-1, 1]), tf.reshape(Y,[-1,1])], axis =1)
prob = tf.reshape(gaussian.prob(idx), tf.shape(X))

with tf.Session() as sess:
   p = sess.run(prob)
   m, c = sess.run([gaussian.mean(), gaussian.covariance()])
   # m is [1., 2.]
   # c is [[1, 0.6], [0.6, 2]]
"""
