import random
import numpy as np

class Random_agent(object):

    # pass action to step
    def select_random_action(self, ID):
        type_side = np.random.randint(0, 5, size=1) # type_side: None=0, market_bid=1, market_ask=2, limit_bid=3, limit_ask=4
        size = [random.randrange(1, 100, 10)] # size in 100s from 0(min) to 1000(max)
        price = [random.randrange(1, 10, 1)] # price from 1(min) to 100(max)
        act = (type_side, size, price)
        print('select_random_action act:', act)
        return act

"""
hidden_layer = tf.layers.dense(self.s, num_hidden, tf.nn.relu, kernel_initializer = a_w, name='a_hidden', trainable=trainable)
# tanh [-1,1]
mu = tf.layers.dense(hidden_layer, A_DIM, tf.nn.tanh, kernel_initializer = a_w, name='mu', trainable=trainable)
# softplus {0,inf)
sigma = tf.layers.dense(hidden_layer, A_DIM, tf.nn.softplus, kernel_initializer = a_w, name='sigma', trainable=trainable) + 1e-4
norm_dist = tf.distributions.Normal(loc=mu, scale=sigma)



hidden_layer = tf.layers.dense(self.s, num_hidden, tf.nn.relu, kernel_initializer = a_w, name='a_hidden', trainable=trainable)
logits = tf.layers.dense(hidden_layer, A_DIM, tf.nn.softmax, kernel_initializer = a_w, name='mu', trainable=trainable)
# tanh [-1,1]
mu = tf.layers.dense(hidden_layer, A_DIM, tf.nn.tanh, kernel_initializer = a_w, name='mu', trainable=trainable)
# softplus [0,inf)
sigma = tf.layers.dense(hidden_layer, A_DIM, tf.nn.softplus, kernel_initializer = a_w, name='sigma', trainable=trainable) + 1e-4
norm_dist = tf.distributions.Normal(loc=mu, scale=sigma)


#https://www.tensorflow.org/api_docs/python/tf/contrib/distributions/MultivariateNormalFullCovariance
import tensorflow_probability as tfp
tfd = tfp.distributions

# Initialize a single 3-variate Gaussian.
mu = [1., 2, 3]
cov = [[ 0.36,  0.12,  0.06],
       [ 0.12,  0.29, -0.13],
       [ 0.06, -0.13,  0.26]]
mvn = tfd.MultivariateNormalFullCovariance(
    loc=mu,
    covariance_matrix=cov)

mvn.mean().eval()
# ==> [1., 2, 3]

# Covariance agrees with covariance_matrix.
mvn.covariance().eval()
# ==> [[ 0.36,  0.12,  0.06],
#      [ 0.12,  0.29, -0.13],
#      [ 0.06, -0.13,  0.26]]

# Compute the pdf of an observation in `R^3` ; return a scalar.
mvn.prob([-1., 0, 1]).eval()  # shape: []

# Initialize a 2-batch of 3-variate Gaussians.
mu = [[1., 2, 3],
      [11, 22, 33]]              # shape: [2, 3]
covariance_matrix = ...  # shape: [2, 3, 3], symmetric, positive definite.
mvn = tfd.MultivariateNormalFullCovariance(
    loc=mu,
    covariance=covariance_matrix)

# Compute the pdf of two `R^3` observations; return a length-2 vector.
x = [[-0.9, 0, 0.1],
     [-10, 0, 9]]     # shape: [2, 3]
mvn.prob(x).eval()    # shape: [2]



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



tfd = tfp.distributions

# Initialize a single 2-variate Gaussian.
mvn = tfd.MultivariateNormalDiag(
    loc=[1., -1],
    scale_diag=[1, 2.])

mvn.mean().eval()
# ==> [1., -1]

mvn.stddev().eval()
# ==> [1., 2]

# Evaluate this on an observation in `R^2`, returning a scalar.
mvn.prob([-1., 0]).eval()  # shape: []

# Initialize a 3-batch, 2-variate scaled-identity Gaussian.
mvn = tfd.MultivariateNormalDiag(
    loc=[1., -1],
    scale_identity_multiplier=[1, 2., 3])

mvn.mean().eval()  # shape: [3, 2]
# ==> [[1., -1]
#      [1, -1],
#      [1, -1]]

mvn.stddev().eval()  # shape: [3, 2]
# ==> [[1., 1],
#      [2, 2],
#      [3, 3]]

# Evaluate this on an observation in `R^2`, returning a length-3 vector.
mvn.prob([-1., 0]).eval()  # shape: [3]

# Initialize a 2-batch of 3-variate Gaussians.
mvn = tfd.MultivariateNormalDiag(
    loc=[[1., 2, 3],
         [11, 22, 33]]           # shape: [2, 3]
    scale_diag=[[1., 2, 3],
                [0.5, 1, 1.5]])  # shape: [2, 3]

# Evaluate this on a two observations, each in `R^3`, returning a length-2
# vector.
x = [[-1., 0, 1],
     [-11, 0, 11.]]   # shape: [2, 3].
mvn.prob(x).eval()    # shape: [2]
"""
