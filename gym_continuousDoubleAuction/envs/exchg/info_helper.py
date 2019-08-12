class Info_Helper(object):

    def set_info(self, infos, trader):
        #info = trader.acc.nav - trader.acc.prev_nav
        infos[trader.ID] = {}
        return infos
