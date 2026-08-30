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
    # `PassiveEnvChecker` is a SINGLE-agent checker, and this is a
    # `MultiAgentEnv`: `reset` returns a dict keyed by agent id, which the
    # checker compares against one agent's Box and reports as out of space on
    # every construction. That is a category error rather than a finding, so
    # the checker is turned off here rather than worked around in the env.
    #
    # The env still carries the singular `observation_space` / `action_space`
    # the checker was reading - RLlib defines them as the space of a single
    # agent - because leaving them None is what made `gymnasium.make` raise
    # outright (doc/15 S2-12). Turning the checker off would have hidden that
    # rather than fixed it.
    disable_env_checker=True,
)
"""
register(
    id='continuousDoubleAuction-extrahard-v0',
    entry_point='gym_continuousDoubleAuction.envs:continuousDoubleAuctionExtraHardEnv',
)
"""
