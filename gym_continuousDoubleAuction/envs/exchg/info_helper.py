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
        
        infos[agent_key] = {
            "reward": trader.acc.reward,
            "NAV": str(trader.acc.nav),
            "num_trades": trader.acc.num_trades
        }

        return infos