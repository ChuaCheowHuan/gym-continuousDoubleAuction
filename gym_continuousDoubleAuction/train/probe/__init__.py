"""Reward-free scoring of what an observation encoder has learned to represent.

Why this exists
---------------
[10](../../../doc/10_testing.md) §7 records the gap plainly: *"No encoder is
tested for whether it learns... Nothing runs long enough to say whether the
transformer or the LSTM beats the MLP, which is the question the `encoder`
group exists to answer."*

The obvious way to answer it - train each architecture and compare returns -
cannot work yet. S1-1 pins `vf_loss` at its clip bound, so PPO is REINFORCE
with a batch baseline and `vf_explained_var` is ~9e-05. S1-3 makes passivity
both a Nash equilibrium and the joint optimum. An architecture comparison run
through that reward measures the reward's defects, and a better encoder scores
as a better do-nothing agent.

This harness answers a narrower question that does not go through the reward at
all: **how much microstructure does the latent make linearly available?** Freeze
an encoder, fit a ridge readout from its latents to a public quantity a few
steps in the future - the midpoint return, the spread change, the depth
imbalance - and score it held out. No policy, no reward, no value function.

What the numbers mean
---------------------
Read a row, never a cell. Three feature sets are scored on identical rows:

  raw                the observation itself, the floor
  <encoder>          that architecture untrained, i.e. its inductive bias
  <encoder> @ckpt    the same architecture with trained weights

Every latent is a deterministic function of `raw`, so under a *linear* readout
a latent can only beat `raw` by having reorganised the information. That is the
whole argument, and it is why the probe is linear rather than as expressive as
possible - see `probe`.

Layout
------
  corpus    the observation stream, from random-agent rollouts or from
            `episode_record`'s Parquet
  targets   the public microstructure quantities, and the episode-boundary
            masking that keeps a return from being read across a reset
  features  raw observations, and frozen latents from a built or restored module
  probe     the ridge readout, its splits and its metrics
  rank      effective rank of a feature set, the one plasticity correlate that
            only means something on a corpus that holds still
  report    the (feature set x target) matrix and its rendering

Run it
------
    python -m gym_continuousDoubleAuction.train.probe
    python -m gym_continuousDoubleAuction.train.probe --encoders mlp transformer
    python -m gym_continuousDoubleAuction.train.probe --checkpoint <iter_dir>

What it does not do
-------------------
It says nothing about whether an encoder makes a better *trader*. A latent that
linearly carries the next midpoint move is evidence that the architecture
represents the market, not that PPO can exploit it. That second question needs
S1-1 and S1-3 fixed first, and this harness is deliberately independent of both
so its answer stays valid when they are.
"""
from gym_continuousDoubleAuction.train.probe.corpus import (  # noqa: F401
    ProbeCorpus,
    from_parquet,
    from_rollouts,
)
from gym_continuousDoubleAuction.train.probe.features import (  # noqa: F401
    RAW_FEATURES,
    build_module,
    latents,
    load_module,
    raw,
)
from gym_continuousDoubleAuction.train.probe.rank import (  # noqa: F401
    RankRow,
    effective_rank,
    rank_table,
)
from gym_continuousDoubleAuction.train.probe.probe import (  # noqa: F401
    ProbeResult,
    balanced_accuracy,
    fit_and_score,
    r2,
)
from gym_continuousDoubleAuction.train.probe.report import (  # noqa: F401
    Row,
    render,
    run,
)
from gym_continuousDoubleAuction.train.probe.targets import (  # noqa: F401
    TARGET_REGISTRY,
    Target,
    horizon_mask,
    selectable_targets,
)
