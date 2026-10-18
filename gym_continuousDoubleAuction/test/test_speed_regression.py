"""Performance regression tests for the matching engine and the env step (issue #209).

`docs/15` S2-12 and S3-30 were both slowdowns that no test caught: they showed up as a
training run that took longer. A wall-clock assertion on a shared CI runner is a flaky
test, so these are built to fail on an order-of-magnitude regression (an O(n) scan that
should be O(log n), a rebuild per step) and not on noise:

- budgets are *multiples of a calibration loop* timed on the same machine in the same
  process, not seconds, so a slow runner scales both sides;
- the margin is about 10x over what the code costs today;
- the scaling test compares the code with itself at two sizes, which needs no clock
  calibration at all and is what an accidental O(n^2) would trip.

Each measurement is the best of a few repeats (the minimum is the least noisy statistic
for a lower bound on the cost).
"""

import logging
import random
import time

import pytest

from gym_continuousDoubleAuction.envs.continuousDoubleAuction_env import (
    continuousDoubleAuctionEnv,
)
from gym_continuousDoubleAuction.envs.orderbook.orderbook import OrderBook


def _best_of(repeats, fn):
    best = float("inf")
    for _ in range(repeats):
        started = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - started)
    return best


def _calibration():
    """Seconds for a fixed slice of plain Python (dict inserts and arithmetic)."""

    def work():
        table = {}
        total = 0
        for i in range(200_000):
            table[i % 1009] = i
            total += table[i % 997] if (i % 997) in table else 0
        return total

    return _best_of(3, work)


def _rest_orders(count, seed=0):
    rng = random.Random(seed)
    book = OrderBook()
    for i in range(count):
        side = "bid" if i % 2 else "ask"
        price = rng.randint(1, 4_000) if side == "bid" else rng.randint(4_001, 8_000)
        book.process_order(
            {
                "type": "limit",
                "side": side,
                "quantity": 1 + i % 7,
                "price": price,
                "trade_id": i % 8,
            },
            False,
            False,
        )
    return book


@pytest.fixture(scope="module")
def unit():
    """One calibration for the module: the cost of the reference loop."""
    return _calibration()


class TestMatchingEngine:
    def test_resting_twenty_thousand_limit_orders_stays_within_budget(self, unit):
        """About 0.13 s when written, against a ~0.03 s calibration: ~5x. Budget 50x."""
        elapsed = _best_of(2, lambda: _rest_orders(20_000))
        assert elapsed < 50 * unit, f"{elapsed:.2f}s vs a {unit:.3f}s calibration loop"

    def test_cost_grows_roughly_linearly_with_the_number_of_orders(self):
        """4x the orders must cost nowhere near 16x: an O(n) scan per order would."""
        small = _best_of(3, lambda: _rest_orders(5_000))
        large = _best_of(3, lambda: _rest_orders(20_000))
        assert large < 10 * small, f"5k: {small:.3f}s, 20k: {large:.3f}s"

    def test_a_market_order_sweeping_a_deep_book_is_not_quadratic(self):
        """Sweeping N resting orders must not cost N separate scans of the book."""

        def sweep(depth):
            book = OrderBook()
            for i in range(depth):
                book.process_order(
                    {
                        "type": "limit",
                        "side": "ask",
                        "quantity": 1,
                        "price": 1_000 + i % 500,
                        "trade_id": i % 8,
                    },
                    False,
                    False,
                )
            started = time.perf_counter()
            trades, _ = book.process_order(
                {"type": "market", "side": "bid", "quantity": depth, "trade_id": 9}, False, False
            )
            assert len(trades) == depth
            return time.perf_counter() - started

        small = min(sweep(2_000) for _ in range(3))
        large = min(sweep(8_000) for _ in range(3))
        assert large < 10 * small + 0.02, f"2k: {small:.3f}s, 8k: {large:.3f}s"


class TestEnvStep:
    def test_a_step_with_eight_agents_stays_within_budget(self, unit):
        """Measured about 1.4 ms per step here, 0.035x the calibration; the budget is 0.35x. The budget is generous: a rebuild of the
        observation or the masks per agent per step would multiply it, not nudge it."""
        logging.disable(logging.CRITICAL)
        try:
            steps = 60
            env = continuousDoubleAuctionEnv(
                {"num_of_agents": 8, "max_step": steps + 5, "is_render": False}
            )
            env.reset(seed=1)
            actions = [{a: env.action_spaces[a].sample() for a in env.agents} for _ in range(steps)]

            def run():
                env.reset(seed=1)
                for i in range(steps):
                    live = {k: v for k, v in actions[i].items() if k in env.agents}
                    _, _, terminated, truncated, _ = env.step(live)
                    if terminated.get("__all__") or truncated.get("__all__"):
                        break

            elapsed = _best_of(3, run)
        finally:
            logging.disable(logging.NOTSET)
        per_step = elapsed / steps
        assert per_step < 0.35 * unit, f"{per_step * 1000:.1f} ms/step vs a {unit:.3f}s calibration"
