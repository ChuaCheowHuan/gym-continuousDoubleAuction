"""`config/train_config.json` is a real input, not a description of one.

`TrainConfig.from_json` loads it and `--config` applies it. The file absorbed
the former `config/env_config.json`, so these also pin the two things that
merge could get wrong: the one key that changes name across the env boundary
(`num_agents` -> `num_of_agents`), and the two keys that had no `TrainConfig`
field at all (`initial_price_min` / `initial_price_max`).

See doc/18_configuration.md section 1.
"""
import dataclasses
import json

import pytest

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.train.train import TrainConfig, _parse_args

REPO_CONFIG = "config/train_config.json"


def _write(tmp_path, payload):
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(payload))
    return str(path)


class TestFromJson:

    def test_repo_config_loads(self):
        """The checked-in file must stay loadable by the loader that reads it."""
        cfg = TrainConfig.from_json(REPO_CONFIG)
        assert isinstance(cfg, TrainConfig)

    def test_every_field_is_representable(self):
        """No TrainConfig field is unreachable from the file."""
        with open(REPO_CONFIG) as fh:
            raw = json.load(fh)
        in_file = set()
        for key, value in raw.items():
            if key.startswith("_"):
                continue
            in_file.update(
                k for k in (value if isinstance(value, dict) else {key: value})
                if not k.startswith("_")
            )
        assert in_file == {f.name for f in dataclasses.fields(TrainConfig)}

    def test_groups_are_flattened(self, tmp_path):
        path = _write(tmp_path, {
            "environment": {"num_agents": 3},
            "ppo": {"lr": 0.01},
            "run": {"num_iters": 2},
        })
        cfg = TrainConfig.from_json(path)
        assert (cfg.num_agents, cfg.lr, cfg.num_iters) == (3, 0.01, 2)

    def test_documentation_keys_are_skipped(self, tmp_path):
        path = _write(tmp_path, {
            "_source": "x", "_description": "y", "_note": "z",
            "environment": {"_note": "nested doc", "num_agents": 4},
        })
        assert TrainConfig.from_json(path).num_agents == 4

    def test_unknown_key_raises(self, tmp_path):
        """A typo must not be silently ignored - that was the old failure mode."""
        path = _write(tmp_path, {"environment": {"num_agnets": 3}})
        with pytest.raises(ValueError, match="num_agnets"):
            TrainConfig.from_json(path)

    def test_env_side_key_name_is_rejected(self, tmp_path):
        """`num_of_agents` is the env's name for it; the field is `num_agents`."""
        path = _write(tmp_path, {"environment": {"num_of_agents": 3}})
        with pytest.raises(ValueError, match="num_of_agents"):
            TrainConfig.from_json(path)


class TestMergedEnvKeys:

    def test_rename_across_the_env_boundary(self):
        cfg = TrainConfig(num_agents=3)
        env_config = cfg.env_config
        assert env_config["num_of_agents"] == 3
        assert "num_agents" not in env_config

    def test_initial_price_bounds_are_forwarded(self):
        """These were readable by the env but had no TrainConfig field."""
        cfg = TrainConfig(num_agents=2, initial_price_min=50, initial_price_max=50)
        assert cfg.env_config["initial_price_min"] == 50
        env = continuousDoubleAuctionEnv(cfg.env_config)
        env.reset()
        assert env.last_price == 50.0

    def test_file_reaches_the_env(self, tmp_path):
        path = _write(tmp_path, {"environment": {
            "num_agents": 2,
            "initial_price_min": 42, "initial_price_max": 42,
            "mkt_max_size": 55, "order_penalty": 0.7,
        }})
        env = continuousDoubleAuctionEnv(TrainConfig.from_json(path).env_config)
        env.reset()
        assert env.last_price == 42.0
        assert env.mkt_max_size == 55
        assert env.order_penalty == 0.7


class TestCliPrecedence:

    def test_defaults_without_config(self):
        cfg = _parse_args([])
        assert cfg.num_agents == TrainConfig().num_agents

    def test_config_file_applies(self, tmp_path):
        path = _write(tmp_path, {"environment": {"num_agents": 3},
                                 "run": {"num_iters": 99}})
        cfg = _parse_args(["--config", path])
        assert (cfg.num_agents, cfg.num_iters) == (3, 99)

    def test_unpassed_flag_does_not_clobber_the_file(self, tmp_path):
        """The trap: argparse defaults would silently overwrite --config."""
        path = _write(tmp_path, {"environment": {"num_agents": 3}})
        cfg = _parse_args(["--config", path, "--iters", "5"])
        assert cfg.num_agents == 3   # from the file, not the flag default of 8
        assert cfg.num_iters == 5

    def test_explicit_flag_overrides_the_file(self, tmp_path):
        path = _write(tmp_path, {"environment": {"num_agents": 3}})
        assert _parse_args(["--config", path, "--agents", "7"]).num_agents == 7

    def test_sample_timeout_is_settable(self, tmp_path):
        # The knob whose absence let every iteration time out silently: RLlib's
        # 60s default cannot be met at this batch size, and a timed-out
        # iteration discards its rollouts rather than shortening them.
        assert _parse_args([]).sample_timeout_s == TrainConfig().sample_timeout_s
        assert _parse_args(["--sample-timeout", "12.5"]).sample_timeout_s == 12.5

        path = _write(tmp_path, {"rollouts": {"sample_timeout_s": 300.0}})
        assert _parse_args(["--config", path]).sample_timeout_s == 300.0

    def test_store_true_flags_still_work(self, tmp_path):
        path = _write(tmp_path, {"league_self_play": {"episode_data_dir": "eps"}})
        assert _parse_args(["--config", path]).episode_data_dir == "eps"
        assert _parse_args(["--config", path, "--no-episode-data"]).episode_data_dir is None
        assert _parse_args([]).is_restore is False
        assert _parse_args(["--restore"]).is_restore is True
