"""Effective rank of a feature set, measured on the corpus.

What this is for
----------------
Effective rank is one of the three correlates of loss of plasticity both
continual-backprop papers track (Nature Methods; arXiv Appendix G): as a
network loses the ability to keep learning, its units become redundant and the
rank of its representation falls, often while no individual unit is dead or
saturated. That last part is why it is worth measuring at all - the unit-wise
metrics miss it.

Why it lives **here** and not on the Learner
--------------------------------------------
Because the answer depends entirely on which observations you measure it over,
and only this harness holds that fixed.

`CBPLearnerMixin` also reports a rank, computed on whatever minibatch training
happened to produce. In a supervised setting that distinction would not matter:
the dataset is fixed, so a falling rank is the network. In *this* setting the
policy shapes its own input distribution, and under S1-3 the reward makes
passivity the joint optimum - so an agent converging on doing nothing visits an
ever narrower set of book states, and the rank of its activations falls for
reasons that have nothing to do with the network.

That is not a hypothetical. Measured on this repo (doc/16 §16.16), over ~18,000
optimiser steps:

    rank on the training minibatch      97.1 -> 73.2      -24.6%
    rank on a fixed corpus              +2.5% to -1.9%, every layer

The first reads as a textbook plasticity collapse. The second says the network's
representational capacity did not move. The difference is the input
distribution, and the first number is the one that would have been believed.

So the rank that means anything is the one this harness computes: the corpus is
collected once, from random-agent rollouts or from a Parquet record, and does
not change while the encoder does. Comparing two checkpoints' ranks here is
comparing two networks. Comparing `cbp_batch_effective_rank` across a run is
comparing two networks *and* two input distributions at the same time.

What a number means
-------------------
Read it against the feature set's width, which is what `rank_table` reports
alongside it. A 256-unit latent with an effective rank of 100 is using about
40% of the directions available to it; the same latent at 20 has collapsed.
Absolute values are not comparable across widths, and a latent's rank is
bounded by `min(rows, width)` - so a corpus shorter than the latent is wide
measures the corpus, not the encoder.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Sequence

import numpy as np

#: Fraction of the total singular-value mass the retained directions must
#: carry. From the Nature paper's Methods, which defines the stable rank of a
#: matrix as the smallest `k` whose top-`k` singular values sum to more than
#: 99% of the total.
DEFAULT_THRESHOLD = 0.99

#: Below this many rows the measurement is reported but flagged: rank is
#: bounded by `min(rows, width)`, so a short corpus caps every feature set at
#: the same number and the comparison silently becomes one about the corpus.
MIN_ROWS_PER_WIDTH = 2.0


def effective_rank(matrix: np.ndarray, threshold: float = DEFAULT_THRESHOLD) -> int:
    """Smallest number of singular values carrying `threshold` of the total.

    The same definition `cbp.effective_rank` implements in torch, on numpy
    here because that is what this harness works in. Two array libraries, one
    definition, and nothing but
    `test_probe.py::TestEffectiveRank.test_it_agrees_with_the_torch_definition`
    keeping them the same measurement.

    Returns 0 for an empty matrix and for one whose singular values are all
    zero, both of which mean "no directions at all" rather than "one".

    **The one place the two deliberately differ** is a matrix with fewer than
    two rows. Here that is 0, because the number goes into a report column
    where it is read as a rank; `cbp.effective_rank` returns NaN, because that
    one goes into a metric series where 0 would be read as total collapse. The
    agreement test pins both answers so the divergence stays deliberate.
    """
    values = np.asarray(matrix, dtype=np.float64)
    if values.ndim > 2:
        values = values.reshape(-1, values.shape[-1])
    if values.size == 0 or values.shape[0] < 2:
        return 0

    singular = np.linalg.svd(values, compute_uv=False)
    total = singular.sum()
    if total <= 0:
        return 0
    return int((np.cumsum(singular) / total < threshold).sum() + 1)


@dataclass(frozen=True)
class RankRow:
    """One feature set's effective rank, and what to read it against."""

    name: str
    rank: int
    width: int
    rows: int

    @property
    def fraction(self) -> float:
        """Rank as a fraction of the directions the feature set has."""
        return self.rank / self.width if self.width else float("nan")

    @property
    def row_limited(self) -> bool:
        """Whether the corpus, not the encoder, is what bounds this."""
        return self.rows < MIN_ROWS_PER_WIDTH * self.width


def rank_table(
    features: Mapping[str, np.ndarray],
    threshold: float = DEFAULT_THRESHOLD,
) -> Dict[str, RankRow]:
    """Effective rank of every feature set, in the order given."""
    return {
        name: RankRow(
            name=name,
            rank=effective_rank(matrix, threshold),
            width=int(matrix.shape[-1]) if matrix.ndim >= 2 else 0,
            rows=int(matrix.shape[0]),
        )
        for name, matrix in features.items()
    }


def render(table: Mapping[str, RankRow], feature_names: Sequence[str]) -> str:
    """The rank table, as text for the report.

    Deliberately a table of its own rather than a column on the score matrix:
    rank is a property of a feature set alone, while every row of that matrix
    is a (feature set, target) pair. Bolting it on would repeat one number
    across every target and invite reading it as a per-target result.
    """
    if not table:
        return ""

    # Against the header too, not just the names: "feature set" is wider
    # than a short encoder name and the columns skew if it overflows.
    width = max(len("feature set"), *(len(n) for n in feature_names)) + 2
    lines = [
        "Effective rank of each feature set, on this corpus "
        f"({DEFAULT_THRESHOLD:.0%} of singular mass)",
        f"{'feature set':<{width}}{'rank':>7}{'width':>8}{'used':>8}",
    ]
    flagged = False
    for name in feature_names:
        row = table.get(name)
        if row is None:
            continue
        mark = " *" if row.row_limited else ""
        flagged = flagged or row.row_limited
        # `used` is 8 wide to match its header; the `*` hangs off the end of
        # the column rather than inside it, so a flagged row still lines up.
        lines.append(
            f"{name:<{width}}{row.rank:>7}{row.width:>8}"
            f"{row.fraction:>8.0%}{mark}"
        )

    if flagged:
        lines += [
            "",
            "  * bounded by the corpus, not the encoder: rank cannot exceed "
            "min(rows, width),",
            "    so this set needs a longer corpus before its number says "
            "anything about it.",
        ]
    lines += [
        "",
        "  Measured on a corpus that does not change while the encoder does, "
        "which is what",
        "  makes it comparable across checkpoints. The Learner's own "
        "`cbp_batch_effective_rank`",
        "  is computed on the training minibatch and moves with the policy's "
        "input distribution",
        "  as well as with the network - see doc/23 and doc/16 §16.16.",
    ]
    return "\n".join(lines)
