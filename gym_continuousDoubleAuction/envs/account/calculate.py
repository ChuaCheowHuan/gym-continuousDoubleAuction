from decimal import Decimal

class Calculate(object):

    def cal_nav(self):
        """
        Calculate Net Asset Value (NAV) for the current time step.
        
        NAV = Cash + Cash on Hold (Collateral) + Position Value (Mark-to-Market).
        In a zero-sum MARL context, this represents the total wealth of the agent.
        Conservation of value implies Sum(NAV_all_agents) is constant (excluding trading fees if any).
        """

        self.nav =  self.cash + self.cash_on_hold + self.position_val
        return self.nav

    def cal_total_profit(self):
        """
        Calculate cumulative profit/loss since the start of the episode.
        
        Total Profit = Current NAV - Initial NAV.
        This is the primary reward signal in many RL implementations.
        """

        self.total_profit = self.nav - self.init_nav
        return self.total_profit

    def cal_profit(self, position, mkt_val, raw_val):
        """
        Calculate unrealized profit/loss for the current position based on market value.
        
        Args:
            position (str): 'long' or 'short'.
            mkt_val (Decimal): Current Market Value of the position.
            raw_val (Decimal): Cost Basis (VWAP * Quantity).
            
        Returns:
            Decimal: Profit or Loss.
        """

        if position == 'long':
            self.profit = mkt_val - raw_val
        else:
            self.profit = raw_val - mkt_val
        return self.profit

    def mark_to_mkt(self, ID, mkt_price):
        """
        Mark the account to market using the latest trade price.
        
        Updates:
            self.profit: Unrealized PnL for the current step.
            self.position_val: Updated position value (Cost Basis + Unrealized PnL).
            self.nav: Updated Net Asset Value.
            
        Note:
            In this system, 'Net Position' acts as the primary state variable.
            Long: Profit = (Price - VWAP) * Q
            Short: Profit = (VWAP - Price) * Q
        """

        price_diff = (self.VWAP - mkt_price, mkt_price - self.VWAP)[self.net_position >= 0] # (on_false, on_true)[condition]
        self.profit = Decimal(abs(self.net_position)) * price_diff

        #print('ID: {}; profit: {}'.format(ID, self.profit))

        raw_val = abs(self.net_position) * self.VWAP
        self.position_val = raw_val + self.profit

        self.prev_nav = self.nav
        self.cal_nav()
        self.cal_total_profit()
        return 0
