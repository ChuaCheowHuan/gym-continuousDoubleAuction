"""
# folder structure:

gym-foo/
  README.md
  setup.py
  gym_foo/
    __init__.py
    envs/
      __init__.py
      foo_env.py
      foo_extrahard_env.py
"""

"""
# installation:
cd gym-continuousDoubleAuction
pip install -e .

# usage:
gym.make('gym_foo:foo-v0')
"""

"""
from setuptools import setup

setup(name='gym_foo',
      version='0.0.1',
      install_requires=['gym']  # And any other dependencies foo needs
)
"""
from setuptools import setup, find_packages

setup(
    name='gym_continuousDoubleAuction',
    version='0.0.1',
    packages=['gym_continuousDoubleAuction'],  # Only this package
    install_requires=[
        # 'gym',
        'gymnasium'
    ],  # And any other dependencies foo needs
    entry_points={
        'gym.envs': [
            'continuousDoubleAuction-v0 = gym_continuousDoubleAuction:YourEnvClass',
        ],
    },    
)
