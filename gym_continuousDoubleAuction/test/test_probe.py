"""The reward-free probe harness.

What is worth pinning here is not that the harness runs - that is one smoke
test - but the handful of properties that decide whether its numbers mean
anything:

  * the split never puts a row's temporal neighbour on the other side of it,
    because adjacent observations share three of their four snapshots and a
    leak there turns the report into a memorisation score;
  * a target is never read across an episode boundary, where the price anchor
    is redrawn at random;
  * every feature set is scored on identical rows with an identical split;
  * an unscoreable cell reports as unscoreable rather than as a floor value;
  * the targets compute what their docstrings say, checked against snapshots
    built by hand rather than by the same expressions under test.
"""
import numpy as np
import pytest

from gym_continuousDoubleAuction.train.model.encoders.obs_layout import ObsLayout
from gym_continuousDoubleAuction.train.probe import corpus as corpus_module
from gym_continuousDoubleAuction.train.probe import probe as probe_module
from gym_continuousDoubleAuction.train.probe import report as report_module
from gym_continuousDoubleAuction.train.probe import targets as targets_module
from gym_continuousDoubleAuction.train.probe.corpus import ProbeCorpus

#: Small enough to stay fast, long enough that a 0.6/0.2/0.2 split of episodes
#: gives every split at least one.
EPISODES = 4
STEPS = 12


@pytest.fixture(scope="module")
def layout():
    """The shipped layout, derived the way the encoders derive it.

    Built from a space of the real width - stacked book *plus* the per-agent
    private block - rather than a bare multiple of `snapshot_dim`, because that
    is what the env declares and `from_obs_space` refuses anything else.
    """
    import gymnasium as gym

    from gym_continuousDoubleAuction.config_loader import group

    spec = group("tunable_constants.json", "observation_layout")
    snapshot = spec["book_rows"] * spec["k_rows"] + spec["extra_dim"]
    width = 4 * snapshot + spec["private_dim"]
    return ObsLayout.from_obs_space(
        gym.spaces.Box(-np.inf, np.inf, shape=(width,), dtype=np.float32)
    )


def synthetic(layout, episodes=EPISODES, steps=STEPS, seed=0):
    """A corpus with known contents, built without touching the env.

    The env is slow and its books are whatever random agents happen to make;
    these tests are about the harness's arithmetic, so the observations here
    are constructed so their targets can be written down independently.
    """
    rng = np.random.default_rng(seed)
    rows, episode_index = [], []
    for episode in range(episodes):
        for step in range(steps):
            snapshot = np.zeros(layout.snapshot_dim, dtype=np.float32)
            snapshot[: layout.k_rows] = rng.normal(size=layout.k_rows) * 0.01
            snapshot[layout.k_rows: 2 * layout.k_rows] = rng.random(layout.k_rows)
            snapshot[3 * layout.k_rows: 4 * layout.k_rows] = -rng.random(layout.k_rows)
            # log_mid: a per-episode level plus an uneven per-step drift, so
            # returns are non-trivial within an episode, large across a
            # boundary, and - because the drift varies - `realized_vol` has
            # something to disperse. A constant drift would make that target
            # degenerate and the report would drop it.
            snapshot[layout.book_dim] = (
                2.0 + episode * 10.0 + 0.25 * (step % 5)
            )
            snapshot[layout.book_dim + 1] = 0.7 + 0.1 * (step % 3)
            # The observation stacks n_hist frames, then a private tail. The
            # tail is filled with a value no target should ever read - if one
            # leaks into a target, it shows up as an obvious constant rather
            # than as a plausible-looking number.
            private = np.full(layout.private_dim, -999.0, dtype=np.float32)
            obs = np.concatenate([np.tile(snapshot, layout.n_hist), private])
            rows.append(obs)
            episode_index.append(episode)
    return ProbeCorpus(
        obs=np.stack(rows).astype(np.float32),
        episode_index=np.asarray(episode_index, dtype=np.int32),
        layout=layout,
    )


# --- Reading the snapshot ----------------------------------------------------

class TestSnapshotReaders:
    def test_snapshots_are_the_newest_book_frame(self, layout):
        """The stack is oldest-first; every target reads the last *book* frame.

        Sliced against `book_flat_dim`, not off the end of the vector. The
        observation ends with the per-agent private block, so
        `obs[-snapshot_dim:]` would hand every target the private tail plus a
        truncated snapshot - misaligning every field while still returning an
        array of exactly the right shape.
        """
        corpus = synthetic(layout)
        end = layout.book_flat_dim
        expected = corpus.obs[:, end - layout.snapshot_dim:end]
        assert np.array_equal(corpus.snapshots, expected)

    def test_snapshots_never_contain_the_private_block(self, layout):
        """`synthetic` fills the private tail with a sentinel no target reads."""
        corpus = synthetic(layout)
        assert not (corpus.snapshots == -999.0).any()
        assert corpus.snapshots.shape[1] == layout.snapshot_dim

    def test_log_mid_is_the_first_extra_scalar(self, layout):
        corpus = synthetic(layout)
        values = targets_module.log_mid(corpus.snapshots, layout)
        assert np.allclose(values, corpus.snapshots[:, layout.book_dim])

    def test_depth_imbalance_uses_the_sign_convention(self, layout):
        """Bid sizes are +sqrt(V) and ask sizes -sqrt(V), so the sum is signed.

        A balanced book must give exactly 0 and a one-sided book exactly +/-1;
        an implementation that took `abs` of the ask block and then subtracted
        would agree on the first and disagree on the second.
        """
        snapshot = np.zeros((3, layout.snapshot_dim), dtype=np.float32)
        k = layout.k_rows
        # Balanced.
        snapshot[0, k:2 * k] = 1.0
        snapshot[0, 3 * k:4 * k] = -1.0
        # Bids only.
        snapshot[1, k:2 * k] = 1.0
        # Asks only.
        snapshot[2, 3 * k:4 * k] = -1.0

        imbalance = targets_module.depth_imbalance(snapshot, layout)
        assert imbalance[0] == pytest.approx(0.0)
        assert imbalance[1] == pytest.approx(1.0)
        assert imbalance[2] == pytest.approx(-1.0)

    def test_depth_imbalance_of_an_empty_book_is_zero(self, layout):
        """Neutral, not a division by zero and not a sentinel."""
        empty = np.zeros((1, layout.snapshot_dim), dtype=np.float32)
        assert targets_module.depth_imbalance(empty, layout)[0] == 0.0


# --- Targets -----------------------------------------------------------------

class TestTargets:
    def test_mid_return_is_the_log_mid_difference(self, layout):
        corpus = synthetic(layout)
        values, valid = targets_module.build(
            targets_module.TARGET_REGISTRY["mid_return"],
            corpus.snapshots, layout, corpus.episode_index, horizon=3,
        )
        mids = targets_module.log_mid(corpus.snapshots, layout)
        rows = np.flatnonzero(valid)
        assert np.allclose(values[rows], mids[rows + 3] - mids[rows])

    def test_realized_vol_of_a_constant_drift_is_zero(self, layout):
        """A steadily trending midpoint has no dispersion to report.

        Built here rather than from `synthetic`, whose drift is deliberately
        uneven, and at a step size exactly representable in float32 - the
        snapshots are stored at that width, so an increment like 0.01 comes
        back with ~1e-6 of jitter and the "exactly zero" claim would need a
        tolerance large enough to hide a real defect.
        """
        steps = 12
        snapshots = np.zeros((steps, layout.snapshot_dim), dtype=np.float32)
        snapshots[:, layout.book_dim] = 2.0 + 0.25 * np.arange(steps)
        values, valid = targets_module.build(
            targets_module.TARGET_REGISTRY["realized_vol"],
            snapshots, layout, np.zeros(steps, dtype=np.int32), horizon=4,
        )
        assert valid.any()
        assert np.all(values[valid] == 0.0)

    def test_realized_vol_is_positive_when_the_drift_varies(self, layout):
        corpus = synthetic(layout)
        values, valid = targets_module.build(
            targets_module.TARGET_REGISTRY["realized_vol"],
            corpus.snapshots, layout, corpus.episode_index, horizon=4,
        )
        assert (values[valid] > 0).any()

    def test_realized_vol_refuses_horizon_one(self, layout):
        """Otherwise it is the standard deviation of a single number - a column
        of exact zeros, and an R^2 of 0 for every feature set."""
        corpus = synthetic(layout)
        with pytest.raises(ValueError, match="min_horizon|horizon >= 2"):
            targets_module.build(
                targets_module.TARGET_REGISTRY["realized_vol"],
                corpus.snapshots, layout, corpus.episode_index, horizon=1,
            )

    def test_unknown_target_raises_naming_the_alternatives(self):
        with pytest.raises(ValueError, match="mid_return"):
            targets_module.resolve(["not_a_target"])

    def test_every_registered_target_is_selectable_and_builds(self, layout):
        corpus = synthetic(layout)
        for name in targets_module.selectable_targets():
            target = targets_module.TARGET_REGISTRY[name]
            values, valid = targets_module.build(
                target, corpus.snapshots, layout, corpus.episode_index,
                horizon=max(2, target.min_horizon),
            )
            assert valid.any(), name
            assert np.isfinite(values[valid]).all(), name


class TestHorizonMask:
    def test_never_crosses_an_episode_boundary(self, layout):
        """A return read across a reset is a jump between unrelated random
        price anchors, which is the largest 'signal' in the corpus and is
        entirely artificial."""
        corpus = synthetic(layout)
        for horizon in (1, 3, 7):
            valid = targets_module.horizon_mask(corpus.episode_index, horizon)
            rows = np.flatnonzero(valid)
            assert np.array_equal(
                corpus.episode_index[rows], corpus.episode_index[rows + horizon]
            )

    def test_drops_the_tail_of_every_episode(self, layout):
        corpus = synthetic(layout)
        valid = targets_module.horizon_mask(corpus.episode_index, 2)
        # Two rows per episode have no in-episode row two steps on.
        assert valid.sum() == len(corpus) - 2 * EPISODES

    def test_a_horizon_longer_than_the_corpus_is_empty_not_an_error(self, layout):
        corpus = synthetic(layout)
        assert not targets_module.horizon_mask(
            corpus.episode_index, len(corpus) + 5
        ).any()


# --- The probe ---------------------------------------------------------------

class TestSplits:
    def test_splits_on_episodes_when_there_are_enough(self, layout):
        """No episode may appear in two splits: that is what removes the
        adjacent-row leak at the seams and gives the test split its own price
        anchors."""
        corpus = synthetic(layout)
        train, validation, test = probe_module.split_masks(
            corpus.episode_index, len(corpus)
        )
        episodes = [set(corpus.episode_index[m]) for m in (train, validation, test)]
        assert episodes[0] and episodes[1] and episodes[2]
        assert not episodes[0] & episodes[1]
        assert not episodes[0] & episodes[2]
        assert not episodes[1] & episodes[2]

    def test_falls_back_to_contiguous_rows_below_the_minimum(self, layout):
        corpus = synthetic(layout, episodes=1, steps=40)
        train, validation, test = probe_module.split_masks(
            corpus.episode_index, len(corpus)
        )
        assert train.sum() and validation.sum() and test.sum()
        # Contiguous and in order: every train row precedes every test row.
        assert np.flatnonzero(train).max() < np.flatnonzero(test).min()

    def test_no_split_is_shuffled(self, layout):
        """Shuffling puts a test row's near-duplicate neighbour in training."""
        corpus = synthetic(layout)
        train, validation, test = probe_module.split_masks(
            corpus.episode_index, len(corpus)
        )
        for mask in (train, validation, test):
            rows = np.flatnonzero(mask)
            assert np.array_equal(rows, np.sort(rows))

    def test_the_three_splits_partition_the_rows(self, layout):
        corpus = synthetic(layout)
        masks = probe_module.split_masks(corpus.episode_index, len(corpus))
        assert (sum(m.astype(int) for m in masks) <= 1).all()


class TestMetrics:
    def test_r2_of_the_mean_predictor_is_zero(self):
        y = np.array([1.0, 2.0, 3.0, 4.0])
        assert probe_module.r2(y, np.full_like(y, y.mean())) == pytest.approx(0.0)

    def test_r2_of_a_constant_target_is_zero_not_one(self):
        """No variance to explain means no feature set earns credit."""
        y = np.full(5, 3.0)
        assert probe_module.r2(y, y) == 0.0

    def test_balanced_accuracy_of_a_constant_predictor_is_chance(self):
        """The reason it is balanced: `two_sided` is true in almost every step,
        so plain accuracy would score a constant-true predictor ~0.99."""
        y = np.array([1.0] * 99 + [0.0])
        assert probe_module.balanced_accuracy(y, np.ones_like(y)) == pytest.approx(0.5)

    def test_balanced_accuracy_of_a_perfect_predictor_is_one(self):
        y = np.array([1.0, 0.0, 1.0, 0.0])
        assert probe_module.balanced_accuracy(y, y) == pytest.approx(1.0)


class TestFitAndScore:
    def test_a_linearly_readable_target_scores_near_one(self):
        """The floor case: if this does not work, nothing above it means
        anything."""
        rng = np.random.default_rng(0)
        features = rng.normal(size=(400, 5))
        values = features @ np.array([1.0, -2.0, 0.5, 0.0, 3.0])
        groups = np.repeat(np.arange(4), 100)
        result = probe_module.fit_and_score(features, values, "regression", groups)
        assert result is not None
        assert result.score > 0.99

    def test_pure_noise_does_not_score_above_zero(self):
        """With the alpha grid reaching far enough, an unlearnable target falls
        back to the near-mean predictor instead of scoring hugely negative."""
        rng = np.random.default_rng(1)
        features = rng.normal(size=(400, 60))
        values = rng.normal(size=400)
        groups = np.repeat(np.arange(4), 100)
        result = probe_module.fit_and_score(features, values, "regression", groups)
        assert result is not None
        assert result.score < 0.1
        assert result.score > -0.5

    def test_a_single_class_binary_target_is_unscoreable(self):
        """Not 0.5. A row of chance-level numbers in every column reads as a
        finding about the encoders; it is a fact about the corpus."""
        rng = np.random.default_rng(2)
        features = rng.normal(size=(200, 4))
        values = np.ones(200)
        groups = np.repeat(np.arange(4), 50)
        assert probe_module.fit_and_score(features, values, "binary", groups) is None

    def test_a_degenerate_validation_split_is_unscoreable(self):
        """Every alpha ties on an uninformative validation split, so the argmax
        lands on whichever the grid lists first and the test score reports a
        fit nothing selected."""
        rng = np.random.default_rng(5)
        features = rng.normal(size=(400, 4))
        values = rng.normal(size=400)
        groups = np.repeat(np.arange(4), 100)
        # Groups 0-1 train, group 2 validation, group 3 test: flatten only the
        # validation group, leaving train and test perfectly well-formed.
        values[groups == 2] = 0.0
        assert probe_module.fit_and_score(
            features, values, "regression", groups
        ) is None

    def test_a_constant_regression_target_is_unscoreable(self):
        rng = np.random.default_rng(3)
        features = rng.normal(size=(200, 4))
        groups = np.repeat(np.arange(4), 50)
        assert probe_module.fit_and_score(
            features, np.full(200, 7.0), "regression", groups
        ) is None

    def test_too_few_rows_reports_unscoreable_rather_than_zero(self):
        features = np.zeros((2, 3))
        values = np.array([0.0, 1.0])
        assert probe_module.fit_and_score(features, values, "regression") is None

    def test_the_intercept_is_not_penalised(self):
        """A target far from zero must still be fit at the strongest alpha; a
        penalised intercept would shrink every prediction toward the origin."""
        rng = np.random.default_rng(4)
        features = rng.normal(size=(400, 3))
        values = np.full(400, 1000.0) + features[:, 0] * 1e-6
        groups = np.repeat(np.arange(4), 100)
        result = probe_module.fit_and_score(
            features, values, "regression", groups, alphas=(1e7,)
        )
        assert result is not None
        # The mean predictor is right here; a shrunk intercept would be ~0 and
        # give an enormously negative R^2.
        assert result.score > -1.0


# --- The report --------------------------------------------------------------

class TestReport:
    def test_every_feature_set_is_scored_on_identical_rows(self, layout):
        """Two sets scored on different subsets differ by the subset as much as
        by the encoding, and nothing in the output would say so."""
        corpus = synthetic(layout)
        features = {
            "raw": corpus.obs.astype(np.float64),
            "half": corpus.obs[:, : layout.snapshot_dim].astype(np.float64),
        }
        rows = report_module.run(corpus, features, ["mid_return"], [2])
        assert rows
        for row in rows:
            scored = [r for r in row.results.values() if r is not None]
            assert len({(r.n_train, r.n_test) for r in scored}) == 1

    def test_a_misaligned_feature_set_raises(self, layout):
        corpus = synthetic(layout)
        with pytest.raises(ValueError, match="rows for a corpus of"):
            report_module.run(
                corpus, {"short": np.zeros((3, 2))}, ["mid_return"], [1]
            )

    def test_a_target_below_its_min_horizon_is_skipped_not_fatal(self, layout):
        """A horizon list is a sweep; one target declining one horizon should
        not end it."""
        corpus = synthetic(layout)
        features = {"raw": corpus.obs.astype(np.float64)}
        rows = report_module.run(
            corpus, features, ["realized_vol", "mid_return"], [1, 3]
        )
        pairs = {(row.target, row.horizon) for row in rows}
        assert ("realized_vol", 1) not in pairs
        assert ("realized_vol", 3) in pairs
        assert ("mid_return", 1) in pairs

    def test_a_tie_names_no_winner(self, layout):
        """Scores inside the harness's own run-to-run variation get reordered
        by a different seed, so naming one would not reproduce."""
        corpus = synthetic(layout)
        features = {"a": corpus.obs.astype(np.float64)}
        rows = report_module.run(corpus, features, ["mid_return"], [2])
        row = rows[0]
        tied = report_module.Row(
            target=row.target, kind=row.kind, metric=row.metric,
            describe=row.describe, horizon=row.horizon, n_rows=row.n_rows,
            results={"a": row.results["a"], "b": row.results["a"]},
        )
        assert tied.best is None

    def test_render_marks_unscoreable_cells_distinctly_from_zero(self, layout):
        corpus = synthetic(layout)
        features = {"raw": corpus.obs.astype(np.float64)}
        rows = report_module.run(corpus, features, ["mid_return"], [2])
        rendered = report_module.render(
            [report_module.Row(
                target="t", kind="regression", metric="r2", describe="d",
                horizon=1, n_rows=0, results={"raw": None},
            )] + list(rows),
            ["raw"],
        )
        assert "| - |" in rendered
        assert "tie" in rendered

    def test_render_of_nothing_says_so(self):
        assert "No target" in report_module.render([], ["raw"])


# --- The corpus --------------------------------------------------------------

class TestCorpusValidation:
    def test_a_width_the_layout_disagrees_with_raises(self, layout):
        with pytest.raises(ValueError, match="floats wide but the layout"):
            ProbeCorpus(
                obs=np.zeros((4, layout.flat_dim + 1), dtype=np.float32),
                episode_index=np.zeros(4, dtype=np.int32),
                layout=layout,
            )

    def test_a_mismatched_episode_index_raises(self, layout):
        with pytest.raises(ValueError, match="episode_index"):
            ProbeCorpus(
                obs=np.zeros((4, layout.flat_dim), dtype=np.float32),
                episode_index=np.zeros(3, dtype=np.int32),
                layout=layout,
            )

    def test_missing_parquet_raises_rather_than_returning_empty(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="parquet"):
            corpus_module.from_parquet(str(tmp_path))


def write_parquet(path, layout, episodes=3, steps=6, agents=4):
    """A file shaped like `episode_record`'s output: one row per (ep, step, agent)."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    obs, episode_id, step_no, agent_id = [], [], [], []
    for episode in range(episodes):
        for step in range(steps):
            for agent in range(agents):
                # A shared book prefix and a per-agent tail, as the env now
                # emits: the rows at one step are NOT identical any more, which
                # is what makes "keep one per step" a choice rather than a
                # lossless collapse.
                row = np.full(layout.flat_dim, float(episode * 100 + step),
                              dtype=np.float32)
                row[layout.book_flat_dim:] = float(agent)
                obs.append(row.tolist())
                episode_id.append(f"ep-{episode}")
                step_no.append(step)
                agent_id.append(f"agent_{agent}")

    pq.write_table(
        pa.table({
            "obs": pa.array(obs, type=pa.list_(pa.float32())),
            "episode_id": pa.array(episode_id, type=pa.string()),
            "step": pa.array(step_no, type=pa.int32()),
            "agent_id": pa.array(agent_id, type=pa.string()),
        }),
        path,
    )


class TestParquetCorpus:
    def test_one_row_per_step_by_default(self, layout, tmp_path):
        """`episode_record` writes one row per (episode, step, agent).

        The rows at one step share a book prefix and differ only in their
        private tail, while every target is a public book quantity - so keeping
        all of them multiplies the corpus without adding an independent
        observation of anything scored, and puts near-identical rows across the
        held-out split.
        """
        file = tmp_path / "record.parquet"
        write_parquet(str(file), layout, episodes=3, steps=6, agents=4)
        corpus = corpus_module.from_parquet(str(file))
        assert len(corpus) == 3 * 6
        assert corpus.num_episodes == 3

    def test_per_agent_keeps_every_row(self, layout, tmp_path):
        """For pretraining, where the private block is part of what the
        objective encodes rather than an input to a book target."""
        file = tmp_path / "record.parquet"
        write_parquet(str(file), layout, episodes=3, steps=6, agents=4)
        corpus = corpus_module.from_parquet(str(file), per_agent=True)

        assert len(corpus) == 3 * 6 * 4
        tails = corpus.obs[:, layout.book_flat_dim:]
        assert len(np.unique(tails[:, 0])) == 4

    def test_the_rows_at_one_step_are_not_identical(self, layout, tmp_path):
        """The premise the old deduplication rested on, which S1-2's fix
        removed: agents no longer see the byte-identical vector."""
        file = tmp_path / "record.parquet"
        write_parquet(str(file), layout, episodes=1, steps=2, agents=4)
        corpus = corpus_module.from_parquet(str(file), per_agent=True)

        first_step = corpus.obs[:4]
        book = first_step[:, :layout.book_flat_dim]
        tail = first_step[:, layout.book_flat_dim:]
        assert np.array_equal(book, np.tile(book[0], (4, 1)))   # shared prefix
        assert len(np.unique(tail[:, 0])) == 4                  # distinct tails

    def test_rows_come_back_in_episode_then_step_order(self, layout, tmp_path):
        file = tmp_path / "record.parquet"
        write_parquet(str(file), layout, episodes=3, steps=6, agents=2)
        corpus = corpus_module.from_parquet(str(file))
        # The synthetic value encodes episode*100 + step, so a correctly
        # ordered corpus is strictly increasing within an episode.
        values = corpus.obs[:, 0]
        for episode in range(3):
            rows = values[corpus.episode_index == episode]
            assert np.array_equal(rows, np.sort(rows))

    def test_reads_a_directory_of_files(self, layout, tmp_path):
        nested = tmp_path / "run" / "episodes"
        nested.mkdir(parents=True)
        write_parquet(str(nested / "a.parquet"), layout, episodes=2, steps=4)
        write_parquet(str(nested / "b.parquet"), layout, episodes=2, steps=4)
        # Both files carry the same episode ids, so deduplication collapses
        # them - which is the correct answer for a re-written episode.
        corpus = corpus_module.from_parquet(str(tmp_path))
        assert len(corpus) == 2 * 4

    def test_max_rows_caps_the_read(self, layout, tmp_path):
        file = tmp_path / "record.parquet"
        write_parquet(str(file), layout, episodes=4, steps=10, agents=2)
        assert len(corpus_module.from_parquet(str(file), max_rows=7)) == 7

    def test_a_file_with_no_usable_observation_raises(self, tmp_path):
        import pyarrow as pa
        import pyarrow.parquet as pq

        file = tmp_path / "empty.parquet"
        pq.write_table(
            pa.table({
                "obs": pa.array([[], []], type=pa.list_(pa.float32())),
                "episode_id": pa.array(["ep-0", "ep-0"], type=pa.string()),
                "step": pa.array([0, 1], type=pa.int32()),
                "agent_id": pa.array(["agent_0", "agent_0"], type=pa.string()),
            }),
            str(file),
        )
        with pytest.raises(ValueError, match="No usable observation"):
            corpus_module.from_parquet(str(file))
