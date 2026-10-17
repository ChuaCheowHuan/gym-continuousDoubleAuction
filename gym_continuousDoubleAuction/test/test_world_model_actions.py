"""The JEPA world model embeds every head of the action (issue #186).

`DISCRETE_ACTIONS` listed `category`, `price` and `price_offset`; `order_slot` (which of the
agent's own orders a modify or cancel targets) was added to the env's action later and never
here. The embedding only checked that its own names existed in the space, so an extra head was
ignored: "cancel my first order" and "cancel my third" embedded identically.
"""

import pytest
import torch

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.envs.exchg.action_helper import ACTION_KEYS
from gym_continuousDoubleAuction.train.model.encoders import jepa


@pytest.fixture(scope="module")
def action_space():
    env = continuousDoubleAuctionEnv({"num_of_agents": 2, "is_render": False, "max_step": 8})
    return env.get_action_space(env.agents[0])


def _actions(action_space, **overrides):
    sample = {
        name: torch.as_tensor(space.sample()).reshape(1, -1)
        for name, space in action_space.spaces.items()
    }
    for name, value in overrides.items():
        sample[name] = torch.tensor([[value]])
    return sample


class TestEveryHeadIsEmbedded:
    def test_the_embedded_heads_are_exactly_the_action_keys(self):
        assert set(jepa.DISCRETE_ACTIONS) | set(jepa.BOX_ACTIONS) == set(ACTION_KEYS), (
            "a head added to the action space must be added to the world model's embedding"
        )

    def test_two_actions_that_differ_only_in_the_slot_embed_differently(self, action_space):
        embed = jepa._ActionEmbed(action_space, 16)
        base = _actions(action_space, category=4, order_slot=1)
        other = _actions(action_space, category=4, order_slot=3)
        for name in base:  # identical in every other head
            if name != "order_slot":
                other[name] = base[name]

        assert not torch.allclose(embed(base), embed(other))

    def test_the_slot_table_is_as_wide_as_the_space(self, action_space):
        embed = jepa._ActionEmbed(action_space, 16)
        assert embed.discrete["order_slot"].num_embeddings == int(action_space["order_slot"].n)

    def test_a_space_missing_a_head_is_still_refused_by_name(self, action_space):
        from gymnasium import spaces

        trimmed = spaces.Dict({k: v for k, v in action_space.spaces.items() if k != "order_slot"})
        with pytest.raises(ValueError, match="order_slot"):
            jepa._ActionEmbed(trimmed, 16)
