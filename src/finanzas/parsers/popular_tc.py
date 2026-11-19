"""Parser del estado de tarjeta de crédito del Banco Popular Dominicano.

Cada página repite el encabezado (tarjeta, límite, corte, balance anterior) y
el pie (pago mínimo, balance total). Hay una sección por moneda (DOP, USD).
Cada consumo ocupa dos líneas: la transacción y, debajo, el código de
categoría del comercio (MCC) con el número de autorización.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from finanzas.parsers.common import (
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

NAME = "popular_tc"
INSTITUTION = "popular"

_CARD = re.compile(r"^\*{4}-\*{4}-\*{4}-(\d{4})$")
_PRODUCT = re.compile(r"^(?P<product>[A-ZÁÉÍÓÚÑ ]+?)\s+(?P<currency>DOP|USD)\b")
_DAY_MONTH = re.compile(r"^\d{2}/\d{2}$")
_REFERENCE = re.compile(r"^\d{15,}$")
_MCC = re.compile(r"^\d{4}$")
_HEADER_VALUES = 5  # límite, disponible, corte, fecha límite, balance anterior


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
                raise ParseError("página con movimientos pero sin encabezado de tarjeta")
            continue
        headers.setdefault(header.currency, header)
        footer = _read_footer(page)
        if footer is not None:
            footers[header.currency] = footer
        movements.setdefault(header.currency, []).extend(_read_transactions(page, header))
    if not headers:
        raise ParseError("no se encontró el encabezado de la tarjeta")
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
        raise ParseError(f"{header.currency}: no se encontró el pie con el balance total")
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
        raise ParseError(f"encabezado incompleto: {values}")
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
    """Pie del estado: una línea que empieza con las cuotas vencidas (entero),
    sigue con montos y termina en el balance total. Hay tres variantes:

    - 5 valores (actual): cuotas, monto vencido, pago mínimo, balance a pagar, total.
    - 4 valores (inicios de 2024): cuotas, monto vencido, pago mínimo, total.
    - 3 valores (2020-2025): cuotas, monto vencido, total; el pago mínimo va en
      otra línea sin etiqueta, junto al mismo balance.
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
    """Pago mínimo: primer monto de la línea de dos montos que termina en el balance."""
    for tokens in rows:
        is_pair = len(tokens) == 2 and all(is_amount(t) for t in tokens)
        if is_pair and parse_amount(tokens[1]) == closing:
            return parse_amount(tokens[0])
    raise ParseError("pie sin etiquetas: no se encontró el pago mínimo")


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
    # Columnas "FECHAS DE ENTRADA / TRANSAC.": primero la aplicación, luego la compra.
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
