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


class _ScriptedEnv:
    """Two agents; agent_1 goes bankrupt on step 2 and leaves, agent_0 runs to
    the truncation at step 4 - the shape the real env gives a mid-episode
    bankruptcy: the terminated agent is absent from every later step."""
    possible_agents = ["agent_0", "agent_1"]
    init_cash = 100

    def reset(self, seed=None):
        self.t = 0
        self.agents = list(self.possible_agents)
        return {a: None for a in self.agents}, {}

    def step(self, actions):
        self.t += 1
        acting = list(self.agents)
        infos = {a: {"NAV": "100", "is_pass_action": 1, "num_rejected_step": 0,
                     "num_unmatched_step": 0, "num_passive_fills_step": 0,
                     "num_trades_step": 0, "num_trades": 0} for a in acting}
        terminateds = {a: False for a in acting}
        if self.t == 2:
            terminateds["agent_1"] = True
            infos["agent_1"]["NAV"] = "0"
            self.agents = ["agent_0"]
        terminateds["__all__"] = False
        truncateds = {"__all__": self.t >= 4}
        return ({a: None for a in acting}, {a: 0.0 for a in acting},
                terminateds, truncateds, infos)


class TestMidEpisodeBankruptcy:
    """An agent bankrupted before the last step was reported as not
    terminated - it is missing from the final `terminateds` - and its activity
    fractions were divided by the whole episode's length."""

    @staticmethod
    def _roll(monkeypatch):
        class _Algo:
            config = type("C", (), {"normalize_actions": True, "clip_actions": False})()

            def get_module(self, module_id):
                return None

        monkeypatch.setattr(evaluate, "act", lambda *args, **kwargs: {})
        record = evaluate.roll_episode(_Algo(), _ScriptedEnv(), lambda agent, ep: "policy_0",
                                       episode_index=0, seed=0, deterministic=True)
        return {row["agent"]: row for row in record["agents"]}

    def test_it_is_reported_terminated(self, monkeypatch):
        rows = self._roll(monkeypatch)
        assert rows["agent_1"]["terminated"] is True
        assert rows["agent_0"]["terminated"] is False

    def test_its_fractions_cover_the_steps_it_played(self, monkeypatch):
        rows = self._roll(monkeypatch)
        assert rows["agent_1"]["pass_fraction"] == 1.0, "it passed on both of its 2 steps"
        assert rows["agent_0"]["pass_fraction"] == 1.0
