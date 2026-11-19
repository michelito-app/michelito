"""Parser of BHD bank's savings-account statement.

The header data go in a right-hand column: each label on one line and its value on the next.
The transactions have debit, credit and balance columns; at the end the count and sum of each
kind are printed.

There are two variants of the table. The emailed one dates rows "dd/mm" and fills only the
movement's column. The website one dates rows "dd/mm/yyyy" and fills both columns ("0.00" in
the one that does not apply): the direction comes from the column with an amount.

The website also lets you download the current month, before the closing date: it prints the
month's closing date (after the last row) and a final balance of 0.00, so it does not balance
as a statement. That document is partial and is stored as a printout (`PARTIAL_NAME`, see
`db.PRINTOUT_PARSERS`), not as a statement. The website does not print when it was downloaded:
it covers from the start of the month (the table's opening-balance line with its dd/mm/yyyy, or
the day after the previous-balance one) to the date of the last row, the only thing known to be
listed already. The following days up to the download stay uncovered: that is better than
taking as covered days that may still be missing postings. Its closing balance is the Balance
column of the last row, and the balance chain is validated row by row (and the printed totals)
instead of the printed final balance. When the full month arrives it is stored as a statement
and wins on those days. A month that really closes at 0.00 with no rows up to the closing date
also stays a printout: it counts while there is no statement and does not block the official
one.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal

from michelito.parsers.common import (
    CREDIT,
    CURRENCIES,
    DEBIT,
    Line,
    Page,
    ParseError,
    Section,
    Statement,
    Transaction,
    Word,
    column_positions,
    is_amount,
    nearest_column,
    normalize,
    parse_amount,
    parse_date,
    resolve_day_month,
)

NAME = "bhd_savings"
PARTIAL_NAME = "bhd_savings_partial"  # the current month downloaded from the website: a printout
INSTITUTION = "bhd"

_DAY_MONTH = re.compile(r"^\d{2}/\d{2}$")
_FULL_DATE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_REFERENCE = re.compile(r"^\d{6,}$")
_VALUE_SEARCH_LINES = 4
# The 2025 format does not print the currency; those accounts are in DOP.
_DEFAULT_CURRENCY = "DOP"
# The statement's Spanish text (labels normalized: lowercase, no accents).
# spanish-data: begin
_DEBITS = "debitos"  # column headers of the transaction table
_CREDITS = "creditos"
_BALANCE = "balance"
# Printed totals at the end: count and sum of debits and of credits.
_DEBIT_TOTAL = re.compile(r"\b(?P<count>\d+)\s?DEBITOS\s+(?P<amount>[\d,]+\.\d{2})\b")
_CREDIT_TOTAL = re.compile(r"\b(?P<count>\d+)\s?CREDITOS\s+(?P<amount>[\d,]+\.\d{2})\b")
# First line of the website table: "Balance inicial: 01/01/2026" is the first day of the period;
# "Balance anterior: 31/12/2025", the previous closing date.
_OPENING = re.compile(r"^balance (?P<kind>inicial|anterior): (?P<day>\d{2}/\d{2}/\d{4})\b")
_OPENING_IS_FIRST_DAY = "inicial"
# Header labels (each value is printed below its label).
_ACCOUNT_LABEL = "numero de cuenta"
_CURRENCY_LABEL = "moneda"
_CLOSING_DATE_LABEL = "fecha de corte"
_OPENING_BALANCE_LABEL = "balance inicial"
_FINAL_BALANCE_LABEL = "balance final"
_PRODUCT = "Cuenta de ahorro"  # stored as the account's product
# spanish-data: end
_COLUMNS = (_DEBITS, _CREDITS, _BALANCE)
_MOVEMENT_COLUMNS = (_DEBITS, _CREDITS)


def matches(pages: tuple[Page, ...]) -> bool:
    if not pages:
        return False
    texts = [normalize(line.text) for line in pages[0]]
    return any(text.endswith(_ACCOUNT_LABEL) for text in texts) and any(
        text.endswith(_OPENING_BALANCE_LABEL) for text in texts
    )


def parse(pages: tuple[Page, ...]) -> Statement:
    if not pages:
        raise ParseError("empty document")
    first = pages[0]
    account = _value_after(first, _ACCOUNT_LABEL, lambda text: "-" in text)
    currency_text = _optional_value(first, _CURRENCY_LABEL, lambda text: text in CURRENCIES)
    currency = CURRENCIES[currency_text] if currency_text else _DEFAULT_CURRENCY
    period_end = parse_date(_value_after(first, _CLOSING_DATE_LABEL, _is_date))
    opening = parse_amount(_value_after(first, _OPENING_BALANCE_LABEL, is_amount))
    printed_final = _optional_value(first, _FINAL_BALANCE_LABEL, is_amount)
    movements = _read_movements(pages, currency, period_end)
    totals = _read_totals(pages)
    statement = Statement(
        parser=NAME,
        institution=INSTITUTION,
        kind="savings",
        product=_PRODUCT,
        identifier=account.split("-", 1)[-1],
        period_end=period_end,
        due_date=None,
        sections=(),
    )
    if _is_partial(printed_final, movements, period_end):
        # The balance chain replaces the 0.00 final balance: each row carries its own.
        chained = [
            replace(m, transaction=replace(m.transaction, balance=m.balance)) for m in movements
        ]
        return _partial(statement, pages, _section(currency, opening, None, totals, chained))
    if printed_final is not None:
        closing = parse_amount(printed_final)
    else:
        closing = movements[-1].balance if movements else opening
    section = _section(currency, opening, closing, totals, movements)
    return replace(statement, sections=(section,))


def _section(
    currency: str,
    opening: Decimal,
    closing: Decimal | None,
    totals: _Totals,
    movements: list[_Movement],
) -> Section:
    return Section(
        currency=currency,
        previous_balance=opening,
        closing_balance=closing,
        minimum_payment=None,
        credit_limit=None,
        printed_debits=totals.debits,
        printed_credits=totals.credits,
        transactions=tuple(m.transaction for m in movements),
    )


def _is_partial(printed_final: str | None, movements: list[_Movement], cut: date) -> bool:
    """Is it the current month? Website rows, a final balance of 0.00 and no rows up to the
    closing date.

    A month that really closes at 0.00 also lands here: as a printout it is safe (it counts
    while there is no official statement and does not prevent importing the full month later).
    """
    if printed_final is None or parse_amount(printed_final) != 0 or not movements:
        return False
    return all(m.portal for m in movements) and movements[-1].transaction.transacted_on < cut


def _partial(statement: Statement, pages: tuple[Page, ...], section: Section) -> Statement:
    """The current month: from the start of the period to the last row, closing at its balance."""
    start = _period_start(pages)
    # Website rows go from oldest to newest: the last one gives the end and the balance.
    last = section.transactions[-1].transacted_on
    outside = [item.transacted_on for item in section.transactions if item.transacted_on < start]
    if outside:
        raise ParseError(f"movement on {outside[0]:%d/%m/%Y} before the start of the period")
    return replace(
        statement,
        parser=PARTIAL_NAME,
        period_end=last,
        period_start=start,
        sections=(replace(section, closing_balance=section.transactions[-1].balance),),
    )


def _period_start(pages: tuple[Page, ...]) -> date:
    for line in (line for page in pages for line in page):
        found = _OPENING.match(normalize(line.text))
        if found:
            day = parse_date(found["day"])
            return day if found["kind"] == _OPENING_IS_FIRST_DAY else day + timedelta(days=1)
    raise ParseError("the start of the current month's period was not found")


def _value_after(page: Page, label: str, accept: Callable[[str], bool]) -> str:
    value = _optional_value(page, label, accept)
    if value is None:
        raise ParseError(f"'{label}' was not found in the savings statement")
    return value


def _optional_value(page: Page, label: str, accept: Callable[[str], bool]) -> str | None:
    """The first acceptable value written below the label, in its same column.

    The left column (name and address) is interleaved with the labels, so the words that end
    before the label starts are skipped; `accept` skips loose text fragments that are not the
    value. The label is compared without case or accents (they change between formats).
    """
    label_size = len(label.split())
    for index, line in enumerate(page):
        if not normalize(line.text).endswith(label):
            continue
        label_left = line.words[-label_size].x0
        for following in page[index + 1 : index + 1 + _VALUE_SEARCH_LINES]:
            for word in following.words:
                if word.x1 > label_left and accept(word.text):
                    return word.text
    return None


def _is_date(text: str) -> bool:
    try:
        parse_date(text)
    except ParseError:
        return False
    return True


@dataclass(frozen=True)
class _Movement:
    transaction: Transaction  # without balance, except in the current month (see `parse`)
    balance: Decimal  # the Balance column's, after the movement
    portal: bool  # a website row (date dd/mm/yyyy)


def _read_movements(pages: tuple[Page, ...], currency: str, period_end: date) -> list[_Movement]:
    columns: dict[str, float] | None = None
    found: list[_Movement] = []
    for line in (line for page in pages for line in page):
        if header := column_positions(line, _COLUMNS):
            columns = header
        elif columns is not None and _is_movement(line.tokens):
            transaction, balance = _movement(line, columns, currency, period_end)
            found.append(
                _Movement(transaction, balance, _FULL_DATE.match(line.tokens[0]) is not None)
            )
    return found


def _is_movement(tokens: tuple[str, ...]) -> bool:
    if len(tokens) < 4 or not (is_amount(tokens[-1]) and is_amount(tokens[-2])):
        return False
    if _FULL_DATE.match(tokens[0]):
        return len(tokens) >= 5 and is_amount(tokens[-3])
    return _DAY_MONTH.match(tokens[0]) is not None


def _movement(
    line: Line, columns: Mapping[str, float], currency: str, period_end: date
) -> tuple[Transaction, Decimal]:
    tokens = line.tokens
    has_reference = _REFERENCE.match(tokens[1]) is not None
    movement_columns = {name: columns[name] for name in _MOVEMENT_COLUMNS}
    if _FULL_DATE.match(tokens[0]):
        transacted_on = parse_date(tokens[0])
        amount, column = _portal_amount(line.words[-3:-1], movement_columns)
        amounts_from = -3
    else:
        transacted_on = resolve_day_month(tokens[0], period_end)
        movement = line.words[-2]
        amount = parse_amount(movement.text)
        column = nearest_column(movement, movement_columns)
        amounts_from = -2
    transaction = Transaction(
        transacted_on=transacted_on,
        posted_on=None,
        description=" ".join(tokens[2 if has_reference else 1 : amounts_from]),
        amount=abs(amount),
        direction=CREDIT if column == _CREDITS else DEBIT,
        currency=currency,
        reference=tokens[1] if has_reference else None,
        mcc=None,
        raw_line=line.text,
    )
    return transaction, parse_amount(tokens[-1])


def _portal_amount(words: tuple[Word, ...], columns: Mapping[str, float]) -> tuple[Decimal, str]:
    """Amount and column of a website row: one amount per column, only one of them non-zero."""
    by_column = {nearest_column(word, columns): parse_amount(word.text) for word in words}
    if len(by_column) != len(columns):
        raise ParseError("a website row does not have an amount in each column")
    filled = [(amount, name) for name, amount in by_column.items() if amount != 0]
    if len(filled) != 1:
        raise ParseError("a website row does not have an amount in exactly one column")
    return filled[0]


@dataclass(frozen=True)
class _Totals:
    debits: Decimal
    credits: Decimal


def _read_totals(pages: tuple[Page, ...]) -> _Totals:
    """The printed sum of debits and of credits (the printed count is not reliable).

    They are required: without them the only check would be the balance of the last row read,
    which is derived from the same thing being validated.
    """
    text = " ".join(line.text for page in pages for line in page)
    debit = _DEBIT_TOTAL.search(text)
    credit = _CREDIT_TOTAL.search(text)
    if debit is None or credit is None:
        raise ParseError("the printed debit and credit totals were not found")
    return _Totals(
        debits=parse_amount(debit["amount"]),
        credits=parse_amount(credit["amount"]),
    )
