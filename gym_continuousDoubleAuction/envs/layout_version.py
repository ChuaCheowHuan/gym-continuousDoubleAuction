"""Which observation and action layout a checkpoint's weights belong to.

doc/15 S4-19: nothing recorded the layout an observation was laid out in, so a
change to it invalidated every existing checkpoint silently - the restore went
through and the first `env.step` died on a tensor shape, or worse did not die
and fed a network floats it had learned to read as something else. The stamp
below is written into `league_state.json` beside every checkpoint by
`train.save_checkpoint`, and `train.build_algo` compares it before restoring.

Two version numbers rather than one, because the observation and the action
Dict change for different reasons and a reader wants to know which moved.
The field and key lists travel too, so a mismatch names what differs.
"""
from __future__ import annotations

from gym_continuousDoubleAuction.envs.exchg.action_helper import (
    ACTION_KEYS,
    ACTION_LAYOUT_VERSION,
)
from gym_continuousDoubleAuction.envs.exchg.state_helper import (
    OBSERVATION_LAYOUT_VERSION,
    PRIVATE_FIELDS,
)

#: The key the stamp is stored under in `league_state.json`.
LAYOUT_KEY = "layout"


def layout_stamp() -> dict:
    """The current layout, as plain JSON-able data."""
    return {
        "observation_version": OBSERVATION_LAYOUT_VERSION,
        "action_version": ACTION_LAYOUT_VERSION,
        "private_fields": list(PRIVATE_FIELDS),
        "action_keys": list(ACTION_KEYS),
    }


def check_layout_stamp(sidecar, path: str) -> None:
    """Raise if a checkpoint's recorded layout is not the current one.

    Args:
        sidecar: the parsed `league_state.json`, or None when the checkpoint
            has none (the old single-directory layout). No sidecar means no
            claim, and the restore proceeds as it always did.
        path: the checkpoint directory, for the message.

    Raises:
        ValueError: naming both versions and the fields or keys that differ.
            A sidecar with no stamp at all was written before layout
            versioning existed, which is layout 1 by definition.
    """
    if sidecar is None:
        return
    stamp = sidecar.get(LAYOUT_KEY)
    current = layout_stamp()
    if stamp is None:
        stamp = {"observation_version": 1, "action_version": 1,
                 "private_fields": None, "action_keys": None}
    problems = []
    for axis in ("observation", "action"):
        theirs = stamp.get(f"{axis}_version")
        ours = current[f"{axis}_version"]
        if theirs != ours:
            problems.append(f"{axis} layout v{theirs} (checkpoint) != v{ours} (this code)")
    for listing in ("private_fields", "action_keys"):
        theirs, ours = stamp.get(listing), current[listing]
        if theirs is not None and list(theirs) != list(ours):
            missing = sorted(set(ours) - set(theirs))
            extra = sorted(set(theirs) - set(ours))
            problems.append(
                f"{listing} differ: checkpoint lacks {missing or 'nothing'}, "
                f"has extra {extra or 'nothing'}"
            )
    if problems:
        raise ValueError(
            f"Cannot restore {path}: it was trained against a different "
            f"observation/action layout.\n  " + "\n  ".join(problems) +
            "\nWeights trained on one layout do not fit another - the input "
            "and output widths changed, and even where they did not the "
            "floats mean something else. Start a fresh run (is_restore false, "
            "or a new log_base_dir). See doc/15 S4-19 and doc/05 section 1."
        )
