"""Helpers about shared expenses and incoming payments that other modules use.

The shared groups themselves (people, entries, splits and payments) are the ledger's
(`ledger`, `ledger_store`, schema 19). What stays here:

- `gross`: a transaction's amount before splitting (the statement's).
- `convert` / `converted`: amounts between RD$ and US$ at a month's rate (`ledger.convert`).
- `is_shareable`: a positive expense; `NOT_SHARED_EXPENSE`: categories never offered to share
  (cash withdrawals, loans, card payments, own transfers, currency exchanges).
- `is_eligible_credit`: a credit that can be a payment from someone (not salary, a card
  payment, an own transfer, interest or another link).
- `fold`, `name_words`: text without accents or capitals, and the words of a name useful to
  match descriptions (`NAME_MIN_LETTERS` letters or more).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from michelito.analysis import categories
from michelito.analysis.ledger import convert as _convert
from michelito.analysis.links import Links
from michelito.analysis.rates import Rate

if TYPE_CHECKING:
    from michelito.analysis.spending import Movement

PICK_WINDOW_DAYS = 120  # how far back the pickers look
NAME_MIN_LETTERS = 4  # words of a name that count for matching descriptions
# Credits that are never a payment from someone.
NOT_REIMBURSEMENT = frozenset(
    {
        categories.SALARY,
        categories.OWN_TRANSFER,
        categories.CARD_PAYMENT,
        categories.CURRENCY_EXCHANGE,
        categories.REIMBURSEMENT,
    }
)
# Transactions that are never a shared expense: cash withdrawals, loan payments (the "AUT PAGO"
# ones), card payments, transfers between my accounts and currency exchanges.
NOT_SHARED_EXPENSE = frozenset(
    {
        categories.CASH,
        categories.LOANS,
        categories.CARD_PAYMENT,
        categories.OWN_TRANSFER,
        categories.CURRENCY_EXCHANGE,
    }
)
# Interest paid by the bank: it lands in "other income" like a transfer, but is never a payment.
_INTEREST = re.compile(r"\bINTERES(ES)?\b")
_WORD = re.compile(r"[a-z0-9]+")


def convert(
    amount: Decimal, source: str, target: str, day: date, rates: Mapping[str, Rate]
) -> Decimal | None:
    """See `ledger.convert`."""
    return _convert(amount, source, target, day, rates)


def converted(credit: Movement, currency: str, rates: Mapping[str, Rate]) -> Decimal | None:
    """What came in with the credit (positive), in `currency` (see `convert`)."""
    return convert(-credit.amount, credit.currency, currency, credit.day, rates)


def gross(move: Movement) -> Decimal:
    """The transaction's amount before splitting (the statement's)."""
    return move.amount if move.gross is None else move.gross


def is_shareable(move: Movement) -> bool:
    return move.kind == "expense" and gross(move) > 0


def is_eligible_credit(move: Movement, links: Links) -> bool:
    """A credit that can be a payment: not salary, a card payment, an own transfer, interest or
    another link."""
    return (
        move.amount < 0
        and move.ref not in NOT_REIMBURSEMENT
        and not move.link
        and not links.is_linked(move.fingerprint)
        and not _INTEREST.search(move.description.upper())
    )


def fold(text: str) -> str:
    """Without accents and in lowercase."""
    plain = unicodedata.normalize("NFKD", text)
    return "".join(c for c in plain if not unicodedata.combining(c)).casefold()


def words(text: str) -> list[str]:
    return _WORD.findall(fold(text))


def name_words(name: str) -> frozenset[str]:
    """The words of a name useful for matching: NAME_MIN_LETTERS letters or more."""
    return frozenset(w for w in words(name) if len(w) >= NAME_MIN_LETTERS and not w.isdigit())
