import numpy as np
import pandas as pd

from ...config_loader import env_default

class Reward_Helper(object):

    def __init__(self, order_penalty=env_default("order_penalty"),
                 trade_penalty=env_default("trade_penalty"),
                 drawdown_penalty=env_default("drawdown_penalty"),
                 passive_bonus=env_default("passive_bonus"),
                 loss_multiplier=env_default("loss_multiplier"),
                 **kwargs):
        """
        Coefficients of the reward formula in `set_reward`.

        Arguments:
            order_penalty: Per order placed this step.
            trade_penalty: Per trade filled this step.
            drawdown_penalty: Per unit of NAV below the running peak.
            passive_bonus: Per passive (liquidity-providing) fill this step.
            loss_multiplier: Extra weight on negative NAV changes.

        Defaults come from `config/env_defaults.json`. A training run sets all
        five from `train_config.json` via `TrainConfig.env_config`.
        """
        self.order_penalty = order_penalty
        self.trade_penalty = trade_penalty
        self.drawdown_penalty = drawdown_penalty
        self.passive_bonus = passive_bonus
        self.loss_multiplier = loss_multiplier

        super().__init__(**kwargs)

    def set_reward(self, rewards, trader):
        """
        Calculate and set the reward for the trader at the current time step.

        The reward aligns with:
        1. Maximizing NAV (nav_change)
        2. Reducing number of trades (trade_penalty)
        3. Selective order placement (order_penalty)
        4. Lowering drawdown risk (drawdown_penalty & loss_multiplier)
        5. Capturing spread (passive_bonus)

        Args:
            rewards (dict): Dictionary to store rewards for each agent.
            trader (object): The trader object containing account information.

        Returns:
            dict: Updated rewards dictionary.
        """
        nav_change = float(trader.acc.nav - trader.acc.prev_nav)

        # Penalties/Bonus coefficients, set from the env config (see __init__).
        order_penalty = self.order_penalty
        trade_penalty = self.trade_penalty
        drawdown_penalty = self.drawdown_penalty
        passive_bonus = self.passive_bonus
        loss_multiplier = self.loss_multiplier

        # 1. Asymmetric Loss Aversion: Penalize negative nav_change more heavily
        nav_term = nav_change * (loss_multiplier if nav_change < 0 else 1.0)
        
        # 2. Drawdown: Distance from peak NAV
        current_drawdown = float(max(0, trader.acc.max_nav - trader.acc.nav))
        
        # 3. Comprehensive Reward Formula
        #
        # Kept as the signed contribution of each term rather than a single
        # expression, so the decomposition doc/07 6.4 asks to monitor is the
        # same arithmetic the agent is actually trained on: accumulating the
        # terms *is* the reward, and there is no second expression that could
        # drift out of step with the logged split.
        terms = {
            "nav_term": nav_term,
            "order_penalty": -(order_penalty * trader.acc.order_step_placed),
            "trade_penalty": -(trade_penalty * trader.acc.num_trades_step),
            "drawdown_penalty": -(drawdown_penalty * current_drawdown),
            "passive_bonus": passive_bonus * trader.acc.num_passive_fills_step,
        }

        # Accumulated left to right, deliberately NOT with sum() or math.fsum().
        # Instrumenting the reward must not change it, and on Python 3.12+ the
        # builtin sum() applies Neumaier compensated summation to floats: it is
        # more accurate, and it disagrees with this loop on ~44% of random
        # inputs (~1e-13 relative). Insertion order matches the original
        # formula and `a - b` is `a + (-b)` exactly in IEEE 754, so this
        # reproduces the previous expression bit for bit. Iterating the dict
        # rather than naming the five keys also means a term added later cannot
        # be logged but left out of the reward.
        reward = 0.0
        for value in terms.values():
            reward += value

        rewards[f'agent_{trader.ID}'] = reward
        trader.acc.reward = reward
        trader.acc.reward_terms = terms
        # The penalty uses the level, so the level is what is worth recording;
        # it was previously computed here and thrown away (doc/11 2.3).
        trader.acc.drawdown = current_drawdown

        return rewards