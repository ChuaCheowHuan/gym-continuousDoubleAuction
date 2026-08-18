import os
import sys

from gym_continuousDoubleAuction.visualize.episode_data import load_episode


def inspect_latest_episode_json(run_dir=None):
    """
    Finds the latest episode in the per-step Parquet record and writes its
    rows to visualize/json/latest_episode_data.json.

    `DataFrame.to_json` handles the numpy/pandas types the columns hold
    (floats, ints, nulls, list-typed obs/action columns) on its own, so unlike
    the old pickle-derived dump this needs no custom encoder.

    run_dir defaults to the most recently written run under
    config/tunable_constants.json -> visualize_paths.episode_parquet_dir; see
    episode_data.load_episode.
    """
    try:
        episode = load_episode(run_dir)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}")
        return

    episode_id = episode["episode_id"].iloc[0]
    print(f"Latest episode: {episode_id} ({len(episode)} rows)")

    output_filename = 'visualize/json/latest_episode_data.json'
    os.makedirs(os.path.dirname(output_filename), exist_ok=True)
    episode.to_json(output_filename, orient="records", indent=2)
    print(f"Data successfully written to {output_filename}")


if __name__ == "__main__":
    # Allow the caller to pass a custom run directory as an argument.
    if len(sys.argv) > 1:
        inspect_latest_episode_json(sys.argv[1])
    else:
        inspect_latest_episode_json()
