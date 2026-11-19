"""Interest paid in a year, by card and currency, and the next pending payment."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal

from michelito.analysis.accounts import account_infos
from michelito.analysis.coverage import bank_coverage
from michelito.analysis.interest import is_interest
from michelito.analysis.rates import Rate, rate_for, to_dop
from michelito.web.accounts import DuePayment, account_views

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
    total_dop: Decimal  # whole DOP units; excludes US$ without a rate
    unconverted_usd: Decimal
    next_due: DuePayment | None


def interest_year(
    conn: sqlite3.Connection,
    rates: Mapping[str, Rate],
    year: int,
    today: date,
    accounts: Collection[str] | None = None,
) -> InterestYear:
    """Interest charged, by transaction date, within `year`.

    `accounts`: only those accounts (interest and next payment); None: all.
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
            continue  # the same charge is already in a newer statement or printout
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
