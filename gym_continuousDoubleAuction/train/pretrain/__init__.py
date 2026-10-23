"""Where offline JEPA pretraining used to live.

The pretrainer moved with the `jepa` encoder into the `cda-jepa` package
(repository `ChuaCheowHuan/cda_jepa`): run it as `python -m cda_jepa.pretrain`,
with the same flags. The checkpoint format it writes stayed here, in
`train.model.encoders.pretrained`, so a training run and the probe load the
weights without importing the trainer, and weights written before the move load.
"""

#: What `python -m gym_continuousDoubleAuction.train.pretrain` prints.
MOVED = (
    "Offline JEPA pretraining moved to the cda-jepa package "
    "(pip install git+https://github.com/ChuaCheowHuan/cda_jepa). "
    "Run `python -m cda_jepa.pretrain` with the same flags."
)
