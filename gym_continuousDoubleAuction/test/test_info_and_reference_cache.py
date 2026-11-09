"""Tests for info and reference cache.

Moved from `test_s4_hardening.py` by issue #361; the class docstrings keep the
original issue numbers.
"""

from decimal import Decimal
from typing import ClassVar

import pytest


from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)


def _q(side, qty, price, tid):
    return {"type": "limit", "side": side, "quantity": qty, "price": price, "trade_id": tid}


import numpy as np  # noqa: E402

from gym_continuousDoubleAuction.envs.exchg.info_helper import _plain  # noqa: E402


def _plain_reference(value):
    """The function as it was before the fast path: the behaviour to preserve."""
    if isinstance(value, np.ndarray):
        if value.ndim == 0:
            return value.item()
        return [_plain_reference(v) for v in value.tolist()]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {k: _plain_reference(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_reference(v) for v in value]
    return value


class TestPlainKeepsItsBehaviourWithAFastPath:
    """#248: `_plain` was 14% of a profiled batch episode, nearly all of it plain scalars
    paying four isinstance checks to learn they needed nothing."""

    VALUES: ClassVar[list] = [
        0,
        1,
        -3,
        2.5,
        True,
        False,
        None,
        "NAV",
        "",
        Decimal("1.5"),
        np.int32(4),
        np.int64(5),
        np.float32(0.25),
        np.float64(0.5),
        np.bool_(True),
        np.array(7),
        np.array([1, 2]),
        np.array([[1.0], [2.0]], dtype=np.float32),
        (np.int32(1), np.array([0.5], dtype=np.float32)),
        {"a": np.int64(1), "b": [np.float32(2.0), {"c": np.array([3])}], "d": "x"},
        [1, 2.5, None],
        {},
    ]

    @pytest.mark.parametrize("value", VALUES, ids=lambda v: type(v).__name__)
    def test_the_result_is_what_it_always_was(self, value):
        got, want = _plain(value), _plain_reference(value)
        assert got == want and type(got) is type(want)

    def test_a_numpy_scalar_is_still_converted_not_passed_through(self):
        assert type(_plain(np.float64(1.5))) is float
        assert type(_plain(np.int64(2))) is int

    def test_a_bool_stays_a_bool(self):
        assert _plain(True) is True

    def test_the_result_is_json_serialisable(self):
        import json

        json.dumps(_plain({"a": np.int64(1), "b": [np.float32(2.0)], "c": np.array([1, 2])}))


class TestReferencePriceIsCachedPerSnapshot:
    """#248: every trader's observation and mask asked for the same number."""

    @staticmethod
    def _uncached(env):
        return env._snap_to_tick(env.mid_price())

    @pytest.mark.parametrize("clearing", ["sequential", "batch"])
    def test_it_always_equals_the_uncached_value(self, clearing):
        env = continuousDoubleAuctionEnv(
            {"num_of_agents": 4, "max_step": 80, "is_render": False, "step_clearing": clearing}
        )
        env.reset(seed=3)
        for _ in range(80):
            for _call in range(3):  # repeated calls inside one step
                assert env.reference_price() == self._uncached(env)
            _o, _r, term, trunc, _i = env.step(
                {a: env.action_spaces[a].sample() for a in env.agents}
            )
            assert env.reference_price() == self._uncached(env)
            if term["__all__"] or trunc["__all__"]:
                break

    def test_a_new_print_on_the_same_snapshot_is_a_miss(self):
        """On a one-sided book the reference follows the last price, so the key has to
        include it, not only the snapshot."""
        env = continuousDoubleAuctionEnv({"num_of_agents": 2, "is_render": False})
        env.reset(seed=1)
        first = env.reference_price()
        env.last_price = Decimal(first) + 7
        assert env.reference_price() == self._uncached(env)

    def test_a_new_snapshot_is_a_miss(self):
        env = continuousDoubleAuctionEnv({"num_of_agents": 2, "is_render": False})
        env.reset(seed=1)
        env.reference_price()
        t = env.traders
        t[0].place_order("limit", "bid", 5, 95.0, env.LOB, t)
        t[1].place_order("limit", "ask", 5, 105.0, env.LOB, t)
        env.step(
            {
                a: {
                    "category": 0,
                    "order_slot": 0,
                    "price": 0,
                    "price_offset": 1,
                    "size": np.zeros(1, dtype=np.float32),
                }
                for a in env.agents
            }
        )
        assert env.reference_price() == self._uncached(env)

    def test_two_envs_do_not_share_a_cache(self):
        a = continuousDoubleAuctionEnv(
            {
                "num_of_agents": 2,
                "is_render": False,
                "initial_price_min": 50,
                "initial_price_max": 50,
            }
        )
        b = continuousDoubleAuctionEnv(
            {
                "num_of_agents": 2,
                "is_render": False,
                "initial_price_min": 150,
                "initial_price_max": 150,
            }
        )
        a.reset(seed=1)
        b.reset(seed=1)
        assert a.reference_price() != b.reference_price()
