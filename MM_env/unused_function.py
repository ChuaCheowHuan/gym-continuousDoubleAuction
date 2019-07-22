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

def expected(e, ID, action, is_init, is_trade, unfilled):
    trader = e.agents[ID]
    cash = trader.cash
    cash_on_hold = trader.cash_on_hold
    position_val = trader.position_val
    nav = trader.nav
    net_position = trader.net_position

    type = action.get('type')
    side = action.get('side')
    trade_price = action.get('price')
    trade_size = action.get('size')

    if side == None:
        return (cash, cash_on_hold, position_val, nav, net_position)

    # expected after processing order:
    if is_init: # init_party
        if is_trade:
            if net_position > 0: # long
                if side == 'bid':
                    position_val = (net_position + trade_size) * trade_price
                else: # ask
                    if net_position >= trade_size: # still net long or neutral
                        cash += trade_size * trade_price # covered part goes to cash
                        position_val = (net_position - trade_size) * trade_price # update remaining position_val
                    else: # net position changes to short
                        cash += net_position * trade_price # covered part goes to cash
                        position_val = (trade_size - net_position) * trade_price # update remaining position_val
            elif net_position < 0: # short
                if side == 'ask':
                    position_val = (abs(net_position) + trade_size) * trade_price
                else: # bid
                    if net_position >= trade_size: # still net long or neutral
                        cash += trade_size * trade_price # covered part goes to cash
                        position_val = (abs(net_position) - trade_size) * trade_price # update remaining position_val
                    else: # net position changes to short
                        cash += net_position * trade_price # covered part goes to cash
                        position_val = (trade_size - abs(net_position)) * trade_price # update remaining position_val
            else: # neutral
                if side == 'bid':
                    cash -= trade_size * trade_price
                    position_val = trade_size * trade_price
                else: # ask
                    cash -= trade_size * trade_price
                    position_val = trade_size * trade_price
            # deal with unfilled
            cash -= unfilled * trade_price # reduce cash
            cash_on_hold += unfilled * trade_price # increase cash_on_hold
        else: # no trade, order goes in LOB
            cash -= unfilled * trade_price # reduce cash
            cash_on_hold += unfilled * trade_price # increase cash_on_hold
    else: # counter_party, therefore trade must have occured
        if net_position > 0: # long
            if side == 'bid':
                position_val = (net_position + trade_size) * trade_price
            else: # ask
                if net_position >= trade_size: # still net long or neutral
                    cash += trade_size * trade_price # covered part goes to cash
                    position_val = (net_position - trade_size) * trade_price # update remaining position_val
                else: # net position changes to short
                    cash += net_position * trade_price # covered part goes to cash
                    position_val = (trade_size - net_position) * trade_price # update remaining position_val
        elif net_position < 0: # short
            if side == 'ask':
                position_val = (abs(net_position) + trade_size) * trade_price
            else: # bid
                if net_position >= trade_size: # still net long or neutral
                    cash += trade_size * trade_price # covered part goes to cash
                    position_val = (abs(net_position) - trade_size) * trade_price # update remaining position_val
                else: # net position changes to short
                    cash += net_position * trade_price # covered part goes to cash
                    position_val = (trade_size - abs(net_position)) * trade_price # update remaining position_val
        else: # neutral
            if side == 'bid':
                cash -= trade_size * trade_price
                position_val = trade_size * trade_price
            else: # ask
                cash -= trade_size * trade_price
                position_val = trade_size * trade_price
        # deal with unfilled
        cash -= unfilled * trade_price # reduce cash
        cash_on_hold += unfilled * trade_price # increase cash_on_hold

    return (cash, cash_on_hold, position_val, nav, net_position)
