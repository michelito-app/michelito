"""Parser of BHD bank's credit-card statement.

The first page has the header and a summary with two columns (DOP and USD). The next ones
list the transactions per currency; debits and credits are told apart only by the column the
amount falls in.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
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
    column_positions,
    is_amount,
    nearest_column,
    normalize,
    parse_amount,
    parse_date,
    resolve_day_month,
)

NAME = "bhd_card"
INSTITUTION = "bhd"

_CURRENCIES = ("DOP", "USD")
_LAST4 = re.compile(r"\*+(\d{4})\b")
_LIMITS = re.compile(r"RD\$\s*(?P<dop>[\d,]+\.\d{2}).*US\$\s*(?P<usd>[\d,]+\.\d{2})")
_FULL_DATE = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")
_DAY_MONTH = re.compile(r"^\d{2}/\d{2}$")
_CARD_DIGITS = re.compile(r"^\d{4}$")
_REFERENCE = re.compile(r"^\d{15,}$")
# The statement's Spanish text (normalized: lowercase, no accents, see `common.normalize`).
# spanish-data: begin
_DEBITS = "debitos"  # column headers of the transaction tables
_CREDITS = "creditos"
_CARD_TITLE = "tarjeta de credito"  # first page: the statement's title...
_CARD_NUMBER_LABEL = "numero de tarjeta"  # ...and the card-number label
_CLOSING_DATE_LABEL = "fecha de corte"  # the dates go below this label
_PRODUCT = re.compile(r"Tipo de tarjeta\s+(?P<product>.+)$")
_DEFAULT_PRODUCT = "TARJETA DE CRÉDITO"  # stored as the product when none is printed
# Summary labels -> what they are.
_SUMMARY = {
    "balance anterior": "previous",
    "pagos y creditos": "credits",
    "compras y debitos": "debits",
    "balance al corte": "closing",
    "pago minimo total": "minimum",
}
# Section titles -> their currency.
_SECTIONS = {"transacciones en pesos": "DOP", "transacciones en dolares": "USD"}
# spanish-data: end
_COLUMNS = (_DEBITS, _CREDITS)

Summary = Mapping[str, tuple[Decimal, Decimal]]


@dataclass(frozen=True)
class _Header:
    last4: str
    product: str
    period_end: date
    due_date: date
    limits: Mapping[str, Decimal]


def matches(pages: tuple[Page, ...]) -> bool:
    if not pages:
        return False
    text = normalize(" ".join(line.text for line in pages[0]))
    return _CARD_TITLE in text and _CARD_NUMBER_LABEL in text


def parse(pages: tuple[Page, ...]) -> Statement:
    if not pages:
        raise ParseError("empty document")
    header = _read_header(pages[0])
    summary = _read_summary(pages[0])
    movements, totals = _read_movements(pages, header.period_end)
    sections = tuple(
        _section(index, currency, header, summary, movements[currency], totals.get(currency))
        for index, currency in enumerate(_CURRENCIES)
    )
    return Statement(
        parser=NAME,
        institution=INSTITUTION,
        kind="credit_card",
        product=header.product,
        identifier=header.last4,
        period_end=header.period_end,
        due_date=header.due_date,
        sections=sections,
    )


def _section(
    index: int,
    currency: str,
    header: _Header,
    summary: Summary,
    transactions: list[Transaction],
    printed: tuple[Decimal, Decimal] | None,
) -> Section:
    def pick(key: str) -> Decimal:
        if key not in summary:
            raise ParseError(f"'{key}' is missing from the statement summary")
        return summary[key][index]

    return Section(
        currency=currency,
        previous_balance=pick("previous"),
        closing_balance=pick("closing"),
        minimum_payment=summary["minimum"][index] if "minimum" in summary else None,
        credit_limit=header.limits.get(currency),
        printed_debits=printed[0] if printed else pick("debits"),
        printed_credits=printed[1] if printed else pick("credits"),
        transactions=tuple(transactions),
    )


def _read_header(page: Page) -> _Header:
    last4 = product = None
    limits: dict[str, Decimal] = {}
    dates: tuple[date, date] | None = None
    after_date_label = False
    for line in page:
        text = line.text
        if _CLOSING_DATE_LABEL in normalize(text):
            after_date_label = True
            continue
        if last4 is None and _CARD_NUMBER_LABEL in normalize(text):
            found = _LAST4.search(text)
            last4 = found.group(1) if found else None
        if product is None and (found_product := _PRODUCT.search(text)):
            product = found_product["product"].strip()
        if not limits and (found_limits := _LIMITS.search(text)):
            limits = {
                "DOP": parse_amount(found_limits["dop"]),
                "USD": parse_amount(found_limits["usd"]),
            }
        # The dates go below the closing-date and due-date labels, in that order.
        if after_date_label and dates is None and len(full := _FULL_DATE.findall(text)) >= 2:
            dates = (parse_date(full[0]), parse_date(full[1]))
    if last4 is None:
        raise ParseError("BHD card header without a card number")
    if dates is None:
        raise ParseError("the closing date and the due date were not found below their label")
    if dates[1] < dates[0]:
        raise ParseError("the payment due date is before the closing date")
    return _Header(last4, product or _DEFAULT_PRODUCT, dates[0], dates[1], limits)


def _read_summary(page: Page) -> dict[str, tuple[Decimal, Decimal]]:
    """The first occurrence of each summary label with its amounts in DOP and USD."""
    found: dict[str, tuple[Decimal, Decimal]] = {}
    for line in page:
        tokens = line.tokens
        if len(tokens) < 3 or not (is_amount(tokens[-1]) and is_amount(tokens[-2])):
            continue
        key = _SUMMARY.get(normalize(" ".join(tokens[:-2])))
        if key and key not in found:
            found[key] = (parse_amount(tokens[-2]), parse_amount(tokens[-1]))
    return found


def _read_movements(
    pages: tuple[Page, ...], period_end: date
) -> tuple[dict[str, list[Transaction]], dict[str, tuple[Decimal, Decimal]]]:
    movements: dict[str, list[Transaction]] = {currency: [] for currency in _CURRENCIES}
    totals: dict[str, tuple[Decimal, Decimal]] = {}
    columns: dict[str, float] | None = None
    currency: str | None = None
    for line in (line for page in pages for line in page):
        if found := column_positions(line, _COLUMNS):
            columns = found
        elif section := _section_currency(line.text):
            currency = section
        elif currency is None or columns is None:
            continue
        elif line.text.startswith("**") and "TOTAL" in line.text:
            # The total line states its currency and closes the section; what follows is the next
            # currency even if its title comes out unreadable.
            closed = _total_currency(line.text) or currency
            totals[closed] = _split_amounts(line, columns)
            currency = _next_currency(closed)
        elif currency is None:
            continue
        elif _is_movement(line.tokens):
            movements[currency].append(_movement(line, columns, currency, period_end))
    return movements, totals


def _total_currency(text: str) -> str | None:
    if "RD$" in text:
        return "DOP"
    if "US$" in text:
        return "USD"
    return None


def _next_currency(currency: str) -> str | None:
    position = _CURRENCIES.index(currency)
    return _CURRENCIES[position + 1] if position + 1 < len(_CURRENCIES) else None


def _section_currency(text: str) -> str | None:
    normalized = normalize(text)
    if "total" in normalized:
        return None
    for prefix, currency in _SECTIONS.items():
        if prefix in normalized:
            return currency
    return None


def _split_amounts(line: Line, columns: Mapping[str, float]) -> tuple[Decimal, Decimal]:
    values = {name: Decimal(0) for name in _COLUMNS}
    for word in line.words:
        if is_amount(word.text):
            values[nearest_column(word, columns)] += parse_amount(word.text)
    return values[_DEBITS], values[_CREDITS]


def _is_movement(tokens: tuple[str, ...]) -> bool:
    return (
        len(tokens) >= 4
        and _DAY_MONTH.match(tokens[0]) is not None
        and _DAY_MONTH.match(tokens[1]) is not None
        and is_amount(tokens[-1])
    )


def _movement(
    line: Line, columns: Mapping[str, float], currency: str, period_end: date
) -> Transaction:
    tokens = line.tokens
    # After the dates comes the card (4 digits) or, for refunds, a reference.
    reference = tokens[2] if _REFERENCE.match(tokens[2]) else None
    has_card = len(tokens) > 4 and _CARD_DIGITS.match(tokens[2]) is not None
    start = 3 if reference or has_card else 2
    amount = parse_amount(tokens[-1])
    in_credit_column = nearest_column(line.words[-1], columns) == _CREDITS
    # Transaction-date and posting-date columns: first the purchase, then the posting.
    return Transaction(
        transacted_on=resolve_day_month(tokens[0], period_end),
        posted_on=resolve_day_month(tokens[1], period_end),
        description=" ".join(tokens[start:-1]),
        amount=abs(amount),
        direction=CREDIT if in_credit_column or amount < 0 else DEBIT,
        currency=currency,
        reference=reference,
        mcc=None,
        raw_line=line.text,
    )
