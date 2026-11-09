"""Tests for config and visualization fixes.

Moved from `test_s4_minor_fixes.py` by issue #361; the class docstrings keep the
original issue numbers.
"""

from decimal import Decimal

import pytest


from gym_continuousDoubleAuction.envs.orderbook.order import Order
from pathlib import Path


def _order(order_list, order_id, qty=1, price=10):
    quote = {
        "timestamp": 1,
        "quantity": Decimal(qty),
        "price": Decimal(price),
        "order_id": order_id,
        "trade_id": "t",
    }
    order = Order(quote, order_list)
    order_list.append_order(order)
    return order


class TestPlatformEnvIsCaseInsensitive:
    """#237: `CDA_USE_GPU` was parsed case-insensitively and `CDA_PLATFORM` was not."""

    @pytest.mark.parametrize("value", ["auto", "Auto", " AUTO "])
    def test_auto_in_any_case_means_detect(self, monkeypatch, value):
        from gym_continuousDoubleAuction.train import runtime

        monkeypatch.setenv("CDA_PLATFORM", value)
        monkeypatch.setattr(runtime, "detect_platform", lambda: "local")
        assert runtime.resolve().platform == "local"

    @pytest.mark.parametrize("value", ["colab", "COLAB", " Colab\n"])
    def test_a_platform_name_in_any_case_is_found(self, monkeypatch, value):
        from gym_continuousDoubleAuction.train import runtime

        monkeypatch.setenv("CDA_PLATFORM", value)
        assert runtime.resolve().platform == "colab"

    def test_an_empty_value_is_unset(self, monkeypatch):
        from gym_continuousDoubleAuction.train import runtime

        monkeypatch.setenv("CDA_PLATFORM", "")
        monkeypatch.setattr(runtime, "detect_platform", lambda: "local")
        assert runtime.resolve().platform == "local"

    def test_an_explicit_argument_is_normalised_too(self):
        from gym_continuousDoubleAuction.train import runtime

        assert runtime.resolve(platform="Docker").platform == "docker"

    def test_an_unknown_platform_is_still_an_error(self, monkeypatch):
        from gym_continuousDoubleAuction.train import runtime

        monkeypatch.setenv("CDA_PLATFORM", "mars")
        with pytest.raises(KeyError, match="mars"):
            runtime.resolve()


class TestConfigDirIgnoresAForeignConfigDirectory:
    """#241: for an installed wheel `<package>/..` is `site-packages`, and any
    other distribution's top-level `config/` was taken for ours."""

    @staticmethod
    def _layout(tmp_path, monkeypatch, *, foreign, packaged, repo_marker=False):
        from gym_continuousDoubleAuction import config_loader

        site = tmp_path / "site-packages"
        pkg = site / "gym_continuousDoubleAuction"
        pkg.mkdir(parents=True)
        if foreign:
            (site / "config").mkdir()
            (site / "config" / "settings.ini").write_text("x")
        if repo_marker:
            (site / "config" / "train_config.json").write_text("{}")
        if packaged:
            (pkg / "config").mkdir()
            (pkg / "config" / "train_config.json").write_text("{}")
        monkeypatch.setattr(config_loader, "_PACKAGE_DIR", pkg)
        monkeypatch.delenv(config_loader.CONFIG_DIR_ENV_VAR, raising=False)
        return config_loader, pkg

    def test_a_foreign_config_directory_is_skipped(self, tmp_path, monkeypatch):
        loader, pkg = self._layout(tmp_path, monkeypatch, foreign=True, packaged=True)
        assert loader.config_dir() == pkg / "config"

    def test_the_repo_layout_still_wins_when_it_is_ours(self, tmp_path, monkeypatch):
        loader, pkg = self._layout(
            tmp_path, monkeypatch, foreign=True, packaged=True, repo_marker=True
        )
        assert loader.config_dir() == pkg.parent / "config"

    def test_only_a_foreign_directory_is_an_error_not_a_wrong_answer(self, tmp_path, monkeypatch):
        loader, _ = self._layout(tmp_path, monkeypatch, foreign=True, packaged=False)
        with pytest.raises(FileNotFoundError, match="train_config.json"):
            loader.config_dir()

    def test_the_real_checkout_resolves(self):
        from gym_continuousDoubleAuction import config_loader

        assert (config_loader.config_dir() / "train_config.json").is_file()


class TestDocSyncSkillDoesNotWriteToTheFilesystemRoot:
    """#265: `"$TMPDIR/facts.json"` expands to `/facts.json` when `TMPDIR` is unset."""

    SKILL = ".claude/skills/cda-doc-sync/SKILL.md"

    def test_every_tmpdir_use_has_a_default(self):
        import re

        text = Path(self.SKILL).read_text(encoding="utf-8")
        uses = re.findall(r"\$\{?TMPDIR[^/\s\"`]*", text)
        assert uses, "the skill no longer mentions TMPDIR; delete this test"
        assert all(use.startswith("${TMPDIR:-") for use in uses), uses

    def test_the_two_steps_name_the_same_file(self):
        import re

        paths = set(
            re.findall(
                r'"(\$\{TMPDIR:-[^}]+\}/facts\.json)"', Path(self.SKILL).read_text(encoding="utf-8")
            )
        )
        assert len(paths) == 1, paths


class TestVisualizeSurvivesBadRecords:
    """#240: an empty recorded observation, or a truncated `progress.jsonl`
    line, aborted the plots."""

    def test_an_empty_observation_is_a_gap_not_an_error(self):
        import numpy as np
        from gym_continuousDoubleAuction.envs.exchg.state_helper import PRIVATE_DIM, SNAPSHOT_DIM
        from gym_continuousDoubleAuction.visualize.visualize_orderbook import _book_sizes

        good = np.ones(SNAPSHOT_DIM + PRIVATE_DIM)
        bids, asks, skipped = _book_sizes([good, [], good])
        assert skipped == 1 and len(bids) == len(asks) == 3
        assert np.isnan(bids[1]) and np.isnan(asks[1])
        assert not np.isnan(bids[0]) and not np.isnan(asks[2])

    def test_a_malformed_non_empty_observation_still_raises(self):
        """Only the recorder's own `[]` is forgiven: a wrong-sized vector means
        the recording and the layout disagree, which the plot must not hide."""
        from gym_continuousDoubleAuction.visualize.visualize_orderbook import _book_sizes

        with pytest.raises(ValueError, match="whole number"):
            _book_sizes([[1.0, 2.0, 3.0]])

    def _progress(self, tmp_path, text):
        path = tmp_path / "progress.jsonl"
        path.write_text(text)
        return str(path)

    def test_a_truncated_last_line_is_skipped_with_a_warning(self, tmp_path):
        from gym_continuousDoubleAuction.visualize.visualize_training import load_progress

        path = self._progress(
            tmp_path, '{"training_iteration": 2}\n{"training_iteration": 1}\n{"training_it'
        )
        with pytest.warns(UserWarning, match="skipped 1 line"):
            rows = load_progress(path)
        assert [r["training_iteration"] for r in rows] == [1, 2]

    def test_a_row_without_an_iteration_is_skipped_not_a_keyerror(self, tmp_path):
        from gym_continuousDoubleAuction.visualize.visualize_training import load_progress

        path = self._progress(tmp_path, '{"training_iteration": 1}\n{"other": 1}\n[1, 2]\n')
        with pytest.warns(UserWarning, match="skipped 2 line"):
            assert len(load_progress(path)) == 1

    def test_a_clean_file_warns_about_nothing(self, tmp_path, recwarn):
        from gym_continuousDoubleAuction.visualize.visualize_training import load_progress

        load_progress(self._progress(tmp_path, '{"training_iteration": 1}\n'))
        assert not [w for w in recwarn if "skipped" in str(w.message)]

    def test_a_file_with_no_complete_row_is_still_an_error(self, tmp_path):
        from gym_continuousDoubleAuction.visualize.visualize_training import load_progress

        with pytest.warns(UserWarning), pytest.raises(ValueError, match="no rows"):
            load_progress(self._progress(tmp_path, '{"training_it'))
