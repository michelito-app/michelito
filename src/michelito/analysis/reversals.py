"""Bank account reversals: a "DEV ..." credit that cancels a recent debit.

A bank credit whose text starts with the word "DEV" (`categories.is_reversal`) is the
reversal of a debit of the same account, currency and amount made up to REVERSAL_DAYS days
earlier (or the same day). It takes that debit's final category (with the user's
corrections), so both cancel out inside that category: correcting only the LBTR to the
"between my accounts" category is enough for its DEV not to become income. Pairing does not
depend on corrections (account, currency, amount and date). One to one: each debit cancels a
single reversal, the closest in date first (on a tie, the first in load order). It is greedy,
in reversal order: with several equal debits and reversals in the same window it may not
find the optimal pairing (rare: same amount, account and week).

The `original_category` of a paired reversal is its debit's final category. There only a
correction of that transaction wins: merchant rules (and those of the previous key) do not
count, because all reversals share a key ("DEV LBTR").

Without its debit, the reversal keeps `categories.categorize_bank`: the debit rules on the
text after "DEV" (a fee, a tax..., negated) or the third-party transfers category, negated;
there merchant rules do apply.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from typing import TYPE_CHECKING

from michelito.analysis import categories
from michelito.analysis.accounts import BANK_KINDS, AccountInfo

if TYPE_CHECKING:
    from michelito.analysis.spending import Movement

REVERSAL_DAYS = 7


def pair_reversals(
    movements: Sequence[Movement], accounts: Sequence[AccountInfo]
) -> dict[str, str]:
    """Fingerprint of each paired reversal -> final category of its debit."""
    banks = {info.key for info in accounts if info.kind in BANK_KINDS}
    rows = [(index, m) for index, m in enumerate(movements) if m.account in banks]
    free = [(index, m) for index, m in rows if m.amount > 0]
    window = timedelta(days=REVERSAL_DAYS)
    found: dict[str, str] = {}
    credits = [(i, m) for i, m in rows if m.amount < 0 and categories.is_reversal(m.description)]
    for _, credit in sorted(credits, key=lambda pair: (pair[1].day, pair[0])):
        near = [
            (index, debit)
            for index, debit in free
            if debit.account == credit.account
            and debit.currency == credit.currency
            and debit.amount == -credit.amount
            and timedelta(0) <= credit.day - debit.day <= window
        ]
        if near:
            chosen = min(near, key=lambda pair: (credit.day - pair[1].day, pair[0]))
            free.remove(chosen)
            found[credit.fingerprint] = chosen[1].ref
    return found
