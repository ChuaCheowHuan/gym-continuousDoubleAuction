"""The observation stream a probe is scored on.

A probe needs `(observation, future)` pairs and nothing else - no rewards, no
actions, no policy. This module produces them from either of the two places
this repository already has observations:

  rollouts   Step the real env with uniformly-random agents, exactly as
             `CDA_rand` does, and keep the observation stream. Self-contained:
             it needs no prior training run, so a probe can be scored on a
             fresh clone.
  Parquet    Read what `episode_record` wrote during a real training run. The
             `obs` column is already there, one row per (episode, step, agent).

The two answer different questions and are not interchangeable. A book made by
uniformly-random agents does not look like a book made by a trained league -
different spreads, different depth, different arrival intensity - so an encoder
scored on random-agent data is being asked how well it represents a market it
will never see. Rollouts are the *default* because they always work; Parquet is
the one to use once a run exists.

The shared-observation subtlety
-------------------------------
S1-2: every agent receives the byte-identical public book vector. For rollouts
that means one agent's stream is the whole story, and the other N-1 are exact
duplicates. For Parquet it means the file has `num_agents` copies of every
observation, and stacking it naively inflates the apparent corpus size by the
agent count while adding no information - the probe's held-out split would then
be leaking, because a row's duplicates land on both sides of it. So the Parquet
reader deduplicates on `(episode_id, step)` and the rollout reader keeps one
agent.

Episode boundaries
------------------
A target at `t+k` read across an episode boundary is the next episode's book,
which has an unrelated random price anchor. `episode_index` marks which episode
each row belongs to so `targets.horizon_mask` can drop those rows rather than
teaching the probe to predict a reset.
"""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass
from typing import List, Optional, Sequence

import numpy as np

from gym_continuousDoubleAuction.config_loader import cli_default
from gym_continuousDoubleAuction.logging_setup import get_logger
from gym_continuousDoubleAuction.train.model.encoders.obs_layout import ObsLayout

logger = get_logger(__name__)


def _cli(key):
    """A default for the probe CLI, from `config/cli_defaults.json`."""
    return cli_default("cda_probe", key)


@dataclass(frozen=True)
class ProbeCorpus:
    """An observation stream, plus which episode each row came from."""

    #: `(N, layout.flat_dim)` float32. Row `i` is the observation after `i`
    #: steps of its episode, oldest first, episodes concatenated.
    obs: np.ndarray

    #: `(N,)` int32. Rows sharing a value are one episode, in order.
    episode_index: np.ndarray

    #: How to read a row of `obs` as a (time, level, field) grid.
    layout: ObsLayout

    def __post_init__(self):
        if self.obs.ndim != 2:
            raise ValueError(f"obs must be 2-D (N, flat_dim); got {self.obs.shape}.")
        if self.obs.shape[1] != self.layout.flat_dim:
            raise ValueError(
                f"obs is {self.obs.shape[1]} floats wide but the layout says "
                f"{self.layout.flat_dim}. The corpus and the encoder would "
                "disagree about what a row is."
            )
        if len(self.episode_index) != len(self.obs):
            raise ValueError(
                f"episode_index has {len(self.episode_index)} entries for "
                f"{len(self.obs)} observations."
            )

    def __len__(self) -> int:
        return len(self.obs)

    @property
    def num_episodes(self) -> int:
        return len(np.unique(self.episode_index)) if len(self) else 0

    @property
    def snapshots(self) -> np.ndarray:
        """`(N, snapshot_dim)` - the *newest* book frame of each observation.

        The stack is oldest-first, so row `i` here is the book as of step `i`.
        Every target is built from this, never from the older frames, which are
        earlier rows of this same array.

        Sliced against `book_flat_dim`, **not** off the end of the observation.
        An observation ends with the per-agent private block, so `[-snapshot_dim:]`
        would return the private tail plus a truncated final snapshot - every
        target then silently reading misaligned fields. That is the same failure
        mode as the `[-40:]` slicing [05](../../../doc/05_observation_space.md) §1
        records, which returned 38 book values and 2 scalars and still passed
        several assertions.
        """
        end = self.layout.book_flat_dim
        return self.obs[:, end - self.layout.snapshot_dim:end]

    def describe(self) -> str:
        return (
            f"{len(self)} observations over {self.num_episodes} episode(s), "
            f"{self.layout.n_hist}x{self.layout.snapshot_dim} book floats "
            f"+ {self.layout.private_dim} private = {self.layout.flat_dim} each"
        )


def from_rollouts(
    num_episodes: Optional[int] = None,
    max_step: Optional[int] = None,
    num_agents: Optional[int] = None,
    init_cash: Optional[int] = None,
    seed: Optional[int] = None,
) -> ProbeCorpus:
    """Collect an observation stream by stepping the env with random agents.

    Any argument left as None is read from `config/cli_defaults.json` ->
    `cda_probe`.

    Args:
        num_episodes: How many episodes to run.
        max_step: Steps per episode, before truncation.
        num_agents: Traders in the market. Affects the book, not the corpus
            width - every agent sees the same observation (S1-2), so only one
            copy is kept.
        init_cash: Starting cash per trader. None leaves the key unset so
            `env_defaults.json` decides, which is the right layering - the
            probe does not own how much cash a trader starts with, and a
            fourth copy of that number could disagree with the other three.
            At 0 no order is ever approved and the book stays empty for the
            whole episode (S1-4), so a corpus collected at 0 is 100% empty
            books.
        seed: Base seed. Episode `e` uses `seed + e`, so episodes differ in
            their price anchor and action draw while the whole corpus stays
            reproducible. None means unseeded.

    Returns:
        A `ProbeCorpus` of `num_episodes * (max_step + 1)` rows at most - the
        `+ 1` is the reset observation, which is a real book state and a valid
        probe input. Fewer if an episode terminates early.
    """
    # Imported here rather than at module scope: this is the only function in
    # the package that needs the env, and importing it at module scope would
    # make `--parquet`, `--help` and a target listing all pay for it.
    from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
        continuousDoubleAuctionEnv,
    )

    if num_episodes is None:
        num_episodes = _cli("num_episodes")
    if max_step is None:
        max_step = _cli("max_step")
    if num_agents is None:
        num_agents = _cli("num_agents")

    env_config = {
        "num_of_agents": num_agents,
        "max_step": max_step,
        "is_render": False,
    }
    if init_cash is not None:
        env_config["init_cash"] = init_cash
    env = continuousDoubleAuctionEnv(env_config)
    layout = ObsLayout.from_obs_space(env.get_observation_space(env.agents[0]))

    rows: List[np.ndarray] = []
    episodes: List[int] = []

    for episode in range(num_episodes):
        episode_seed = None if seed is None else int(seed) + episode
        observations, _ = env.reset(seed=episode_seed)
        if episode_seed is not None:
            for agent_id in env.agents:
                env.action_spaces[agent_id].seed(episode_seed)

        # Every agent's observation is the same array (S1-2); keep one.
        keep = env.agents[0]
        rows.append(np.asarray(observations[keep], dtype=np.float32))
        episodes.append(episode)

        for _ in range(max_step):
            actions = {
                agent_id: env.action_spaces[agent_id].sample()
                for agent_id in env.agents
            }
            observations, _r, terminateds, truncateds, _i = env.step(actions)

            # A terminated agent drops out of the observation dict, so read
            # whichever agent is still present rather than assuming `keep` is.
            present = next(iter(observations), None)
            if present is not None:
                rows.append(np.asarray(observations[present], dtype=np.float32))
                episodes.append(episode)

            if terminateds.get("__all__", False) or truncateds.get("__all__", False):
                break

    corpus = ProbeCorpus(
        obs=np.stack(rows).astype(np.float32),
        episode_index=np.asarray(episodes, dtype=np.int32),
        layout=layout,
    )
    logger.info("rollout corpus: %s", corpus.describe())
    return corpus


def from_parquet(
    path: str,
    max_rows: Optional[int] = None,
    obs_column: str = "obs",
) -> ProbeCorpus:
    """Read an observation stream from `episode_record`'s Parquet output.

    Args:
        path: A `.parquet` file, or a directory searched recursively for them.
        max_rows: Stop after this many *deduplicated* observations. None reads
            everything.
        obs_column: Column holding the flat observation.

    Returns:
        A `ProbeCorpus` in `(episode_id, step)` order, one row per step rather
        than one per (step, agent) - see the module docstring on why the
        deduplication is load-bearing rather than an optimisation.

    Raises:
        FileNotFoundError: if `path` matches no Parquet file.
        ValueError: if the files carry no usable observation.
    """
    import pyarrow.parquet as pq

    files = _parquet_files(path)
    if not files:
        raise FileNotFoundError(f"No .parquet file at or under {path!r}.")

    columns = [obs_column, "episode_id", "step"]
    seen = set()
    rows: List[np.ndarray] = []
    keys: List[str] = []
    steps: List[int] = []

    for file in files:
        table = pq.read_table(file, columns=columns)
        obs_col = table.column(obs_column).to_pylist()
        episode_col = table.column("episode_id").to_pylist()
        step_col = table.column("step").to_pylist()

        for obs, episode_id, step in zip(obs_col, episode_col, step_col):
            # `episode_record` writes an empty list when the observation was
            # not available for that row; those rows carry no probe input.
            if not obs:
                continue
            key = (episode_id, step)
            if key in seen:
                continue
            seen.add(key)
            rows.append(np.asarray(obs, dtype=np.float32))
            keys.append(episode_id)
            steps.append(step)
            if max_rows is not None and len(rows) >= max_rows:
                break
        if max_rows is not None and len(rows) >= max_rows:
            break

    if not rows:
        raise ValueError(
            f"No usable observation in {len(files)} Parquet file(s) under "
            f"{path!r}. Was `episode_record` enabled for the run that wrote "
            "them?"
        )

    obs = np.stack(rows).astype(np.float32)
    layout = _layout_for_width(obs.shape[1])

    # Group by episode, ordered by step within one. `episode_id` is a string,
    # so episodes are numbered by first appearance rather than sorted.
    episode_numbers = {}
    for episode_id in keys:
        episode_numbers.setdefault(episode_id, len(episode_numbers))
    episode_index = np.asarray([episode_numbers[k] for k in keys], dtype=np.int32)

    order = np.lexsort((np.asarray(steps), episode_index))
    corpus = ProbeCorpus(
        obs=obs[order],
        episode_index=episode_index[order],
        layout=layout,
    )
    logger.info("parquet corpus from %s file(s): %s", len(files), corpus.describe())
    return corpus


def _parquet_files(path: str) -> Sequence[str]:
    if os.path.isfile(path):
        return [path]
    return sorted(glob.glob(os.path.join(path, "**", "*.parquet"), recursive=True))


def _layout_for_width(flat_dim: int) -> ObsLayout:
    """`ObsLayout` for a bare width, with no observation space to ask.

    A Parquet file records the observation but not the space it came from, so
    the layout is rebuilt from the width against the current
    `tunable_constants.json`. A file written under a different `n_hist` still
    reads correctly; one written under a different `k_rows` raises, which is
    the right answer - its rows are not this encoder's inputs.
    """
    import gymnasium as gym

    return ObsLayout.from_obs_space(
        gym.spaces.Box(-np.inf, np.inf, shape=(flat_dim,), dtype=np.float32)
    )
