"""doc/15 S4-19: a checkpoint records the layout its weights were trained on.

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
    assert stamp["observation_version"] == 5
    assert stamp["action_version"] == 2
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
    with pytest.raises(ValueError, match="action layout v1 .* v2"):
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
        callbacks = [SelfPlayCallback(num_trainable_policies=1, num_random_policies=1,
                                      episode_data_dir=None)]

    train_module._write_league_state(str(tmp_path), FakeAlgo(), iteration=3)
    written = json.load(open(tmp_path / train_module.LEAGUE_STATE_FILE))
    assert written[LAYOUT_KEY] == layout_stamp()
    assert written["training_iteration"] == 3
    check_layout_stamp(written, str(tmp_path))
