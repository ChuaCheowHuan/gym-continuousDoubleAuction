"""
#gym-foo/gym_foo/__init__.py should have:

register(
    id='foo-v0',
    entry_point='gym_foo.envs:FooEnv',
)
register(
    id='foo-extrahard-v0',
    entry_point='gym_foo.envs:FooExtraHardEnv',
)
"""

# from gym.envs.registration import register
from gymnasium.envs.registration import register


register(
    id='continuousDoubleAuction-v0',
    entry_point='gym_continuousDoubleAuction.envs:continuousDoubleAuctionEnv',
)
"""
register(
    id='continuousDoubleAuction-extrahard-v0',
    entry_point='gym_continuousDoubleAuction.envs:continuousDoubleAuctionExtraHardEnv',
)
"""
