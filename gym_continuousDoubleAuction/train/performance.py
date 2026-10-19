"""Risk-adjusted performance of one agent over one episode, from running sums.

docs/29 S3-9: NAV, trade count and reward were recorded, and nothing a trader would
judge a strategy by was: no Sharpe or Sortino, no drawdown over the path (only the
last step's), no hit rate, no turnover, no inventory statistics. The counters were
discarded after the reward consumed them.

`PerformanceTally` keeps O(1) state per agent - the same rule as the rest of the
callback's tally (an episode is `max_step` x `num_agents` agent-steps and keeping them
all to compute a handful of numbers is the memory cost docs/21 §2.2 is about) - and is
fed one `(nav, net_position)` per step.

Definitions, so a number is not mistaken for a different one:

* A step's return is `(nav_t - nav_{t-1}) / nav_{t-1}`, taken in `Decimal` from the exact
  NAV string `info["NAV"]` carries and converted to float only at the end, so it keeps
  the exactness `Decimal` was chosen for. A step whose previous NAV is not positive has
  no defined return and is skipped.
* **Sharpe** is the mean per-step return over its standard deviation, and **Sortino**
  the mean over the downside deviation (root mean square of the negative returns, over
  every step). Neither is annualised: a step is not a calendar unit, and the number is
  for comparing policies on one setup. Both are None when the denominator is zero, never
  0 or infinity, so an agent that did nothing is not scored as either.
* **Max drawdown** is the largest peak-to-trough fall of NAV over the episode as a
  fraction of the peak.
* **Hit rate** is the share of steps with a nonzero return that were positive. A pass
  step has a zero return and is not counted either way.
* **Position turnover** is the sum of `|change in net position|` over the episode, in
  contracts. **Mean / max |position|** are the inventory carried.
* **Realised / unrealised P&L** are the account's, gross of fees, at the episode's last
  step: realised is banked by closing lots against their average entry price,
  unrealised is the open position at the mark. With the fees they account for NAV
  exactly: `NAV - starting NAV == realised + unrealised - fees` (issue #286).
* **Mark-out at horizon h** is the adverse-selection measure: for the fills of a step,
  signed (buys +, sells -), `qty x mid_{t+h} - value`, which is positive when the price
  moved the agent's way after it traded. Reported per contract (summed over the
  episode, over contracts traded). It is linear in a step's fills, so a step needs
  only its net signed quantity and value, not each fill. Forced closes and
  auto-deleveraging are not the agent's executions and are not counted. A step that
  both bought and sold nets within itself. Fills whose horizon runs past the end of the
  episode are dropped, not marked at the last price.
"""

from __future__ import annotations

import math
from collections import deque
from decimal import Decimal, InvalidOperation
from typing import Dict, Optional, Sequence

#: The fixed metric names `summary()` returns, in a fixed order. A mark-out per
#: configured horizon, `markout_<h>`, follows them.
METRICS = (
    "sharpe",
    "sortino",
    "max_drawdown",
    "hit_rate",
    "position_turnover",
    "mean_abs_position",
    "max_abs_position",
    "realised_pnl",
    "unrealised_pnl",
)


def _decimal(value) -> Optional[Decimal]:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


class PerformanceTally:
    """Running statistics for one agent in one episode."""

    __slots__ = (
        "_prev_nav",
        "_prev_position",
        "_peak",
        "n",
        "_sum",
        "_sum_sq",
        "_downside_sq",
        "_up",
        "_down",
        "max_drawdown",
        "turnover",
        "_abs_position_sum",
        "_steps",
        "max_abs_position",
        "horizons",
        "_fills",
        "_markout",
        "_markout_qty",
        "realised",
        "unrealised",
    )

    def __init__(self, markout_horizons: Sequence[int] = ()) -> None:
        self._prev_nav: Optional[Decimal] = None
        self._prev_position: Optional[float] = None
        self._peak: Optional[Decimal] = None
        self.n = 0  # steps with a defined return
        self._sum = 0.0
        self._sum_sq = 0.0
        self._downside_sq = 0.0
        self._up = 0
        self._down = 0
        self.max_drawdown = 0.0
        self.turnover = 0.0
        self._abs_position_sum = 0.0
        self._steps = 0
        self.max_abs_position = 0.0
        self.realised: Optional[float] = None
        self.unrealised: Optional[float] = None
        self.horizons = tuple(sorted({int(h) for h in markout_horizons if int(h) >= 1}))
        # The last `max(horizons)` steps' (signed qty, signed value), oldest first,
        # and per horizon the running mark-out and the contracts it covers.
        self._fills = deque(maxlen=max(self.horizons)) if self.horizons else None
        self._markout = {h: 0.0 for h in self.horizons}
        self._markout_qty = {h: 0.0 for h in self.horizons}

    def update(
        self,
        nav,
        net_position=None,
        *,
        realised=None,
        unrealised=None,
        fill_qty=None,
        fill_value=None,
        mid=None,
    ) -> None:
        """Feed one step. `nav` is the exact NAV (a string or a Decimal).

        `realised` / `unrealised` are the account's P&L now (the last one fed is
        reported). `fill_qty` / `fill_value` are this step's signed fills and `mid`
        the market midpoint after the step, which resolves the fills of `h` steps
        ago for each mark-out horizon.
        """
        if realised is not None:
            self.realised = float(realised)
        if unrealised is not None:
            self.unrealised = float(unrealised)
        if self._fills is not None:
            if mid is not None and math.isfinite(float(mid)):
                for h in self.horizons:
                    if len(self._fills) >= h:
                        qty, value = self._fills[-h]
                        if qty:
                            self._markout[h] += qty * float(mid) - value
                            self._markout_qty[h] += abs(qty)
            self._fills.append((float(fill_qty or 0), float(fill_value or 0.0)))
        value = _decimal(nav)
        if value is not None:
            if self._prev_nav is not None and self._prev_nav > 0:
                step = float((value - self._prev_nav) / self._prev_nav)
                self.n += 1
                self._sum += step
                self._sum_sq += step * step
                if step > 0:
                    self._up += 1
                elif step < 0:
                    self._down += 1
                    self._downside_sq += step * step
            if self._peak is None or value > self._peak:
                self._peak = value
            if self._peak > 0:
                fall = float((self._peak - value) / self._peak)
                self.max_drawdown = max(self.max_drawdown, fall)
            self._prev_nav = value

        if net_position is not None:
            position = float(net_position)
            if self._prev_position is not None:
                self.turnover += abs(position - self._prev_position)
            self._prev_position = position
            self._steps += 1
            self._abs_position_sum += abs(position)
            self.max_abs_position = max(self.max_abs_position, abs(position))

    # --- the numbers ----------------------------------------------------------

    def sharpe(self) -> Optional[float]:
        if self.n < 2:
            return None
        mean = self._sum / self.n
        variance = (self._sum_sq - self.n * mean * mean) / (self.n - 1)
        if variance <= 0 or not math.isfinite(variance):
            return None
        return mean / math.sqrt(variance)

    def sortino(self) -> Optional[float]:
        if self.n < 1 or self._downside_sq <= 0:
            return None
        return (self._sum / self.n) / math.sqrt(self._downside_sq / self.n)

    def hit_rate(self) -> Optional[float]:
        moved = self._up + self._down
        return None if moved == 0 else self._up / moved

    def summary(self) -> Dict[str, Optional[float]]:
        """Every metric, None where it is undefined for this agent's episode."""
        return {
            "sharpe": self.sharpe(),
            "sortino": self.sortino(),
            "max_drawdown": self.max_drawdown if self._peak is not None else None,
            "hit_rate": self.hit_rate(),
            "position_turnover": self.turnover if self._steps else None,
            "mean_abs_position": (self._abs_position_sum / self._steps) if self._steps else None,
            "max_abs_position": self.max_abs_position if self._steps else None,
            "realised_pnl": self.realised,
            "unrealised_pnl": self.unrealised,
            **{
                f"markout_{h}": (
                    self._markout[h] / self._markout_qty[h] if self._markout_qty[h] else None
                )
                for h in self.horizons
            },
        }
