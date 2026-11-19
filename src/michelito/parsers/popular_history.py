"""Parser of Popular's "historical" statements (checking or savings account).

It is the format the bank's account officer sends: a single PDF with several monthly
statements of the same account in a row, with blank pages (or with only a number) between them.
`split` cuts it into statements and `parse` parses one; `ingest` validates and stores each part
separately.

Each statement starts on the page whose holder line ends in "PAG 1" (the following pages of the
same statement say "PAG 2", "PAG 3"… and repeat the header). The header has the closing date
("12 NOV 2025"), the account line (product, number, currency and name: "CTA CTE NOMINA <n> RD$
<name>", "AHORRO US$ PERS <n> USD <name>", "CUENTA DIGITAL <n> RD$ <name>") and a summary with
counts and amounts. Each movement starts with two "DD MMM" dates (posting and transaction,
without a year), may have the description on the same line and ends with the amount (a trailing
"-" for a debit) and the balance; the detail goes on in the lines below, to the right of the
dates. An amount under one has no leading zero (".00").

Interest paid comes out as one more credit row and is not included in the summary's deposit
count. The counts are read but do not invalidate (see `common.count_notes`): in the months with
interest on the dollar savings account the bank counts one debit row less even though the
amounts and the balance chain balance.
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
    normalize,
    parse_amount,
    resolve_day_month,
)

NAME = "popular_history"
INSTITUTION = "popular"  # the same as popular_account and popular_web (see db.account_key)

_DAY = re.compile(r"^\d{2}$")
_YEAR = re.compile(r"^\d{4}$")
_NUMBER = re.compile(r"^\d{6,}$")
_MONEY = re.compile(r"^(?:\d{1,3}(?:,\d{3})*)?\.\d{2}-?$")
_A = r"((?:\d{1,3}(?:,\d{3})*)?\.\d{2}-?)"
_REQUIRED = ("opening", "credits", "debits", "closing")
_PLACEHOLDER = re.compile(r"\b(?:RD|US)\$ \.00\b")  # the empty check column
# Broken separators between words: U+FFFD in UTF-8 read as latin-1, U+FFFD and the no-break
# space. The first one goes first: it contains characters that are not U+FFFD.
_BROKEN_SPACES = ("\u00ef\u00bf\u00bd", "\ufffd", "\u00a0")
# A detail line goes right below the previous one and to the right of the dates.
_CONTINUATION_GAP = 14.0
# The first detail line starts up to this distance to the right of the dates (in the
# statements, about 30 points); the following ones, within this tolerance of the first.
_DETAIL_BAND = 60.0
_ALIGN_TOLERANCE = 3.0
# The statement's Spanish text (lowercase lines are normalized: no accents).
# spanish-data: begin
# Month abbreviations of the dates.
_MONTHS = {
    "ENE": 1,
    "FEB": 2,
    "MAR": 3,
    "ABR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AGO": 8,
    "SEP": 9,
    "SET": 9,
    "OCT": 10,
    "NOV": 11,
    "DIC": 12,
}
_PAGE = re.compile(r"(?:^|\s)PAG ?(?P<number>\d+)(?: DE \d+)?$")
_SUMMARY = {
    "opening": re.compile(rf"^balance anterior {_A}$"),
    "credits": re.compile(rf"^\+ depositos y otros creditos (?:(\d+) )?{_A}$"),
    "debits": re.compile(rf"^- cheques y otros? debitos (?:(\d+) )?{_A}$"),
    "interest_paid": re.compile(rf"^\+ interes pagado {_A}$"),
    "interest_charged": re.compile(rf"^- interes cargado {_A}$"),
    "closing": re.compile(rf"^balance al corte {_A}$"),
}
# Account kind by the first words of the product; what is left is the product name.
_PRODUCTS = (
    (("CTA", "CTE"), "checking", 2),
    (("CUENTA", "DIGITAL"), "checking", 1),
    (("CTA", "AHO"), "savings", 2),
    (("AHORRO",), "savings", 0),
)
_ACCENTS = {"NOMINA": "Nómina"}  # product words written with their accent
_PREVIOUS_BALANCE_ROW = ("BALANCE", "ANTERIOR")
# spanish-data: end


@dataclass(frozen=True)
class _Summary:
    opening: Decimal
    credits: Decimal
    debits: Decimal
    closing: Decimal
    credit_count: int | None
    debit_count: int | None


def matches(pages: tuple[Page, ...]) -> bool:
    """It never raises: an unknown product is recognized too, and `parse` says why it cannot be
    read."""
    return any(_page_number(page) == 1 and _account_line(page) is not None for page in pages)


def split(pages: tuple[Page, ...]) -> tuple[tuple[Page, ...], ...]:
    """Cut the PDF into statements: each "PAG 1" starts one and the blank pages (no text or only
    a number) are dropped. The pages with text before the first "PAG 1" go together in a part of
    their own: they cannot be read as a statement, but this way they are recorded as a failed
    part instead of being lost silently."""
    parts: list[list[Page]] = []
    for page in pages:
        if _is_blank(page):
            continue
        if _page_number(page) == 1 or not parts:
            parts.append([page])
        else:
            parts[-1].append(page)
    return tuple(tuple(part) for part in parts)


def label(pages: tuple[Page, ...]) -> str | None:
    """The closing date (YYYY-MM-DD) of a part that `parse` could not read, if it is found."""
    for page in pages[:1]:
        try:
            return _period_end(page).isoformat()
        except ParseError:
            return None
    return None


def parse(pages: tuple[Page, ...]) -> Statement:
    """Parse one statement (a part from `split`)."""
    if not pages:
        raise ParseError("empty statement")
    first = pages[0]
    found = _account_line(first)
    if found is None:
        raise ParseError("the account line was not found")
    words, identifier, currency = found
    kind, product = _product(words)
    period_end = _period_end(first)
    summary = _summary([normalize(line.text) for page in pages for line in page])
    section = Section(
        currency=currency,
        previous_balance=summary.opening,
        closing_balance=summary.closing,
        minimum_payment=None,
        credit_limit=None,
        printed_debits=summary.debits,
        printed_credits=summary.credits,
        transactions=tuple(_movements(pages, currency, period_end)),
        printed_debit_count=summary.debit_count,
        printed_credit_count=summary.credit_count,
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


def _is_blank(page: Page) -> bool:
    return all(token.isdigit() for line in page for token in line.tokens)


def _page_number(page: Page) -> int | None:
    """The page number at the end of a line (the holder's): "PAG n", "PAGn" or
    "PAG n DE m"."""
    for line in page:
        found = _PAGE.search(line.text)
        if found:
            return int(found["number"])
    return None


def _account_line(page: Page) -> tuple[tuple[str, ...], str, str] | None:
    """The product words, number and currency of the "<product> <number> <currency> <name>"
    line; the kind is decided by `_product` (which does raise with an unknown product)."""
    for line in page:
        tokens = line.tokens
        for index in range(1, len(tokens) - 1):
            if _NUMBER.match(tokens[index]) and tokens[index + 1] in CURRENCIES:
                return tokens[:index], tokens[index], CURRENCIES[tokens[index + 1]]
    return None


def _product(words: tuple[str, ...]) -> tuple[str, str]:
    for prefix, kind, drop in _PRODUCTS:
        if words[: len(prefix)] == prefix:
            name = words[drop:] or words
            return kind, " ".join(_title(word) for word in name)
    raise ParseError(f"unknown account type: {' '.join(words)!r}")


def _title(word: str) -> str:
    if "$" in word:
        return word
    return _ACCENTS.get(word, word.capitalize())


def _period_end(page: Page) -> date:
    """The header's closing date: "DD MMM YYYY" at the end of a line."""
    for line in page:
        tokens = line.tokens
        if (
            len(tokens) >= 3
            and _DAY.match(tokens[-3])
            and tokens[-2] in _MONTHS
            and _YEAR.match(tokens[-1])
        ):
            return date(int(tokens[-1]), _MONTHS[tokens[-2]], int(tokens[-3]))
    raise ParseError("the closing date was not found")


def _summary(texts: list[str]) -> _Summary:
    """Printed totals; interest paid or charged goes apart in the summary but comes out as one
    more row, so it is added to its side (and to the count, if it is not zero)."""
    values: dict[str, Decimal] = {}
    counts: dict[str, int | None] = {}
    for text in texts:
        for name, pattern in _SUMMARY.items():
            found = pattern.match(text)
            if found is None or name in values:
                continue
            values[name] = _amount(found.groups()[-1])
            if name in ("credits", "debits"):
                counts[name] = None if found.group(1) is None else int(found.group(1))
    missing = [name for name in _REQUIRED if name not in values]
    if missing:
        raise ParseError(f"incomplete summary; missing: {', '.join(missing)}")
    paid = values.get("interest_paid", Decimal(0))
    charged = values.get("interest_charged", Decimal(0))
    return _Summary(
        opening=values["opening"],
        credits=values["credits"] + paid,
        debits=values["debits"] + charged,
        closing=values["closing"],
        credit_count=_with_interest(counts["credits"], paid),
        debit_count=_with_interest(counts["debits"], charged),
    )


def _with_interest(count: int | None, interest: Decimal) -> int | None:
    return None if count is None else count + (1 if interest else 0)


def _amount(text: str) -> Decimal:
    return parse_amount(f"0{text}" if text.startswith(".") else text)


def _period_start(pages: tuple[Page, ...], period_end: date) -> date | None:
    """The day after the previous-balance row (the previous closing), if any."""
    for page in pages:
        for line in page:
            tokens = line.tokens
            if (
                len(tokens) == 5
                and _is_date(tokens, 0)
                and tokens[2:4] == _PREVIOUS_BALANCE_ROW
                and _MONEY.match(tokens[4])
            ):
                return _date(tokens, 0, period_end) + timedelta(days=1)
    return None


def _movements(pages: tuple[Page, ...], currency: str, period_end: date) -> Iterator[Transaction]:
    for page in pages:
        current: Transaction | None = None
        anchor: Line | None = None  # the previous line, which may have detail below it
        dates_right = 0.0
        detail_left: float | None = None  # x of the row's first detail line
        for line in page:
            if _is_movement(line):
                if current is not None:
                    yield current
                current = _movement(line, currency, period_end)
                anchor, dates_right, detail_left = line, line.words[3].x1, None
            elif (
                current is not None
                and anchor is not None
                and _continues(line, anchor, dates_right, detail_left)
            ):
                current = replace(current, description=_clean(f"{current.description} {line.text}"))
                anchor = line
                detail_left = line.words[0].x0 if detail_left is None else detail_left
            else:
                anchor = None
        if current is not None:
            yield current


def _is_movement(line: Line) -> bool:
    tokens = line.tokens
    return (
        len(tokens) >= 6
        and _is_date(tokens, 0)
        and _is_date(tokens, 2)
        and _MONEY.match(tokens[-1]) is not None
        and _MONEY.match(tokens[-2]) is not None
    )


def _is_date(tokens: tuple[str, ...], index: int) -> bool:
    return (
        len(tokens) > index + 1
        and _DAY.match(tokens[index]) is not None
        and tokens[index + 1] in _MONTHS
    )


def _continues(line: Line, anchor: Line, dates_right: float, detail_left: float | None) -> bool:
    """A detail line goes right below the previous one, without dates at the start. The first
    one starts a little after the dates (the description column); the following ones, aligned
    with it. That way a page footer further right does not stick to the description."""
    first = line.words[0]
    if detail_left is None:
        aligned = dates_right < first.x0 <= dates_right + _DETAIL_BAND
    else:
        aligned = abs(first.x0 - detail_left) <= _ALIGN_TOLERANCE
    return (
        aligned
        and first.top - anchor.words[0].top <= _CONTINUATION_GAP
        and not _is_date(line.tokens, 0)
    )


def _movement(line: Line, currency: str, period_end: date) -> Transaction:
    tokens = line.tokens
    amount = tokens[-2]
    return Transaction(
        transacted_on=_date(tokens, 2, period_end),
        posted_on=_date(tokens, 0, period_end),
        description=_clean(" ".join(tokens[4:-2])),
        amount=abs(_amount(amount)),
        # By the suffix and not the sign: ".00-" is a debit even though -0.00 is not negative.
        direction=DEBIT if amount.endswith("-") else CREDIT,
        currency=currency,
        reference=None,
        mcc=None,
        raw_line=line.text,
        balance=_amount(tokens[-1]),
    )


def _date(tokens: tuple[str, ...], index: int, period_end: date) -> date:
    """A "DD MMM" date without a year: the latest one not after the closing date (December in a
    January statement is from the year before)."""
    return resolve_day_month(f"{tokens[index]}/{_MONTHS[tokens[index + 1]]:02d}", period_end)


def _clean(text: str) -> str:
    """Remove the empty check column ('RD$ .00') that slips into the detail and leave a single
    space where the PDF has a broken separator: the replacement character (U+FFFD), its UTF-8
    bytes read as latin-1 (seen between the words of a name) or a no-break space. Without that
    a name split by them is not recognized as the holder."""
    for broken in _BROKEN_SPACES:
        text = text.replace(broken, " ")
    return " ".join(_PLACEHOLDER.sub(" ", text).split())
