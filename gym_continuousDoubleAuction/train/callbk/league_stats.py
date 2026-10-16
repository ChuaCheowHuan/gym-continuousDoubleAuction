"""What the league check reads out of one iteration's results (issue #253).

The champion check in `on_train_result` mixes three things: reading numbers out of the
result, deciding whether to promote, and changing the league. The first is pure and lives
here, so the rules for NaN returns, idle modules and the does-it-trade guard's input can be
tested without an algorithm.
"""

import math
from typing import Dict, List, NamedTuple, Optional, Sequence

import numpy as np

from gym_continuousDoubleAuction.train.callbk.activity import as_float
from gym_continuousDoubleAuction.train.returns import usable_return


class Returns(NamedTuple):
    """The modules' mean returns this iteration, split by whether they played."""

    valid: List[float]  # the returns that are numbers
    idle: List[str]  # modules that played no episodes (None or NaN), sorted


def split_returns(policy_returns: Dict[str, Optional[float]]) -> Returns:
    """Separate the returns that are numbers from the modules that played nothing.

    NaN, not just None: a module the mapping fn did not draw this iteration played no
    episodes, and RLlib reports its mean return as NaN. One of those poisons `np.mean`,
    so the threshold becomes NaN and `best_return > threshold` is False for every
    candidate - the champion trigger stops firing, silently and permanently (the GPU runs
    of 2026-08-15 died this way).
    """
    idle = sorted(
        module_id for module_id, value in policy_returns.items() if value is None or np.isnan(value)
    )
    valid = [v for v in policy_returns.values() if v is not None and not np.isnan(v)]
    return Returns(valid, idle)


class Candidate(NamedTuple):
    module_id: Optional[str]
    value: float


def best_trainable(
    policy_returns: Dict[str, Optional[float]], trainable_ids: Sequence[str]
) -> Candidate:
    """The trainable module with the highest usable return; `(None, -inf)` when none has one."""
    best, best_return = None, -float("inf")
    for module_id in trainable_ids:
        if module_id in policy_returns:
            value = usable_return(policy_returns[module_id])
            if value is not None and value > best_return:
                best_return, best = value, module_id
    return Candidate(best, best_return)


def candidate_trades(env_runner_results, module_id, metric) -> Optional[float]:
    """The module's mean trades per episode this iteration (`metric`'s entry), or None if absent."""
    by_module = env_runner_results.get(metric)
    if not isinstance(by_module, dict):
        return None
    value = as_float(by_module.get(module_id))
    if value is None or math.isnan(value):
        return None
    return value
