"""Regenerates every chart in `visualize/`, in one command.

Replaces the retired `visualize.ipynb`, whose `%run` cells only ever covered
three of the six chart-producing scripts here (`visualize_orderbook.py`,
`visualize_nav.py`, `visualize_rewards.py`) and silently fell behind as the
other three were added - `visualize_execution.py`, `visualize_modules.py`,
and `visualize_training.py` never got a notebook cell. This just calls each
script's own public function directly, so a script that gains a new plot is
picked up here for free with no second place to update.

Run from the `gym_continuousDoubleAuction` directory - the scripts save to a
relative `visualize/*.png` - e.g.:

    cd gym_continuousDoubleAuction
    python -m visualize.run_all
"""
import argparse

from gym_continuousDoubleAuction.visualize import (
    visualize_execution,
    visualize_modules,
    visualize_nav,
    visualize_orderbook,
    visualize_rewards,
    visualize_training,
)


def run_all(
    run_dir=None, episode_id=None, agent_id=None, num_trained_agents=None,
    training_run_dir=None,
):
    """Runs every visualize_*.py chart function and saves the results.

    run_dir/episode_id/agent_id/num_trained_agents are passed straight
    through to the per-episode and per-run views, which all read from the
    same episode Parquet record (`visualize.episode_data`); each defaults to
    the same "latest" value it would if called on its own.

    training_run_dir is separate and NOT `run_dir`: `visualize_training`
    reads `progress.jsonl` under `visualize_paths.training_log_dir`, a
    different directory tree than the episode Parquet record the rest of
    these read, so the two are never interchangeable.
    """
    visualize_orderbook.visualize_episode_data(run_dir, episode_id, agent_id)
    visualize_nav.visualize_nav(run_dir, episode_id)
    visualize_nav.visualize_nav_drawdown(run_dir, episode_id)
    visualize_rewards.visualize_rewards(run_dir, episode_id)
    visualize_rewards.visualize_reward_decomposition(run_dir, episode_id, agent_id)
    visualize_execution.visualize_execution_quality(run_dir, episode_id, agent_id)
    visualize_modules.visualize_modules(run_dir, num_trained_agents)
    visualize_training.visualize_training(training_run_dir)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument(
        "--run-dir", default=None,
        help="episode Parquet run directory; defaults to the most recently written run",
    )
    p.add_argument(
        "--episode-id", default=None,
        help="episode within --run-dir; defaults to the most recently completed one",
    )
    p.add_argument(
        "--agent-id", default=None,
        help="agent for the single-agent views; defaults to visualize_paths.default_agent_id",
    )
    p.add_argument(
        "--trained-agents", dest="num_trained_agents", type=int, default=None,
        help="trainable policy count for the module comparison; defaults to train_config.json",
    )
    p.add_argument(
        "--training-run-dir", default=None,
        help="progress.jsonl run directory; defaults to the most recently written run",
    )
    args = p.parse_args()
    run_all(
        args.run_dir, args.episode_id, args.agent_id, args.num_trained_agents,
        args.training_run_dir,
    )
