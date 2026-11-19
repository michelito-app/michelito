"""Types and helpers shared by the bank-statement parsers.

`validate_statement` and `count_notes` return Spanish text from the catalog (`core.validation.*`):
it is stored as the document's detail and shown to the user (the demo's sample statement shows
it when a statement does not balance). `ParseError` messages are for the operator (English): they
are stored in `documents.detail` and only `michelito import` / `michelito report` print them.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from michelito.i18n import t

DEBIT = "debit"
CREDIT = "credit"
CURRENCIES = {"RD$": "DOP", "DOP": "DOP", "US$": "USD", "USD": "USD"}
LINE_TOLERANCE = 2.5
# Minimum difference (in points) between the two columns closest to an amount.
COLUMN_MARGIN = 3.0
POSTING_TOLERANCE = timedelta(days=7)

_AMOUNT = re.compile(r"^(?P<lead>-)?(?P<int>\d{1,3}(?:,\d{3})+|\d+)\.(?P<dec>\d{2})(?P<trail>-)?$")
_DATE_FORMATS = ("%d/%m/%Y", "%Y-%m-%d")


class ParseError(ValueError):
    """The document does not have the shape the parser expects."""


@dataclass(frozen=True)
class Word:
    text: str
    x0: float
    x1: float
    top: float


@dataclass(frozen=True)
class Line:
    words: tuple[Word, ...]

    @property
    def tokens(self) -> tuple[str, ...]:
        return tuple(word.text for word in self.words)

    @property
    def text(self) -> str:
        return " ".join(self.tokens)


Page = tuple[Line, ...]


@dataclass(frozen=True)
class Transaction:
    transacted_on: date
    posted_on: date | None
    description: str
    amount: Decimal  # always positive; the sign goes in `direction`
    direction: str
    currency: str
    reference: str | None
    mcc: str | None
    raw_line: str
    balance: Decimal | None = None  # printed balance after the movement, if the bank gives it


@dataclass(frozen=True)
class Section:
    """The part of a statement in a single currency."""

    currency: str
    previous_balance: Decimal | None
    closing_balance: Decimal | None
    minimum_payment: Decimal | None
    credit_limit: Decimal | None
    printed_debits: Decimal | None
    printed_credits: Decimal | None
    transactions: tuple[Transaction, ...]
    # Number of movements the summary prints, if it prints it and the parser reads it.
    printed_debit_count: int | None = None
    printed_credit_count: int | None = None


@dataclass(frozen=True)
class Statement:
    parser: str
    institution: str
    kind: str
    product: str
    identifier: str
    period_end: date
    due_date: date | None
    sections: tuple[Section, ...]
    period_start: date | None = None  # first day covered, if the document says it

    @property
    def is_liability(self) -> bool:
        return self.kind == "credit_card"


def is_amount(text: str) -> bool:
    return _AMOUNT.match(text) is not None


def parse_amount(text: str) -> Decimal:
    match = _AMOUNT.match(text)
    if match is None:
        raise ParseError(f"invalid amount: {text!r}")
    value = Decimal(f"{match['int'].replace(',', '')}.{match['dec']}")
    return -value if match["lead"] or match["trail"] else value


def parse_date(text: str) -> date:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ParseError(f"invalid date: {text!r}")


def resolve_day_month(text: str, reference: date) -> date:
    """Turn 'dd/mm' into the latest date that is not after the closing date.

    A movement cannot be after the closing date; `POSTING_TOLERANCE` is allowed for late posting
    dates.
    """
    try:
        day, month = (int(part) for part in text.split("/"))
    except ValueError as exc:
        raise ParseError(f"invalid date: {text!r}") from exc
    latest = reference + POSTING_TOLERANCE
    candidates = []
    for year in (reference.year - 1, reference.year, reference.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if candidate <= latest:
            candidates.append(candidate)
    if not candidates:
        raise ParseError(f"invalid date: {text!r}")
    return max(candidates)


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return decomposed.encode("ascii", "ignore").decode("ascii").lower()


def group_lines(words: Iterable[Word], tolerance: float = LINE_TOLERANCE) -> Page:
    """Group words into lines by their height and sort them left to right."""
    rows: list[list[Word]] = []
    for word in sorted(words, key=lambda w: (w.top, w.x0)):
        if rows and abs(word.top - rows[-1][0].top) <= tolerance:
            rows[-1].append(word)
        else:
            rows.append([word])
    return tuple(Line(tuple(sorted(row, key=lambda w: w.x0))) for row in rows)


def column_positions(line: Line, names: tuple[str, ...]) -> dict[str, float] | None:
    """The right edge of each column header, if the line has all of them."""
    found: dict[str, float] = {}
    for word in line.words:
        key = normalize(word.text)
        if key in names and key not in found:
            found[key] = word.x1
    return found if len(found) == len(names) else None


def nearest_column(word: Word, columns: Mapping[str, float]) -> str:
    """The column whose right edge is closest to the word's (amounts are right-aligned).

    If the word is almost equally far from two columns, it does not guess.
    """
    ranked = sorted(columns, key=lambda name: abs(columns[name] - word.x1))
    if len(ranked) > 1:
        best, runner_up = (abs(columns[name] - word.x1) for name in ranked[:2])
        if runner_up - best < COLUMN_MARGIN:
            raise ParseError(f"cannot decide the column of an amount at x={word.x1:.0f}")
    return ranked[0]


def validate_statement(statement: Statement) -> tuple[str, ...]:
    if not statement.sections:
        return (t("core.validation.no_sections"),)
    return tuple(
        problem
        for section in statement.sections
        for problem in validate_section(section, liability=statement.is_liability)
    )


def count_notes(statement: Statement) -> tuple[str, ...]:
    """Differences between the rows read and the count the summary prints. They do not
    invalidate the statement: the amounts and the balance chain already validate it, and the
    bank sometimes counts one row less (seen in the months with interest paid on Popular's
    savings account)."""
    notes = []
    for section in statement.sections:
        for label, direction, count in (
            (t("core.validation.debits"), DEBIT, section.printed_debit_count),
            (t("core.validation.credits"), CREDIT, section.printed_credit_count),
        ):
            rows = sum(1 for item in section.transactions if item.direction == direction)
            if count is not None and rows != count:
                notes.append(
                    t(
                        "core.validation.count_note",
                        currency=section.currency,
                        label=label,
                        rows=rows,
                        count=count,
                    )
                )
    return tuple(notes)


def validate_section(section: Section, *, liability: bool) -> tuple[str, ...]:
    """Compare what was read against the totals the bank prints."""
    debits = _total(section, DEBIT)
    credits = _total(section, CREDIT)
    problems: list[str] = []
    checks = 0
    for label, read, printed in (
        (t("core.validation.debits"), debits, section.printed_debits),
        (t("core.validation.credits"), credits, section.printed_credits),
    ):
        if printed is None:
            continue
        checks += 1
        if read != printed:
            problems.append(
                t(
                    "core.validation.total_mismatch",
                    currency=section.currency,
                    label=label,
                    read=read,
                    printed=printed,
                )
            )
    if section.previous_balance is not None and section.closing_balance is not None:
        checks += 1
        change = debits - credits if liability else credits - debits
        expected = section.previous_balance + change
        if expected != section.closing_balance:
            problems.append(
                t(
                    "core.validation.balance_mismatch",
                    currency=section.currency,
                    previous=section.previous_balance,
                    expected=expected,
                    closing=section.closing_balance,
                )
            )
    chain = _chain_problems(section, liability=liability)
    if chain is not None:
        checks += 1
        problems.extend(chain)
    if checks == 0:
        problems.append(t("core.validation.no_totals", currency=section.currency))
    return tuple(problems)


def _chain_problems(section: Section, *, liability: bool) -> list[str] | None:
    """Check the printed balance row by row; None if the document prints no balances."""
    balances = [item.balance for item in section.transactions]
    if section.previous_balance is None or not balances or None in balances:
        return None
    problems = []
    running = section.previous_balance
    for index, item in enumerate(section.transactions, start=1):
        grows = (item.direction == DEBIT) == liability
        running += item.amount if grows else -item.amount
        if item.balance is not None and running != item.balance:
            problems.append(
                t(
                    "core.validation.chain_mismatch",
                    currency=section.currency,
                    index=index,
                    day=item.transacted_on,
                    balance=item.balance,
                    running=running,
                )
            )
            running = item.balance
    return problems


def _total(section: Section, direction: str) -> Decimal:
    return sum(
        (item.amount for item in section.transactions if item.direction == direction), Decimal(0)
    )
