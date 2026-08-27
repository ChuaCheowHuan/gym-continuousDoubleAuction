"""The probe itself: a ridge-regularised linear readout, fit and scored.

Why linear, and why that is the whole argument
----------------------------------------------
An encoder's latent is a *deterministic function of the observation it was
computed from*. So a probe with enough capacity scores identically on the
latent and on the raw observation - it would just re-derive the encoder - and
the comparison would measure the probe, not the encoder.

A **linear** probe cannot do that. It can only read what the encoder has
already made linearly separable. So "the latent beats the raw observation under
a linear readout" is exactly the claim that the encoder has reorganised the
information rather than merely preserved it, which is what representation
quality means. Raising the probe's capacity would not make the result stronger;
it would make it vacuous.

Why ridge, closed-form
----------------------
`w = (X'X + lambda I)^-1 X'y` is deterministic, has one hyperparameter, needs
no optimiser, no learning rate and no epoch count, and runs in milliseconds at
this scale. Every one of those is a knob that would otherwise have to be tuned
per feature set - and tuning per feature set is how a comparison quietly starts
measuring the tuning. `lambda` is chosen on a validation split from a fixed
grid, identically for every feature set and every target.

The three splits
----------------
Train, validation (picks `lambda`), test (scored) - **never shuffled**. Rows
are consecutive book states: `obs[t]` and `obs[t+1]` share three of their four
snapshots. A shuffled split puts near-duplicates of a test row in the training
set, and the reported score is then a memorisation score. This is the single
easiest way to get a spectacular and meaningless number out of this harness.

Where the corpus has enough episodes the split is made **on episode
boundaries** rather than on row counts, which is strictly stronger. It removes
the adjacent-row leak at the seams entirely, and it gives the test split its
own random price anchors - each episode draws one on reset - so the score
measures generalisation to an unseen market rather than to the tail of a
market already trained on. Below `MIN_GROUPS_TO_SPLIT_BY_GROUP` episodes there
are not enough anchors to go round and it falls back to contiguous rows, which
still bars shuffling but cannot promise the anchor separation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

import numpy as np

#: `lambda` grid, searched on the validation split. It has to span "essentially
#: unregularised" all the way to "almost the mean predictor", and the top end
#: is the one that matters here: `raw` is 168 standardised features and a short
#: corpus gives a few hundred training rows, where an under-regularised fit
#: scores an R^2 of -125 and the report ends up ranking overfitting rather than
#: representation. With the grid reaching this far the validation split simply
#: declines those fits and the score falls back toward 0, which is the honest
#: answer for "these features carry nothing usable at this sample size".
RIDGE_ALPHAS = (
    1e-4, 1e-3, 1e-2, 1e-1, 1.0, 10.0, 100.0,
    1e3, 1e4, 1e5, 1e6, 1e7,
)

#: Fractions of the corpus used for fitting and for choosing `lambda`. The
#: remainder is the test split.
TRAIN_FRACTION = 0.6
VALIDATION_FRACTION = 0.2

#: Distinct episodes needed before the split is made on episode boundaries.
#: Three is the minimum that can give all three splits an episode of its own.
MIN_GROUPS_TO_SPLIT_BY_GROUP = 3


@dataclass(frozen=True)
class ProbeResult:
    """One (feature set, target) cell of the report."""

    score: float
    #: What `score` means: `r2` for regression, `balanced_accuracy` for binary.
    metric: str
    #: Chosen from `RIDGE_ALPHAS` on the validation split.
    alpha: float
    n_train: int
    n_test: int
    n_features: int


def _standardise(
    train: np.ndarray, *others: np.ndarray
) -> Tuple[np.ndarray, ...]:
    """Zero-mean, unit-variance every column, using the *training* statistics.

    Fitting the scaler on the whole corpus would leak test-split statistics
    into training. Constant columns get scale 1 rather than 0 - a dead feature
    should contribute nothing, not an infinity.
    """
    mean = train.mean(axis=0, keepdims=True)
    scale = train.std(axis=0, keepdims=True)
    scale = np.where(scale > 1e-12, scale, 1.0)
    return tuple((block - mean) / scale for block in (train, *others))


def _fit(x: np.ndarray, y: np.ndarray, alpha: float) -> np.ndarray:
    """Ridge weights for a bias-augmented design matrix.

    The bias column is appended after standardisation and is deliberately left
    *out* of the penalty: shrinking the intercept toward zero would bias every
    prediction toward the origin rather than toward the target's mean, which on
    a target like `two_sided` - almost always 1 - is a large and entirely
    artificial error.
    """
    design = np.hstack([x, np.ones((len(x), 1))])
    penalty = alpha * np.eye(design.shape[1])
    penalty[-1, -1] = 0.0
    gram = design.T @ design + penalty
    return np.linalg.solve(gram, design.T @ y)


def _predict(x: np.ndarray, weights: np.ndarray) -> np.ndarray:
    return np.hstack([x, np.ones((len(x), 1))]) @ weights


def r2(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Coefficient of determination against the *test split's own* mean.

    Returns 0.0 for a constant target: there is no variance to explain, so no
    feature set can be credited with explaining it. The alternative convention
    (1.0, or NaN) would either flatter every feature set equally or poison the
    report's arithmetic.
    """
    variance = float(((y_true - y_true.mean()) ** 2).sum())
    if variance <= 0.0:
        return 0.0
    residual = float(((y_true - y_pred) ** 2).sum())
    return 1.0 - residual / variance


def balanced_accuracy(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Mean of the per-class recalls, thresholding the readout at 0.5.

    Balanced rather than plain accuracy because these targets are lopsided -
    `two_sided` is true in almost every step of a healthy market, so a
    constant-true predictor scores ~0.99 accuracy and 0.5 balanced accuracy.
    Only the second number distinguishes a feature set that knows something.

    Returns 0.5 - the chance level - when the test split holds only one class,
    since no ranking of it can be demonstrated.
    """
    positive = y_true > 0.5
    negative = ~positive
    if not positive.any() or not negative.any():
        return 0.5
    predicted = y_pred > 0.5
    return 0.5 * (
        float(predicted[positive].mean()) + float((~predicted[negative]).mean())
    )


def split_indices(
    n: int,
    train_fraction: float = TRAIN_FRACTION,
    validation_fraction: float = VALIDATION_FRACTION,
) -> Tuple[slice, slice, slice]:
    """Contiguous train / validation / test slices over `n` rows in order."""
    n_train = int(n * train_fraction)
    n_validation = int(n * validation_fraction)
    return (
        slice(0, n_train),
        slice(n_train, n_train + n_validation),
        slice(n_train + n_validation, n),
    )


def split_masks(
    groups: Optional[np.ndarray],
    n: int,
    train_fraction: float = TRAIN_FRACTION,
    validation_fraction: float = VALIDATION_FRACTION,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Boolean train / validation / test masks over `n` rows.

    Splits on group (episode) boundaries when `groups` names at least
    `MIN_GROUPS_TO_SPLIT_BY_GROUP` of them, and on contiguous row counts
    otherwise. See the module docstring for why the group split is preferred
    and why neither variant shuffles.

    Groups are assigned to splits in order of first appearance, so the split is
    deterministic and the test split is always the *latest* episodes - the same
    direction as the contiguous fallback.
    """
    masks = []
    if groups is not None:
        # `np.unique` sorts; first-appearance order is what keeps the test
        # split at the end of the corpus rather than at the highest episode id.
        _, first = np.unique(groups, return_index=True)
        ordered = groups[np.sort(first)]
        spans = _group_spans(ordered, train_fraction, validation_fraction)
        if spans is not None:
            masks = [np.isin(groups, span) for span in spans]

    if not masks:
        masks = []
        for part in split_indices(n, train_fraction, validation_fraction):
            mask = np.zeros(n, dtype=bool)
            mask[part] = True
            masks.append(mask)

    return tuple(masks)


def _group_spans(ordered, train_fraction, validation_fraction):
    """Which groups go to train / validation / test, or None to fall back.

    `int(g * fraction)` alone starves a split at small group counts - at three
    episodes it allocates 1 / 0 / 2 and the validation split is empty, so the
    group split would silently never engage at exactly the sizes a quick run
    uses. Each of train and validation therefore takes at least one group, with
    test keeping the remainder, and the whole thing declines only when there
    are genuinely too few groups to go round.
    """
    total = len(ordered)
    if total < MIN_GROUPS_TO_SPLIT_BY_GROUP:
        return None

    n_train = max(1, int(total * train_fraction))
    n_validation = max(1, int(total * validation_fraction))
    if n_train + n_validation >= total:
        # Leave test at least one group; give back from train first, since it
        # is the larger share.
        n_train = total - n_validation - 1
    if n_train < 1:
        return None

    return (
        ordered[:n_train],
        ordered[n_train:n_train + n_validation],
        ordered[n_train + n_validation:],
    )


def is_degenerate(values: np.ndarray, kind: str) -> bool:
    """Whether a target column is unscoreable rather than merely hard.

    A regression target with no variance and a binary target with one class
    both admit a perfect constant predictor, so every feature set ties at the
    metric's floor and the row says nothing about any of them. Reporting that
    as a number - 0.0, or a balanced accuracy of exactly 0.5 in every column -
    reads like a finding about the encoders. It is a finding about the corpus.
    """
    if kind == "binary":
        positive = values > 0.5
        return bool(positive.all() or (~positive).all())
    return bool(np.ptp(values) <= 0.0)


def fit_and_score(
    features: np.ndarray,
    values: np.ndarray,
    kind: str,
    groups: Optional[np.ndarray] = None,
    alphas: Sequence[float] = RIDGE_ALPHAS,
    train_fraction: float = TRAIN_FRACTION,
    validation_fraction: float = VALIDATION_FRACTION,
) -> Optional[ProbeResult]:
    """Fit a linear readout of `values` from `features` and score it held out.

    Args:
        features: `(N, F)`. Already restricted to rows where the target is
            defined - this function does no masking of its own.
        values: `(N,)` target values, in the same row order.
        kind: `regression` or `binary`, deciding the metric.
        groups: `(N,)` episode number per row. Given, and with enough distinct
            episodes, the split is made on episode boundaries; None falls back
            to contiguous rows. See `split_masks`.
        alphas: Ridge grid, searched on the validation split.
        train_fraction: Share used to fit.
        validation_fraction: Share used to choose `alpha`.

    Returns:
        A `ProbeResult`, or None when the cell cannot be scored at all - too
        few rows to fill three splits, or a target that is degenerate on any of
        them. None rather than a number, because "unscoreable" and "the
        features say nothing" are different findings and a report that renders
        them identically hides the first.
    """
    n = len(values)
    train, validation, test = split_masks(
        groups, n, train_fraction, validation_fraction
    )
    if min(train.sum(), validation.sum(), test.sum()) < 1:
        return None
    # All three, not just train and test. A degenerate *validation* split scores
    # every alpha identically - `r2` returns 0.0 for a constant target and
    # `balanced_accuracy` 0.5 for a single-class one - so the argmax falls on
    # whichever alpha the grid happens to list first, and the test score then
    # reports an unregularised fit that nothing selected. Refusing the cell
    # keeps the harness's guarantee uniform: a number it prints always had its
    # regularisation chosen on data.
    if any(is_degenerate(values[part], kind)
           for part in (train, validation, test)):
        return None

    x_train, x_validation, x_test = _standardise(
        features[train], features[validation], features[test]
    )
    y_train, y_validation, y_test = values[train], values[validation], values[test]

    metric = r2 if kind == "regression" else balanced_accuracy

    best_alpha, best_validation = alphas[0], -np.inf
    for alpha in alphas:
        weights = _fit(x_train, y_train, alpha)
        candidate = metric(y_validation, _predict(x_validation, weights))
        if candidate > best_validation:
            best_alpha, best_validation = alpha, candidate

    weights = _fit(x_train, y_train, best_alpha)
    return ProbeResult(
        score=float(metric(y_test, _predict(x_test, weights))),
        metric="r2" if kind == "regression" else "balanced_accuracy",
        alpha=float(best_alpha),
        n_train=int(train.sum()),
        n_test=int(test.sum()),
        n_features=int(features.shape[1]),
    )
