"""Intereses pagados en un año, por tarjeta y moneda, y el próximo pago pendiente."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal

from finanzas.analysis.accounts import account_infos
from finanzas.analysis.coverage import bank_coverage
from finanzas.analysis.interest import is_interest
from finanzas.analysis.rates import Rate, rate_for, to_dop
from finanzas.web.accounts import DuePayment, account_views

_SQL = """
SELECT t.statement_id, a.key AS account_key, s.currency, t.transacted_on, t.description,
       t.amount_cents,
       t.direction
FROM transactions t
JOIN statements s ON s.id = t.statement_id
JOIN accounts a ON a.id = s.account_id
WHERE t.direction = 'debit' AND t.transacted_on >= ? AND t.transacted_on < ?
"""


@dataclass(frozen=True)
class InterestLine:
    key: str
    label: str
    currency: str
    total: Decimal


@dataclass(frozen=True)
class InterestYear:
    year: int
    lines: list[InterestLine]
    total_dop: Decimal  # en pesos enteros; no incluye los US$ sin tasa
    unconverted_usd: Decimal
    next_due: DuePayment | None


def interest_year(
    conn: sqlite3.Connection,
    rates: Mapping[str, Rate],
    year: int,
    today: date,
    accounts: Collection[str] | None = None,
) -> InterestYear:
    """Intereses cobrados por fecha de transacción dentro de `year`.

    `accounts`: solo esas cuentas (intereses y próximo pago); None: todas.
    """
    totals: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    total_dop = Decimal(0)
    unconverted = Decimal(0)
    covered = bank_coverage(conn)
    for row in conn.execute(_SQL, (f"{year:04d}-01-01", f"{year + 1:04d}-01-01")):
        if not is_interest(row["description"], row["direction"]):
            continue
        if accounts is not None and row["account_key"] not in accounts:
            continue
        if not covered.keeps(row["statement_id"], date.fromisoformat(row["transacted_on"])):
            continue  # el mismo cargo ya está en un estado o en una impresión más nueva
        amount = Decimal(row["amount_cents"]) / 100
        totals[(row["account_key"], row["currency"])] += amount
        converted = to_dop(amount, row["currency"], rate_for(rates, row["transacted_on"][:7]))
        if converted is None:
            unconverted += amount
        else:
            total_dop += converted
    return InterestYear(
        year=year,
        lines=_lines(conn, totals),
        total_dop=total_dop.quantize(Decimal(1), rounding=ROUND_HALF_EVEN),
        unconverted_usd=unconverted,
        next_due=_next_due(conn, today, accounts),
    )


def _lines(
    conn: sqlite3.Connection, totals: Mapping[tuple[str, str], Decimal]
) -> list[InterestLine]:
    lines = []
    for info in account_infos(conn):
        for currency in sorted({c for key, c in totals if key == info.key}, key=_dop_first):
            lines.append(InterestLine(info.key, info.label, currency, totals[(info.key, currency)]))
    return lines


def _dop_first(currency: str) -> tuple[bool, str]:
    return (currency != "DOP", currency)


def _next_due(
    conn: sqlite3.Connection, today: date, accounts: Collection[str] | None
) -> DuePayment | None:
    views = [v for v in account_views(conn, today) if accounts is None or v.key in accounts]
    due = [v.to_pay for v in views if v.to_pay is not None]
    upcoming = [p for p in due if p.due_date >= today]
    return min(upcoming, key=lambda p: p.due_date, default=None)
