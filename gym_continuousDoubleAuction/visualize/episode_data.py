"""Shared loader for the visualize scripts: reads the per-step Parquet record.

`train.episode_record.EpisodeRecorder` writes one row per (episode, step, agent)
to `<episode_data_dir>/<run_id>/episodes.<tag>.<seq>.parquet` (doc/21 logging
review, recommendation 4). That replaced the per-episode `pickle.dump` this
package used to convert to `latest_episode_data.json` for these scripts to
read; every visualize_*.py script now goes through `load_episode` here instead
of each re-deriving where a run's data lives and which episode is "the" one.
"""
import glob
import os

import pandas as pd

from gym_continuousDoubleAuction.config_loader import constant


def default_parquet_root():
    """Where the per-step record lives, resolved the same way the old
    `nav_json_path`/`nav_json_fallback` pair was: the configured path if it
    exists, else the same name one directory up, which is what running from
    inside `visualize/` needs.
    """
    root = constant("visualize_paths", "episode_parquet_dir")
    if os.path.isdir(root):
        return root
    return constant("visualize_paths", "episode_parquet_fallback")


def latest_run_dir(root):
    """The most recently written run under `root`.

    `root` may itself already be a directory of `.parquet` files - a single
    run pointed at explicitly - in which case it is returned as-is. Otherwise
    its subdirectories are `<run_id>` directories, one per training run, and
    the most recently modified one is the latest.
    """
    if glob.glob(os.path.join(root, "*.parquet")):
        return root
    run_dirs = [d for d in glob.glob(os.path.join(root, "*")) if os.path.isdir(d)]
    if not run_dirs:
        return None
    return max(run_dirs, key=os.path.getmtime)


def load_episode(run_dir=None, episode_id=None, columns=None):
    """The rows of one episode from the per-step record, sorted by step.

    run_dir: a directory of `.parquet` files. Defaults to the most recently
        written run under `config/tunable_constants.json` ->
        `visualize_paths.episode_parquet_dir`.
    episode_id: which episode. Defaults to the one holding the row with the
        latest `wall_time`, i.e. the most recently recorded episode.
    columns: restrict the read to these plus `episode_id`/`step`/`wall_time`,
        which the selection above needs regardless of what the caller plots.
    """
    if run_dir is None:
        root = default_parquet_root()
        run_dir = latest_run_dir(root)
        if run_dir is None:
            raise FileNotFoundError(
                f"no .parquet files under {root!r} - run training with "
                "episode_data_dir set (config/train_config.json), or pass "
                "run_dir explicitly"
            )

    needed = None
    if columns is not None:
        needed = sorted(set(columns) | {"episode_id", "step", "wall_time"})
    frame = pd.read_parquet(run_dir, columns=needed)
    if frame.empty:
        raise ValueError(f"{run_dir} contains no rows")

    if episode_id is None:
        episode_id = frame.loc[frame["wall_time"].idxmax(), "episode_id"]

    episode = frame[frame["episode_id"] == episode_id].sort_values("step")
    if episode.empty:
        raise ValueError(f"no rows for episode_id={episode_id!r} in {run_dir}")
    return episode
