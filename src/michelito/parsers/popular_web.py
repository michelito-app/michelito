"""Parser of the transactions printout of Popular's website (checking or savings account).

It is not a statement: it is the website page saved as a PDF from the browser. It has the
account (account kind " / <number>"), and a table with posting date, effective date, check
number, reference number, description, amount (a trailing "-" for a debit) and balance (an
overdraft has a leading "-": "-$5.40"). It prints no totals: what is validated is the balance
chain, row by row (each balance is the previous one plus the amount). Rows go from oldest to
newest.

A long description is spread over lines above and below the row (centered on it); that is why
each loose line of the description column is joined to the row closest in height, not to the
one above.

The page does not state the account's currency: a dollar savings account prints a bare "$",
just like a peso one. "$" is DOP unless whoever imports says otherwise (`currency`); "RD$" and
"US$" do state it, and if they contradict the given one the printout is not accepted.

The posting date is used: it is the one that orders the table and the balance chain, and the
one that splits movements between statements, so the printout's range compares well with an
official statement's period.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from michelito.parsers.common import (
    CREDIT,
    DEBIT,
    Line,
    Page,
    ParseError,
    Section,
    Statement,
    Transaction,
    Word,
    normalize,
    parse_amount,
    parse_date,
)

NAME = "popular_web"
INSTITUTION = "popular"

_DATE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
# A negative amount has a trailing "-" ("$5.40-"); a negative balance (overdraft), a leading one
# ("-$5.40"). Both forms are accepted in both columns, never at the same time.
_MONEY = re.compile(
    r"^(?P<lead>-)?(?P<symbol>US\$|RD\$|\$)(?P<amount>\d{1,3}(?:,\d{3})*\.\d{2})(?P<trail>-)?$"
)
CURRENCIES = ("DOP", "USD")
_SYMBOLS = {"RD$": "DOP", "US$": "USD"}  # a bare "$": the given currency, or DOP
# An amount is in its column if its right edge is within this distance of the header's.
_COLUMN_TOLERANCE = 15.0
_ALIGN_TOLERANCE = 3.0
# A description line is joined to the closest row if it is at this height or less.
_ATTACH_DISTANCE = 24.0
# The printout's Spanish text (normalized: lowercase, no accents).
# spanish-data: begin
_ACCOUNT = re.compile(r"^cuenta (?P<type>corriente|de ahorros?) / (?P<number>\d{6,})$")
# Account type -> (kind, product stored for the account).
_KINDS = {
    "corriente": ("checking", "Cuenta corriente"),
    "de ahorro": ("savings", "Cuenta de ahorro"),
    "de ahorros": ("savings", "Cuenta de ahorro"),
}
_TITLE = "transacciones"
_DESCRIPTION = "descripcion"  # table column headers
_AMOUNT = "monto"
_BALANCE = "balance"
# spanish-data: end
_HEADER = (_DESCRIPTION, _AMOUNT, _BALANCE)


@dataclass(frozen=True)
class _Columns:
    detail_left: float
    amount_right: float
    balance_right: float


@dataclass(frozen=True)
class _Row:
    page: int
    top: float
    posted: date
    reference: str | None
    inline: str
    amount: str
    balance: str
    raw: str


def matches(pages: tuple[Page, ...]) -> bool:
    if not pages:
        return False
    texts = [normalize(line.text) for line in pages[0]]
    return (
        any(_ACCOUNT.match(text) for text in texts)
        and _TITLE in texts
        and any(_is_header(line) for line in pages[0])
    )


def parse(pages: tuple[Page, ...], currency: str | None = None) -> Statement:
    """`currency`: the account's currency, if known (the bare "$" does not state it)."""
    if currency is not None and currency not in CURRENCIES:
        raise ValueError(f"unknown currency: {currency!r}")
    if not pages:
        raise ParseError("empty document")
    kind, product, identifier = _account(pages[0])
    rows, details = _rows_and_details(pages)
    if not rows:
        raise ParseError("the printout has no movements")
    currency = _currency(rows, currency)
    transactions = tuple(
        _transaction(row, details.get(i, []), currency) for i, row in enumerate(rows)
    )
    first = transactions[0]
    if first.balance is None:  # pragma: no cover - _transaction always sets the balance
        raise ParseError("the first row has no balance")
    opening = first.balance - _signed(first)
    section = Section(
        currency=currency,
        previous_balance=opening,
        closing_balance=transactions[-1].balance,
        minimum_payment=None,
        credit_limit=None,
        printed_debits=_sum(transactions, DEBIT),
        printed_credits=_sum(transactions, CREDIT),
        transactions=transactions,
    )
    days = [item.transacted_on for item in transactions]
    return Statement(
        parser=NAME,
        institution=INSTITUTION,
        kind=kind,
        product=product,
        identifier=identifier,
        period_end=max(days),
        due_date=None,
        sections=(section,),
        period_start=min(days),
    )


def _account(page: Page) -> tuple[str, str, str]:
    for line in page:
        found = _ACCOUNT.match(normalize(line.text))
        if found:
            kind, product = _KINDS[found["type"]]
            return kind, product, found["number"]
    raise ParseError("the account was not found in the header")


def _is_header(line: Line) -> bool:
    keys = {normalize(word.text) for word in line.words}
    return all(name in keys for name in _HEADER)


def _columns(line: Line) -> _Columns:
    found: dict[str, Word] = {}
    for word in line.words:
        found.setdefault(normalize(word.text), word)
    return _Columns(found[_DESCRIPTION].x0, found[_AMOUNT].x1, found[_BALANCE].x1)


def _rows_and_details(
    pages: tuple[Page, ...],
) -> tuple[list[_Row], dict[int, list[tuple[int, float, str]]]]:
    """Rows (in order) and, per row, the description lines that belong to it."""
    rows: list[_Row] = []
    loose: list[tuple[int, float, str]] = []
    columns: _Columns | None = None
    for number, page in enumerate(pages):
        # What comes before the table header (the account's header, the browser's) is not
        # table; a page without a table header goes on with the previous page's columns.
        in_table = not any(_is_header(line) for line in page)
        for line in page:
            if _is_header(line):
                columns, in_table = _columns(line), True
                continue
            if columns is None or not in_table:
                continue
            row = _row(line, columns, number)
            if row is not None:
                rows.append(row)
            elif _has_money(line, columns):
                # An amount outside a row would be a movement lost silently.
                raise ParseError("a line with an amount outside a row")
            elif _is_detail(line, columns):
                loose.append((number, line.words[0].top, line.text))
    details: dict[int, list[tuple[int, float, str]]] = {}
    for item in loose:
        owner = _nearest_row(rows, item[0], item[1])
        if owner is not None:
            details.setdefault(owner, []).append(item)
    return rows, details


def _row(line: Line, columns: _Columns, page: int) -> _Row | None:
    """The row that starts with the posting date; if something is not in its column, it fails
    (a row lost silently would only be noticed if it breaks the chain)."""
    words = line.words
    if not _DATE.match(words[0].text) or words[0].x0 >= columns.detail_left - _ALIGN_TOLERANCE:
        return None
    if len(words) < 4:
        raise ParseError(f"incomplete row of {words[0].text}")
    amount, balance = words[-2:]
    if not (
        _DATE.match(words[1].text)
        and _in_column(amount, columns.amount_right)
        and _in_column(balance, columns.balance_right)
    ):
        raise ParseError(f"row of {words[0].text} without effective date, amount or balance")
    middle = words[2:-2]
    left = columns.detail_left - _ALIGN_TOLERANCE
    # The check-number and reference-number columns go together in `reference`.
    reference = " ".join(w.text for w in middle if w.x0 < left) or None
    inline = " ".join(w.text for w in middle if w.x0 >= left)
    return _Row(
        page=page,
        top=words[0].top,
        posted=parse_date(words[0].text),
        reference=reference,
        inline=inline,
        amount=amount.text,
        balance=balance.text,
        raw=line.text,
    )


def _in_column(word: Word, right: float) -> bool:
    return _match_money(word.text) is not None and abs(word.x1 - right) <= _COLUMN_TOLERANCE


def _match_money(text: str) -> re.Match[str] | None:
    found = _MONEY.match(text)
    if found is None or (found["lead"] and found["trail"]):
        return None
    return found


def _has_money(line: Line, columns: _Columns) -> bool:
    return any(
        _in_column(w, columns.amount_right) or _in_column(w, columns.balance_right)
        for w in line.words
    )


def _is_detail(line: Line, columns: _Columns) -> bool:
    """A loose description line: it starts in its column (and has no amounts)."""
    return line.words[0].x0 >= columns.detail_left - _ALIGN_TOLERANCE


def _nearest_row(rows: list[_Row], page: int, top: float) -> int | None:
    """The row of the same page closest in height; on a tie, the one above."""
    candidates = [(abs(row.top - top), index) for index, row in enumerate(rows) if row.page == page]
    if not candidates:
        return None
    distance, index = min(candidates)
    return index if distance <= _ATTACH_DISTANCE else None


def _currency(rows: list[_Row], chosen: str | None) -> str:
    symbols = {_symbol(text) for row in rows for text in (row.amount, row.balance)}
    bare = chosen or "DOP"
    currencies = {_SYMBOLS.get(symbol, bare) for symbol in symbols}
    if len(currencies) != 1:
        raise ParseError("the printout mixes currencies")
    found = currencies.pop()
    if chosen is not None and found != chosen:
        raise ParseError(f"the printout says {found}, but {chosen} was given")
    return found


def _symbol(text: str) -> str:
    found = _match_money(text)
    if found is None:  # pragma: no cover - _row only accepts amounts with a symbol
        raise ParseError(f"invalid amount: {text!r}")
    return found["symbol"]


def _money(text: str) -> Decimal:
    found = _match_money(text)
    if found is None:  # pragma: no cover - _row only accepts amounts with a symbol
        raise ParseError(f"invalid amount: {text!r}")
    value = parse_amount(found["amount"])
    return -value if found["lead"] or found["trail"] else value


def _transaction(row: _Row, details: list[tuple[int, float, str]], currency: str) -> Transaction:
    pieces = sorted([(row.top, row.inline), *((top, text) for _, top, text in details)])
    signed = _money(row.amount)
    return Transaction(
        transacted_on=row.posted,
        posted_on=row.posted,
        description=" ".join(" ".join(text for _, text in pieces).split()),
        amount=abs(signed),
        direction=DEBIT if signed < 0 else CREDIT,
        currency=currency,
        reference=row.reference,
        mcc=None,
        raw_line=row.raw,
        balance=_money(row.balance),
    )


def _signed(item: Transaction) -> Decimal:
    return item.amount if item.direction == CREDIT else -item.amount


def _sum(transactions: tuple[Transaction, ...], direction: str) -> Decimal:
    return sum((item.amount for item in transactions if item.direction == direction), Decimal(0))
