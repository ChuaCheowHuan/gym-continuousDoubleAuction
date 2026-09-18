"""The pure half of `train.export`: choosing a module, and what gets written.

The half that needs a real checkpoint - that `RLModule.from_checkpoint` on the
resolved subdirectory returns the trained network - is
`test/integration/test_export_checkpoint.py`. What is checkable without one is
the part that decides *which* module, which is where a wrong answer is silent:
exporting policy_0 when the user wanted the winner produces a perfectly valid
file of the wrong weights.
"""
import json

import pytest
import torch

from gym_continuousDoubleAuction.config_loader import cli_default
from gym_continuousDoubleAuction.envs.layout_version import LAYOUT_KEY, layout_stamp
from gym_continuousDoubleAuction.train import export
from gym_continuousDoubleAuction.train.train import LEAGUE_STATE_FILE


def _champion(cid, source, iteration, ret):
    return {"id": cid, "source_policy": source, "iteration": iteration, "return": ret}


STATE = {
    "champion_history": [
        _champion("champion_1", "policy_0", 4, -900.0),
        _champion("champion_2", "policy_1", 9, -100.0),
        _champion("champion_3", "policy_0", 14, -400.0),
    ],
    "training_iteration": 16,
    LAYOUT_KEY: layout_stamp(),
}


class _FakeModule(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.pi = torch.nn.Linear(3, 2)


class TestResolveModule:
    def test_no_module_id_picks_the_best_return(self):
        module_id, record = export.resolve_module(STATE, None)
        assert module_id == "champion_2"
        assert record["source_policy"] == "policy_1"

    def test_a_named_module_wins_over_the_champion(self):
        module_id, record = export.resolve_module(STATE, "policy_0")
        assert module_id == "policy_0"
        assert record is None, "policy_0 was never promoted, so it has no record"

    def test_a_named_champion_keeps_its_record(self):
        _module_id, record = export.resolve_module(STATE, "champion_3")
        assert record["iteration"] == 14

    def test_no_champions_is_an_error_that_says_what_to_do(self):
        with pytest.raises(ValueError, match="--module-id"):
            export.resolve_module({"champion_history": []}, None)

    def test_ties_go_to_the_earlier_promotion(self):
        state = {"champion_history": [_champion("champion_1", "policy_0", 2, -5.0),
                                      _champion("champion_2", "policy_1", 8, -5.0)]}
        assert export.resolve_module(state, None)[0] == "champion_1"


class TestSidecar:
    def test_a_missing_sidecar_is_empty_not_fatal(self, tmp_path):
        assert export.read_league_state(str(tmp_path)) == {}

    def test_an_unreadable_sidecar_is_empty_not_fatal(self, tmp_path):
        (tmp_path / LEAGUE_STATE_FILE).write_text("{not json")
        assert export.read_league_state(str(tmp_path)) == {}

    def test_a_good_sidecar_comes_back_whole(self, tmp_path):
        (tmp_path / LEAGUE_STATE_FILE).write_text(json.dumps(STATE))
        assert export.read_league_state(str(tmp_path))["training_iteration"] == 16


class TestLayoutWarning:
    def test_the_current_layout_says_nothing(self):
        assert export.warn_about_layout(STATE) is None

    def test_a_foreign_layout_is_named_but_not_refused(self):
        stale = dict(STATE)
        stale[LAYOUT_KEY] = {**layout_stamp(), "observation_version": 1}
        message = export.warn_about_layout(stale)
        assert message is not None and "observation layout v1" in message

    def test_no_stamp_says_nothing(self):
        assert export.warn_about_layout({}) is None


class TestRecord:
    def test_it_carries_the_stamp_and_the_promotion(self):
        record = export.build_record(
            _FakeModule(), "champion_2", "/tmp/iter_00016", STATE,
            STATE["champion_history"][1],
        )
        assert record["module_id"] == "champion_2"
        assert record["module_class"].endswith("_FakeModule")
        assert record["training_iteration"] == 16
        assert record["promotion"]["source_policy"] == "policy_1"
        assert record[LAYOUT_KEY] == layout_stamp()
        assert set(record["state_dict"]) == {"pi.weight", "pi.bias"}

    def test_the_weights_are_detached_cpu_tensors(self):
        record = export.build_record(_FakeModule(), "policy_0", ".", {}, None)
        for tensor in record["state_dict"].values():
            assert not tensor.requires_grad
            assert tensor.device.type == "cpu"

    def test_it_round_trips_through_torch_save(self, tmp_path):
        path = tmp_path / "w.pt"
        torch.save(export.build_record(_FakeModule(), "policy_0", ".", STATE, None), path)
        back = torch.load(path, weights_only=False)
        assert back["module_id"] == "policy_0"
        assert back["state_dict"]["pi.weight"].shape == (2, 3)


class TestRender:
    def test_it_marks_the_best_and_says_why_that_is_a_guess(self):
        text = export.render(STATE, ["champion_1", "policy_0"])
        assert "modules: champion_1, policy_0" in text
        assert "| champion_2 | policy_1 | 9 | -100 | yes |" in text
        assert "| champion_1 | policy_0 | 4 | -900 |  |" in text
        assert "own iteration" in text

    def test_no_champions_says_so(self):
        assert "champions: none promoted" in export.render({}, ["policy_0"])


def test_cli_defaults_exist():
    for key in ("module_id", "out", "log_level"):
        cli_default("cda_export", key)
