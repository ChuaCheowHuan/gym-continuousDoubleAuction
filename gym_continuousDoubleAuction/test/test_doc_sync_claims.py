"""Issue #264: `cda-doc-sync`'s `claims.py` promised the config keys, CLI flags and file
inventory and checked only seven number categories.

Run as a subprocess on a throwaway tree, the way the skill runs it: a hand-written
`facts.json` and a few docs, so each category can be driven both ways.
"""
import json
import os
import subprocess
import sys

SCRIPT = os.path.join(".claude", "skills", "cda-doc-sync", "scripts", "claims.py")
ROOT = os.getcwd()

FACTS = {
    "tests": {"unit": 10, "integration": 2, "total": 12,
              "per_file": {"gym_continuousDoubleAuction/test/test_a.py": 7,
                           "gym_continuousDoubleAuction/test/integration/test_b.py": 2}},
    "obs": {"train_width": 233, "levels_width": 305, "private_dim": 41,
            "grid_snapshot": 48, "levels_snapshot": 66},
    "action": {"_heads": 5},
    "reward_terms": ["a", "b", "c", "d", "e", "f"],
    "encoders": ["mlp", "lstm", "transformer", "moe_transformer", "jepa"],
    "config": {"train_config.json": {"alpha": 1, "_note": "prose", "group": {"beta": 2}}},
    "flags": {"train.train": ["--help", "--gamma"]},
    "code": {"lines": 1234, "files": 12},
}

INVENTORY = (
    "| file | tests |\n|---|---|\n"
    "| `test_a.py` | 7 | something |\n"
    "| `integration/test_b.py` | 2 | something |\n"
)


def _run(tmp_path, *, inventory=INVENTORY, facts=None, prose=""):
    (tmp_path / "doc").mkdir()
    (tmp_path / "README.md").write_text("readme\n")
    (tmp_path / "doc" / "10_testing.md").write_text(inventory)
    (tmp_path / "doc" / "14_x.md").write_text(
        "> 1,234 lines across 12 Python files, with 10 unit tests\n" + prose)
    (tmp_path / "doc" / "18_config.md").write_text("`alpha` `beta` `--gamma`\n")
    path = tmp_path / "facts.json"
    path.write_text(json.dumps(facts or FACTS))
    out = subprocess.run([sys.executable, os.path.join(ROOT, SCRIPT), str(tmp_path), str(path)],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_a_consistent_tree_reports_nothing(tmp_path):
    assert _run(tmp_path).strip() == ""


class TestInventory:

    def test_a_wrong_count_is_reported(self, tmp_path):
        out = _run(tmp_path, inventory=INVENTORY.replace("`test_a.py` | 7", "`test_a.py` | 5"))
        assert "inventory" in out and "test_a.py 5 -> 7" in out

    def test_an_integration_row_is_checked_too(self, tmp_path):
        out = _run(tmp_path, inventory=INVENTORY.replace("test_b.py` | 2", "test_b.py` | 9"))
        assert "test_b.py 9 -> 2" in out

    def test_a_test_file_with_no_row_is_reported(self, tmp_path):
        out = _run(tmp_path, inventory="| `test_a.py` | 7 | x |\n")
        assert "test_b.py (2 tests) has no row" in out

    def test_a_row_for_a_file_that_is_gone_is_reported(self, tmp_path):
        out = _run(tmp_path, inventory=INVENTORY + "| `test_gone.py` | 3 | x |\n")
        assert "test_gone.py is listed but no longer collected" in out


class TestCodeSize:

    def test_a_stale_size_is_reported(self, tmp_path):
        facts = {**FACTS, "code": {"lines": 2000, "files": 15}}
        out = _run(tmp_path, facts=facts)
        assert "code size" in out and "1,234 lines / 12 files -> 2,000 / 15" in out

    def test_a_matching_size_is_not(self, tmp_path):
        assert "code size" not in _run(tmp_path)


class TestConfigKeysAndFlags:

    def test_an_undocumented_key_is_reported(self, tmp_path):
        facts = {**FACTS, "config": {"train_config.json": {"alpha": 1, "orphan": 2}}}
        out = _run(tmp_path, facts=facts)
        assert "config key" in out and "orphan is mentioned in no doc" in out
        assert "alpha is mentioned" not in out

    def test_a_nested_key_is_checked_by_its_leaf(self, tmp_path):
        facts = {**FACTS, "config": {"train_config.json": {"group": {"beta": 1, "lost": 2}}}}
        out = _run(tmp_path, facts=facts)
        assert "group.lost is mentioned in no doc" in out and "group.beta" not in out

    def test_prose_keys_are_not_settings(self, tmp_path):
        facts = {**FACTS, "config": {"train_config.json": {"_note": "x", "_source": "y"}}}
        assert "config key" not in _run(tmp_path, facts=facts)

    def test_an_undocumented_flag_is_reported(self, tmp_path):
        facts = {**FACTS, "flags": {"train.train": ["--help", "--gamma", "--secret"]}}
        out = _run(tmp_path, facts=facts)
        assert "cli flag" in out and "--secret is mentioned in no doc" in out
        assert "--gamma" not in out and "--help" not in out

    def test_a_flag_that_is_a_prefix_of_a_documented_one_is_not_covered_by_it(self, tmp_path):
        facts = {**FACTS, "flags": {"train.train": ["--gamma"]}}
        _run(tmp_path, facts=facts, prose="uses `--gamma-ray` only\n")
        (tmp_path / "doc" / "18_config.md").write_text("`alpha` `beta`\n")
        out = subprocess.run(
            [sys.executable, os.path.join(ROOT, SCRIPT), str(tmp_path), str(tmp_path / "facts.json")],
            capture_output=True, text=True).stdout
        assert "--gamma is mentioned in no doc" in out


def test_the_real_facts_script_emits_the_code_size_the_check_reads():
    """The check is dead if `facts.py` never writes `code`."""
    source = open(os.path.join(ROOT, ".claude", "skills", "cda-doc-sync", "scripts", "facts.py")).read()
    assert 'facts["code"]' in source and "git" in source
