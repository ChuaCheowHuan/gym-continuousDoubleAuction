from typing import Any, Dict

import numpy as np


_PASS_THROUGH = frozenset({int, float, str, bool, type(None)})


def _plain(value):
    """Convert a numpy scalar or array into something JSON can hold.

    Actions arrive from the model as a tuple mixing `np.int32` with
    single-element `float32` arrays. `json.dumps` handles none of that, and the
    per-iteration progress log (doc/11 1.6) is only useful if what goes into
    `info` can actually be written out.

    The 0-d case is not hypothetical: `tolist()` on a 0-d array returns a bare
    scalar rather than a list, so iterating it raises. A stateless module never
    produced one, but a stateful one does - RLlib's time-dimension connectors
    hand back the Discrete action components 0-d - which made every recurrent
    encoder fail on the first env step until this branch existed.
    """
    # The common case first. `set_info` runs this over ~35 fields per agent per step,
    # nearly all of them plain Python scalars, and each used to pay four isinstance
    # checks to learn it had nothing to do (14% of a profiled batch episode, issue
    # #248). `type(...) in` is exact: a numpy scalar, a bool subclass or a str
    # subclass is not one of these types and takes the full path below.
    if type(value) in _PASS_THROUGH:
        return value
    if isinstance(value, np.ndarray):
        if value.ndim == 0:
            return value.item()
        # `tolist()` already yields Python scalars and lists all the way down, so
        # there is nothing left to convert (issue #258).
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        # The pass-through test is inlined: a call per plain field was most of the
        # recursion (issue #258), and a dict's values are nearly all plain.
        return {k: v if type(v) in _PASS_THROUGH else _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [v if type(v) in _PASS_THROUGH else _plain(v) for v in value]
    return value


def _as_float(value):
    """Decimal (or None) to float, for the JSON boundary. None passes through."""
    return None if value is None else float(value)


class InfoBuilder(object):
    """Builds an agent's `info` for a step (issue #152).

    Was `Info_Helper`, a mixin that read the mark price, the market snapshot, the pass set
    and the model actions off the env. It holds nothing; the exchange passes them in.
    """

    def set_info(self, infos: Dict[str, Dict[str, Any]], trader, *, mark, pass_agents,
                 last_price, best_bid, best_ask, spread, model_actions
                 ) -> Dict[str, Dict[str, Any]]:
        """
        Update the infos dictionary with the latest data from the trader.

        Args:
            infos (dict): Dictionary of agent information.
            trader (object): A trader object with an account containing reward, nav, and num_trades.
            mark: The price the accounts were marked at this step.
            pass_agents: The agents that chose to do nothing this step.
            last_price, best_bid, best_ask, spread: The market state after the step.
            model_actions: The actions the models emitted this step, or None.

        Returns:
            dict: Updated infos dictionary.
        """
        agent_key = f'agent_{trader.ID}'
        acc = trader.acc

        # `reward`, `NAV` and `num_trades` keep their names, types and order.
        # NAV stays a string: it is the exact str() of a Decimal, which is what
        # lets the conservation check parse it back without loss, and both
        # consumers already handle it (doc/11 2.6 tracks the round trip itself).
        #
        # The fields below are diagnostics rather than invariants, so they go
        # out as plain numbers - float is what the metrics stack and json
        # consume, and nothing reconstructs the ledger from them.
        info = {
            "reward": acc.reward,
            "NAV": str(acc.nav),
            "num_trades": acc.num_trades,
        }

        # Account state (doc/11 2.3). Read before set_step_outputs zeroes the
        # per-step counters, which happens after this call.
        info.update({
            # int, straight through: net_position is a count of contracts and
            # the account now holds it as one for the whole episode, so there
            # is nothing left here to paper over.
            "net_position": acc.net_position,
            # The cost basis, not `acc.VWAP`, which carries realised P&L
            # rolled in by `_size_decrease` and is not a price at all
            # once a position has been partly closed - it can be
            # negative. Anyone reading this column out of the episode
            # Parquet wants the price actually paid.
            "VWAP": float(acc.entry_vwap),
            # The rolled basis the ledger uses, kept under its own name
            # so the two are distinguishable rather than conflated.
            "carrying_vwap": float(acc.VWAP),
            "cash": float(acc.cash),
            "cash_on_hold": float(acc.cash_on_hold),
            "position_val": float(acc.position_val),
            "drawdown": float(acc.drawdown),
            "max_nav": float(acc.max_nav),
            "num_trades_step": acc.num_trades_step,
            "num_passive_fills_step": acc.num_passive_fills_step,
            "order_step_placed": acc.order_step_placed,
            "num_rejected_step": acc.num_rejected_step,
            # modify/cancel actions that named no resting order this step -
            # the third way an action can silently do nothing (doc/15 S4-14).
            "num_unmatched_step": acc.num_unmatched_step,
            # Observation elements clipped to the declared Box bounds this
            # step (doc/15 S4-15). Zero unless a bound is wrong for the market.
            "num_obs_clipped_step": acc.num_obs_clipped_step,
            "num_liquidations_step": acc.num_liquidations_step,
            "liquidated_book_qty_step": acc.liquidated_book_qty_step,
            "liquidated_adl_qty_step": acc.liquidated_adl_qty_step,
            "adl_qty_step": acc.adl_qty_step,
            "liquidation_steps_left": acc.liquidation_steps_left,
            # Realised and unrealised P&L, gross of fees (issue #286). Exact in the
            # ledger and converted here, like every diagnostic: `nav - init_nav ==
            # realised + unrealised - fees_paid` holds on the Decimals, to the
            # last digit the ledger keeps.
            "realised_pnl": float(acc.realised_pnl),
            "unrealised_pnl": float(acc.unrealised_pnl(mark)),
            # This step's fills, signed (buys +): contracts and price x contracts.
            # A mark-out at horizon h is `qty x mid_{t+h} - value`.
            "fill_qty_step": acc.fill_qty_step,
            "fill_value_step": float(acc.fill_value_step),
        })

        # Did this agent choose to do nothing this step? The two behaviours a
        # return series cannot tell apart: passing, and quoting past your cash
        # so that every order is refused.
        info["is_pass_action"] = agent_key in pass_agents

        # Reward decomposition (doc/11 2.4). The five signed contributions that
        # sum to `reward`, so the variance split in doc/07 6.4 is measurable
        # without re-deriving anything.
        info["reward_terms"] = dict(acc.reward_terms)

        # Market state (doc/11 2.2). Identical for every agent this step; it is
        # repeated per agent because that is the shape RLlib gives `info`.
        #
        # These are Decimal on the env and float here: `info` is a
        # serialisation boundary, and JSON has no Decimal. NAV is the one field
        # that pays the string cost to stay exact, because the conservation
        # check depends on it; these are read for plots and diagnostics, where a
        # float is both sufficient and directly usable. None stays None.
        info.update({
            "last_price": _as_float(last_price),
            "best_bid": _as_float(best_bid),
            "best_ask": _as_float(best_ask),
            "spread": _as_float(spread),
        })

        # The action this agent actually submitted, as the model emitted it -
        # before set_actions reshapes it for the LOB. Set at the top of step()
        # and None before the first one.
        model_actions = model_actions or {}
        if agent_key in model_actions:
            info["model_action"] = _plain(model_actions[agent_key])

        # One conversion over the whole dict rather than per field. The counters
        # and coefficients are a mix of Python and numpy scalars depending on
        # where they came from, and np.int64 - unlike np.float64, which
        # subclasses float - is not JSON serialisable. Converting at the exit
        # means a field added later cannot reintroduce the problem.
        infos[agent_key] = _plain(info)

        return infos
