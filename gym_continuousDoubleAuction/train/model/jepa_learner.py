"""Where the JEPA encoder's module and Learner used to live, kept for old checkpoints.

The `jepa` encoder moved out of this repository into the `cda-jepa` package
(repository `ChuaCheowHuan/cda_jepa`), which gym-CDA finds through the
`gym_cda.encoders` entry point; a run selects it with `encoder_type: "jepa"` and
`extensions_enabled: ["jepa"]` (docs/30).

This module stays because a checkpoint pickles its module and Learner classes by
module path: a run that used `jepa` names `jepa_learner.JEPARLModule` and
`jepa_learner.CDAJEPALearner` (or a composed class whose base is the latter).
Both must keep resolving, or such a checkpoint cannot be loaded
(test_learner_class_compat.py). They resolve to the package's classes; without
the package this raises, naming it.
"""

#: Printed when a checkpoint needs the JEPA classes and the package is not installed.
MISSING_PACKAGE = (
    "This checkpoint was trained with the jepa encoder, which is no longer part of "
    "gym-continuousDoubleAuction. Install the cda-jepa package "
    "(pip install git+https://github.com/ChuaCheowHuan/cda_jepa) to resume it."
)

#: The names old checkpoints reference, all served by `cda_jepa.learner`.
_MOVED = frozenset(
    {
        "CDAJEPALearner",
        "JEPARLModule",
        "JEPA_AUX_LOSS_KEY",
        "JEPA_LATENT_STD_KEY",
        "JEPA_OFFDIAG_COV_KEY",
        "JEPA_PREDICT_LOSS_KEY",
        "JEPA_WORLD_LOSS_KEY",
    }
)


def __getattr__(name):
    # PEP 562: resolved only when something asks for the name - unpickling an
    # old checkpoint does - so importing this module never needs the package.
    if name in _MOVED:
        try:
            from cda_jepa import learner
        except ImportError as exc:
            raise ImportError(MISSING_PACKAGE) from exc
        return getattr(learner, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
