"""Checkpoint retention, restore selection, and what survives the round trip.

Every save used to be written to the single `chkpt/` directory, so a run had
exactly one recoverable state; a restore then rebuilt everything from the
checkpoint's own config while silently discarding config edits, restarted the
driver's iteration count at zero, and handed the caller a freshly built callback
holding an empty champion pool. These tests pin the fixes.

See doc/20_colab.md 20.5 and doc/15_findings_and_recommendations.md S3-8/S3-11.
"""
import json
import logging
import os
import time
from dataclasses import replace as dataclasses_replace
from types import SimpleNamespace

import pytest

from gym_continuousDoubleAuction.logging_setup import ROOT_NAME as LOGGER
from gym_continuousDoubleAuction.train import train as train_mod
from gym_continuousDoubleAuction.train.train import (
    CHECKPOINT_PREFIX,
    CHECKPOINT_TMP_SUFFIX,
    LEAGUE_STATE_FILE,
    TrainConfig,
    _check_restored_config,
    algo_callback,
    list_checkpoints,
    restore_candidates,
    save_checkpoint,
    train,
    warn_about_foreign_checkpoints,
)
from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import (
    SelfPlayCallback,
)


def _write_checkpoint(path, marker="x"):
    """The minimum that makes a directory look like an RLlib checkpoint."""
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "rllib_checkpoint.json"), "w") as fh:
        json.dump({"marker": marker}, fh)
    return path


def _write_stale_checkpoint(root, iteration, age_s=3600):
    """A checkpoint an earlier run left behind, backdated so it looks it.

    Retention ranks by mtime, and a test that wrote these in the same second as
    the run's own save would be ranking on a tie.
    """
    path = _write_checkpoint(
        os.path.join(root, f"{CHECKPOINT_PREFIX}{iteration:05d}"), marker="stale"
    )
    stamp = time.time() - age_s
    os.utime(path, (stamp, stamp))
    return path


class FakeAlgo:
    """Enough of an Algorithm for the loop and the save path.

    `iteration` advances the way RLlib's does, and is what a restore brings
    back - the property the driver loop now reads instead of counting from zero.
    """

    def __init__(self, callback=None, start_iteration=0):
        self.iteration = start_iteration
        self.callbacks = [callback] if callback else []
        self.saved = []

    def train(self):
        self.iteration += 1
        return {"training_iteration": self.iteration}

    def save(self, path):
        self.saved.append(path)
        return _write_checkpoint(path, marker=str(self.iteration))


@pytest.fixture
def cfg(tmp_path):
    return TrainConfig(log_base_dir=str(tmp_path / "results"), chkpt_keep=3)


class TestCheckpointDiscovery:

    def test_orders_oldest_first_and_ignores_partial_saves(self, tmp_path):
        root = str(tmp_path)
        _write_checkpoint(os.path.join(root, f"{CHECKPOINT_PREFIX}00010"))
        _write_checkpoint(os.path.join(root, f"{CHECKPOINT_PREFIX}00002"))
        # A save killed partway through: staged, never renamed into place.
        _write_checkpoint(
            os.path.join(root, f"{CHECKPOINT_PREFIX}00011{CHECKPOINT_TMP_SUFFIX}")
        )
        # A directory that is not a checkpoint at all.
        os.makedirs(os.path.join(root, f"{CHECKPOINT_PREFIX}00003"))

        assert [i for i, _ in list_checkpoints(root)] == [2, 10]

    def test_old_single_directory_layout_sorts_oldest(self, tmp_path):
        root = _write_checkpoint(str(tmp_path))
        found = list_checkpoints(root)
        assert found == [(-1, root)]

        _write_checkpoint(os.path.join(root, f"{CHECKPOINT_PREFIX}00001"))
        # Still a candidate, but never preferred over a save whose iteration is known.
        assert [i for i, _ in list_checkpoints(root)] == [-1, 1]

    def test_missing_root_is_not_an_error(self, tmp_path):
        assert list_checkpoints(str(tmp_path / "nope")) == []


class TestRetention:

    def test_each_save_is_its_own_directory(self, cfg):
        algo = FakeAlgo()
        for iteration in (1, 2):
            save_checkpoint(algo, cfg, iteration)

        assert [i for i, _ in list_checkpoints(cfg.checkpoint_dir)] == [1, 2]

    def test_prunes_oldest_beyond_keep(self, cfg):
        cfg = TrainConfig(log_base_dir=cfg.log_base_dir, chkpt_keep=2)
        algo = FakeAlgo()
        for iteration in range(1, 6):
            save_checkpoint(algo, cfg, iteration)

        assert [i for i, _ in list_checkpoints(cfg.checkpoint_dir)] == [4, 5]

    def test_keep_zero_retains_everything(self, cfg):
        cfg = TrainConfig(log_base_dir=cfg.log_base_dir, chkpt_keep=0)
        algo = FakeAlgo()
        for iteration in range(1, 5):
            save_checkpoint(algo, cfg, iteration)

        assert len(list_checkpoints(cfg.checkpoint_dir)) == 4

    def test_old_layout_checkpoint_is_never_pruned(self, cfg):
        cfg = TrainConfig(log_base_dir=cfg.log_base_dir, chkpt_keep=1)
        _write_checkpoint(cfg.checkpoint_dir)
        algo = FakeAlgo()
        for iteration in (1, 2):
            save_checkpoint(algo, cfg, iteration)

        assert [i for i, _ in list_checkpoints(cfg.checkpoint_dir)] == [-1, 2]

    def test_a_stale_higher_numbered_save_never_prunes_a_fresh_one(self, cfg):
        """The bug both GPU runs of 2026-08-15 hit, in miniature.

        A fresh run reaching iteration 2 in a directory left holding
        `iter_00012/14/16` used to prune by iteration number, so the save it had
        just written was the "oldest" of four and was deleted microseconds after
        the rename that made it real - leaving the previous run's checkpoints as
        the only recoverable state.
        """
        cfg = TrainConfig(log_base_dir=cfg.log_base_dir, chkpt_keep=3)
        for iteration in (12, 14, 16):
            _write_stale_checkpoint(cfg.checkpoint_dir, iteration)

        save_checkpoint(FakeAlgo(), cfg, 2)

        surviving = [i for i, _ in list_checkpoints(cfg.checkpoint_dir)]
        assert 2 in surviving, (
            "the checkpoint this run just wrote was pruned in favour of an "
            "earlier run's"
        )
        # Retention is still `keep`, and the one dropped is the least recently
        # written of the strangers.
        assert surviving == [2, 14, 16]

    def test_prunes_the_least_recently_written(self, cfg):
        cfg = TrainConfig(log_base_dir=cfg.log_base_dir, chkpt_keep=2)
        _write_stale_checkpoint(cfg.checkpoint_dir, 30, age_s=7200)
        _write_stale_checkpoint(cfg.checkpoint_dir, 40, age_s=3600)

        save_checkpoint(FakeAlgo(), cfg, 1)

        assert [i for i, _ in list_checkpoints(cfg.checkpoint_dir)] == [1, 40]

    def test_save_is_staged_then_renamed(self, cfg):
        """The rename is what makes an interrupted save non-destructive."""
        seen = {}

        class Interrupting(FakeAlgo):
            def save(self, path):
                seen["path"] = path
                return super().save(path)

        save_checkpoint(Interrupting(), cfg, 7)

        assert seen["path"].endswith(CHECKPOINT_TMP_SUFFIX)
        assert not os.path.exists(seen["path"])
        assert os.path.isdir(os.path.join(cfg.checkpoint_dir, f"{CHECKPOINT_PREFIX}00007"))

    def test_resaving_an_iteration_replaces_it(self, cfg):
        """A restored run reaching an iteration it already saved."""
        save_checkpoint(FakeAlgo(start_iteration=3), cfg, 3)
        save_checkpoint(FakeAlgo(start_iteration=99), cfg, 3)

        path = os.path.join(cfg.checkpoint_dir, f"{CHECKPOINT_PREFIX}00003")
        with open(os.path.join(path, "rllib_checkpoint.json")) as fh:
            assert json.load(fh)["marker"] == "99"


class TestLeagueSidecar:

    def test_written_beside_every_checkpoint(self, cfg):
        callback = SelfPlayCallback(num_trainable_policies=2, num_random_policies=2)
        callback.champion_history = [
            {"id": "champion_1", "source_policy": "policy_0",
             "iteration": 3, "return": 12.5},
        ]
        callback.champion_count = 1
        callback.champion_id_counter = 1
        callback.available_modules.append("champion_1")

        path = save_checkpoint(FakeAlgo(callback=callback), cfg, 4)

        with open(os.path.join(path, LEAGUE_STATE_FILE)) as fh:
            state = json.load(fh)
        assert state["champion_id_counter"] == 1
        assert [c["id"] for c in state["champion_history"]] == ["champion_1"]
        assert state["training_iteration"] == 4

    def test_algo_callback_finds_the_live_instance(self):
        callback = SelfPlayCallback(num_trainable_policies=1, num_random_policies=1)
        assert algo_callback(FakeAlgo(callback=callback)) is callback
        assert algo_callback(FakeAlgo()) is None


class TestLeagueStateReconciliation:
    """`restore_league_state` against the three sources that can disagree."""

    def _callback(self):
        return SelfPlayCallback(num_trainable_policies=2, num_random_policies=2)

    def _with_champions(self, callback, ids):
        callback.champion_history = [
            {"id": i, "source_policy": "policy_0", "iteration": 1, "return": 1.0}
            for i in ids
        ]
        callback.champion_count = len(ids)
        callback.champion_id_counter = len(ids)
        callback.available_modules = [f"policy_{i}" for i in range(4)] + list(ids)
        return callback

    def test_agreement_repairs_nothing(self):
        callback = self._with_champions(self._callback(), ["champion_1"])
        state = callback.league_state()

        repairs = callback.restore_league_state(
            state, present_modules={"policy_0", "policy_1", "champion_1"}
        )

        assert repairs == []
        assert callback.champion_count == 1

    def test_sidecar_repairs_a_callback_that_lost_its_history(self):
        """The unpickling-drift case: modules came back, bookkeeping did not."""
        saved = self._with_champions(self._callback(), ["champion_1", "champion_2"])
        state = saved.league_state()

        drifted = self._callback()  # fresh __init__, empty league
        repairs = drifted.restore_league_state(
            state, present_modules={"policy_0", "champion_1", "champion_2"}
        )

        assert repairs
        assert [c["id"] for c in drifted.champion_history] == ["champion_1", "champion_2"]
        assert drifted.available_modules[-2:] == ["champion_1", "champion_2"]
        assert drifted.champion_count == 2

    def test_counter_never_goes_backwards(self):
        """A restarted counter re-mints IDs and overwrites a live champion."""
        drifted = self._callback()
        state = {"champion_id_counter": 0, "champion_history": []}

        drifted.restore_league_state(state, present_modules={"champion_1", "champion_2"})

        assert drifted.champion_id_counter == 2

    def test_champion_without_a_module_is_dropped(self):
        callback = self._with_champions(self._callback(), ["champion_1", "champion_2"])
        state = callback.league_state()

        repairs = callback.restore_league_state(
            state, present_modules={"policy_0", "champion_1"}
        )

        assert any("champion_2" in r for r in repairs)
        assert [c["id"] for c in callback.champion_history] == ["champion_1"]
        assert "champion_2" not in callback.available_modules
        assert callback.champion_count == 1

    def test_module_without_a_champion_entry_is_adopted(self):
        callback = self._with_champions(self._callback(), ["champion_1"])
        state = callback.league_state()

        repairs = callback.restore_league_state(
            state, present_modules={"champion_1", "champion_5"}
        )

        assert any("champion_5" in r for r in repairs)
        assert "champion_5" in callback.available_modules
        # Adopting must not let the counter re-issue champion_5.
        assert callback.champion_id_counter == 5

    def test_unknown_module_list_still_protects_the_counter(self):
        callback = self._callback()
        state = {"champion_id_counter": 7, "champion_history": []}

        callback.restore_league_state(state, present_modules=None)

        assert callback.champion_id_counter == 7


class TestRestoredConfigCheck:
    """A restore rebuilds from the checkpoint's config and ignores the file's."""

    def _config(self, **overrides):
        values = {
            "lr": 5e-05,
            "num_epochs": 4,
            "minibatch_size": None,
            "train_batch_size_per_learner": 128,
            "num_env_runners": 0,
            "num_envs_per_env_runner": 1,
            "num_learners": 0,
            "num_gpus_per_learner": 0.0,
            "policies": ["policy_0", "policy_1"],
            "policies_to_train": ["policy_0"],
            "env_config": {"num_of_agents": 2, "n_hist": 4, "order_penalty": 0.1},
        }
        env_overrides = overrides.pop("env_config", {})
        values.update(overrides)
        values["env_config"] = {**values["env_config"], **env_overrides}
        return SimpleNamespace(**values)

    def test_identical_config_says_nothing(self, caplog):
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            _check_restored_config(self._config(), self._config())
        assert caplog.text == ""

    def test_ignored_edits_are_reported(self, caplog):
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            _check_restored_config(
                self._config(),
                self._config(lr=0.001, env_config={"order_penalty": 0.9}),
            )

        assert any(r.levelno == logging.WARNING for r in caplog.records)
        assert "lr" in caplog.text and "0.001" in caplog.text
        assert "env_config.order_penalty" in caplog.text

    def test_shape_changing_edits_are_fatal(self):
        with pytest.raises(ValueError, match="shape of the problem"):
            _check_restored_config(
                self._config(),
                self._config(
                    policies=["policy_0", "policy_1", "policy_2"],
                    env_config={"num_of_agents": 3},
                ),
            )

    def test_champions_are_not_a_config_change(self, capsys):
        """The league grows `policies` during a run; that is not an edit."""
        restored = self._config(
            policies=["policy_0", "policy_1", "champion_1", "champion_2"]
        )

        _check_restored_config(restored, self._config())

        assert capsys.readouterr().out == ""


class TestRestoreCandidates:
    """`restore_path` selects the checkpoint; `is_restore` still gates restoring."""

    def test_none_means_every_checkpoint_newest_last(self, cfg):
        for iteration in (1, 2):
            save_checkpoint(FakeAlgo(), cfg, iteration)

        candidates = restore_candidates(dataclasses_replace(cfg, is_restore=True))

        assert [i for i, _ in candidates] == [1, 2]

    def test_a_path_narrows_it_to_that_one(self, cfg):
        for iteration in (1, 2):
            save_checkpoint(FakeAlgo(), cfg, iteration)
        pinned = os.path.join(cfg.checkpoint_dir, f"{CHECKPOINT_PREFIX}00001")

        candidates = restore_candidates(
            dataclasses_replace(cfg, is_restore=True, restore_path=pinned)
        )

        assert candidates == [(1, pinned)]

    def test_not_restoring_ignores_the_tree(self, cfg):
        save_checkpoint(FakeAlgo(), cfg, 1)

        assert restore_candidates(dataclasses_replace(cfg, is_restore=False)) == []

    def test_a_path_without_is_restore_raises(self, cfg):
        """Otherwise the run silently starts from scratch."""
        save_checkpoint(FakeAlgo(), cfg, 1)
        pinned = os.path.join(cfg.checkpoint_dir, f"{CHECKPOINT_PREFIX}00001")

        with pytest.raises(ValueError, match="is_restore is false"):
            restore_candidates(
                dataclasses_replace(cfg, is_restore=False, restore_path=pinned)
            )

    def test_a_path_that_is_not_a_checkpoint_lists_the_ones_that_are(self, cfg):
        for iteration in (1, 2):
            save_checkpoint(FakeAlgo(), cfg, iteration)

        with pytest.raises(ValueError) as excinfo:
            restore_candidates(
                dataclasses_replace(
                    cfg, is_restore=True, restore_path=cfg.checkpoint_dir
                )
            )

        message = str(excinfo.value)
        assert "not a checkpoint directory" in message
        assert f"{CHECKPOINT_PREFIX}00002" in message  # newest listed first
        assert message.index(f"{CHECKPOINT_PREFIX}00002") < message.index(
            f"{CHECKPOINT_PREFIX}00001"
        )

    def test_a_missing_path_says_so_even_with_no_checkpoints(self, cfg):
        with pytest.raises(ValueError, match="none under"):
            restore_candidates(
                dataclasses_replace(cfg, is_restore=True, restore_path="/nope")
            )


class TestCommandLine:

    def test_from_checkpoint_implies_restore(self):
        cfg = train_mod._parse_args(["--from-checkpoint", "results/chkpt/iter_00008"])

        assert cfg.restore_path == "results/chkpt/iter_00008"
        assert cfg.is_restore is True

    def test_restore_alone_leaves_the_path_unset(self):
        cfg = train_mod._parse_args(["--restore"])

        assert cfg.is_restore is True
        assert cfg.restore_path is None


class TestForeignCheckpoints:
    """What a fresh run says about the saves it is about to write alongside.

    Nothing is deleted: the directory belongs to the operator. But until the run
    passes those iteration numbers, `list_checkpoints` reports a stranger as the
    newest, so an interrupted run restored with `--restore` resumes someone
    else's weights - which is how the run that trained on nothing could have
    been picked up as if it were the good one.
    """

    def test_names_them_newest_first(self, cfg, caplog):
        for iteration in (12, 14, 16):
            _write_stale_checkpoint(cfg.checkpoint_dir, iteration)

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            stale = warn_about_foreign_checkpoints(cfg)

        assert [os.path.basename(p) for p in stale] == [
            f"{CHECKPOINT_PREFIX}00016",
            f"{CHECKPOINT_PREFIX}00014",
            f"{CHECKPOINT_PREFIX}00012",
        ]
        assert f"{CHECKPOINT_PREFIX}00016" in caplog.text
        assert caplog.text.index(f"{CHECKPOINT_PREFIX}00016") < caplog.text.index(
            f"{CHECKPOINT_PREFIX}00012"
        )

    def test_an_empty_directory_says_nothing(self, cfg, caplog):
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            assert warn_about_foreign_checkpoints(cfg) == []
        assert caplog.text == ""

    def test_a_restoring_run_is_not_warned(self, cfg, caplog):
        """Those checkpoints are the point of the run, not a hazard."""
        _write_stale_checkpoint(cfg.checkpoint_dir, 16)

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            stale = warn_about_foreign_checkpoints(
                dataclasses_replace(cfg, is_restore=True)
            )

        assert stale == []
        assert caplog.text == ""

    def test_build_algo_warns_on_the_scratch_path(self, cfg, monkeypatch, caplog):
        _write_stale_checkpoint(cfg.checkpoint_dir, 16)
        monkeypatch.setattr(
            train_mod, "build_config",
            lambda _cfg: (SimpleNamespace(build_algo=FakeAlgo), None),
        )

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            train_mod.build_algo(cfg)

        assert f"{CHECKPOINT_PREFIX}00016" in caplog.text


class TestRestoreSelection:
    """Which checkpoint a restore picks, and what it hands back."""

    @pytest.fixture
    def restorable(self, cfg, monkeypatch):
        """`build_algo` with the env build and RLlib's loader stubbed out."""
        callback = SelfPlayCallback(num_trainable_policies=2, num_random_policies=2)
        fresh = SelfPlayCallback(num_trainable_policies=2, num_random_policies=2)
        config = SimpleNamespace(
            env_config={},
            policies=["policy_0"],
            build_algo=lambda: FakeAlgo(callback=fresh),
        )

        monkeypatch.setattr(train_mod, "build_config", lambda _cfg: (config, fresh))
        monkeypatch.setattr(train_mod, "_fix_checkpoint_optimizer_betas", lambda _a: None)

        loaded = []

        def from_checkpoint(path):
            loaded.append(path)
            if unreadable and path.endswith(unreadable):
                raise RuntimeError("truncated checkpoint")
            algo = FakeAlgo(callback=callback)
            algo.config = config
            return algo

        unreadable = None
        monkeypatch.setattr(
            train_mod, "Algorithm", SimpleNamespace(from_checkpoint=from_checkpoint)
        )

        def configure(broken=None):
            nonlocal unreadable
            unreadable = broken
            return loaded

        return SimpleNamespace(
            cfg=cfg, callback=callback, fresh=fresh, configure=configure
        )

    def test_restores_the_newest(self, restorable):
        cfg = restorable.cfg
        for iteration in (1, 2, 3):
            save_checkpoint(FakeAlgo(), cfg, iteration)
        loaded = restorable.configure()

        train_mod.build_algo(dataclasses_replace(cfg, is_restore=True))

        assert loaded[-1].endswith(f"{CHECKPOINT_PREFIX}00003")

    def test_falls_back_when_the_newest_is_unreadable(self, restorable):
        """A save interrupted mid-write must not cost the whole run."""
        cfg = restorable.cfg
        for iteration in (1, 2, 3):
            save_checkpoint(FakeAlgo(), cfg, iteration)
        loaded = restorable.configure(broken=f"{CHECKPOINT_PREFIX}00003")

        algo, _ = train_mod.build_algo(dataclasses_replace(cfg, is_restore=True))

        assert algo is not None
        assert [os.path.basename(p) for p in loaded] == [
            f"{CHECKPOINT_PREFIX}00003", f"{CHECKPOINT_PREFIX}00002"
        ]

    def test_returns_the_algorithms_own_callback(self, restorable):
        """Not the freshly built decoy, whose champion pool is always empty."""
        cfg = restorable.cfg
        save_checkpoint(FakeAlgo(), cfg, 1)
        restorable.configure()

        algo, callback = train_mod.build_algo(dataclasses_replace(cfg, is_restore=True))

        assert callback is restorable.callback
        assert callback is algo_callback(algo)

    def test_restore_path_pins_one_checkpoint(self, restorable):
        cfg = restorable.cfg
        for iteration in (1, 2, 3):
            save_checkpoint(FakeAlgo(), cfg, iteration)
        loaded = restorable.configure()
        pinned = os.path.join(cfg.checkpoint_dir, f"{CHECKPOINT_PREFIX}00001")

        train_mod.build_algo(
            dataclasses_replace(cfg, is_restore=True, restore_path=pinned)
        )

        assert loaded == [pinned]

    def test_a_pinned_checkpoint_never_falls_back(self, restorable):
        """Silently training from a different checkpoint defeats the point."""
        cfg = restorable.cfg
        for iteration in (1, 2):
            save_checkpoint(FakeAlgo(), cfg, iteration)
        restorable.configure(broken=f"{CHECKPOINT_PREFIX}00002")
        pinned = os.path.join(cfg.checkpoint_dir, f"{CHECKPOINT_PREFIX}00002")

        with pytest.raises(RuntimeError, match="truncated checkpoint"):
            train_mod.build_algo(
                dataclasses_replace(cfg, is_restore=True, restore_path=pinned)
            )

    def test_no_checkpoint_starts_from_scratch(self, restorable, caplog):
        restorable.configure()

        with caplog.at_level(logging.INFO, logger=LOGGER):
            algo, callback = train_mod.build_algo(
                dataclasses_replace(restorable.cfg, is_restore=True)
            )

        assert isinstance(algo, FakeAlgo)
        assert callback is restorable.fresh
        assert "starting from scratch" in caplog.text


class TestIterationAccounting:

    def _run(self, cfg, monkeypatch, start_iteration=0, callback=None):
        algo = FakeAlgo(callback=callback, start_iteration=start_iteration)
        monkeypatch.setattr(train_mod, "build_algo", lambda _cfg: (algo, callback))
        train(cfg)
        return algo

    def test_num_iters_is_a_target_not_an_amount(self, cfg, monkeypatch):
        cfg = TrainConfig(log_base_dir=cfg.log_base_dir, num_iters=16, chkpt_freq=0)
        algo = self._run(cfg, monkeypatch, start_iteration=9)

        assert algo.iteration == 16  # 7 more, not 16 more

    def test_delta_mode_counts_from_the_restore_point(self, cfg, monkeypatch):
        cfg = TrainConfig(
            log_base_dir=cfg.log_base_dir,
            num_iters=4,
            num_iters_is_delta=True,
            chkpt_freq=0,
        )
        algo = self._run(cfg, monkeypatch, start_iteration=9)

        assert algo.iteration == 13

    def test_a_completed_run_does_no_further_training(self, cfg, monkeypatch, caplog):
        cfg = TrainConfig(log_base_dir=cfg.log_base_dir, num_iters=5, chkpt_freq=0)
        with caplog.at_level(logging.INFO, logger=LOGGER):
            algo = self._run(cfg, monkeypatch, start_iteration=5)

        assert algo.iteration == 5
        assert algo.saved == []
        assert "nothing to do" in caplog.text

    def test_checkpoints_land_on_true_iteration_numbers(self, cfg, monkeypatch):
        cfg = TrainConfig(
            log_base_dir=cfg.log_base_dir, num_iters=8, chkpt_freq=2, chkpt_keep=0
        )
        self._run(cfg, monkeypatch, start_iteration=3)

        # 3 -> 8, saving on the even iterations, plus the final one.
        assert [i for i, _ in list_checkpoints(cfg.checkpoint_dir)] == [4, 6, 8]

    def test_final_save_is_not_duplicated(self, cfg, monkeypatch):
        cfg = TrainConfig(
            log_base_dir=cfg.log_base_dir, num_iters=4, chkpt_freq=2, chkpt_keep=0
        )
        algo = self._run(cfg, monkeypatch)

        assert len(algo.saved) == 2  # iters 2 and 4, not 4 again at the end


class TestTrainReturnsTheLastResult:
    """`train()` hands back the final iteration's result along with the algo.

    It used to return only the Algorithm, so reading the league meant calling
    `algo.train()` again - a whole extra iteration of sampling and learning, run
    for its return value, outside the checkpointing this loop does.
    """

    def _train(self, cfg, monkeypatch, start_iteration=0):
        algo = FakeAlgo(start_iteration=start_iteration)
        monkeypatch.setattr(train_mod, "build_algo", lambda _cfg: (algo, None))
        return train(cfg)

    def test_result_is_the_last_iterations(self, cfg, monkeypatch):
        cfg = TrainConfig(log_base_dir=cfg.log_base_dir, num_iters=3, chkpt_freq=0)
        algo, result = self._train(cfg, monkeypatch)

        assert algo.iteration == 3
        assert result == {"training_iteration": 3}

    def test_a_completed_run_returns_an_empty_result(self, cfg, monkeypatch):
        cfg = TrainConfig(log_base_dir=cfg.log_base_dir, num_iters=5, chkpt_freq=0)
        algo, result = self._train(cfg, monkeypatch, start_iteration=5)

        assert result == {}


class TestEmptyIterationIsReported:
    """An iteration whose result carries no `env_runners` block trained on
    nothing - the samples timed out and were discarded - and says so.

    Left unsaid, the loop counts the iteration, checkpoints, and produces a run
    whose weights never moved. FakeAlgo's result has no env_runners block, which
    is exactly the shape RLlib returns when `sample_timeout_s` elapses.
    """

    def _train(self, cfg, monkeypatch):
        monkeypatch.setattr(
            train_mod, "build_algo", lambda _cfg: (FakeAlgo(), None)
        )
        return train(cfg)

    def test_warns_and_names_the_timeout(self, cfg, monkeypatch, caplog):
        cfg = TrainConfig(
            log_base_dir=cfg.log_base_dir,
            num_iters=1,
            chkpt_freq=0,
            num_env_runners=2,
            sample_timeout_s=17.0,
        )
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            self._train(cfg, monkeypatch)

        assert "trained on no samples" in caplog.text
        assert "sample_timeout_s=17.0" in caplog.text

    def test_silent_when_sampling_is_in_process(self, cfg, monkeypatch, caplog):
        # num_env_runners=0 samples in the driver, where there is no timeout to
        # miss, so an empty block there means something else entirely.
        cfg = TrainConfig(
            log_base_dir=cfg.log_base_dir,
            num_iters=1,
            chkpt_freq=0,
            num_env_runners=0,
        )
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            self._train(cfg, monkeypatch)

        assert "trained on no samples" not in caplog.text
