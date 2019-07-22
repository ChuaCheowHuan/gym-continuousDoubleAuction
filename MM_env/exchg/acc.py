    def acc(self, net_position, position_val, side, trade_size, trade_price):
        prev_position_val = position_val
        prev_position_price = prev_position_val / net_position
        curr_position_val = abs(net_position) * trade_price
        trade_val = trade_size * trade_price
        # if price decrease, diff is negative
        position_val_diff = curr_position_val - prev_position_val
        short_position_val = prev_position_val - position_val_diff

        if net_position >= 0: # long or neutral
            if side == 'bid':
                position_val = curr_position_val + trade_val
            else: # ask
                if net_position >= trade_size: # still long or neutral
                    # val of how much long left
                    position_val = (net_position - trade_size) * trade_price
                else: # net_position changed
                    # val of how much short left
                    position_val = (trade_size - net_position) * trade_price
        else: # short
            if side == 'ask':
                position_val = short_position_val + trade_val
            else: # bid
                if abs(net_position) >= trade_size: # still short or neutral
                    left_over_short_prev_val = (abs(net_position) - trade_size) * prev_position_price
                    left_over_short_curr_val = (abs(net_position) - trade_size) * trade_price
                    left_over_short_val_diff = left_over_short_curr_val - left_over_short_prev_val
                    left_over_short_val = left_over_short_prev_val - left_over_short_val_diff
                    position_val = left_over_short_val
                    #trade_val goes back to cash

                else: # net_position changed
                    short_prev_val = abs(net_position) * prev_position_price
                    short_curr_val = abs(net_position) * trade_price
                    short_val_diff = short_curr_val - short_prev_val
                    short_val = short_prev_val - short_val_diff
                    # short_val goes back to cash

                    left_over_long_val = (trade_size - abs(net_position)) * trade_price
                    position_val = left_over_long_val
        return 0
