class Info_Helper(object):

    def set_info(self, infos, trader):
        """
        Set infos dictionary.

        Argument:
            infos: Dictionary of dictionaries.
            trader: A trader object.

        Returns:
            infos: Dictionary of dictionaries.
        """
        infos[trader.ID] = {"reward": trader.acc.reward,
                            # "NAV": str(trader.acc.nav),
                            "NAV": str(trader.acc.step_nav),
                            "num_trades": trader.acc.num_trades,
                            }

        return infos
