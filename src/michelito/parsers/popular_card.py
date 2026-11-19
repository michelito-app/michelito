"""Parser of Popular's (Popular Dominicano bank) credit-card statement.

Each page repeats the header (card, limit, closing date, previous balance) and the footer
(minimum payment, total balance). There is one section per currency (DOP, USD). Each purchase
takes two lines: the transaction and, below it, the merchant category code (MCC) with the
authorization number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from michelito.parsers.common import (
    CREDIT,
    DEBIT,
    Page,
    ParseError,
    Section,
    Statement,
    Transaction,
    is_amount,
    parse_amount,
    parse_date,
    resolve_day_month,
)

NAME = "popular_card"
INSTITUTION = "popular"

_CARD = re.compile(r"^\*{4}-\*{4}-\*{4}-(\d{4})$")
# The product name before the currency, as the bank prints it (Spanish capitals).
_PRODUCT = re.compile(r"^(?P<product>[A-ZÁÉÍÓÚÑ ]+?)\s+(?P<currency>DOP|USD)\b")  # spanish-data
_DAY_MONTH = re.compile(r"^\d{2}/\d{2}$")
_REFERENCE = re.compile(r"^\d{15,}$")
_MCC = re.compile(r"^\d{4}$")
_HEADER_VALUES = 5  # limit, available, closing date, due date, previous balance


@dataclass(frozen=True)
class _Header:
    last4: str
    product: str
    currency: str
    credit_limit: Decimal
    period_end: date
    due_date: date
    previous_balance: Decimal


@dataclass(frozen=True)
class _Footer:
    minimum_payment: Decimal
    closing_balance: Decimal


def matches(pages: tuple[Page, ...]) -> bool:
    return any(line.tokens and _CARD.match(line.tokens[0]) for page in pages for line in page)


def parse(pages: tuple[Page, ...]) -> Statement:
    headers: dict[str, _Header] = {}
    footers: dict[str, _Footer] = {}
    movements: dict[str, list[Transaction]] = {}
    for page in pages:
        header = _read_header(page)
        if header is None:
            if any(_is_transaction(line.tokens) for line in page):
                raise ParseError("page with movements but without a card header")
            continue
        headers.setdefault(header.currency, header)
        footer = _read_footer(page)
        if footer is not None:
            footers[header.currency] = footer
        movements.setdefault(header.currency, []).extend(_read_transactions(page, header))
    if not headers:
        raise ParseError("the card header was not found")
    first = next(iter(headers.values()))
    sections = tuple(
        _section(header, footers.get(currency), movements[currency])
        for currency, header in headers.items()
    )
    return Statement(
        parser=NAME,
        institution=INSTITUTION,
        kind="credit_card",
        product=first.product,
        identifier=first.last4,
        period_end=first.period_end,
        due_date=first.due_date,
        sections=sections,
    )


def _section(header: _Header, footer: _Footer | None, transactions: list[Transaction]) -> Section:
    if footer is None:
        raise ParseError(f"{header.currency}: the footer with the total balance was not found")
    return Section(
        currency=header.currency,
        previous_balance=header.previous_balance,
        closing_balance=footer.closing_balance,
        minimum_payment=footer.minimum_payment,
        credit_limit=header.credit_limit,
        printed_debits=None,
        printed_credits=None,
        transactions=tuple(transactions),
    )


def _read_header(page: Page) -> _Header | None:
    product = currency = None
    card: tuple[str, tuple[str, ...]] | None = None
    for line in page:
        tokens = line.tokens
        if not tokens:
            continue
        found = _PRODUCT.match(line.text)
        if found and currency is None:
            product, currency = found["product"].strip(), found["currency"]
        card_match = _CARD.match(tokens[0])
        if card_match and card is None:
            card = (card_match.group(1), tokens[1:])
    if card is None or currency is None or product is None:
        return None
    last4, values = card
    if len(values) < _HEADER_VALUES:
        raise ParseError(f"incomplete header: {values}")
    limit, _available, cut, due, previous = values[:_HEADER_VALUES]
    return _Header(
        last4=last4,
        product=product,
        currency=currency,
        credit_limit=parse_amount(limit),
        period_end=parse_date(cut),
        due_date=parse_date(due),
        previous_balance=parse_amount(previous),
    )


def _read_footer(page: Page) -> _Footer | None:
    """The statement footer: a line that starts with the overdue installments (an integer),
    goes on with amounts and ends in the total balance. There are three variants:

    - 5 values (current): installments, overdue amount, minimum payment, balance to pay, total.
    - 4 values (early 2024): installments, overdue amount, minimum payment, total.
    - 3 values (2020-2025): installments, overdue amount, total; the minimum payment goes on
      another line without a label, next to the same balance.
    """
    rows = [line.tokens for line in page]
    for tokens in rows:
        is_footer = (
            3 <= len(tokens) <= 5 and tokens[0].isdigit() and all(is_amount(t) for t in tokens[1:])
        )
        if not is_footer:
            continue
        closing = parse_amount(tokens[-1])
        if len(tokens) >= 4:
            return _Footer(parse_amount(tokens[2]), closing)
        return _Footer(_minimum_paired_with(rows, closing), closing)
    return None


def _minimum_paired_with(rows: list[tuple[str, ...]], closing: Decimal) -> Decimal:
    """Minimum payment: the first amount of the two-amount line that ends in the balance."""
    for tokens in rows:
        is_pair = len(tokens) == 2 and all(is_amount(t) for t in tokens)
        if is_pair and parse_amount(tokens[1]) == closing:
            return parse_amount(tokens[0])
    raise ParseError("footer without labels: the minimum payment was not found")


def _read_transactions(page: Page, header: _Header) -> list[Transaction]:
    found: list[Transaction] = []
    previous_was_transaction = False
    for line in page:
        tokens = line.tokens
        if _is_transaction(tokens):
            found.append(_transaction(tokens, line.text, header))
            previous_was_transaction = True
            continue
        if previous_was_transaction and _is_mcc_line(tokens):
            found[-1] = replace(found[-1], mcc=tokens[0])
        previous_was_transaction = False
    return found


def _is_transaction(tokens: tuple[str, ...]) -> bool:
    return (
        len(tokens) >= 4
        and _DAY_MONTH.match(tokens[0]) is not None
        and _DAY_MONTH.match(tokens[1]) is not None
        and is_amount(tokens[-1])
    )


def _is_mcc_line(tokens: tuple[str, ...]) -> bool:
    return (
        1 <= len(tokens) <= 2
        and _MCC.match(tokens[0]) is not None
        and all(token.isdigit() for token in tokens)
    )


def _transaction(tokens: tuple[str, ...], raw: str, header: _Header) -> Transaction:
    has_reference = _REFERENCE.match(tokens[2]) is not None
    start = 3 if has_reference else 2
    signed = parse_amount(tokens[-1])
    # Posting-date / transaction-date columns: first the posting, then the purchase.
    return Transaction(
        transacted_on=resolve_day_month(tokens[1], header.period_end),
        posted_on=resolve_day_month(tokens[0], header.period_end),
        description=" ".join(tokens[start:-1]),
        amount=abs(signed),
        direction=CREDIT if signed < 0 else DEBIT,
        currency=header.currency,
        reference=tokens[2] if has_reference else None,
        mcc=None,
        raw_line=raw,
    )
