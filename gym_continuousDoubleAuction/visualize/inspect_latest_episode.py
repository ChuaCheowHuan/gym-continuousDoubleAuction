import pprint
import sys

from gym_continuousDoubleAuction.visualize.episode_data import load_episode


def inspect_latest_episode(run_dir=None):
    """
    Finds the latest episode in the per-step Parquet record and writes its
    rows, as plain Python dicts, to visualize/latest_episode_data.txt.

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

    output_filename = 'visualize/latest_episode_data.txt'
    with open(output_filename, 'w') as out_f:
        out_f.write(f"--- Episode {episode_id} ---\n")
        pprint.pprint(episode.to_dict(orient="records"), stream=out_f)
        out_f.write("\n--- End of File ---\n")

    print(f"Data successfully written to {output_filename}")


if __name__ == "__main__":
    # Allow the caller to pass a custom run directory as an argument.
    if len(sys.argv) > 1:
        inspect_latest_episode(sys.argv[1])
    else:
        inspect_latest_episode()
