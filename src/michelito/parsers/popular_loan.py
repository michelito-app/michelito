"""Parser of Popular's loan history, the PDF the bank's account officer sends on request: one
loan, every movement since its disbursement.

The header has the loan number, the currency, the holder and the loan's state on the day it was
printed: the principal balance, the interest accrued, late charges, insurance and what paying
it off that day costs. Then one row per movement: one
or two dates (the older rows have the posting and the effective date as "D-MM-YY" and a
transaction code; the newer ones only the effective date as "D-Mon-YY"), the description, the
amount and the principal balance after it.

A row does not say how its amount splits. It is read from the balances: what the balance went
down is principal and the rest of the amount is interest; a payment that leaves the balance as
it was paid no principal, so it is a charge (insurance, fees, late interest) and goes to
`other`. The payments of one day become one line, like the bank's statements have them.

The history is only stored if it squares: the rows are in date order, no amount or balance is
negative, every disbursement adds its amount to the balance, no payment pays more principal
than its amount, and the last row ends on the printed principal balance.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from michelito.analysis.loan_schedule import StatementLine
from michelito.parsers.common import (
    Line,
    LoanStatement,
    Page,
    ParseError,
    is_amount,
    normalize,
    parse_amount,
)

NAME = "popular_loan"
INSTITUTION = "popular"

# spanish-data: begin
_TITLE = ("historial", "prestamo")
_NUMBER_LABEL = "prestamo:"
_BALANCE_LABEL = ("saldo", "de", "capital:")
_NUMBER = re.compile(r"^\d{6,}$")
_DATE = re.compile(r"^(?P<day>\d{1,2})-(?P<month>\d{2}|[A-Za-z]{3})-(?P<year>\d{2})$")
_CODE = re.compile(r"^\d{1,3}$")
_CENTURY = 2000
_DISBURSEMENT = "desembolso"
_PAYMENT = "pago"
# spanish-data: end
# The bank prints the month in English; Spanish is accepted where it differs.
_MONTHS = {
    "jan": 1, "ene": 1, "feb": 2, "mar": 3, "apr": 4, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12, "dic": 12,
}  # fmt: skip


@dataclass(frozen=True)
class _Movement:
    row: int  # its place in the history, from 1 (for the error messages)
    day: date
    description: str
    amount: Decimal
    balance: Decimal


def matches(pages: tuple[Page, ...]) -> bool:
    if not pages:
        return False
    starts = [_normal(line)[:3] for line in pages[0]]
    return any(start[:2] == _TITLE for start in starts) and _BALANCE_LABEL in starts


def parse(pages: tuple[Page, ...]) -> LoanStatement:
    lines = [line for page in pages for line in page]
    number = _number(lines)
    printed = _printed_balance(lines)
    movements = list(_movements(lines))
    payments = _payments(movements)
    if not payments:
        raise ParseError("the loan history has no payments")
    if movements[-1].balance != printed:
        raise ParseError("the history does not end on the printed principal balance")
    return LoanStatement(number=number, lines=_by_day(payments))


def _normal(line: Line) -> tuple[str, ...]:
    return tuple(normalize(token) for token in line.tokens)


def _number(lines: list[Line]) -> str:
    for line in lines:
        tokens = line.tokens
        if len(tokens) > 1 and normalize(tokens[0]) == _NUMBER_LABEL and _NUMBER.match(tokens[1]):
            return tokens[1]
    raise ParseError("the loan number was not found")


def _printed_balance(lines: list[Line]) -> Decimal:
    size = len(_BALANCE_LABEL)
    for line in lines:
        tokens = line.tokens
        if _normal(line)[:size] == _BALANCE_LABEL and len(tokens) > size:
            return _amount(tokens[size])
    raise ParseError("the principal balance was not found")


def _amount(text: str) -> Decimal:
    if not is_amount(text):
        raise ParseError("an amount could not be read")
    return parse_amount(text)


def _day(text: str) -> date | None:
    found = _DATE.match(text)
    if found is None:
        return None
    month = found["month"]
    number = int(month) if month.isdigit() else _MONTHS.get(month.lower())
    if number is None:
        return None
    try:
        return date(_CENTURY + int(found["year"]), number, int(found["day"]))
    except ValueError:
        return None


def _movements(lines: list[Line]) -> Iterator[_Movement]:
    """The rows that start with a date: the last date is the effective one, the last two tokens
    are the amount and the balance after it, and what is between them (without the transaction
    code) is the description."""
    row = 0
    for line in lines:
        tokens = list(line.tokens)
        days = []
        while tokens and (day := _day(tokens[0])) is not None:
            days.append(day)
            tokens.pop(0)
        if not days:
            continue
        row += 1
        if tokens and _CODE.match(tokens[0]):
            tokens.pop(0)
        if len(tokens) < 3:  # noqa: PLR2004 (a description, the amount and the balance)
            raise ParseError(f"row {row} of the loan history is incomplete")
        *words, amount, balance = tokens
        yield _Movement(
            row, days[-1], normalize(" ".join(words)), _amount(amount), _amount(balance)
        )


def _payments(movements: list[_Movement]) -> list[StatementLine]:
    """Each payment split by the balances, after checking that every row follows the one
    before it."""
    balance: Decimal | None = None
    last_day: date | None = None
    found: list[StatementLine] = []
    for item in movements:
        if item.amount < 0 or item.balance < 0:
            raise ParseError(f"row {item.row}: a negative amount or balance")
        if last_day is not None and item.day < last_day:
            raise ParseError(f"row {item.row}: its date is before the previous row's")
        last_day = item.day
        if item.description.startswith(_DISBURSEMENT):
            if item.balance != (balance or Decimal(0)) + item.amount:
                raise ParseError(f"row {item.row}: the disbursement does not add up")
            balance = item.balance
            continue
        if item.description != _PAYMENT or balance is None:
            raise ParseError(f"row {item.row} of the loan history is not a known movement")
        principal = balance - item.balance
        if not Decimal(0) <= principal <= item.amount:
            raise ParseError(f"row {item.row}: the payment does not explain the balance")
        rest = item.amount - principal
        zero = Decimal(0)
        found.append(
            StatementLine(
                day=item.day,
                principal=principal,
                interest=rest if principal else zero,
                balance=item.balance,
                other=zero if principal else rest,
            )
        )
        balance = item.balance
    return found


def _by_day(payments: list[StatementLine]) -> tuple[StatementLine, ...]:
    """One line per day: the sum of that day's payments and the balance after the last one."""
    merged: dict[date, StatementLine] = {}
    for line in payments:
        before = merged.get(line.day)
        merged[line.day] = (
            line
            if before is None
            else StatementLine(
                day=line.day,
                principal=before.principal + line.principal,
                interest=before.interest + line.interest,
                balance=line.balance,
                other=before.other + line.other,
            )
        )
    return tuple(merged[day] for day in sorted(merged))
