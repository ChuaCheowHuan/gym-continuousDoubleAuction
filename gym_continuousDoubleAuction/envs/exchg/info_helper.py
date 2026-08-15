import numpy as np


def _plain(value):
    """Convert a numpy scalar or array into something JSON can hold.

    Actions arrive from the model as a tuple mixing `np.int32` with
    single-element `float32` arrays. `json.dumps` handles none of that, and the
    per-iteration progress log (doc/11 1.6) is only useful if what goes into
    `info` can actually be written out.
    """
    if isinstance(value, np.ndarray):
        return [_plain(v) for v in value.tolist()]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


class Info_Helper(object):

    def set_info(self, infos, trader):
        """
        Update the infos dictionary with the latest data from the trader.

        Args:
            infos (dict): Dictionary of agent information.
            trader (object): A trader object with an account containing reward, nav, and num_trades.

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
            # float(), despite account.py initialising this to int 0: the
            # position becomes a Decimal the moment a trade lands (account.py
            # rebuilds it as Decimal +/- Decimal), so the type is int before the
            # first fill and Decimal after. Contract counts are integral, so
            # float loses nothing and the key holds one type all episode.
            "net_position": float(acc.net_position),
            "VWAP": float(acc.VWAP),
            "cash": float(acc.cash),
            "cash_on_hold": float(acc.cash_on_hold),
            "position_val": float(acc.position_val),
            "drawdown": float(acc.drawdown),
            "max_nav": float(acc.max_nav),
            "num_trades_step": acc.num_trades_step,
            "num_passive_fills_step": acc.num_passive_fills_step,
            "order_step_placed": acc.order_step_placed,
        })

        # Reward decomposition (doc/11 2.4). The five signed contributions that
        # sum to `reward`, so the variance split in doc/07 6.4 is measurable
        # without re-deriving anything.
        info["reward_terms"] = dict(acc.reward_terms)

        # Market state (doc/11 2.2). Identical for every agent this step; it is
        # repeated per agent because that is the shape RLlib gives `info`.
        info.update({
            "last_price": float(getattr(self, "last_price", 0.0)),
            "best_bid": getattr(self, "best_bid", None),
            "best_ask": getattr(self, "best_ask", None),
            "spread": getattr(self, "spread", None),
        })

        # The action this agent actually submitted, as the model emitted it -
        # before set_actions reshapes it for the LOB. Cleared at the end of
        # step(), so it is live here but absent on any other call path.
        model_actions = getattr(self, "model_actions", None) or {}
        if agent_key in model_actions:
            info["model_action"] = _plain(model_actions[agent_key])

        # One conversion over the whole dict rather than per field. The counters
        # and coefficients are a mix of Python and numpy scalars depending on
        # where they came from, and np.int64 - unlike np.float64, which
        # subclasses float - is not JSON serialisable. Converting at the exit
        # means a field added later cannot reintroduce the problem.
        infos[agent_key] = _plain(info)

        return infos
