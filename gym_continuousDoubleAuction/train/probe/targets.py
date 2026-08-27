"""What the probe is asked to predict.

Every target here is a **public microstructure quantity read out of a future
snapshot**. Nothing is a reward, a NAV, or a policy output, which is the whole
point: S1-1 pins `vf_loss` at its clip bound and S1-3 makes passivity dominant,
so any score computed downstream of the reward measures those defects rather
than the encoder. These targets are computable from the observation stream
alone, so they stay valid however the reward is eventually fixed.

Reading a snapshot
------------------
The layout is `State_Helper.set_agg_LOB`'s, via `ObsLayout`:

    [0:k]        norm_bid_price  = (M - P_bid) / M          >= 0
    [k:2k]       norm_bid_size   = sqrt(V_bid)              >= 0
    [2k:3k]      norm_ask_price  = -(|P_ask| - M) / M       <= 0
    [3k:4k]      norm_ask_size   = -sqrt(V_ask)             <= 0
    [4k]         log_mid         = log(M)
    [4k + 1]     log1p_spread_ticks, with 0.0 as the "no two-sided market"
                 sentinel - a resting book can never be locked or crossed, so
                 a real two-sided spread is at least log1p(1) = 0.693 and the
                 sentinel is unambiguous.

`log_mid` is why a price target is expressible at all. Midpoint normalisation
throws the price level away everywhere else in the snapshot, so without that
scalar a market at 10 and one at 100 would be indistinguishable and "did the
price move" would have no answer.

Choosing targets that discriminate
----------------------------------
A target that is nearly constant over `k` steps is predicted almost perfectly
by *any* feature set, including the raw observation, and so separates none of
them. The current book's spread is such a target; the *change* in spread is
not. So the levels here are differences wherever a level would be trivially
persistent, and `two_sided` - the one retained level - is kept precisely
because it is the regime indicator the others are conditional on.

Horizons
--------
Every target looks `horizon` steps ahead of the row it is attached to, and a
row whose `t + horizon` falls outside its own episode is dropped by
`horizon_mask`. That matters more than it looks: episodes draw an independent
random price anchor on reset, so a return read across a boundary is a jump
between unrelated price levels, and a probe trained on those rows is being
taught to predict a reset.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Tuple

import numpy as np

from gym_continuousDoubleAuction.train.model.encoders.obs_layout import ObsLayout

#: A target's scoring family. `regression` is scored by R^2, `binary` by
#: balanced accuracy - see `probe.score`.
KINDS = ("regression", "binary")

#: Builds one target. `(snapshots, layout, horizon) -> values (N,)`. Entries
#: whose `t + horizon` runs off the end are free to be garbage; `horizon_mask`
#: removes them before the probe ever sees them.
TargetBuilder = Callable[[np.ndarray, ObsLayout, int], np.ndarray]


@dataclass(frozen=True)
class Target:
    """One probe target: what it is, how it is scored, what it needs."""

    name: str
    kind: str
    #: One line, printed in the report. Say what it *is*, not how it is built.
    describe: str
    build: TargetBuilder
    #: Smallest horizon at which the definition means anything. `realized_vol`
    #: needs two future steps to have a dispersion at all.
    min_horizon: int = 1


#: `name` -> `Target`. Populated by `@register` at import time.
TARGET_REGISTRY: Dict[str, Target] = {}


def register(name: str, kind: str, describe: str, min_horizon: int = 1):
    """Register a target builder under a name the CLI can select."""
    if kind not in KINDS:
        raise ValueError(f"Unknown kind {kind!r}. Available: {', '.join(KINDS)}.")

    def decorate(build: TargetBuilder) -> TargetBuilder:
        if name in TARGET_REGISTRY:
            raise ValueError(f"Target {name!r} is already registered.")
        TARGET_REGISTRY[name] = Target(
            name=name, kind=kind, describe=describe, build=build,
            min_horizon=min_horizon,
        )
        return build

    return decorate


# --- Reading the snapshot ----------------------------------------------------

def log_mid(snapshots: np.ndarray, layout: ObsLayout) -> np.ndarray:
    """`log(M)` per row. Always finite: `M` is floored positive in the env."""
    return snapshots[:, layout.book_dim].astype(np.float64)


def spread(snapshots: np.ndarray, layout: ObsLayout) -> np.ndarray:
    """`log1p(spread in ticks)`, 0.0 where there is no two-sided market."""
    return snapshots[:, layout.book_dim + 1].astype(np.float64)


def depth_imbalance(snapshots: np.ndarray, layout: ObsLayout) -> np.ndarray:
    """`(bid depth - ask depth) / total depth` over all `k_rows` levels.

    Bid sizes are `+sqrt(V)` and ask sizes `-sqrt(V)`, so their sum is the
    signed numerator and their difference the total - no `abs` needed, and the
    sign convention is used rather than worked around.

    In `sqrt(V)` units, not shares. That is what the observation carries, and
    converting back would claim a precision the encoder never sees. Zero for an
    empty book, which is the neutral value rather than a sentinel.
    """
    k = layout.k_rows
    bid = snapshots[:, k:2 * k].astype(np.float64).sum(axis=1)
    ask = snapshots[:, 3 * k:4 * k].astype(np.float64).sum(axis=1)
    total = bid - ask
    return np.divide(bid + ask, total, out=np.zeros_like(total), where=total > 0)


def _ahead(values: np.ndarray, horizon: int) -> np.ndarray:
    """`values[t + horizon]`, with the overrun clamped to the last row.

    Clamping rather than padding with NaN keeps the array finite so a stray
    unmasked row is a wrong number rather than a NaN that silently poisons the
    ridge solve. `horizon_mask` is what actually removes those rows.
    """
    return values[np.minimum(np.arange(len(values)) + horizon, len(values) - 1)]


# --- The targets -------------------------------------------------------------

@register(
    "mid_return", "regression",
    "log change in the L1 midpoint over the horizon",
)
def _mid_return(snapshots, layout, horizon):
    values = log_mid(snapshots, layout)
    return _ahead(values, horizon) - values


@register(
    "mid_moves", "binary",
    "whether the L1 midpoint changes at all over the horizon",
)
def _mid_moves(snapshots, layout, horizon):
    values = log_mid(snapshots, layout)
    return (_ahead(values, horizon) != values).astype(np.float64)


@register(
    "spread_change", "regression",
    "change in log1p(spread in ticks) over the horizon",
)
def _spread_change(snapshots, layout, horizon):
    values = spread(snapshots, layout)
    return _ahead(values, horizon) - values


@register(
    "imbalance_change", "regression",
    "change in signed depth imbalance over the horizon",
)
def _imbalance_change(snapshots, layout, horizon):
    values = depth_imbalance(snapshots, layout)
    return _ahead(values, horizon) - values


@register(
    "two_sided", "binary",
    "whether a two-sided market exists at the horizon",
)
def _two_sided(snapshots, layout, horizon):
    # 0.0 is the env's sentinel for "no two-sided market" and a real spread is
    # at least log1p(1); there is no ambiguity to resolve here.
    return (_ahead(spread(snapshots, layout), horizon) > 0.0).astype(np.float64)


@register(
    "realized_vol", "regression",
    "dispersion of midpoint returns across the horizon",
    min_horizon=2,
)
def _realized_vol(snapshots, layout, horizon):
    """Standard deviation of the per-step log-midpoint changes in `(t, t+h]`.

    Built by walking the horizon rather than with a stride trick, because the
    row-clamping in `_ahead` has to apply to every intermediate step too and a
    windowed view would read across the end of the array.
    """
    values = log_mid(snapshots, layout)
    steps = np.stack([
        _ahead(values, i + 1) - _ahead(values, i) for i in range(horizon)
    ])
    return steps.std(axis=0)


# --- Assembly ----------------------------------------------------------------

def horizon_mask(episode_index: np.ndarray, horizon: int) -> np.ndarray:
    """`(N,)` bool: rows whose `t + horizon` is still inside the same episode.

    A row is valid when the row `horizon` further on exists *and* carries the
    same episode number. The episode check is what stops a return being read
    across a reset, where the price anchor is redrawn at random.
    """
    n = len(episode_index)
    valid = np.zeros(n, dtype=bool)
    if horizon < n:
        valid[: n - horizon] = (
            episode_index[: n - horizon] == episode_index[horizon:]
        )
    return valid


def selectable_targets() -> List[str]:
    """Every target name the CLI may select, sorted."""
    return sorted(TARGET_REGISTRY)


def resolve(names) -> List[Target]:
    """Look target names up, raising on an unknown one.

    Raises:
        ValueError: if a name is not registered.
    """
    unknown = sorted(set(names) - set(TARGET_REGISTRY))
    if unknown:
        raise ValueError(
            f"Unknown probe target(s) {unknown}. Available: "
            f"{', '.join(selectable_targets())}."
        )
    return [TARGET_REGISTRY[name] for name in names]


def build(
    target: Target,
    snapshots: np.ndarray,
    layout: ObsLayout,
    episode_index: np.ndarray,
    horizon: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """One target's values and the rows on which they are defined.

    Returns:
        `(values, valid)`, both `(N,)`. Read `values[valid]`; the rest are
        placeholders, not data.

    Raises:
        ValueError: if `horizon` is below the target's `min_horizon`, which
            would silently produce a degenerate column - `realized_vol` at
            horizon 1 is the standard deviation of a single number, i.e. zero
            for every row, and an R^2 of exactly 0 for every feature set.
    """
    if horizon < target.min_horizon:
        raise ValueError(
            f"Target {target.name!r} needs horizon >= {target.min_horizon}; "
            f"got {horizon}."
        )
    values = np.asarray(target.build(snapshots, layout, horizon), dtype=np.float64)
    valid = horizon_mask(episode_index, horizon) & np.isfinite(values)
    return values, valid
