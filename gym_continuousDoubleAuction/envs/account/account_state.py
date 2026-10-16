"""The account fields `Calculate` and `Cash_Processor` work on (issue #152).

Both are mixins of `Account`: they read and write its money fields through `self`. The
fields are created by `Account.reset_acc`; this names the ones the mixins use, so a type
checker can see them and a reader can find out what the mixins depend on without reading
every method. The declarations exist for the checker only (nothing is created at runtime).
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING


class AccountState:
    if TYPE_CHECKING:
        cash: Decimal
        cash_on_hold: Decimal
        position_val: Decimal
        init_nav: Decimal
        nav: Decimal
        prev_nav: Decimal
        max_nav: Decimal
        net_position: int
        cost_basis: Decimal
        entry_vwap: Decimal
        profit: Decimal
        total_profit: Decimal
