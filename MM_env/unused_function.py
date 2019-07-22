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
