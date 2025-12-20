import numpy as np
import pandas as pd

class Reward_Helper(object): 
    
    def set_reward(self, rewards, trader):
        """
        Calculate and set the reward for the trader at the current time step.

        The reward is based on the change in Net Asset Value (NAV), with a penalty
        for the number of trades: positive NAV changes are divided by the number
        of trades (plus one), while negative changes are multiplied by it.

        Args:
            rewards (dict): Dictionary to store rewards for each agent.
            trader (object): The trader object containing account information.

        Returns:
            dict: Updated rewards dictionary.
        """
        nav_change = float(trader.acc.nav - trader.acc.prev_nav)
        num_trades = trader.acc.num_trades + 1  # Avoid division by zero

        if nav_change >= 0:
            # maximize NAV
            # reward = nav_change
        
            reward = nav_change / num_trades
        else:
            # reward = nav_change
            reward = nav_change * num_trades

        rewards[f'agent_{trader.ID}'] = reward
        trader.acc.reward = reward

        return rewards