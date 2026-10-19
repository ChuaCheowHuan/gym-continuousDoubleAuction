"""Which observation and action layout a checkpoint's weights belong to.

docs/29 S4-19: nothing recorded the layout an observation was laid out in, so a
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
from gym_continuousDoubleAuction.config_loader import constants
from gym_continuousDoubleAuction.envs.exchg.state_helper import (
    BOOK_MODE,
    K_ROWS,
    OBSERVATION_LAYOUT_VERSION,
    PRIVATE_FIELDS,
    check_book_mode,
)

#: The key the stamp is stored under in `league_state.json`.
LAYOUT_KEY = "layout"


def action_head_sizes() -> dict:
    """How wide each head of the action Dict is, from the config the space is built from.

    `max_own_orders` sets `order_slot`, `k_rows` sets `price`, and so on: none of them changes
    the observation width the rest of the stamp protects, but each changes a head of the
    network. `test_layout_version` holds this equal to a real env's action space, so the two
    cannot drift apart (docs/29 R-5, #175).
    """
    act = constants("action_space")
    return {
        "category": int(act["category_n"]),
        "order_slot": int(act["max_own_orders"]) + 1,
        "price": int(K_ROWS),
        "price_offset": int(act["price_offset_n"]),
        "size": 1,
    }


def layout_stamp(book_mode=None) -> dict:
    """The current layout, as plain JSON-able data.

    `book_mode` is the run's (docs/29 S3-15); None means the process default.
    It travels in the stamp because the two modes have different widths and
    meanings under the same version number.
    """
    return {
        "observation_version": OBSERVATION_LAYOUT_VERSION,
        "action_version": ACTION_LAYOUT_VERSION,
        "book_mode": check_book_mode(BOOK_MODE if book_mode is None else book_mode),
        "private_fields": list(PRIVATE_FIELDS),
        "action_keys": list(ACTION_KEYS),
        "action_sizes": action_head_sizes(),
    }


def check_layout_stamp(sidecar, path: str, book_mode=None) -> None:
    """Raise if a checkpoint's recorded layout is not the current one.

    Args:
        sidecar: the parsed `league_state.json`, or None when the checkpoint
            has none (the old single-directory layout). No sidecar means no
            claim, and the restore proceeds as it always did.
        path: the checkpoint directory, for the message.
        book_mode: the mode this run will build its env in, to compare with
            the checkpoint's. None skips that comparison - `train.evaluate`
            builds its env from the checkpoint's own config, so the two agree
            by construction.

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
        stamp = {
            "observation_version": 1,
            "action_version": 1,
            "private_fields": None,
            "action_keys": None,
        }
    problems = []
    recorded_sizes = stamp.get("action_sizes")
    if recorded_sizes is not None and recorded_sizes != current["action_sizes"]:
        differing = sorted(
            head
            for head in set(recorded_sizes) | set(current["action_sizes"])
            if recorded_sizes.get(head) != current["action_sizes"].get(head)
        )
        problems.append(
            "action_sizes differ: "
            + ", ".join(
                f"{head} is {recorded_sizes.get(head)} in the checkpoint and "
                f"{current['action_sizes'].get(head)} in this code"
                for head in differing
            )
        )
    for axis in ("observation", "action"):
        theirs = stamp.get(f"{axis}_version")
        ours = current[f"{axis}_version"]
        if theirs != ours:
            problems.append(f"{axis} layout v{theirs} (checkpoint) != v{ours} (this code)")
    theirs = stamp.get("book_mode")
    if book_mode is not None and theirs is not None and theirs != book_mode:
        problems.append(f"book_mode {theirs!r} (checkpoint) != {book_mode!r} (this run)")
    for listing in ("private_fields", "action_keys"):
        theirs, ours = stamp.get(listing), current[listing]
        if theirs is not None and list(theirs) != list(ours):
            missing = sorted(set(ours) - set(theirs))
            extra = sorted(set(theirs) - set(ours))
            if missing or extra:
                problems.append(
                    f"{listing} differ: checkpoint lacks {missing or 'nothing'}, "
                    f"has extra {extra or 'nothing'}"
                )
            else:
                # The same members in another order is still a mismatch (the
                # floats sit at other offsets), and "lacks nothing, has extra
                # nothing" would leave the reader nothing to act on.
                at = next(i for i, (a, b) in enumerate(zip(theirs, ours)) if a != b)
                problems.append(
                    f"{listing} differ in order, not membership: position {at} is "
                    f"{list(theirs)[at]!r} in the checkpoint and {list(ours)[at]!r} "
                    f"in this code"
                )
    if problems:
        raise ValueError(
            f"Cannot restore {path}: it was trained against a different "
            f"observation/action layout.\n  "
            + "\n  ".join(problems)
            + "\nWeights trained on one layout do not fit another - the input "
            "and output widths changed, and even where they did not the "
            "floats mean something else. Start a fresh run (is_restore false, "
            "or a new log_base_dir). See docs/29 S4-19 and docs/05 section 10."
        )
