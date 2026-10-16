"""One definition of "this module reported no return".

A module that played no episodes in an iteration reports `None` (a champion
adopted on restore has `return: None` in the league sidecar), and a run that
produced no usable number can report NaN. The league statistics treated the two
alike; three other places compared, rounded or formatted the raw value and
raised on `None` (issue #235). They all ask here instead.

Pure Python on purpose: `train.export` reads a sidecar and must not pay for
RLlib to do so.
"""
from __future__ import annotations

import math
from typing import Optional


def usable_return(value) -> Optional[float]:
    """`value` as a float, or None when it is missing, NaN or not a number."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def format_return(value, spec: str = ".6g") -> str:
    """`value` formatted with `spec`, or "n/a" when it is not a usable return."""
    number = usable_return(value)
    return "n/a" if number is None else format(number, spec)
