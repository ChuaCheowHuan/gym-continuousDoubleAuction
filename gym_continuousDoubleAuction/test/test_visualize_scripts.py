"""The `visualize/` entry points, run end to end on small synthetic runs (issue #211).

Only `visualize_orderbook._newest_snapshot` and the reward-term colours were tested. The rest
of `visualize/` (the loader, the six chart scripts, `run_all` and the two inspectors) had
no test, and a column renamed in the episode record would have broken every chart without a
failing build.

Each test writes a tiny Parquet run, points a script at it from a temporary working
directory (the scripts save to a relative `visualize/chart/`) and asserts on what the script
read: the data in the plotted lines, the files written, the rows selected.
"""

import json
import os

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from gym_continuousDoubleAuction.envs.exchg.state_helper import (  # noqa: E402
    PRIVATE_DIM,
    SNAPSHOT_DIM,
    obs_row_slice,
)
from gym_continuousDoubleAuction.train.episode_record import REWARD_TERMS  # noqa: E402
from gym_continuousDoubleAuction.visualize import (  # noqa: E402
    episode_data,
    inspect_latest_episode,
    inspect_latest_episode_json,
    run_all,
    visualize_execution,
    visualize_modules,
    visualize_nav,
    visualize_orderbook,
    visualize_rewards,
    visualize_training,
)

AGENTS = ["agent_0", "agent_1", "agent_2"]
MODULES = {"agent_0": "policy_0", "agent_1": "policy_1", "agent_2": "champion_1"}
STEPS = 6
N_HIST = 2


def _obs(step, bid_size):
    """A recorded observation whose newest snapshot has a known bid-size row."""
    obs = np.zeros(N_HIST * SNAPSHOT_DIM + PRIVATE_DIM, dtype=np.float32)
    newest = (N_HIST - 1) * SNAPSHOT_DIM
    obs[newest + obs_row_slice("bid_size").start : newest + obs_row_slice("bid_size").stop] = (
        bid_size
    )
    obs[newest + obs_row_slice("ask_size").start : newest + obs_row_slice("ask_size").stop] = 2.0
    obs[-PRIVATE_DIM:] = 99.0  # an own-position block that must never be read as book size
    return obs.tolist()


def _episode_rows(episode_id, wall_time, complete=True, steps=STEPS):
    rows = []
    for step in range(steps):
        for agent in AGENTS:
            row = {
                "run_id": "r",
                "iteration": 1,
                "episode_id": episode_id,
                "step": step,
                "agent_id": agent,
                "module_id": MODULES[agent],
                "wall_time": wall_time + step * 0.01,
                "episode_complete": complete,
                "nav": 1000.0 + step * (1 + AGENTS.index(agent)),
                "max_nav": 1000.0 + step * 2 + AGENTS.index(agent),
                "reward": 0.5 * step,
                "best_bid": 100.0 + step,
                "best_ask": 102.0 + step,
                "order_step_placed": 1,
                "num_rejected_step": step % 2,
                "num_trades_step": 2,
                "num_passive_fills_step": 1,
                "is_pass_action": step % 3 == 0,
                "obs": _obs(step, bid_size=1.0 + step),
            }
            for term in REWARD_TERMS:
                row[f"reward_term_{term}"] = 0.25 if term == REWARD_TERMS[0] else 0.0
            rows.append(row)
    return rows


def _write_run(directory, episodes):
    os.makedirs(directory, exist_ok=True)
    rows = [row for ep in episodes for row in _episode_rows(**ep)]
    pd.DataFrame(rows).to_parquet(os.path.join(directory, "episodes.0.parquet"))
    return str(directory)


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    """A run with two complete episodes (the newer is `ep_b`) and one fragment."""
    monkeypatch.chdir(tmp_path)  # the scripts save to a relative visualize/chart/
    yield _write_run(
        tmp_path / "episode_data" / "run_1",
        [
            {"episode_id": "ep_a", "wall_time": 100.0},
            {"episode_id": "ep_b", "wall_time": 200.0},
            {"episode_id": "ep_frag", "wall_time": 300.0, "complete": False, "steps": 2},
        ],
    )
    plt.close("all")


@pytest.fixture(autouse=True)
def _close_figures():
    yield
    plt.close("all")


def _lines():
    return {line.get_label(): line.get_ydata() for line in plt.gcf().axes[0].get_lines()}


class TestEpisodeData:
    def test_the_latest_complete_episode_is_chosen_not_the_newest_fragment(self, run_dir):
        episode = episode_data.load_episode(run_dir)
        assert set(episode["episode_id"]) == {"ep_b"}
        assert list(episode["step"].unique()) == list(range(STEPS))

    def test_a_named_episode_is_honoured_even_if_unfinished(self, run_dir):
        episode = episode_data.load_episode(run_dir, episode_id="ep_frag")
        assert set(episode["episode_id"]) == {"ep_frag"} and episode["step"].max() == 1

    def test_columns_are_restricted_but_the_selection_columns_come_along(self, run_dir):
        episode = episode_data.load_episode(run_dir, columns=["nav"])
        assert set(episode.columns) == {
            "nav",
            "episode_id",
            "step",
            "wall_time",
            "episode_complete",
        }

    def test_load_run_drops_fragments_unless_asked(self, run_dir):
        assert set(episode_data.load_run(run_dir)["episode_id"]) == {"ep_a", "ep_b"}
        everything = episode_data.load_run(run_dir, complete_only=False)
        assert set(everything["episode_id"]) == {"ep_a", "ep_b", "ep_frag"}

    def test_only_fragments_is_an_error_naming_the_remedy(self, tmp_path):
        directory = _write_run(
            tmp_path / "frag", [{"episode_id": "x", "wall_time": 1.0, "complete": False}]
        )
        with pytest.raises(ValueError, match="complete_only=False"):
            episode_data.load_run(directory)

    def test_latest_run_dir_prefers_the_newest_and_accepts_a_run_itself(self, tmp_path):
        old = _write_run(tmp_path / "root" / "old", [{"episode_id": "o", "wall_time": 1.0}])
        new = _write_run(tmp_path / "root" / "new", [{"episode_id": "n", "wall_time": 2.0}])
        os.utime(old, (1, 1))
        assert episode_data.latest_run_dir(str(tmp_path / "root")) == new
        assert episode_data.latest_run_dir(new) == new  # already a directory of parquet files
        assert episode_data.latest_run_dir(str(tmp_path / "nothing_here")) is None

    def test_no_data_anywhere_says_how_to_produce_it(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(FileNotFoundError, match="episode_data_dir"):
            episode_data.load_episode()

    def test_default_root_falls_back_when_the_configured_one_is_missing(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        assert episode_data.default_parquet_root() == "../episode_data"
        (tmp_path / "episode_data").mkdir()
        assert episode_data.default_parquet_root() == "episode_data"


class TestChartsReadTheRightRows:
    def test_nav_plots_each_agents_nav_for_the_chosen_episode(self, run_dir):
        visualize_nav.visualize_nav(run_dir, "ep_b")
        lines = _lines()
        assert sorted(lines) == sorted(AGENTS)
        assert list(lines["agent_1"]) == [1000.0 + 2 * s for s in range(STEPS)]
        assert os.path.isfile("visualize/chart/nav_visualization.png")

    def test_drawdown_has_a_panel_per_agent_and_the_gap_shaded(self, run_dir):
        visualize_nav.visualize_nav_drawdown(run_dir, "ep_b")
        fig = plt.gcf()
        assert len(fig.axes) == len(AGENTS)
        nav = [l for l in fig.axes[0].get_lines() if l.get_label() == "NAV"][0].get_ydata()
        peak = [l for l in fig.axes[0].get_lines() if l.get_label() == "Running peak"][
            0
        ].get_ydata()
        assert list(peak - nav) == [float(s) for s in range(STEPS)]  # agent_0: 2s - s
        assert os.path.isfile("visualize/chart/nav_drawdown_visualization.png")

    def test_cumulative_rewards_are_the_running_sum(self, run_dir):
        visualize_rewards.visualize_rewards(run_dir, "ep_b")
        assert list(_lines_of_figure()["agent_0"]) == list(
            np.cumsum([0.5 * s for s in range(STEPS)])
        )
        assert os.path.isfile("visualize/chart/cumulative_rewards_visualization.png")

    def test_reward_decomposition_draws_every_term_plus_the_total(self, run_dir):
        visualize_rewards.visualize_reward_decomposition(run_dir, "ep_b", "agent_1")
        labels = set(_lines_of_figure())
        assert labels >= set(REWARD_TERMS) | {"reward (total)"}
        assert list(_lines_of_figure()[REWARD_TERMS[0]]) == [0.25 * (s + 1) for s in range(STEPS)]

    def test_a_missing_agent_prints_instead_of_plotting(self, run_dir, capsys):
        visualize_rewards.visualize_reward_decomposition(run_dir, "ep_b", "agent_9")
        assert "No rows for agent 'agent_9'" in capsys.readouterr().out
        assert not os.path.exists("visualize/chart/reward_decomposition_visualization.png")

    def test_execution_quality_saves_a_chart(self, run_dir):
        visualize_execution.visualize_execution_quality(run_dir, "ep_b", "agent_0", window=3)
        assert os.path.isfile("visualize/chart/execution_quality_visualization.png")
        cumulative = {l.get_label(): l.get_ydata() for l in plt.gcf().axes[0].get_lines()}
        assert list(cumulative["Trades (both sides)"]) == [2.0 * (s + 1) for s in range(STEPS)]
        assert list(cumulative["Orders rejected"]) == list(np.cumsum([s % 2 for s in range(STEPS)]))

    def test_orderbook_reads_the_newest_book_not_the_private_block(self, run_dir):
        visualize_orderbook.visualize_episode_data(run_dir, "ep_b", "agent_0")
        price_axis, size_axis = plt.gcf().axes
        prices = {l.get_label(): l.get_ydata() for l in price_axis.get_lines()}
        assert list(prices["Best Bid"]) == [100.0 + s for s in range(STEPS)]
        sizes = {l.get_label(): l.get_ydata() for l in size_axis.get_lines()}
        width = obs_row_slice("bid_size").stop - obs_row_slice("bid_size").start
        assert list(sizes["Total Bid Size"]) == [width * (1.0 + s) for s in range(STEPS)]
        assert max(sizes["Total Ask Size"]) < 99.0  # 99 is the private block's marker

    def test_modules_compares_by_module_over_complete_episodes_only(self, run_dir, capsys):
        visualize_modules.visualize_modules(run_dir, num_trained_agents=2)
        out = capsys.readouterr().out
        assert "2 completed episode(s)" in out and "3 module(s)" in out
        assert os.path.isfile("visualize/chart/modules_visualization.png")

    def test_modules_with_no_module_ids_says_so_and_draws_nothing(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        rows = pd.DataFrame(_episode_rows("e", 1.0))
        rows["module_id"] = None
        os.makedirs("run")
        rows.to_parquet("run/episodes.0.parquet")
        visualize_modules.visualize_modules("run", num_trained_agents=2)
        assert "Every module_id is null" in capsys.readouterr().out
        assert not os.path.exists("visualize/chart/modules_visualization.png")


def _lines_of_figure():
    ax = plt.gcf().axes[0]
    return {line.get_label(): line.get_ydata() for line in ax.get_lines()}


class TestModuleFamilies:
    @pytest.mark.parametrize(
        "module_id, family",
        [
            ("policy_0", "trainable"),
            ("policy_1", "trainable"),
            ("policy_2", "baseline"),
            ("policy_x", "baseline"),
            ("champion_7", "champion"),
            ("something_else", "baseline"),
        ],
    )
    def test_family_comes_from_the_name_and_the_trainable_count(self, module_id, family):
        assert visualize_modules.module_family(module_id, 2) == family

    def test_maker_share_is_nan_not_zero_when_nothing_traded(self):
        frame = pd.DataFrame(_episode_rows("e", 1.0))
        frame.loc[frame["agent_id"] == "agent_0", "num_trades_step"] = 0
        rows = visualize_modules.per_agent_episode(frame)
        by_agent = rows.set_index("agent_id")
        assert np.isnan(by_agent.loc["agent_0", "maker_share"])
        assert by_agent.loc["agent_1", "maker_share"] == pytest.approx(0.5)


class TestTraining:
    def _progress(self, directory, iterations=3, junk=False):
        os.makedirs(directory, exist_ok=True)
        lines = []
        for it in range(1, iterations + 1):
            runner = {
                "nav_conservation_error": 1e-9 * it,
                "nav_conservation_violations": 0,
                "pass_action_fraction": 0.1 * it,
                "order_rejection_fraction": 0.05,
                "maker_fill_ratio_max": 0.4,
            }
            for term in REWARD_TERMS:
                runner[f"reward_term_mean_{term}"] = -0.1
                runner[f"reward_term_var_share_{term}"] = 1.0 / len(REWARD_TERMS)
            lines.append(
                json.dumps(
                    {
                        "training_iteration": it,
                        "env_runners": runner,
                        "league": {
                            "mean_return": float(it),
                            "std_return": 0.5,
                            "promoted": it == 2,
                        },
                    }
                )
            )
        text = "\n".join(reversed(lines)) + "\n"  # out of order on purpose
        if junk:
            text += '{"training_iteration": 9, "env_run'  # a run killed mid-write
        with open(os.path.join(directory, "progress.jsonl"), "w") as fh:
            fh.write(text)
        return str(directory)

    def test_progress_rows_are_sorted_by_iteration(self, tmp_path):
        rows = visualize_training.load_progress(self._progress(tmp_path / "t"))
        assert [r["training_iteration"] for r in rows] == [1, 2, 3]

    def test_a_partial_last_line_is_skipped_with_a_warning(self, tmp_path):
        directory = self._progress(tmp_path / "t", junk=True)
        with pytest.warns(UserWarning, match="skipped 1 line"):
            rows = visualize_training.load_progress(directory)
        assert len(rows) == 3

    def test_missing_progress_is_a_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            visualize_training.load_progress(str(tmp_path))

    def test_the_chart_has_five_panels_and_marks_the_promotion(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        visualize_training.visualize_training(self._progress(tmp_path / "t"))
        fig = plt.gcf()
        assert len(fig.axes) == 5
        league = fig.axes[1]
        mean = [l for l in league.get_lines() if l.get_label() == "Mean return"][0]
        assert list(mean.get_ydata()) == [1.0, 2.0, 3.0]
        assert os.path.isfile("visualize/chart/training_visualization.png")


class TestRunAllAndInspectors:
    def test_run_all_regenerates_every_chart(self, run_dir, tmp_path):
        progress = TestTraining()._progress(tmp_path / "t")
        run_all.run_all(
            run_dir=run_dir,
            episode_id="ep_b",
            agent_id="agent_0",
            num_trained_agents=2,
            training_run_dir=progress,
        )
        charts = sorted(os.listdir("visualize/chart"))
        assert charts == [
            "cumulative_rewards_visualization.png",
            "execution_quality_visualization.png",
            "modules_visualization.png",
            "nav_drawdown_visualization.png",
            "nav_visualization.png",
            "orderbook_visualization.png",
            "reward_decomposition_visualization.png",
            "training_visualization.png",
        ]
        assert all(os.path.getsize(f"visualize/chart/{c}") > 0 for c in charts)

    def test_the_json_inspector_writes_the_latest_complete_episode(self, run_dir):
        inspect_latest_episode_json.inspect_latest_episode_json(run_dir)
        with open("visualize/json/latest_episode_data.json") as fh:
            records = json.load(fh)
        assert {r["episode_id"] for r in records} == {"ep_b"}
        assert len(records) == STEPS * len(AGENTS)

    def test_the_text_inspector_writes_the_same_episode(self, run_dir):
        inspect_latest_episode.inspect_latest_episode(run_dir)
        text = open("visualize/json/latest_episode_data.txt").read()
        assert text.startswith("--- Episode ep_b ---") and text.rstrip().endswith("End of File ---")

    def test_the_inspectors_report_a_missing_run_instead_of_raising(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        inspect_latest_episode.inspect_latest_episode()
        inspect_latest_episode_json.inspect_latest_episode_json()
        assert capsys.readouterr().out.count("Error: no .parquet files") == 2
        assert not os.path.exists("visualize/json")
