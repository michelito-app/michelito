"""Parser of Popular's (Popular Dominicano bank) checking or savings-account statement.

The first page has the product with the account number, the currency and a summary with the
previous balance, deposits, debits, interest paid and charged and the closing balance. Each
movement starts with two "DDMMM" dates (posting and transaction; the month sometimes comes out
in English), goes on with the detail and ends with the amount (negative for a debit) and the
balance. The detail may continue on the lines below, aligned with it.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
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
    is_amount,
    normalize,
    parse_amount,
    resolve_day_month,
)

NAME = "popular_account"
INSTITUTION = "popular"

_DAY_MONTH = re.compile(r"^(?P<day>\d{2})(?P<month>[A-Z]{3})$")
_AMOUNT = r"(-?[\d,]+\.\d{2})"
_REQUIRED = ("opening", "credits", "debits", "closing")
# A detail line goes right below (the next line) and aligned with the detail; the page footer
# is further away or further left.
_CONTINUATION_GAP = 12.0
_ALIGN_TOLERANCE = 2.0
# The statement's Spanish text (lowercase lines are normalized: no accents).
# spanish-data: begin
# Month abbreviations of the "DDMMM" dates, in Spanish or English.
_MONTHS = {
    **dict.fromkeys(("ENE", "JAN"), 1),
    "FEB": 2,
    "MAR": 3,
    **dict.fromkeys(("ABR", "APR"), 4),
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    **dict.fromkeys(("AGO", "AUG"), 8),
    **dict.fromkeys(("SEP", "SET"), 9),
    "OCT": 10,
    "NOV": 11,
    **dict.fromkeys(("DIC", "DEC"), 12),
}
# Month names of the statement date ("dd de <month> de yyyy").
_MONTH_NAMES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)
_LONG_DATE = re.compile(r"^(?P<day>\d{1,2}) de (?P<month>[a-z]+) de (?P<year>\d{4})$")
_ACCOUNT = re.compile(r"^cta (?P<type>[a-z]+)\b.*?\s(?P<number>\d{6,})$")
# Account type abbreviation -> (kind, product stored for the account).
_KINDS = {
    "cte": ("checking", "Cuenta corriente"),
    "aho": ("savings", "Cuenta de ahorro"),
}
_SUMMARY = {
    "opening": re.compile(rf"^balance anterior {_AMOUNT}$"),
    "credits": re.compile(rf"^\+ depositos y otros creditos \d+ {_AMOUNT}$"),
    "debits": re.compile(rf"^- cheques y otros? debitos \d+ {_AMOUNT}$"),
    "interest_paid": re.compile(rf"^\+ interes pagado {_AMOUNT}$"),
    "interest_charged": re.compile(rf"^- interes cargado {_AMOUNT}$"),
    "closing": re.compile(rf"^balance al corte {_AMOUNT}$"),
}
_CURRENCY_LINE = re.compile(r"^cantidad monto (?P<currency>\S+)$")
_PLACEHOLDER = re.compile(r"\b(?:RD|US)\$ \.00\b")  # the empty check column
_REGIONAL_ACCOUNT_LABEL = "numero de cuenta regional"
_DEPOSITS_LABEL = "+ depositos y otros creditos"
_PREVIOUS_BALANCE_ROW = ("BALANCE", "ANTERIOR")
# spanish-data: end


@dataclass(frozen=True)
class _Summary:
    opening: Decimal
    credits: Decimal
    debits: Decimal
    closing: Decimal


def matches(pages: tuple[Page, ...]) -> bool:
    if not pages:
        return False
    texts = [normalize(line.text) for line in pages[0]]
    return (
        any(text.startswith(_REGIONAL_ACCOUNT_LABEL) for text in texts)
        and any(text.startswith(_DEPOSITS_LABEL) for text in texts)
        and any(_ACCOUNT.match(text) for text in texts)
        and any(_ACCOUNT.match(t) for t in texts)
    )


def parse(pages: tuple[Page, ...]) -> Statement:
    if not pages:
        raise ParseError("empty document")
    texts = [normalize(line.text) for line in pages[0]]
    kind, product, identifier = _account(texts)
    currency = _currency(texts)
    period_end = _period_end(texts)
    summary = _summary(texts)
    section = Section(
        currency=currency,
        previous_balance=summary.opening,
        closing_balance=summary.closing,
        minimum_payment=None,
        credit_limit=None,
        printed_debits=summary.debits,
        printed_credits=summary.credits,
        transactions=tuple(_movements(pages, currency, period_end)),
    )
    return Statement(
        parser=NAME,
        institution=INSTITUTION,
        kind=kind,
        product=product,
        identifier=identifier,
        period_end=period_end,
        due_date=None,
        sections=(section,),
        period_start=_period_start(pages, period_end),
    )


def _account(texts: list[str]) -> tuple[str, str, str]:
    for text in texts:
        found = _ACCOUNT.match(text)
        if found is None:
            continue
        if found["type"] not in _KINDS:
            raise ParseError(f"unknown account type: {found['type']!r}")
        kind, product = _KINDS[found["type"]]
        return kind, product, found["number"]
    raise ParseError("the product with the account number was not found")


def _currency(texts: list[str]) -> str:
    for text in texts:
        found = _CURRENCY_LINE.match(text)
        if found:
            code = found["currency"].upper()
            if code not in CURRENCIES:
                raise ParseError(f"unknown currency: {code!r}")
            return CURRENCIES[code]
    raise ParseError("the summary's currency was not found")


def _period_end(texts: list[str]) -> date:
    """The statement date, written as 'dd de <month> de yyyy' in the header."""
    for text in texts:
        found = _LONG_DATE.match(text)
        if found and found["month"] in _MONTH_NAMES:
            month = _MONTH_NAMES.index(found["month"]) + 1
            return date(int(found["year"]), month, int(found["day"]))
    raise ParseError("the statement date was not found")


def _period_start(pages: tuple[Page, ...], period_end: date) -> date | None:
    """The day after the date of the previous-balance row (the previous closing), if any."""
    for page in pages:
        for line in page:
            tokens = line.tokens
            if (
                len(tokens) == 4
                and _DAY_MONTH.match(tokens[0])
                and tokens[1:3] == _PREVIOUS_BALANCE_ROW
                and is_amount(tokens[3])
            ):
                return resolve_day_month(_day_month(tokens[0]), period_end) + timedelta(days=1)
    return None


def _summary(texts: list[str]) -> _Summary:
    """Printed totals. Interest paid or charged goes apart from deposits and debits in the
    summary, but it shows up as one more movement; it is added to its side."""
    values: dict[str, Decimal] = {}
    for text in texts:
        for name, pattern in _SUMMARY.items():
            found = pattern.match(text)
            if found and name not in values:
                values[name] = parse_amount(found.group(1))
    missing = [name for name in _REQUIRED if name not in values]
    if missing:
        raise ParseError(f"incomplete summary; missing: {', '.join(missing)}")
    return _Summary(
        opening=values["opening"],
        credits=values["credits"] + values.get("interest_paid", Decimal(0)),
        debits=values["debits"] + values.get("interest_charged", Decimal(0)),
        closing=values["closing"],
    )


def _movements(pages: tuple[Page, ...], currency: str, period_end: date) -> Iterator[Transaction]:
    for page in pages:
        current: Transaction | None = None
        anchor: Line | None = None  # the previous line, which may have detail below it
        detail_left = 0.0
        for line in page:
            if _is_movement(line):
                if current is not None:
                    yield current
                current = _movement(line, currency, period_end)
                anchor, detail_left = line, line.words[2].x0
            elif (
                current is not None and anchor is not None and _continues(line, anchor, detail_left)
            ):
                current = replace(current, description=_clean(f"{current.description} {line.text}"))
                anchor = line
            else:
                anchor = None
        if current is not None:
            yield current


def _is_movement(line: Line) -> bool:
    tokens = line.tokens
    return (
        len(tokens) >= 5
        and _DAY_MONTH.match(tokens[0]) is not None
        and _DAY_MONTH.match(tokens[1]) is not None
        and is_amount(tokens[-1])
        and is_amount(tokens[-2])
    )


def _continues(line: Line, anchor: Line, detail_left: float) -> bool:
    first = line.words[0]
    return (
        first.top - anchor.words[0].top <= _CONTINUATION_GAP
        and first.x0 >= detail_left - _ALIGN_TOLERANCE
        and _DAY_MONTH.match(first.text) is None
    )


def _movement(line: Line, currency: str, period_end: date) -> Transaction:
    tokens = line.tokens
    signed = parse_amount(tokens[-2])
    return Transaction(
        transacted_on=resolve_day_month(_day_month(tokens[1]), period_end),
        posted_on=resolve_day_month(_day_month(tokens[0]), period_end),
        description=_clean(" ".join(tokens[2:-2])),
        amount=abs(signed),
        direction=DEBIT if signed < 0 else CREDIT,
        currency=currency,
        reference=None,
        mcc=None,
        raw_line=line.text,
    )


def _day_month(token: str) -> str:
    found = _DAY_MONTH.match(token)
    if found is None or found["month"] not in _MONTHS:
        raise ParseError(f"invalid date: {token!r}")
    return f"{found['day']}/{_MONTHS[found['month']]:02d}"


def _clean(text: str) -> str:
    """Remove the empty check column ('RD$ .00') that slips into the detail."""
    return " ".join(_PLACEHOLDER.sub(" ", text).split())
