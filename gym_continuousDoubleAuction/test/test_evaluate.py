"""The pure half of `train.evaluate`: unbatching, summarising, rendering."""
import numpy as np
import pytest
import torch

from gym_continuousDoubleAuction.config_loader import cli_default
from gym_continuousDoubleAuction.train import evaluate


def _row(agent, module, ret, nav, trades=3, passf=0.1, rej=0.0, unm=0.2, share=0.5, term=False):
    return {"agent": agent, "module": module, "return": ret, "final_nav": nav,
            "nav_change_frac": None if nav is None else nav / 1e6 - 1, "num_trades": trades,
            "pass_fraction": passf, "rejection_fraction": rej, "unmatched_fraction": unm,
            "passive_fill_share": share, "terminated": term}


EPISODES = [
    {"episode": 0, "steps": 10, "agents": [_row("agent_0", "policy_0", 1.0, 1_010_000),
                                           _row("agent_1", "policy_2", -1.0, 990_000, share=None)]},
    {"episode": 1, "steps": 10, "agents": [_row("agent_0", "policy_0", 3.0, 1_030_000, term=True),
                                           _row("agent_1", "policy_2", -3.0, 970_000, share=None)]},
]


def test_unbatch_handles_dicts_tensors_and_discrete():
    batched = {"category": torch.tensor([4]), "size_mean": torch.tensor([[0.25]]),
               "order_slot": np.array([2])}
    out = evaluate._unbatch(batched)
    assert out["category"] == 4 and isinstance(out["category"], int)
    assert out["order_slot"] == 2
    assert out["size_mean"].shape == (1,) and float(out["size_mean"][0]) == 0.25


def test_summarise_means_per_module():
    s = evaluate.summarise(EPISODES)
    assert set(s) == {"policy_0", "policy_2"}
    assert s["policy_0"]["agent_episodes"] == 2
    assert s["policy_0"]["return"] == 2.0
    assert s["policy_0"]["nav_change_frac"] == pytest.approx(0.02)
    assert s["policy_0"]["terminated"] == 1
    assert s["policy_2"]["passive_fill_share"] is None, "no fills -> no share, not 0"


def test_render_has_a_row_per_module():
    text = evaluate.render(evaluate.summarise(EPISODES))
    lines = text.splitlines()
    assert lines[0].startswith("| module | agent-eps | return | nav change |")
    assert any(l.startswith("| policy_0 | 2 | 2 | 2.00% |") for l in lines), text
    assert any("| - |" in l for l in lines if l.startswith("| policy_2"))


def test_cli_defaults_exist():
    for key in ("episodes", "seed", "out", "log_level"):
        cli_default("cda_evaluate", key)
