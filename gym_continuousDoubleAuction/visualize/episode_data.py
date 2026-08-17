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


def load_run(run_dir=None, columns=None, complete_only=True):
    """Every episode's rows from one run, for aggregating *across* episodes.

    `load_episode` answers "what happened in this episode"; this answers
    "what happened over this run", which is what a per-module comparison
    needs - the league reassigns opponents every episode, so one episode is
    one sample of one matchup.

    complete_only: keep only rows whose episode actually ended. On by
        default, and it is not a nicety: `EpisodeRecorder.flush` writes
        whatever was still in flight when a run stopped, tagged
        `episode_complete=False`, and those rows stop at whatever step
        sampling stopped at with nothing else in them saying so. Every
        per-episode aggregate - a return, a final NAV, a rate over an
        episode - would silently count that fragment as a whole episode
        (`EpisodeRecorder._release`). Pass False only to look at the
        fragments deliberately.

    run_dir/columns: as `load_episode`, except that `episode_complete` is
        always read too, since the filter above needs it.
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
        needed = sorted(set(columns) | {"episode_id", "step", "episode_complete"})
    frame = pd.read_parquet(run_dir, columns=needed)
    if frame.empty:
        raise ValueError(f"{run_dir} contains no rows")

    if complete_only:
        total_episodes = frame["episode_id"].nunique()
        frame = frame[frame["episode_complete"]]
        if frame.empty:
            raise ValueError(
                f"{run_dir} has {total_episodes} episode(s) but none of them "
                "completed - every row is from an episode that was still in "
                "flight when the run stopped. Pass complete_only=False to "
                "look at those fragments anyway."
            )
    return frame


def load_episode(run_dir=None, episode_id=None, columns=None):
    """The rows of one episode from the per-step record, sorted by step.

    run_dir: a directory of `.parquet` files. Defaults to the most recently
        written run under `config/tunable_constants.json` ->
        `visualize_paths.episode_parquet_dir`.
    episode_id: which episode. Defaults to the most recently recorded episode
        that actually *ended* - the latest `wall_time` among rows whose
        `episode_complete` is true.

        The completeness part is not incidental. `EpisodeRecorder.flush`
        writes whatever was in flight when the run stopped, so the row with
        the highest `wall_time` in a finished run is very often a fragment of
        a few steps from an episode that never ended (`_release`). Picking it
        by default drew a plot of that fragment while saying nothing about
        it - a five-step chart of what should be a `max_step` episode. An
        explicitly passed `episode_id` is always honoured, complete or not,
        because asking for one by name is asking for that one.
    columns: restrict the read to these plus `episode_id`/`step`/`wall_time`/
        `episode_complete`, which the selection above needs regardless of what
        the caller plots.
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
        needed = sorted(
            set(columns) | {"episode_id", "step", "wall_time", "episode_complete"}
        )
    frame = pd.read_parquet(run_dir, columns=needed)
    if frame.empty:
        raise ValueError(f"{run_dir} contains no rows")

    if episode_id is None:
        complete = frame[frame["episode_complete"]]
        if complete.empty:
            # Nothing finished. Better a fragment than nothing, but say so:
            # every per-step chart drawn from it stops wherever sampling did.
            print(
                f"warning: no completed episode in {run_dir} - falling back to "
                "an episode that was still in flight, so it stops wherever "
                "sampling stopped rather than at the end of an episode."
            )
            complete = frame
        if complete["wall_time"].notna().any():
            episode_id = complete.loc[complete["wall_time"].idxmax(), "episode_id"]
        else:
            # `EpisodeRecorder` always stamps `wall_time`, so this is a
            # hand-built or damaged file. File order is a worse answer than
            # the newest episode, but it is an answer.
            episode_id = complete["episode_id"].iloc[-1]

    episode = frame[frame["episode_id"] == episode_id].sort_values("step")
    if episode.empty:
        raise ValueError(f"no rows for episode_id={episode_id!r} in {run_dir}")
    return episode
