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

        #info = trader.acc.nav - trader.acc.prev_nav
        infos[trader.ID] = {}
        return infos
