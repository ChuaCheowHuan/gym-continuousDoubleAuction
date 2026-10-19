"""docs/29 S4-19: a checkpoint records the layout its weights were trained on.

`train.save_checkpoint` writes `layout_stamp()` into `league_state.json`, and
`train.build_algo` runs `check_layout_stamp` before handing a candidate to
`Algorithm.from_checkpoint`, so a restore into a different observation or
action layout fails by name rather than by tensor shape - or worse, not at all.
"""

import pytest

from gym_continuousDoubleAuction.envs.layout_version import (
    LAYOUT_KEY,
    check_layout_stamp,
    layout_stamp,
)
from gym_continuousDoubleAuction.envs.exchg.action_helper import ACTION_KEYS
from gym_continuousDoubleAuction.envs.exchg.state_helper import BOOK_MODE, PRIVATE_FIELDS


def test_stamp_describes_the_current_layout():
    stamp = layout_stamp()
    assert stamp["observation_version"] == 6
    assert stamp["action_version"] == 4
    assert stamp["book_mode"] == BOOK_MODE
    assert layout_stamp("levels")["book_mode"] == "levels"
    assert stamp["private_fields"] == list(PRIVATE_FIELDS)
    assert stamp["action_keys"] == list(ACTION_KEYS)


def test_book_mode_mismatch_is_refused_by_name():
    """S3-15: same version, different width and meaning - the mode travels."""
    stamp = layout_stamp("levels")
    with pytest.raises(ValueError, match="book_mode 'levels' .* 'grid'"):
        check_layout_stamp({LAYOUT_KEY: stamp}, "/x", book_mode="grid")
    check_layout_stamp({LAYOUT_KEY: stamp}, "/x", book_mode="levels")
    check_layout_stamp({LAYOUT_KEY: stamp}, "/x")  # None: not compared


def test_an_unknown_book_mode_is_rejected():
    with pytest.raises(ValueError, match="book_mode"):
        layout_stamp("ladder")


def test_current_stamp_passes():
    check_layout_stamp({LAYOUT_KEY: layout_stamp()}, "/x")


def test_no_sidecar_is_no_claim():
    check_layout_stamp(None, "/x")


def test_sidecar_without_a_stamp_is_layout_one():
    with pytest.raises(ValueError, match="observation layout v1"):
        check_layout_stamp({"champion_count": 0}, "/x")


def test_version_mismatch_names_the_axis():
    stamp = layout_stamp()
    stamp["action_version"] = 1
    with pytest.raises(ValueError, match="action layout v1 .* v4"):
        check_layout_stamp({LAYOUT_KEY: stamp}, "/x")


@pytest.mark.parametrize("old", [2, 3])
def test_a_checkpoint_from_the_size_mean_and_sigma_heads_is_refused(old):
    """v2 had the signed `size_mean`, v3 the unsigned one; both had `size_sigma`.
    v4 has the one `size` head, so neither restores."""
    stamp = layout_stamp()
    stamp["action_version"] = old
    with pytest.raises(ValueError, match=f"action layout v{old} .* v4"):
        check_layout_stamp({LAYOUT_KEY: stamp}, "/x")


def test_field_drift_names_the_fields():
    stamp = layout_stamp()
    stamp["private_fields"] = [f for f in stamp["private_fields"] if not f.startswith("own_")]
    with pytest.raises(ValueError, match="private_fields differ.*own_bid_size_0"):
        check_layout_stamp({LAYOUT_KEY: stamp}, "/x")


def test_save_writes_it(tmp_path, monkeypatch):
    """`_write_league_state` puts the stamp beside the champion bookkeeping."""
    import json
    from gym_continuousDoubleAuction.train import train as train_module
    from gym_continuousDoubleAuction.train.callbk.league_based_self_play_callback import (
        SelfPlayCallback,
    )

    class FakeAlgo:
        callbacks = [
            SelfPlayCallback(num_trainable_policies=1, num_random_policies=1, episode_data_dir=None)
        ]

    train_module._write_league_state(str(tmp_path), FakeAlgo(), iteration=3)
    written = json.load(open(tmp_path / train_module.LEAGUE_STATE_FILE))
    assert written[LAYOUT_KEY] == layout_stamp()
    assert written["training_iteration"] == 3
    check_layout_stamp(written, str(tmp_path))


class TestTheStampRecordsHowWideEachActionHeadIs:
    """docs/29 R-5 (#175): `max_own_orders` sets the `order_slot` head's width, and the stamp
    listed only the head names. Two checkpoints with the same label could be trained for
    different heads, and the observation width (which the label's other fields protect) is
    identical, so only the action head differed."""

    def test_the_recorded_sizes_equal_the_real_action_space(self):
        """Ties the stamp to the space itself, so the two cannot drift apart."""
        import numpy as np

        from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
            continuousDoubleAuctionEnv,
        )

        env = continuousDoubleAuctionEnv({"num_of_agents": 2, "is_render": False, "max_step": 4})
        space = env.get_action_space(env.agents[0])
        real = {
            name: int(sub.n) if hasattr(sub, "n") else int(np.prod(sub.shape))
            for name, sub in space.spaces.items()
        }
        assert layout_stamp()["action_sizes"] == real

    def test_every_action_key_has_a_size(self):
        assert sorted(layout_stamp()["action_sizes"]) == sorted(ACTION_KEYS)

    def test_a_different_order_slot_width_is_refused_by_name(self):
        stamp = layout_stamp()
        stamp["action_sizes"] = {**stamp["action_sizes"], "order_slot": 8}
        with pytest.raises(ValueError, match=r"order_slot.*8.*5|action_sizes"):
            check_layout_stamp({LAYOUT_KEY: stamp}, "/x")

    def test_a_stamp_from_before_the_sizes_were_recorded_is_not_refused(self):
        stamp = layout_stamp()
        del stamp["action_sizes"]
        check_layout_stamp({LAYOUT_KEY: stamp}, "/x")

    def test_the_stamp_changes_with_max_own_orders(self, tmp_path):
        import json
        import os
        import shutil
        import subprocess
        import sys

        config = tmp_path / "config"
        shutil.copytree("config", config)
        path = config / "tunable_constants.json"
        constants = json.loads(path.read_text())
        constants["action_space"]["max_own_orders"] = 7
        path.write_text(json.dumps(constants))
        code = (
            "import json;"
            "from gym_continuousDoubleAuction.envs.layout_version import layout_stamp;"
            "print(json.dumps(layout_stamp()['action_sizes']))"
        )
        env = {**os.environ, "CDA_CONFIG_DIR": str(config), "PYTHONPATH": os.getcwd()}
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True
        ).stdout
        assert json.loads(out.strip().splitlines()[-1])["order_slot"] == 8
        assert layout_stamp()["action_sizes"]["order_slot"] == 5
