"""Payments and interest of each statement, summed from its transactions."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from michelito.analysis.categories import clean, is_payment

_INTEREST = re.compile(r"\bINTERES(?:ES)?\b")
_REVERSAL = re.compile(r"\bCR\b.*\bINTERES(?:ES)?\b")

_SQL = "SELECT statement_id, transacted_on, description, amount_cents, direction FROM transactions"


@dataclass(frozen=True)
class StatementMoney:
    """What was paid to the card and what was charged as interest within a statement."""

    payments: Decimal
    interest: Decimal
    # Payments with their date (left out of the equality comparison).
    dated_payments: tuple[tuple[date, Decimal], ...] = field(default=(), compare=False)

    def payments_through(self, cutoff: date | None) -> Decimal:
        """Payments made up to `cutoff` inclusive; with no cutoff, all of them count."""
        if cutoff is None:
            return self.payments
        return sum((value for day, value in self.dated_payments if day <= cutoff), Decimal(0))


def is_interest(description: str, direction: str) -> bool:
    """Interest charge: a debit with the word INTERES(ES) and no "CR" before it (a reversal)."""
    if direction != "debit":
        return False
    text = clean(description)
    return _INTEREST.search(text) is not None and _REVERSAL.search(text) is None


def statement_money(conn: sqlite3.Connection) -> dict[int, StatementMoney]:
    """Payments and interest per `statements.id`; only statements with either kind of line."""
    payments: dict[int, int] = {}
    dated: dict[int, list[tuple[date, Decimal]]] = {}
    interest: dict[int, int] = {}
    for row in conn.execute(_SQL):
        statement_id, transacted_on, description, cents, direction = tuple(row)
        if direction == "credit" and is_payment(description):
            payments[statement_id] = payments.get(statement_id, 0) + cents
            dated.setdefault(statement_id, []).append(
                (date.fromisoformat(transacted_on), Decimal(cents) / 100)
            )
        elif is_interest(description, direction):
            interest[statement_id] = interest.get(statement_id, 0) + cents
    return {
        statement_id: StatementMoney(
            Decimal(payments.get(statement_id, 0)) / 100,
            Decimal(interest.get(statement_id, 0)) / 100,
            tuple(dated.get(statement_id, ())),
        )
        for statement_id in payments.keys() | interest.keys()
    }
