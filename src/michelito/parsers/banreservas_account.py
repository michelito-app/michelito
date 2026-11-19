"""Parser of Banreservas' monthly savings-account statement, downloaded from the website.

One page per month (more if there are many movements). At the top it has the holder line, an
account-number / alias / report-date / balance row with its values, and the movements title with
the period ("01/01/2026 - 01/02/2026"). The table has date, description, debit, credit and
balance columns: a debit has a leading "-" and goes in its column; a credit, unsigned, in its
own. Rows go from newest to oldest; here they are returned from oldest to newest, like the other
parsers. The description continues on lines below the row (the counterparty of a transfer): each
loose line is joined to the row above.

It prints neither totals nor the closing balance: the header's balance is that of the report
day. The balance chain is validated row by row; the previous balance comes from the oldest row
(its balance minus its amount) and the closing one is the newest row's.

The printed period ends on the first day of the next month, the same day the next statement
starts with (their balances chain without a gap): that last day is not part of the statement.
The closing date is the day before, and a row dated on the final date is out of the period (an
error): if the bank repeated it in both statements it would be counted twice.

A statement downloaded before the month closes (reported on the last covered day or earlier) is
partial: it is stored as a printout (`PARTIAL_NAME`, see `db.PRINTOUT_PARSERS`), not as a
statement. It covers from the start of the period to the report day: up to that day the bank
lists everything there was (days without rows are covered too), and what came later it cannot
bring. Its closing balance is the header's, that of the report day, and the chain has to reach
it. When the full month arrives it is stored as a statement and wins on those days.

The statement does not state the account type: it is taken as savings (it pays interest). Nor
does it state the currency unless "US$"/"USD" shows up: without that it is DOP.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
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
    is_amount,
    normalize,
    parse_amount,
    parse_date,
)

NAME = "banreservas_account"
PARTIAL_NAME = "banreservas_partial"  # the current month: a printout, not a statement
INSTITUTION = "banreservas"
KIND = "savings"

_DATE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_ACCOUNT = re.compile(r"^\d{6,}$")
_PERIOD = re.compile(r"^(?P<start>\d{2}/\d{2}/\d{4}) - (?P<end>\d{2}/\d{2}/\d{4})\b")
_USD = {"us$", "usd"}
_DOP = {"rd$", "dop"}
# An amount is in its column if its right edge is within this distance of the header's.
_COLUMN_TOLERANCE = 15.0
_ALIGN_TOLERANCE = 3.0
# A description line follows the row (or its previous line) at this height or less.
_WRAP_DISTANCE = 16.0
# The statement's Spanish text (normalized: lowercase, no accents).
# spanish-data: begin
PRODUCT = "Cuenta de ahorro"  # stored as the account's product
_TABLE_HEADER = ("fecha", "descripcion", "debito", "credito", "balance")
_ACCOUNT_HEADER = ("numero de cuenta", "alias", "fecha del reporte", "balance")
_HOLDER_LABEL = "titular:"
_MOVEMENTS_TITLE = "movimientos"  # the line above the period
# Page footer ("Página 1 de 2"): not part of a description.
_FOOTER = re.compile(r"^(pagina\s+)?\d+\s*(de|/)\s*\d+$|^pagina\s+\d+$")
# spanish-data: end


@dataclass(frozen=True)
class _Columns:
    detail_left: float
    debit_left: float  # a description does not reach the debit column
    debit_right: float
    credit_right: float
    balance_right: float


@dataclass(frozen=True)
class _Header:
    identifier: str
    report: date
    balance: Decimal  # the one of the report day


@dataclass(frozen=True)
class _Row:
    day: date
    signed: Decimal
    balance: Decimal
    pieces: tuple[str, ...]
    raw: str


def matches(pages: tuple[Page, ...]) -> bool:
    if not pages:
        return False
    texts = [normalize(line.text) for line in pages[0]]
    return (
        any(text.startswith(_HOLDER_LABEL) for text in texts)
        and any(all(label in text for label in _ACCOUNT_HEADER) for text in texts)
        and _MOVEMENTS_TITLE in texts
        and any(_is_table_header(line) for line in pages[0])
    )


def parse(pages: tuple[Page, ...]) -> Statement:
    if not pages:
        raise ParseError("empty document")
    header = _header(pages[0])
    start, end = _period(pages[0])
    partial = header.report <= end
    covered = header.report if partial else end
    rows = _rows(pages)
    if not rows:
        raise ParseError("the statement has no movements")
    outside = [row.day for row in rows if not start <= row.day <= covered]
    if outside:
        raise ParseError(f"movement on {outside[0]:%d/%m/%Y} out of the period")
    currency = _currency(pages)
    oldest = rows[-1]
    section = Section(
        currency=currency,
        previous_balance=oldest.balance - oldest.signed,
        # Partial: the header's balance is today's, and the chain has to reach it.
        closing_balance=header.balance if partial else rows[0].balance,
        minimum_payment=None,
        credit_limit=None,
        printed_debits=None,
        printed_credits=None,
        transactions=tuple(_transaction(row, currency) for row in reversed(rows)),
    )
    return Statement(
        parser=PARTIAL_NAME if partial else NAME,
        institution=INSTITUTION,
        kind=KIND,
        product=PRODUCT,
        identifier=header.identifier,
        period_end=covered,
        due_date=None,
        sections=(section,),
        period_start=start,
    )


def _header(page: Page) -> _Header:
    """Account number, report date and balance: the line after their header."""
    for index, line in enumerate(page[:-1]):
        text = normalize(line.text)
        if all(label in text for label in _ACCOUNT_HEADER):
            words = page[index + 1].tokens
            dates = [w for w in words if _DATE.match(w)]
            if words and _ACCOUNT.match(words[0]) and len(dates) == 1 and is_amount(words[-1]):
                return _Header(words[0], parse_date(dates[0]), parse_amount(words[-1]))
            break
    raise ParseError("the account, report date and balance were not found")


def _period(page: Page) -> tuple[date, date]:
    """The first and last days covered: the printed end date already belongs to the next one."""
    for index, line in enumerate(page[:-1]):
        if normalize(line.text) == _MOVEMENTS_TITLE:
            found = _PERIOD.match(page[index + 1].text)
            if found:
                start, after = parse_date(found["start"]), parse_date(found["end"])
                if start < after:
                    return start, after - timedelta(days=1)
            break
    raise ParseError("the period of the movements was not found")


def _currency(pages: tuple[Page, ...]) -> str:
    """The currency the header states (up to the table titles), never a description."""
    tokens = {normalize(w) for line in _header_lines(pages[0]) for w in line.tokens}
    dollars, dop = bool(tokens & _USD), bool(tokens & _DOP)
    if dollars and dop:
        raise ParseError("the statement mixes currencies")
    return "USD" if dollars else "DOP"


def _header_lines(page: Page) -> list[Line]:
    lines = sorted(page, key=lambda item: item.words[0].top)
    end = next((i for i, line in enumerate(lines) if _is_table_header(line)), len(lines) - 1)
    return lines[: end + 1]


def _is_table_header(line: Line) -> bool:
    return tuple(normalize(word.text) for word in line.words) == _TABLE_HEADER


def _columns(line: Line) -> _Columns:
    words = line.words
    return _Columns(words[1].x0, words[2].x0, words[2].x1, words[3].x1, words[4].x1)


def _rows(pages: tuple[Page, ...]) -> list[_Row]:
    """Rows in the statement's order, each one with its description lines."""
    rows: list[_Row] = []
    columns: _Columns | None = None
    for page in pages:
        # What comes before the table header (the page header) is not table; a page without a
        # table header goes on with the previous page's columns. At the top of a new page, the
        # description lines follow the previous page's last row (`carry`).
        in_table = not any(_is_table_header(line) for line in page)
        last_top: float | None = None
        carry = bool(rows)
        for line in sorted(page, key=lambda item: item.words[0].top):
            if _is_table_header(line):
                columns, in_table, last_top = _columns(line), True, None
                continue
            if columns is None or not in_table:
                continue
            top = line.words[0].top
            row = _row(line, columns)
            if row is not None:
                rows.append(row)
                last_top, carry = top, False
            elif _has_money(line, columns):
                raise ParseError("a line with an amount outside a row")
            elif _is_footer(line):
                last_top = None  # the footer ends the row, but not the one going on next page
            elif _in_detail(line, columns) and (carry or _near(line, last_top)):
                rows[-1] = _with_piece(rows[-1], line.text)
                last_top = top
            else:
                last_top, carry = None, False  # other text: the row is over
    return rows


def _row(line: Line, columns: _Columns) -> _Row | None:
    words = line.words
    if not _DATE.match(words[0].text) or words[0].x0 >= columns.detail_left - _ALIGN_TOLERANCE:
        return None
    money = [w for w in words[1:] if _money_column(w, columns) is not None]
    if len(money) != 2 or money[1] is not words[-1]:
        raise ParseError(f"row of {words[0].text} without an amount and its balance")
    amount, balance = money
    if _money_column(balance, columns) != "balance":
        raise ParseError(f"row of {words[0].text} without a balance")
    signed = parse_amount(amount.text)
    column = _money_column(amount, columns)
    if column == "debit" and signed >= 0:
        raise ParseError(f"row of {words[0].text}: unsigned debit")
    if column == "credit" and signed <= 0:
        raise ParseError(f"row of {words[0].text}: signed credit")
    if column == "balance":
        raise ParseError(f"row of {words[0].text} without a debit or a credit")
    detail = " ".join(w.text for w in words[1:] if w is not amount and w is not balance)
    return _Row(
        day=parse_date(words[0].text),
        signed=signed,
        balance=parse_amount(balance.text),
        pieces=(detail,) if detail else (),
        raw=line.text,
    )


def _money_column(word: Word, columns: _Columns) -> str | None:
    if not is_amount(word.text):
        return None
    for name, right in (
        ("debit", columns.debit_right),
        ("credit", columns.credit_right),
        ("balance", columns.balance_right),
    ):
        if abs(word.x1 - right) <= _COLUMN_TOLERANCE:
            return name
    return None


def _has_money(line: Line, columns: _Columns) -> bool:
    return any(_money_column(w, columns) is not None for w in line.words)


def _in_detail(line: Line, columns: _Columns) -> bool:
    """It starts in the description column: not before, nor in the debit column or further right."""
    left = line.words[0].x0
    return columns.detail_left - _ALIGN_TOLERANCE <= left < columns.debit_left - _ALIGN_TOLERANCE


def _near(line: Line, last_top: float | None) -> bool:
    """Next to the row (or to its previous line)."""
    return last_top is not None and line.words[0].top - last_top <= _WRAP_DISTANCE


def _is_footer(line: Line) -> bool:
    return _FOOTER.match(normalize(line.text)) is not None


def _with_piece(row: _Row, text: str) -> _Row:
    return _Row(row.day, row.signed, row.balance, (*row.pieces, text), row.raw)


def _transaction(row: _Row, currency: str) -> Transaction:
    return Transaction(
        transacted_on=row.day,
        posted_on=row.day,
        description=" ".join(" ".join(row.pieces).split()),
        amount=abs(row.signed),
        direction=DEBIT if row.signed < 0 else CREDIT,
        currency=currency,
        reference=None,
        mcc=None,
        raw_line=row.raw,
        balance=row.balance,
    )
