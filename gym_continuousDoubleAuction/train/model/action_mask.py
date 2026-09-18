"""Apply the observation's action mask to the policy's category logits.

doc/06 section 6. The env writes, into the last `category_n` entries of each
agent's private block, which of the action categories that agent can take on
the coming step (`Action_Helper.action_mask_for`): a modify or cancel needs a
resting order on that side, a market or limit order needs to pass the cash
check for the minimum size at the reference price. Those are the two dead
actions the activity metrics count - 27-30% of random agent-steps were
"unmatched" before this - and a policy given the choice can only learn to
avoid them slowly, because from its side a dead action and a pass are the same
event.

Masking removes the choice. `masked_logits` adds a large negative number to
the logit of every impossible category, so the categorical distribution puts
no mass on it: sampling never draws it, `log_prob` of the drawn action is
unchanged, and the entropy term counts only the live categories. It is the
standard construction (RLlib's own action-masking example does the same); the
constant is finite rather than `-inf` so a softmax over the row can never be
NaN even if every entry were masked, which the env prevents anyway by keeping
`pass` always possible.

Where the mask sits in the observation and where the category logits sit in
`ACTION_DIST_INPUTS` are both derived, not assumed: the former from the
private-field layout, the latter from the action Dict's component order and
each component's distribution width - `Discrete(n)` takes `n` logits, a
`Box` of `d` values takes `2d` (mean and log-std). The shipped Dict lists
`category` first, so the slice is `[0:9]`, and a test pins that.
"""
from __future__ import annotations

from typing import Optional, Tuple

import gymnasium as gym
import numpy as np

from gym_continuousDoubleAuction.envs.exchg.state_helper import (
    MASK_FIELDS,
    action_mask_offset,
    private_fields,
)
from gym_continuousDoubleAuction.train.model.encoders.obs_layout import ObsLayout

#: Added to a masked category's logit. exp(-1e9) underflows to exactly 0.
MASK_LOGIT = -1.0e9


def category_logit_slice(action_space: gym.spaces.Dict) -> slice:
    """Where `category`'s logits sit inside the flat `ACTION_DIST_INPUTS`.

    Components appear in the Dict's iteration order; a `Discrete(n)` component
    contributes `n` inputs and a `Box` component `2 * prod(shape)` (RLlib's
    `TorchDiagGaussian.required_input_dim`).
    """
    offset = 0
    for name, space in action_space.spaces.items():
        if isinstance(space, gym.spaces.Discrete):
            width = int(space.n)
        elif isinstance(space, gym.spaces.Box):
            width = 2 * int(np.prod(space.shape))
        else:
            raise TypeError(f"action component {name!r} has unsupported space {space!r}")
        if name == "category":
            return slice(offset, offset + width)
        offset += width
    raise KeyError("action space has no 'category' component")


def mask_slice(obs_space: gym.Space, book_mode: Optional[str] = None) -> Optional[slice]:
    """Where the mask sits inside the flat observation, or None if it has none.

    None for an observation whose private block is not the current layout
    (a hand-built test space, or a pre-mask env), in which case the module
    applies no mask.
    """
    try:
        layout = ObsLayout.from_obs_space(obs_space, book_mode=book_mode)
    except (TypeError, ValueError):
        return None
    if layout.private_dim != len(private_fields(layout.own_levels)):
        return None
    start = layout.book_flat_dim + action_mask_offset(layout.own_levels)
    return slice(start, start + len(MASK_FIELDS))


def slices_for(obs_space: gym.Space, action_space: gym.Space) -> Tuple[Optional[slice], slice]:
    """`(mask slice in obs, category slice in logits)`; the first may be None."""
    return mask_slice(obs_space), category_logit_slice(action_space)


def masked_logits(logits, obs, obs_mask: slice, cat: slice):
    """`logits` (a torch tensor) with `MASK_LOGIT` added where the mask is 0.

    Out of place: the encoder's output is left as it was, and the masked copy
    is what goes into `ACTION_DIST_INPUTS`.
    """
    mask = obs[..., obs_mask].to(logits.dtype)
    penalty = (1.0 - mask) * MASK_LOGIT
    out = logits.clone()
    out[..., cat] = out[..., cat] + penalty
    return out
