"""Where Continual Backprop's Learner mixin used to live, kept for old checkpoints.

Continual Backprop moved out of this repository into the `cda-cbp` package
(repository `ChuaCheowHuan/cda_cbp`), an extension enabled with
`extensions_enabled: ["cbp"]` (docs/30, docs/25). Tuned Adam stayed here, in
`optim_learner`.

This module stays because a checkpoint pickles its composed Learner class with
each mixin referenced by module path: a run that used tuned Adam names
`cbp_learner.TunedAdamMixin`, and one that used CBP names
`cbp_learner.CBPLearnerMixin`. Both must keep resolving, or such a checkpoint
cannot be loaded (test_learner_class_compat.py). `CBPLearnerMixin` resolves to
the package's mixin, which reads the old `continual_backprop` settings stored
in the checkpoint, so the run resumes with CBP on; without the package it
raises, naming it.
"""

from gym_continuousDoubleAuction.train.model.optim_learner import TunedAdamMixin

# `CBPLearnerMixin` is served by `__getattr__` below, so it is not listed here:
# pyflakes checks that every `__all__` name is defined in the module.
__all__ = ["TunedAdamMixin"]

#: Printed when a checkpoint needs CBP and the package is not installed.
MISSING_PACKAGE = (
    "This checkpoint was trained with Continual Backprop, which is no longer part of "
    "gym-continuousDoubleAuction. Install the cda-cbp package "
    "(pip install git+https://github.com/ChuaCheowHuan/cda_cbp) to resume it."
)


def __getattr__(name):
    # PEP 562: resolved only when something asks for the name - unpickling an
    # old Learner class does - so importing this module never needs the package.
    if name == "CBPLearnerMixin":
        try:
            from cda_cbp.learner import CBPLearnerMixin
        except ImportError as exc:
            raise ImportError(MISSING_PACKAGE) from exc
        return CBPLearnerMixin
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
