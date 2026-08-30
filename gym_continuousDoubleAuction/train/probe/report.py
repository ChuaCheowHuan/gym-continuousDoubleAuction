"""Running the (feature set x target) matrix and rendering it.

The unit of the report is a **row of feature sets** compared on **one target**,
because that is the only comparison that means anything: scores are not
comparable across targets (an R^2 on `mid_return` and a balanced accuracy on
`two_sided` are different quantities on different scales), and they are
comparable across feature sets only because every set is fit on identical rows,
with an identical split and an identical ridge grid.

`run` therefore builds each target's rows *once* and reuses them for every
feature set, rather than letting each set mask independently. Two feature sets
scored on different row subsets would differ by the subset as much as by the
encoding, and nothing in the output would say so. The episode number of each
retained row travels with them, so every feature set also gets the identical
train/validation/test split - see `probe.split_masks`.

A (target, horizon) that no feature set could score is dropped rather than
rendered as a row of dashes or, worse, a row of identical floor values. That
is a fact about the corpus - a target with one class or no variance in it - and
printing it beside real results invites reading it as a fact about the
encoders.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

import numpy as np

from gym_continuousDoubleAuction.train.probe import targets as targets_module
from gym_continuousDoubleAuction.train.probe.corpus import ProbeCorpus
from gym_continuousDoubleAuction.train.probe.probe import ProbeResult, fit_and_score

#: Two feature sets closer than this are reported as tied rather than ranked.
#: Scores this close are inside the harness's own run-to-run variation - a
#: different seed reorders them - and naming a winner there reads as a finding
#: that a re-run would not reproduce. It happens routinely at the floor, where
#: the validation split has sent every set to the same near-mean predictor.
TIE_MARGIN = 0.005


@dataclass(frozen=True)
class Row:
    """One target at one horizon, scored across every feature set."""

    target: str
    kind: str
    metric: str
    describe: str
    horizon: int
    n_rows: int
    #: feature set name -> result, or None where the split was too small.
    results: Dict[str, Optional[ProbeResult]]

    @property
    def best(self) -> Optional[str]:
        """The winning feature set, or None if nothing scored or nothing won.

        None on a tie as well as on an empty row: see `TIE_MARGIN`.
        """
        scored = {k: v for k, v in self.results.items() if v is not None}
        if not scored:
            return None
        ranked = sorted(scored, key=lambda k: scored[k].score, reverse=True)
        if len(ranked) > 1:
            margin = scored[ranked[0]].score - scored[ranked[1]].score
            if margin < TIE_MARGIN:
                return None
        return ranked[0]


def run(
    corpus: ProbeCorpus,
    features: Dict[str, np.ndarray],
    target_names: Sequence[str],
    horizons: Sequence[int],
) -> List[Row]:
    """Score every feature set on every (target, horizon) it is defined for.

    Args:
        corpus: The observation stream. Supplies the snapshots targets read and
            the episode boundaries they are masked by.
        features: Feature set name -> `(N, F)` matrix, all with `N == len(corpus)`.
        target_names: Names from `targets.TARGET_REGISTRY`.
        horizons: Steps ahead. A (target, horizon) pair below the target's
            `min_horizon` is skipped rather than raising - a horizon list is a
            sweep, and one target declining one horizon should not end it.

    Returns:
        One `Row` per scored (target, horizon), targets in the order given.

    Raises:
        ValueError: on an unknown target name, or a feature matrix whose row
            count does not match the corpus.
    """
    for name, matrix in features.items():
        if len(matrix) != len(corpus):
            raise ValueError(
                f"Feature set {name!r} has {len(matrix)} rows for a corpus of "
                f"{len(corpus)}. Every set must be aligned to the same "
                "observations or the comparison is between different data."
            )

    resolved = targets_module.resolve(target_names)
    rows: List[Row] = []

    for target in resolved:
        for horizon in horizons:
            if horizon < target.min_horizon:
                continue
            values, valid = targets_module.build(
                target, corpus.snapshots, corpus.layout,
                corpus.episode_index, horizon,
            )
            if not valid.any():
                continue

            # Built once, outside the feature loop - see the module docstring.
            y = values[valid]
            groups = corpus.episode_index[valid]
            results = {
                name: fit_and_score(matrix[valid], y, target.kind, groups=groups)
                for name, matrix in features.items()
            }
            if all(result is None for result in results.values()):
                continue
            rows.append(Row(
                target=target.name,
                kind=target.kind,
                metric="r2" if target.kind == "regression" else "balanced_accuracy",
                describe=target.describe,
                horizon=horizon,
                n_rows=int(valid.sum()),
                results=results,
            ))

    return rows


def render(rows: Sequence[Row], feature_names: Sequence[str]) -> str:
    """The report as a Markdown table, one line per (target, horizon)."""
    if not rows:
        return "No target could be scored on this corpus."

    header = ["target", "h", "metric", "rows"] + list(feature_names) + ["best"]
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join(["---"] * len(header)) + "|",
    ]
    for row in rows:
        cells = [
            row.target,
            str(row.horizon),
            row.metric,
            str(row.n_rows),
        ]
        for name in feature_names:
            result = row.results.get(name)
            cells.append("-" if result is None else f"{result.score:+.4f}")
        cells.append(row.best or "tie")
        lines.append("| " + " | ".join(cells) + " |")

    lines.append("")
    lines.append(_legend(rows))
    return "\n".join(lines)


def _legend(rows: Sequence[Row]) -> str:
    described = {row.target: row.describe for row in rows}
    lines = ["Targets:"]
    lines += [f"  {name}: {text}" for name, text in described.items()]
    lines += [
        "",
        "r2 is against the test split's own mean; 0 means no better than "
        "predicting the average.",
        "balanced_accuracy is the mean of the per-class recalls; 0.5 is chance.",
        "Every feature set is fit on identical rows with an identical split and "
        "ridge grid.",
        "A latent is a function of `raw`, so a latent below `raw` has "
        "reorganised nothing a linear readout can use.",
        f"`tie` means the top two are within {TIE_MARGIN} - inside this "
        "harness's own run-to-run variation.",
        "`-` in a cell means that set could not be scored at all, not that it "
        "scored zero.",
    ]
    return "\n".join(lines)
