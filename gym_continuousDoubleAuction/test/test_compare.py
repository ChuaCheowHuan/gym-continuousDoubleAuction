"""The pure half of `train.compare`: aggregation and rendering.

The training half is `train.train`, which the integration suite already
exercises; these pin what the driver does with the numbers it collects, which
is the part a reader will quote.
"""
import json

import pytest

from gym_continuousDoubleAuction.config_loader import cli_default
from gym_continuousDoubleAuction.train import compare


def _row(encoder, seed, ret, vf, pas=0.1, params=1000, **probe):
    row = {"encoder": encoder, "seed": seed, "return": ret,
           "vf_explained_var": vf, "pass_action_fraction": pas,
           "parameters": params}
    row.update({f"probe:{k}": v for k, v in probe.items()})
    return row


ROWS = [
    _row("mlp", 0, 1.0, 0.5, mid_return_1=0.10),
    _row("mlp", 1, 1.2, 0.6, mid_return_1=0.12),
    _row("mlp", 2, 0.8, 0.4, mid_return_1=0.08),
    _row("transformer", 0, 5.0, 0.7, params=9000, mid_return_1=0.30),
    _row("transformer", 1, 5.2, 0.8, params=9000, mid_return_1=0.31),
    _row("transformer", 2, 4.8, 0.6, params=9000, mid_return_1=0.29),
]


class TestAggregate:

    def test_mean_std_n_per_encoder(self):
        summary = compare.aggregate(ROWS)
        assert summary["mlp"]["return"]["n"] == 3
        assert summary["mlp"]["return"]["mean"] == pytest.approx(1.0)
        assert summary["mlp"]["return"]["std"] == pytest.approx(0.2)
        assert summary["transformer"]["parameters"]["mean"] == 9000

    def test_single_seed_has_no_std(self):
        summary = compare.aggregate(ROWS[:1])
        assert summary["mlp"]["return"]["std"] is None
        assert summary["mlp"]["return"]["n"] == 1

    def test_missing_and_non_finite_values_are_skipped(self):
        rows = [_row("mlp", 0, float("nan"), None), _row("mlp", 1, 2.0, 0.5)]
        summary = compare.aggregate(rows)
        assert summary["mlp"]["return"] == {"mean": 2.0, "std": None, "n": 1}
        assert summary["mlp"]["vf_explained_var"]["n"] == 1

    def test_probe_metrics_are_discovered(self):
        assert "probe:mid_return_1" in compare.metric_names(ROWS)


class TestSeparated:

    def test_clear_gap_is_separated(self):
        summary = compare.aggregate(ROWS)
        assert compare.separated(summary, "return") == {"mlp": True, "transformer": True}

    def test_overlapping_spread_is_not(self):
        rows = [_row("a", 0, 1.0, 0.5), _row("a", 1, 3.0, 0.5),
                _row("b", 0, 2.0, 0.5), _row("b", 1, 4.0, 0.5)]
        summary = compare.aggregate(rows)
        assert compare.separated(summary, "return") == {"a": False, "b": False}

    def test_single_seed_never_separates(self):
        rows = [_row("a", 0, 1.0, 0.5), _row("b", 0, 100.0, 0.5)]
        assert compare.separated(compare.aggregate(rows), "return") == {"a": False, "b": False}

    def test_single_encoder_never_separates(self):
        assert compare.separated(compare.aggregate(ROWS[:3]), "return") == {"mlp": False}


class TestRender:

    def test_table_has_a_row_per_encoder_and_the_caveat(self):
        text = compare.render(ROWS)
        lines = text.splitlines()
        assert lines[0].startswith("| encoder | seeds | params | return |")
        assert any(l.startswith("| mlp | 3 | 1,000 |") for l in lines)
        assert any(l.startswith("| transformer | 3 | 9,000 |") for l in lines)
        assert "return, vf_explained_var" in text
        assert "not a significance test" in text
        assert "Fewer than three seeds" not in text

    def test_few_seeds_are_called_a_smoke_test(self):
        text = compare.render(ROWS[:2] + ROWS[3:5])
        assert "Fewer than three seeds" in text
        assert "| nothing |" in text

    def test_summary_is_json_serialisable(self):
        json.dumps(compare.aggregate(ROWS))


def test_cli_defaults_exist():
    for key in ("encoders", "seeds", "num_iters", "out_dir", "probe_episodes",
                "probe_steps", "probe_seed", "targets", "horizons", "module_id",
                "log_level"):
        cli_default("cda_compare", key)
    assert len(cli_default("cda_compare", "seeds")) >= 3
