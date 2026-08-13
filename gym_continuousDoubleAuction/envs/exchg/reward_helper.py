import numpy as np
import pandas as pd

class Reward_Helper(object):

    def __init__(self, order_penalty=0.1, trade_penalty=0.05,
                 drawdown_penalty=0.2, passive_bonus=0.1, loss_multiplier=1.5,
                 **kwargs):
        """
        Coefficients of the reward formula in `set_reward`.

        Arguments:
            order_penalty: Per order placed this step.
            trade_penalty: Per trade filled this step.
            drawdown_penalty: Per unit of NAV below the running peak.
            passive_bonus: Per passive (liquidity-providing) fill this step.
            loss_multiplier: Extra weight on negative NAV changes.
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
        reward = (nav_term 
                  - (order_penalty * trader.acc.order_step_placed) 
                  - (trade_penalty * trader.acc.num_trades_step) 
                  - (drawdown_penalty * current_drawdown) 
                  + (passive_bonus * trader.acc.num_passive_fills_step))

        rewards[f'agent_{trader.ID}'] = reward
        trader.acc.reward = reward

        return rewards