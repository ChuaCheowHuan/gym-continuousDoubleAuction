"""Every observation block is on a scale a bounded activation can use.

doc/15 S2-2. The network's first layer is `tanh` and there is no
`MeanStdFilter` or normalisation connector anywhere in the pipeline, so the
relative scale of the feature blocks *is* their relative influence. Measured
before this: `sqrt(V)` sizes reached +-47 with a standard deviation of 9.0
against 0.04 for the normalised prices beside them - a 220x spread - so size
features saturated and dominated while price features contributed almost
nothing. `log_mid` was a near-constant +4.6, a standing bias rather than a
signal, and the private `position` field divided by `limit_max_size`, which
inventory exceeded on 13.2% of agent-steps.

These tests assert the *property* rather than the formulas - that the blocks
are comparable and bounded - so a future change to how a feature is computed
is free as long as it keeps them so. The formulas themselves are pinned in
`test_obs_normalization.py` and `test_obs_market_features.py`.
"""
import numpy as np
import pytest

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.envs.exchg.state_helper import PRIVATE_FIELDS


def _rollout(steps=400, seed=7, agents=4):
    """Random play, returning the last snapshot of each step and the privates."""
    env = continuousDoubleAuctionEnv(
        {"num_of_agents": agents, "max_step": steps, "is_render": False}
    )
    obs, _ = env.reset(seed=seed)

    k, snap_dim, n_hist = env.k_rows, env.snapshot_dim, env.n_hist
    blocks = {
        "bid_price": (0, k),
        "bid_size": (k, 2 * k),
        "ask_price": (2 * k, 3 * k),
        "ask_size": (3 * k, 4 * k),
        "log_mid": (4 * k, 4 * k + 1),
        "log1p_spread": (4 * k + 1, 4 * k + 2),
    }
    collected = {name: [] for name in blocks}
    privates = []
    saturating = 0
    agent_steps = 0

    for _ in range(steps):
        actions = {a: env.action_spaces[a].sample() for a in env.agents}
        obs, _rew, terminateds, truncateds, _infos = env.step(actions)
        vector = obs["agent_0"]
        newest = vector[(n_hist - 1) * snap_dim: n_hist * snap_dim]
        for name, (lo, hi) in blocks.items():
            collected[name].append(newest[lo:hi])
        privates.append(vector[n_hist * snap_dim:])
        for trader in env.traders:
            agent_steps += 1
            if abs(trader.acc.net_position) > env.position_scale:
                saturating += 1
        if terminateds.get("__all__") or truncateds.get("__all__"):
            break

    stacked = {name: np.concatenate(rows) for name, rows in collected.items()}
    return env, stacked, np.array(privates), saturating, agent_steps


class TestFeatureBlocksAreComparable:
    def setup_method(self):
        self.env, self.blocks, self.privates, self.sat, self.steps = _rollout()

    def test_sizes_no_longer_dwarf_prices(self):
        """The headline number: a 220x standard-deviation spread."""
        size_std = self.blocks["bid_size"].std()
        price_std = self.blocks["bid_price"].std()

        assert price_std > 0, "precondition: prices actually varied"
        assert size_std / price_std < 20, (
            f"size std {size_std:.4f} against price std {price_std:.4f} - the "
            "blocks are back to different orders of magnitude"
        )

    def test_every_book_feature_stays_within_a_tanh_s_useful_range(self):
        for name in ("bid_price", "bid_size", "ask_price", "ask_size"):
            values = self.blocks[name]
            assert np.abs(values).max() < 5.0, (
                f"{name} reached {np.abs(values).max():.2f}; anything much "
                "past 2 is flat under tanh"
            )

    def test_log_mid_is_centred_rather_than_a_standing_bias(self):
        """It was 4.55..4.64 - all offset, no signal."""
        log_mid = self.blocks["log_mid"]

        assert np.abs(log_mid).max() < 3.0
        assert np.abs(log_mid.mean()) < 2.0, (
            f"log_mid mean {log_mid.mean():.2f} is still mostly a constant"
        )

    def test_log_mid_still_carries_the_anchor(self):
        """Centring must not have flattened it into nothing."""
        assert self.blocks["log_mid"].std() > 1e-3

    def test_no_observation_is_nan_or_infinite(self):
        for name, values in self.blocks.items():
            assert np.all(np.isfinite(values)), f"{name} carries nan/inf"
        assert np.all(np.isfinite(self.privates))

    def test_inventory_stays_inside_its_own_scale(self):
        fraction = self.sat / max(1, self.steps)
        assert fraction < 0.02, (
            f"{fraction:.1%} of agent-steps exceed position_scale "
            f"({self.env.position_scale:.0f}); it was 13.2% against "
            "limit_max_size"
        )

    def test_every_private_field_is_order_one(self):
        for i, name in enumerate(PRIVATE_FIELDS):
            column = self.privates[:, i]
            assert np.abs(column).max() < 5.0, (
                f"private field {name} reached {np.abs(column).max():.2f}"
            )


class TestTheScalesAreConfigured:
    def test_position_scale_is_read_from_config(self):
        env = continuousDoubleAuctionEnv(
            {"num_of_agents": 2, "is_render": False, "position_scale": 250}
        )
        assert env.position_scale == 250.0

    def test_a_non_positive_position_scale_is_refused(self):
        with pytest.raises(ValueError, match="position_scale"):
            continuousDoubleAuctionEnv(
                {"num_of_agents": 2, "is_render": False, "position_scale": 0}
            )

    def test_log_mid_centre_follows_the_anchor_range(self):
        env = continuousDoubleAuctionEnv({
            "num_of_agents": 2, "is_render": False,
            "initial_price_min": 100, "initial_price_max": 100,
        })
        assert env.log_mid_centre == pytest.approx(float(np.log(100.0)))
