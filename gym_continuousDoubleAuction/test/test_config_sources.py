"""The `config/` files are the only place configured values exist.

`test_config_loading.py` covers `train_config.json` reaching a TrainConfig and
the env. These tests cover the stronger property the codebase now claims: that
no module holds a literal copy of a configured value. The method is to build a
*modified* config tree, point `$CDA_CONFIG_DIR` at it, and check the change
comes out the other end. A literal left behind in Python would keep the old
value and fail the assertion.

See doc/18_configuration.md.
"""
import importlib
import json
import shutil

import pytest

from gym_continuousDoubleAuction import config_loader
from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.train.train import TrainConfig

REPO_CONFIG = "config/train_config.json"


@pytest.fixture
def config_tree(tmp_path, monkeypatch):
    """A writable copy of `config/`, installed as the active config directory.

    Returns a function `edit(filename, mutate)` that rewrites one file through
    a callback and clears the loader cache.
    """
    target = tmp_path / "config"
    shutil.copytree(config_loader.config_dir(), target)
    monkeypatch.setenv(config_loader.CONFIG_DIR_ENV_VAR, str(target))
    config_loader.reload()

    def edit(filename, mutate):
        path = target / filename
        with open(path) as fh:
            raw = json.load(fh)
        mutate(raw)
        with open(path, "w") as fh:
            json.dump(raw, fh)
        config_loader.reload()

    yield edit

    # The env var has to go back *before* the cache is dropped, or the reload
    # repopulates it from the modified tree and every later test in the session
    # reads the edited values. monkeypatch would restore it on its own, but not
    # until after this teardown has already run.
    monkeypatch.delenv(config_loader.CONFIG_DIR_ENV_VAR, raising=False)
    config_loader.reload()


class TestLoader:

    def test_documentation_keys_are_stripped_at_every_level(self):
        data = config_loader.load("tunable_constants.json")
        assert not any(k.startswith("_") for k in data)
        for group in data.values():
            assert not any(k.startswith("_") for k in group)

    def test_missing_key_raises_and_names_what_is_available(self):
        with pytest.raises(KeyError) as exc:
            config_loader.constant("observation_layout", "no_such_key")
        assert "k_rows" in str(exc.value)

    def test_missing_group_raises(self):
        with pytest.raises(KeyError, match="no group"):
            config_loader.group("tunable_constants.json", "no_such_group")

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            config_loader.load("no_such_file.json")

    def test_overlapping_groups_raise_when_flattened(self):
        """A key in two groups would resolve to whichever came last."""
        with pytest.raises(ValueError, match="appears in both"):
            config_loader.flatten({"a": {"dup": 1}, "b": {"dup": 2}}, "test")

    def test_bad_config_dir_raises(self, monkeypatch):
        monkeypatch.setenv(config_loader.CONFIG_DIR_ENV_VAR, "/nonexistent/config")
        config_loader.reload()
        with pytest.raises(FileNotFoundError):
            config_loader.load("train_config.json")
        monkeypatch.delenv(config_loader.CONFIG_DIR_ENV_VAR)
        config_loader.reload()


class TestTrainConfigHasNoValuesOfItsOwn:

    def test_defaults_equal_the_repo_file(self):
        """TrainConfig() and the file it reads cannot disagree."""
        assert TrainConfig() == TrainConfig.from_json(REPO_CONFIG)

    def test_editing_the_file_changes_the_default(self, config_tree):
        config_tree(
            "train_config.json",
            lambda raw: raw["environment"].update(num_agents=3, max_step=77),
        )
        cfg = TrainConfig()
        assert (cfg.num_agents, cfg.max_step) == (3, 77)

    def test_a_missing_field_raises_rather_than_falling_back(self, config_tree):
        """The failure mode this design exists to remove: a silent default."""
        config_tree("train_config.json", lambda raw: raw["ppo"].pop("lr"))
        with pytest.raises(KeyError, match="lr"):
            TrainConfig()

    def test_derived_properties_follow_the_file(self, config_tree):
        config_tree(
            "train_config.json",
            lambda raw: (raw["environment"].update(max_step=10),
                         raw["ppo"].update(num_episodes_per_iter=3)),
        )
        assert TrainConfig().train_batch_size == 30


class TestEnvFallbacksComeFromTheFile:

    def test_bare_env_uses_env_defaults(self, config_tree):
        config_tree(
            "env_defaults.json",
            lambda raw: raw["environment"].update(num_of_agents=3, max_step=7),
        )
        env = continuousDoubleAuctionEnv({})
        assert (env.num_of_agents, env.max_step) == (3, 7)

    def test_explicit_config_still_wins_over_the_fallback(self, config_tree):
        config_tree(
            "env_defaults.json",
            lambda raw: raw["environment"].update(num_of_agents=3),
        )
        env = continuousDoubleAuctionEnv({"num_of_agents": 2})
        assert env.num_of_agents == 2

    def test_reward_coefficients_fall_back_to_the_file(self, config_tree):
        config_tree(
            "env_defaults.json",
            lambda raw: raw["environment"].update(order_penalty=0.9),
        )
        env = continuousDoubleAuctionEnv({"num_of_agents": 2})
        assert env.order_penalty == 0.9

    def test_price_anchor_bounds_fall_back_to_the_file(self, config_tree):
        config_tree(
            "env_defaults.json",
            lambda raw: raw["environment"].update(initial_price_min=33,
                                                  initial_price_max=33),
        )
        env = continuousDoubleAuctionEnv({"num_of_agents": 2})
        env.reset()
        assert env.last_price == 33.0

    def test_book_is_built_on_the_configured_tick(self):
        """reset() used to rebuild the book with a literal 1."""
        env = continuousDoubleAuctionEnv({"num_of_agents": 2, "tick_size": 5})
        env.reset()
        assert env.LOB.tick_size == 5
        assert env.min_tick == 5


class TestStructuralConstantsComeFromTheFile:

    def test_book_depth_drives_observation_and_action_spaces(self, config_tree):
        """k_rows is one definition, read by both spaces and by _set_price."""
        config_tree(
            "tunable_constants.json",
            lambda raw: raw["observation_layout"].update(k_rows=6),
        )
        env = continuousDoubleAuctionEnv({"num_of_agents": 2, "n_hist": 2})

        assert env.k_rows == 6
        assert env.book_dim == 4 * 6
        assert env.snapshot_dim == 4 * 6 + 2
        assert env.observation_spaces["agent_0"].shape == (2 * (4 * 6 + 2),)
        assert env.action_spaces["agent_0"]["price"].n == 6

        obs, _ = env.reset()
        assert obs["agent_0"].shape == (2 * (4 * 6 + 2),)

    def test_extra_dim_widens_the_snapshot(self, config_tree):
        config_tree(
            "tunable_constants.json",
            lambda raw: raw["observation_layout"].update(k_rows=5, extra_dim=2),
        )
        env = continuousDoubleAuctionEnv({"num_of_agents": 2, "n_hist": 1})
        assert env.snapshot_dim == 22

    def test_book_rows_must_match_what_set_agg_LOB_builds(self, config_tree):
        """A structural value that code cannot honour must raise, not be ignored."""
        config_tree(
            "tunable_constants.json",
            lambda raw: raw["observation_layout"].update(book_rows=5),
        )
        with pytest.raises(ValueError, match="book_rows"):
            continuousDoubleAuctionEnv({"num_of_agents": 2})

    def test_category_n_must_match_the_side_type_mapping(self, config_tree):
        config_tree(
            "tunable_constants.json",
            lambda raw: raw["action_space"].update(category_n=7),
        )
        with pytest.raises(ValueError, match="category_n"):
            continuousDoubleAuctionEnv({"num_of_agents": 2})

    def test_price_offset_n_must_be_odd(self, config_tree):
        """An even count has no middle code, so 'join' would be undefined."""
        config_tree(
            "tunable_constants.json",
            lambda raw: raw["action_space"].update(price_offset_n=4),
        )
        with pytest.raises(ValueError, match="price_offset_n"):
            continuousDoubleAuctionEnv({"num_of_agents": 2})

    def test_wider_price_offset_extends_the_tick_range_symmetrically(self, config_tree):
        config_tree(
            "tunable_constants.json",
            lambda raw: raw["action_space"].update(price_offset_n=5),
        )
        env = continuousDoubleAuctionEnv({"num_of_agents": 2})
        env.reset()
        assert env.action_spaces["agent_0"]["price_offset"].n == 5
        # The neutral 'join' code is the middle one, so offsets run -2..+2.
        assert env._neutral_price_offset() == 2

    def test_size_bounds_come_from_the_file(self, config_tree):
        config_tree(
            "tunable_constants.json",
            lambda raw: raw["action_space"].update(size_mean_low=-2.0,
                                                   size_mean_high=2.0),
        )
        env = continuousDoubleAuctionEnv({"num_of_agents": 2})
        space = env.action_spaces["agent_0"]["size_mean"]
        assert (float(space.low[0]), float(space.high[0])) == (-2.0, 2.0)

    def test_module_id_prefixes_come_from_the_file(self, config_tree, monkeypatch):
        """`policy_handler` reads the prefixes once, at import.

        That makes this the one test that has to put a *module* back, not just
        the loader cache: `importlib.reload` re-executes policy_handler in its
        own namespace, so POLICY_PREFIX stays at whatever the tree said until
        something reloads it against the real one. Restoring the env var before
        the reload is what makes that reload read the real one - leaving it set
        pins `agent_` for the rest of the session, and anything later that
        builds a ModuleID (`train.vf_explained_var`, for one) silently looks up
        names no result will ever have.
        """
        config_tree(
            "tunable_constants.json",
            lambda raw: raw["module_id_prefixes"].update(policy_prefix="agent_"),
        )
        import gym_continuousDoubleAuction.train.policy.policy_handler as ph
        importlib.reload(ph)
        try:
            assert ph.policy_id(0) == "agent_0"
        finally:
            monkeypatch.delenv(config_loader.CONFIG_DIR_ENV_VAR, raising=False)
            config_loader.reload()
            importlib.reload(ph)

        assert ph.policy_id(0) == "policy_0", (
            "the prefix leaked out of this test and into the rest of the session"
        )

    def test_price_anchor_fallbacks_are_read_once_for_both_users(self, config_tree):
        """The two fallbacks used to be independent literals that had to agree."""
        config_tree(
            "tunable_constants.json",
            lambda raw: (raw["price_anchor_fallbacks"].update(
                action_helper_last_price=55.0, state_helper_midpoint=55.0)),
        )
        env = continuousDoubleAuctionEnv({"num_of_agents": 2})
        assert env.last_price == 55.0
        assert env.midpoint_fallback == 55.0


class TestCliDefaultsComeFromTheFile:

    def test_random_runner_defaults(self, config_tree):
        from gym_continuousDoubleAuction.CDA_env_rand import _cli
        config_tree(
            "cli_defaults.json",
            lambda raw: raw["cda_env_rand"].update(num_agents=3, max_step=5),
        )
        assert (_cli("num_agents"), _cli("max_step")) == (3, 5)

    def test_train_flags_carry_no_defaults_of_their_own(self):
        """Every train.py flag is SUPPRESS, so the file is the only source.

        An argparse default would silently overwrite the config file for any
        flag the user did not pass - the bug this design rules out.
        """
        import argparse

        from gym_continuousDoubleAuction.train.train import _parse_args

        parser_defaults = []

        real_parse_args = argparse.ArgumentParser.parse_args

        def capture(self, *args, **kwargs):
            parser_defaults.extend(
                action.default for action in self._actions
                if action.dest not in ("help", "config")
            )
            return real_parse_args(self, *args, **kwargs)

        argparse.ArgumentParser.parse_args = capture
        try:
            _parse_args([])
        finally:
            argparse.ArgumentParser.parse_args = real_parse_args

        assert parser_defaults
        assert all(d is argparse.SUPPRESS for d in parser_defaults)
